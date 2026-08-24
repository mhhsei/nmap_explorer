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
from typing import List, Dict, Any, Optional

RE_MARKETING = re.compile(r'[（\(【\[].*?(推薦|官方|粉絲團|批發|教學|清粉刺|皮膚管理|體驗|專用|營業時間|用品|潤滑).*?[）\)】\]]')
RE_ROLE = re.compile(r'[_xX×].*?(推薦|總監|設計師|老師|教學|美學).*')


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
        self._db_connections: Dict[str, sqlite3.Connection] = {}
        
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

    def _get_connection(self, path: str) -> Optional[sqlite3.Connection]:
        """
        【取得持久化 SQLite 資料庫連線並啟用記憶體映射優化】
        作用：避免重複 open/close 資料庫檔案，並透過 mmap_size 進行極速記憶體存取。
        """
        if not path or not os.path.exists(path):
            return None
        if path in self._db_connections:
            return self._db_connections[path]
        try:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA cache_size = -32000;")  # 32MB 快取
            conn.execute("PRAGMA mmap_size = 268435456;") # 256MB 記憶體映射
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA query_only = TRUE;")     # 唯讀模式消除鎖開銷
            self._db_connections[path] = conn
            return conn
        except Exception as e:
            print(f"Error opening SQLite connection for {path}: {e}")
            return None

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
                    
        # 2. 去除括號內的廣告/行銷字串 (使用預編譯正則表達式)
        name = RE_MARKETING.sub('', name)
        
        # 3. 去除 _設計師 / x總監等後綴
        name = RE_ROLE.sub('', name)
        
        return name.strip() or raw_name.strip()

    @staticmethod
    def is_geographically_valid(name: str, lat: float, lon: float) -> bool:
        """
        防禦性地理邊界檢驗：防止圖資開源社群錯誤標註或假節點（例如將台中火車站標在淡水）。
        """
        if not name or lat is None or lon is None:
            return True
        if any(k in name for k in ['站', '車站', '高鐵', '捷運', '轉運站', '棒球場', '公園']):
            if ('台中' in name or '臺中' in name) and (lat > 24.5 or lat < 23.9):
                return False
            if ('高雄' in name or '左營' in name) and (lat > 23.4 or lat < 22.3):
                return False
            if ('台南' in name or '臺南' in name) and (lat > 23.5 or lat < 22.8):
                return False
            if ('台北' in name or '臺北' in name) and (lat < 24.8):
                return False
        return True

    def _fetch_overture_local(self, lat: float, lon: float, radius_deg: float = 0.008) -> List[Dict[str, Any]]:
        """
        從我們在地端建置的 Unified Places 資料庫 (SQLite) 瞬間拉取大量真實店家與商工稅籍資訊。
        利用持久化連線與 Memory-Mapped I/O，查詢速度可達 2 毫秒內。
        """
        results = []
        db_path, _ = self._resolve_db_paths()
        if not db_path:
            return results
            
        conn = self._get_connection(db_path)
        if not conn:
            return results
            
        try:
            c = conn.cursor()
            min_lat = lat - radius_deg
            max_lat = lat + radius_deg
            min_lon = lon - radius_deg
            max_lon = lon + radius_deg
            
            # 優先查詢精簡商工結構的 places 資料表
            try:
                c.execute('''
                    SELECT id, name, legal_name, brand, category, address, floor, business_desc, lat, lon 
                    FROM places 
                    WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                ''', (min_lat, max_lat, min_lon, max_lon))
                
                rows = c.fetchall()
                for r in rows:
                    c_name = self.clean_poi_name(r[1])
                    if not c_name:
                        continue
                    lat_val = float(r[8])
                    lon_val = float(r[9])
                    if not self.is_geographically_valid(c_name, lat_val, lon_val):
                        continue
                    legal_name = r[2] or c_name
                    brand = r[3] or ""
                    cat = r[4] or "poi"
                    addr = r[5] or ""
                    floor = r[6] or "1F"
                    b_desc = r[7] or ""
                    
                    results.append({
                        "id": f"places_{r[0]}",
                        "name": c_name,
                        "legal_name": legal_name,
                        "brand": brand,
                        "category": cat,
                        "business_desc": b_desc,
                        "address": addr,
                        "floor": floor,
                        "lat": lat_val,
                        "lon": lon_val,
                        "tags": {
                            "amenity": cat,
                            "name": c_name,
                            "legal_name": legal_name,
                            "brand": brand,
                            "address": addr,
                            "floor": floor,
                            "business_desc": b_desc,
                            "source": "places"
                        }
                    })
                return results
            except sqlite3.OperationalError:
                # 兼容舊版 overture_places 表結構
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
                    lat_v = float(r[3])
                    lon_v = float(r[4])
                    if not self.is_geographically_valid(c_name, lat_v, lon_v):
                        continue
                    results.append({
                        "id": f"overture_{r[0]}",
                        "name": c_name,
                        "legal_name": c_name,
                        "category": r[2] or "poi",
                        "lat": lat_v,
                        "lon": lon_v,
                        "floor": "1F",
                        "tags": {
                            "amenity": r[2] or "place",
                            "name": c_name,
                            "floor": "1F",
                            "source": "overture"
                        }
                    })
        except Exception as e:
            print(f"Overture DB error: {e}")
            
        return results


    def _fetch_gov_local(self, lat: float, lon: float, radius_deg: float = 0.008) -> List[Dict[str, Any]]:
        """
        從我們在地端建置的政府開放資料庫 (SQLite) 拉取資料。
        """
        results = []
        _, gov_path = self._resolve_db_paths()
        if not gov_path:
            return results
            
        conn = self._get_connection(gov_path)
        if not conn:
            return results
            
        try:
            c = conn.cursor()
            min_lat, max_lat = lat - radius_deg, lat + radius_deg
            min_lon, max_lon = lon - radius_deg, lon + radius_deg
            
            c.execute('''
                SELECT id, name, category, lat, lon, address, source 
                FROM gov_places 
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            ''', (min_lat, max_lat, min_lon, max_lon))
            
            rows = c.fetchall()
            for r in rows:
                c_name = self.clean_poi_name(r[1])
                if not c_name:
                    continue
                lat_v = float(r[3])
                lon_v = float(r[4])
                if not self.is_geographically_valid(c_name, lat_v, lon_v):
                    continue
                results.append({
                    "id": f"gov_{r[0]}",
                    "name": c_name,
                    "legal_name": c_name,
                    "category": r[2],
                    "lat": float(r[3]),
                    "lon": float(r[4]),
                    "address": r[5] or "",
                    "floor": "1F",
                    "tags": {
                        "amenity": r[2],
                        "name": c_name,
                        "address": r[5] or "",
                        "floor": "1F",
                        "source": r[6] or "gov"
                    }
                })

        except Exception as e:
            print(f"Gov DB error: {e}")
            
        return results

    def fetch_offline_pois(self, lat: float, lon: float, radius_deg: float = 0.012) -> List[Dict[str, Any]]:
        """
        【瞬間從本地離線資料庫載入 POI (Instant Local Offline POI Loading)】
        作用：在 0.002 秒內瞬間讀取 Overture Places DB 與 TDX 政府開放資料庫，不經任何網路請求。
        """
        all_pois = []
        seen_names = set()

        # 1. 讀取 Overture Places 資料庫
        overture_pois = self._fetch_overture_local(lat, lon, radius_deg)
        for p in overture_pois:
            if p['name'] not in seen_names:
                seen_names.add(p['name'])
                all_pois.append(p)

        # 2. 讀取政府開放資料庫
        gov_pois = self._fetch_gov_local(lat, lon, radius_deg)
        for p in gov_pois:
            if p['name'] not in seen_names:
                seen_names.add(p['name'])
                all_pois.append(p)

        return all_pois

    def fetch_real_pois(self, lat: float, lon: float, pages: int = 2, radius_deg: float = 0.008) -> List[Dict[str, Any]]:
        """
        多執行緒並發爬取 (Multithreaded Fetching)
        """
        start_time = time.time()
        all_pois = self.fetch_offline_pois(lat, lon, radius_deg)
        seen_names = {p['name'] for p in all_pois}
        
        # 3. 開啟執行緒池，同時執行 _fetch_ifoodie_page (補充電子報與食記新餐廳)
        with concurrent.futures.ThreadPoolExecutor(max_workers=pages) as executor:
            future_to_page = {executor.submit(self._fetch_ifoodie_page, lat, lon, p): p for p in range(1, pages + 1)}
            
            for future in concurrent.futures.as_completed(future_to_page):
                try:
                    pois = future.result()
                    for p in pois:
                        if p['name'] not in seen_names:
                            seen_names.add(p['name'])
                            all_pois.append(p)
                except Exception as e:
                    pass
                    
        end_time = time.time()
        print(f"[RealPoiFetcher] Fetched {len(all_pois)} real POIs in {end_time - start_time:.3f}s")
        return all_pois
