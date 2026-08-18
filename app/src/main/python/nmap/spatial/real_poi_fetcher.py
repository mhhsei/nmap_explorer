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
    
    為什麼要寫這個類別？
    因為開源地圖 (OpenStreetMap) 的台灣圖資在巷弄間經常缺乏店家資料，
    為了讓視障者在遊戲中有「逛街」的熱鬧感，又必須堅持「真實資料（不捏造）」，
    我們只能透過爬蟲即時向外部的食記/外送平台索取該經緯度周遭的店家。
    """
    
    def __init__(self, db_path=None):
        # 偽裝成一般瀏覽器，避免被伺服器直接阻擋 (Anti-bot)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        
        if db_path is None:
            # 自動定位到專案根目錄下的 data/overture_places.db
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(base_dir, "data", "overture_places.db")
            self.gov_db_path = os.path.join(base_dir, "data", "gov_places.db")
        else:
            self.db_path = db_path
            self.gov_db_path = db_path.replace("overture_places", "gov_places")

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
                name = item.get('name')
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

    def _fetch_overture_local(self, lat: float, lon: float, radius_deg: float = 0.005) -> List[Dict[str, Any]]:
        """
        從我們在地端建置的 Overture Maps 資料庫 (SQLite) 瞬間拉取大量真實店家。
        查詢速度不到 0.01 秒，且資料量驚人。
        """
        results = []
        if not os.path.exists(self.db_path):
            return results
            
        try:
            conn = sqlite3.connect(self.db_path)
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
                results.append({
                    "id": f"overture_{r[0]}",
                    "name": r[1],
                    "category": r[2] or "poi",
                    "lat": float(r[3]),
                    "lon": float(r[4]),
                    "tags": {
                        "amenity": r[2] or "place",
                        "name": r[1],
                        "source": "overture"
                    }
                })
            conn.close()
        except Exception as e:
            print(f"Overture DB error: {e}")
            
        return results

    def _fetch_gov_local(self, lat: float, lon: float, radius_deg: float = 0.005) -> List[Dict[str, Any]]:
        """
        從我們在地端建置的政府開放資料庫 (SQLite) 拉取資料。
        """
        results = []
        if not os.path.exists(self.gov_db_path):
            return results
            
        try:
            conn = sqlite3.connect(self.gov_db_path)
            c = conn.cursor()
            
            min_lat, max_lat = lat - radius_deg, lat + radius_deg
            min_lon, max_lon = lon - radius_deg, lon + radius_deg
            
            c.execute('''
                SELECT id, name, category, lat, lon, source 
                FROM gov_places 
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            ''', (min_lat, max_lat, min_lon, max_lon))
            
            for r in c.fetchall():
                results.append({
                    "id": r[0],
                    "name": r[1],
                    "category": r[2] or "poi",
                    "lat": float(r[3]),
                    "lon": float(r[4]),
                    "tags": {
                        "amenity": r[2] or "place",
                        "name": r[1],
                        "source": f"gov_{r[5]}"
                    }
                })
            conn.close()
        except Exception as e:
            print(f"Gov DB error: {e}")
            
        return results

    def fetch_real_pois(self, lat: float, lon: float, pages: int = 2) -> List[Dict[str, Any]]:
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
        
        # 1. 瞬間從本地 Overture 資料庫抓取 (0.01 秒)
        overture_pois = self._fetch_overture_local(lat, lon, 0.003)
        for p in overture_pois:
            if p['name'] not in seen_names:
                seen_names.add(p['name'])
                all_pois.append(p)

        # 2. 瞬間從本地政府開放資料庫抓取 (TDX / 財政部)
        gov_pois = self._fetch_gov_local(lat, lon, 0.003)
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
