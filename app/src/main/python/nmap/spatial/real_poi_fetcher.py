"""
真實地標綜合抓取引擎 (Real POI Multi-Source Fetcher)

作用：
1. 整合本地離線 SQLite 資料庫（Overture Places DB 與 政府 TDX 開放資料庫），在 0.01 秒內瞬間載入真實店家。
2. 線上食記補全（iFoodie 多執行緒 SSR 爬取）：補充最新開幕的餐飲店家。
3. 嚴格去重 (Deduplication)：以店名為鍵值去重，保證同一個地點不會反覆出現相同招牌。
"""
import urllib.request
import urllib.parse
import json
import re
import concurrent.futures
import time
import sqlite3
import os
from typing import List, Dict, Any

class RealPoiFetcher:
    """
    真實地標抓取引擎 (RealPoiFetcher)
    """

    
    def __init__(self, db_path=None):
        # 偽裝成一般瀏覽器，避免被伺服器直接阻擋 (Anti-bot)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        
        if db_path is None:
            # 優先讀取自訂資料目錄 (Android App 動態下載儲存目錄)
            data_dir = os.environ.get("NMAP_DATA_DIR")
            if data_dir:
                self.db_path = os.path.join(data_dir, "overture_places.db")
                self.gov_db_path = os.path.join(data_dir, "gov_places.db")
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                self.db_path = os.path.join(base_dir, "data", "overture_places.db")
                self.gov_db_path = os.path.join(base_dir, "data", "gov_places.db")
        else:
            self.db_path = db_path
            self.gov_db_path = db_path.replace("overture_places", "gov_places")

    def _resolve_db_paths(self):
        """動態偵測並鎖定本機/手機內有效存在的離線資料庫路徑"""
        # 1. 優先檢查目前 db_path
        if self.db_path and os.path.exists(self.db_path):
            return self.db_path, self.gov_db_path

        # 2. 檢查 NMAP_DATA_DIR 環境變數
        data_dir = os.environ.get("NMAP_DATA_DIR")
        if data_dir:
            cand = os.path.join(data_dir, "overture_places.db")
            if os.path.exists(cand):
                self.db_path = cand
                self.gov_db_path = os.path.join(data_dir, "gov_places.db")
                return self.db_path, self.gov_db_path

        # 3. 搜尋 Android 內部/外部儲存區與專案目錄
        candidates = [
            "/sdcard/Android/data/com.example.nmapexplorer/files/data/overture_places.db",
            "/storage/emulated/0/Android/data/com.example.nmapexplorer/files/data/overture_places.db",
            "/data/user/0/com.example.nmapexplorer/files/data/overture_places.db",
            "/data/data/com.example.nmapexplorer/files/data/overture_places.db",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "database_assets", "overture_places.db"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "overture_places.db"),
            "database_assets/overture_places.db",
            "data/overture_places.db"
        ]
        for cand in candidates:
            if os.path.exists(cand):
                self.db_path = cand
                self.gov_db_path = cand.replace("overture_places", "gov_places")
                return self.db_path, self.gov_db_path

        return None, None

    def _fetch_ifoodie_page(self, lat: float, lon: float, page: int) -> List[Dict[str, Any]]:

        """
        單一頁面的爬取工作函數。
        為什麼抓愛食記 (iFoodie)？
        因為它使用 SSR (Server-Side Rendering)，網頁的 HTML 內直接包含了 JSON 格式的餐廳資料 (__NEXT_DATA__)，
        不需要執行複雜的 JavaScript 或是破解圖形驗證碼，能極速抓出經緯度附近的餐廳。
        """
        url = f'https://ifoodie.tw/explore/?lat={lat}&lng={lon}&page={page}'
        try:
            req = urllib.request.Request(url, headers=self.headers)
            # 設定 3 秒 timeout，防止網路不穩卡死執行緒
            with urllib.request.urlopen(req, timeout=3.0) as response:
                html = response.read().decode('utf-8')
            
            # 使用正規表達式，直接從 HTML 源碼中暴力抽出隱藏的 JSON 狀態資料
            match = re.search(r'__NEXT_DATA__.*?>(.*?)</script>', html)
            if not match:
                return []
                
            data = json.loads(match.group(1))
            explore = data.get('props', {}).get('initialState', {}).get('search', {}).get('explore', {})
            items = explore.get('data', [])
            
            results = []
            for item in items:
                raw_n = item.get('name')
                name = self.clean_poi_name(raw_n) if raw_n else ""
                item_lat = item.get('lat')
                item_lng = item.get('lng')
                # 確保資料具備完整的名稱與經緯度，才能放入空間索引中
                if name and item_lat and item_lng:
                    results.append({
                        "id": f"ifoodie_{item.get('id', hash(name))}",
                        "name": name,
                        "category": "restaurant",
                        "lat": float(item_lat),
                        "lon": float(item_lng),
                        "tags": {
                            "amenity": "restaurant",
                            "name": name,
                            "source": "ifoodie",
                            "rating": item.get('rating', 0),
                            "address": item.get('address', '')
                        }
                    })
            return results
        except Exception as e:
            print(f"iFoodie fetch error page {page}: {e}")
            return []

    @staticmethod
    def clean_poi_name(raw_name: str) -> str:
        """智慧淨化 POI 店名，剔除過長的行銷標籤、斜線與廣告詞彙"""
        if not raw_name:
            return ""
        name = str(raw_name).strip()
        
        # 1. 拆解斜線、豎線等複合標籤 (取主要商標名)
        for sep in ['/', '|', '丨', '｜']:
            if sep in name:
                parts = name.split(sep)
                if parts[0].strip():
                    name = parts[0].strip()
                    
        # 2. 去除括號內的廣告/行銷字串
        name = re.sub(r'[（\(【\[].*?(推薦|官方|粉絲團|批發|教學|清粉刺|皮膚管理|體驗|專用|營業時間|用品|潤滑).*?[）\)】\]]', '', name)
        
        # 3. 去除 _設計師 / x總監等後綴
        name = re.sub(r'[_xX×].*?(推薦|總監|設計師|老師|教學|美學).*', '', name)
        
        return name.strip() or raw_name.strip()

    def _fetch_overture_local(self, lat: float, lon: float, radius_deg: float = 0.008) -> List[Dict[str, Any]]:
        """
        從我們在地端建置的 Overture Maps 資料庫 (SQLite) 瞬間拉取大量真實店家。
        查詢速度不到 0.01 秒，且資料量驚人。
        """
        results = []
        db_path, _ = self._resolve_db_paths()
        if not db_path or not os.path.exists(db_path):
            return results
            
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            
            min_lat = lat - radius_deg
            max_lat = lat + radius_deg
            min_lon = lon - radius_deg
            max_lon = lon + radius_deg
            
            c.execute('''
                SELECT id, name, category, lat, lon 
                FROM overture_places 
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            ''', (min_lat, max_lat, min_lon, max_lon))
            
            rows = c.fetchall()
            for r in rows:
                c_name = self.clean_poi_name(r[1])
                if not c_name:
                    continue
                results.append({
                    "id": f"overture_{r[0]}",
                    "name": c_name,
                    "category": r[2] or "poi",
                    "lat": float(r[3]),
                    "lon": float(r[4]),
                    "tags": {
                        "amenity": r[2] or "place",
                        "name": c_name,
                        "source": "overture"
                    }
                })
            conn.close()
            print(f"[RealPoiFetcher] Successfully loaded {len(results)} POIs from {db_path}")
        except Exception as e:
            print(f"Overture DB error: {e}")
            
        return results


    def _fetch_gov_local(self, lat: float, lon: float, radius_deg: float = 0.008) -> List[Dict[str, Any]]:
        """
        從我們在地端建置的政府開放資料庫 (SQLite) 拉取資料。
        """
        results = []
        _, gov_path = self._resolve_db_paths()
        if not gov_path or not os.path.exists(gov_path):
            return results
            
        try:
            conn = sqlite3.connect(gov_path)
            c = conn.cursor()
            
            min_lat, max_lat = lat - radius_deg, lat + radius_deg
            min_lon, max_lon = lon - radius_deg, lon + radius_deg
            
            c.execute('''
                SELECT id, name, category, lat, lon, source 
                FROM gov_places 
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            ''', (min_lat, max_lat, min_lon, max_lon))
            
            rows = c.fetchall()
            for r in rows:
                c_name = self.clean_poi_name(r[1])
                if not c_name:
                    continue
                results.append({
                    "id": f"gov_{r[0]}",
                    "name": c_name,
                    "category": r[2],
                    "lat": float(r[3]),
                    "lon": float(r[4]),
                    "tags": {
                        "amenity": r[2],
                        "name": c_name,
                        "source": r[5] or "gov"
                    }
                })
            conn.close()

        except Exception as e:
            print(f"Gov DB error: {e}")
            
        return results

    def fetch_real_pois(self, lat: float, lon: float, pages: int = 2, radius_deg: float = 0.008) -> List[Dict[str, Any]]:
        """
        多執行緒並發爬取 (Multithreaded Fetching)
        
        為什麼要用多執行緒？
        如果我們需要 45 間餐廳，就必須翻 3 頁。如果一頁一頁慢慢抓，一頁 1 秒，總共要 3 秒。
        但透過 ThreadPoolExecutor，我們同時派出 3 個工人去抓第 1, 2, 3 頁，
        整體消耗的時間就等於「最慢的那個工人花的時間」（大約 1 秒內），大幅提升效率。
        """
        start_time = time.time()
        all_pois = []
        seen_names = set()
        
        # 1. 瞬間從本地 Overture 資料庫抓取 (0.01 秒，半徑 ~880 公尺)
        overture_pois = self._fetch_overture_local(lat, lon, radius_deg)
        for p in overture_pois:
            if p['name'] not in seen_names:
                seen_names.add(p['name'])
                all_pois.append(p)

        # 2. 瞬間從本地政府開放資料庫抓取 (TDX / 財政部)
        gov_pois = self._fetch_gov_local(lat, lon, radius_deg)
        for p in gov_pois:
            if p['name'] not in seen_names:
                seen_names.add(p['name'])
                all_pois.append(p)
                
        # 3. 開啟執行緒池，同時執行 _fetch_ifoodie_page (補充電子報與食記新餐廳)
        with concurrent.futures.ThreadPoolExecutor(max_workers=pages) as executor:
            # 建立工作任務清單
            future_to_page = {executor.submit(self._fetch_ifoodie_page, lat, lon, p): p for p in range(1, pages + 1)}
            
            # 當任何一個工作完成時，立刻收集結果
            for future in concurrent.futures.as_completed(future_to_page):
                try:
                    pois = future.result()
                    for p in pois:
                        # 進行基礎的名稱去重（Deduplication），避免重複把同一間店放入地圖
                        if p['name'] not in seen_names:
                            seen_names.add(p['name'])
                            all_pois.append(p)
                except Exception as e:
                    pass
                    
        end_time = time.time()
        print(f"[RealPoiFetcher] Fetched {len(all_pois)} real POIs in {end_time - start_time:.3f}s")
        return all_pois
