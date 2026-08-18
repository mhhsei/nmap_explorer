import math
import re
import gc
from typing import List, Dict, Any, Optional, Tuple
import networkx as nx
import threading
from nmap.spatial.grid_index import GridSpatialIndex
from nmap.spatial.pure_geometry import find_closest_point_on_line, get_line_bounds
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_cardinal,
    bearing_to_relative_direction
)
from nmap.spatial.real_poi_fetcher import RealPoiFetcher


"""
【台灣 50+ 熱門連鎖品牌大字典 (Taiwan Chain Brand Auto-Recognizer)】
為什麼要硬編碼 (Hardcode) 這個字典，而不使用 LLM？
1. 視障導航需要「絕對的即時性 (0-latency)」：在街上每走一步，系統可能需要掃描周圍幾十個 POI。
   如果呼叫語言模型進行實體識別 (NER)，延遲高達數秒，對於正在移動的視障者是致命的危險。
2. 資料清洗 (Data Sanitization)：OSM 或商工登記資料往往會帶有雜亂的字尾 (例如: "統一超商股份有限公司台北分公司")。
   透過 O(1) 的雜湊查找與子字串比對，可以瞬間將其轉換為視障者熟悉的 "7-Eleven 統一超商"。
"""
TAIWAN_BRAND_DICTIONARY = {
    "7-Eleven": "7-Eleven 統一超商", "7-11": "7-Eleven 統一超商", "統一超商": "7-Eleven 統一超商",
    "FamilyMart": "全家便利商店", "全家": "全家便利商店",
    "Hi-Life": "萊爾富便利商店", "萊爾富": "萊爾富便利商店",
    "OK Mart": "OK便利商店", "OK超商": "OK便利商店",
    "PX Mart": "全聯福利中心", "全聯": "全聯福利中心",
    "Carrefour": "家樂福", "美廉社": "美廉社", "愛買": "愛買", "大潤發": "大潤發", "Costco": "好市多",
    "50嵐": "50嵐手搖飲", "清心福全": "清心福全飲料店", "Louisa": "路易莎咖啡", "路易莎": "路易莎咖啡",
    "Starbucks": "星巴克咖啡", "星巴克": "星巴克咖啡", "Milksha": "迷客夏手搖飲", "迷客夏": "迷客夏手搖飲",
    "可不可": "可不可熟成紅茶", "麻古": "麻古茶坊", "大苑子": "大苑子水果茶", "CoCo": "CoCo都可飲料",
    "龜記": "龜記茗品", "得正": "得正烏龍茶", "五桐號": "五桐號手搖飲", "春水堂": "春水堂人文茶館",
    "麥當勞": "麥當勞速食店", "McDonald's": "麥當勞速食店", "肯德基": "肯德基炸雞", "KFC": "肯德基炸雞",
    "摩斯": "摩斯漢堡 MOS", "MOS Burger": "摩斯漢堡 MOS", "八方雲集": "八方雲集鍋貼水餃",
    "三商巧福": "三商巧福牛肉麵", "爭鮮": "爭鮮迴轉壽司", "壽司郎": "壽司郎 Sushiro", "藏壽司": "藏壽司 Kura",
    "薩莉亞": "薩莉亞義式餐飲", "鬍鬚張": "鬍鬚張魯肉飯", "鼎泰豐": "鼎泰豐小籠包", "孫東寶": "孫東寶台式牛排",
    "屈臣氏": "屈臣氏藥妝 Watsons", "Watsons": "屈臣氏藥妝 Watsons", "康是美": "康是美藥妝 Cosmed",
    "寶雅": "寶雅生活館 POYA", "POYA": "寶雅生活館 POYA", "小北百貨": "小北百貨", "大創": "大創 DAISO",
    "MUJI": "無印良品 MUJI", "無印良品": "無印良品 MUJI", "誠品": "誠品書店/生活館",
    "台灣銀行": "臺灣銀行", "中國信託": "中國信託商業銀行", "國泰世華": "國泰世華銀行", "玉山銀行": "玉山商業銀行",
    "台新銀行": "台新國際商業銀行", "中華郵政": "中華郵政 (郵局)", "郵局": "中華郵政 (郵局)",
    "信義房屋": "信義房屋房仲", "永慶房屋": "永慶房屋房仲", "中信房屋": "中信房屋房仲", "住商不動產": "住商不動產"
}


class SpatialPOI:
    """
    【空間興趣點 (Spatial Point of Interest)】
    將原始資料庫的 POI 進行封裝，並提供相對方位計算。
    """

    def __init__(self, raw_poi: Dict[str, Any]):
        self.id = raw_poi["id"]
        raw_name = raw_poi.get("name", "未命名設施")
        
        # Recognize famous Taiwan brands
        recognized_brand = ""
        for b_key, b_val in TAIWAN_BRAND_DICTIONARY.items():
            if b_key.lower() in raw_name.lower():
                recognized_brand = b_val
                break

        self.name = recognized_brand if recognized_brand else raw_name
        self.category = raw_poi.get("category", "amenity")
        self.lat = raw_poi["lat"]
        self.lon = raw_poi["lon"]
        self.phone = raw_poi.get("phone", "")
        self.website = raw_poi.get("website", "")
        self.opening_hours = raw_poi.get("opening_hours", "")
        self.wheelchair = raw_poi.get("wheelchair", "unknown")
        self.level = raw_poi.get("level", "")
        self.cuisine = raw_poi.get("cuisine", "")
        self.brand = raw_poi.get("brand", "") or recognized_brand
        self.payment = raw_poi.get("payment", "")
        self.takeaway = raw_poi.get("takeaway", "")
        self.tags = raw_poi.get("tags", {})

    def calculate_relative(self, ref_lat: float, ref_lon: float, heading_deg: float) -> Dict[str, Any]:
        """
        【計算相對方位與非視覺 12 小時鐘點制】
        為什麼不直接報經緯度或絕對方位 (東南西北)？
        因為對於正在走路的視障者，最直覺的相對座標系統是「以自己為中心的時鐘」。
        此函式將幾何學的 True Bearing (真方位角) 扣除玩家的 Heading (當前朝向)，
        得出 Relative Bearing，並透過 `bearing_to_clock_position` 轉換為「2點鐘方向」、「10點鐘方向」，
        這是整套系統能讓視障者「聽聲辨位」的核心演算法。
        """
        dist = haversine_distance(ref_lat, ref_lon, self.lat, self.lon)
        target_brng = calculate_bearing(ref_lat, ref_lon, self.lat, self.lon)
        rel_brng = relative_bearing(heading_deg, target_brng)
        clock = bearing_to_clock_position(rel_brng)
        cardinal = bearing_to_cardinal(target_brng)
        rel_dir = bearing_to_relative_direction(rel_brng)

        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "lat": self.lat,
            "lon": self.lon,
            "distance_m": round(dist, 1),
            "bearing_deg": round(target_brng, 1),
            "relative_bearing_deg": round(rel_brng, 1),
            "clock_position": clock,
            "cardinal_direction": cardinal,
            "relative_direction": rel_dir,
            "phone": self.phone,
            "website": self.website,
            "opening_hours": self.opening_hours,
            "wheelchair": self.wheelchair,
            "level": self.level,
            "cuisine": self.cuisine,
            "brand": self.brand,
            "payment": self.payment,
            "takeaway": self.takeaway,
            "tags": self.tags
        }


class WorldModel:
    """
    【數位雙生世界模型 (Digital Twin World Model)】
    這是 nmap 系統的最底層大腦。
    為什麼需要自己維護一套 Graph 與 R-Tree？
    如果每次玩家移動 1 公尺，都去查 SQLite 或呼叫外部 API，延遲會太高。
    因此我們在玩家一落地時，就將周遭的街道載入 `NetworkX (圖學模型)`，
    並將 POI 載入 `R-Tree (空間索引結構)`。
    有了 R-Tree，我們可以達成 O(log N) 的極速碰撞與半徑檢索，讓「踏步」的運算壓在 22 毫秒內。
    """

    def __init__(self):
        self.road_graph = nx.MultiDiGraph()
        self.roads: List[Dict[str, Any]] = []
        self.pois: List[SpatialPOI] = []
        self.crossings: List[Dict[str, Any]] = []
        self.traffic_signals: List[Dict[str, Any]] = []
        self.transit_stops: List[Dict[str, Any]] = []
        self.buildings: List[Dict[str, Any]] = []
        self.house_numbers: List[Dict[str, Any]] = []
        
        # Spatial Grid indices
        self.poi_rtree = GridSpatialIndex()
        self.road_rtree = GridSpatialIndex()
        self.building_rtree = GridSpatialIndex()
        self.crossing_rtree = GridSpatialIndex()
        
        self.poi_fetcher = RealPoiFetcher()
        self.next_external_poi_id = 1000000
        self.rtree_lock = threading.Lock()

    def build_from_osm(self, parsed_data: Dict[str, Any], ref_lat: Optional[float] = None, ref_lon: Optional[float] = None):
        """
        Populate the World Model from parsed OSM elements.
        Clears previous spatial indices to prevent memory leaks and ghost features when relocating.
        """
        with self.rtree_lock:
            self.poi_rtree = GridSpatialIndex()
            self.road_rtree = GridSpatialIndex()
            self.building_rtree = GridSpatialIndex()
            self.crossing_rtree = GridSpatialIndex()
            self.next_external_poi_id = 1000000

        self.roads = parsed_data.get("roads", [])
        self.crossings = parsed_data.get("crossings", [])
        self.traffic_signals = parsed_data.get("traffic_signals", [])
        self.transit_stops = parsed_data.get("transit_stops", [])
        self.buildings = parsed_data.get("buildings", [])
        self.house_numbers = parsed_data.get("house_numbers", [])

        # Build POIs
        raw_pois = parsed_data.get("pois", [])
        self.pois = []
        p_idx = 0
        for p in raw_pois:
            sp = SpatialPOI(p)
            self.pois.append(sp)
            with self.rtree_lock:
                self.poi_rtree.insert(p_idx, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
            p_idx += 1

        # Build Transit as POIs if not already present
        for ts in self.transit_stops:
            sp = SpatialPOI({
                "id": ts["id"],
                "name": ts["name"],
                "category": ts["transit_type"],
                "lat": ts["lat"],
                "lon": ts["lon"],
                "tags": ts.get("tags", {})
            })
            self.pois.append(sp)
            with self.rtree_lock:
                self.poi_rtree.insert(p_idx, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
            p_idx += 1

        # Build Road Graph & Road R-Tree
        self.road_graph.clear()
        r_idx = 0
        for road in self.roads:
            geom = road["geometry"]
            if len(geom) < 2:
                continue
            bounds = get_line_bounds(geom)
            self.road_rtree.insert(r_idx, bounds, obj=road)
            r_idx += 1

            # Add edges to NetworkX graph
            node_ids = road.get("node_ids", [])
            for i in range(len(geom) - 1):
                u_lat, u_lon = geom[i]
                v_lat, v_lon = geom[i+1]
                u_id = node_ids[i] if i < len(node_ids) else f"pt_{u_lat}_{u_lon}"
                v_id = node_ids[i+1] if i+1 < len(node_ids) else f"pt_{v_lat}_{v_lon}"

                dist = haversine_distance(u_lat, u_lon, v_lat, v_lon)
                brng = calculate_bearing(u_lat, u_lon, v_lat, v_lon)

                self.road_graph.add_node(u_id, lat=u_lat, lon=u_lon)
                self.road_graph.add_node(v_id, lat=v_lat, lon=v_lon)
                self.road_graph.add_edge(u_id, v_id, weight=dist, name=road["name"], bearing=brng, road=road)
                
                if road.get("oneway") != "yes":
                    rev_brng = (brng + 180.0) % 360.0
                    self.road_graph.add_edge(v_id, u_id, weight=dist, name=road["name"], bearing=rev_brng, road=road)

        # Build Buildings R-Tree
        b_idx = 0
        for b in self.buildings:
            c_lat = b["center_lat"]
            c_lon = b["center_lon"]
            self.building_rtree.insert(b_idx, (c_lon, c_lat, c_lon, c_lat), obj=b)
            b_idx += 1

        # Build Crossings R-Tree
        c_idx = 0
        for c in self.crossings:
            c_lat = c["lat"]
            c_lon = c["lon"]
            self.crossing_rtree.insert(c_idx, (c_lon, c_lat, c_lon, c_lat), obj=c)
            c_idx += 1

        # Determine reference center for real POI fetching
        target_ref_lat = ref_lat
        target_ref_lon = ref_lon
        if target_ref_lat is None or target_ref_lon is None:
            if self.roads and len(self.roads[0].get("geometry", [])) > 0:
                target_ref_lat = self.roads[0]["geometry"][0][0]
                target_ref_lon = self.roads[0]["geometry"][0][1]

        if target_ref_lat is not None and target_ref_lon is not None:
            def fetch_and_inject():
                try:
                    external_pois = self.poi_fetcher.fetch_real_pois(target_ref_lat, target_ref_lon, pages=3)
                    for p in external_pois:
                        sp = SpatialPOI(p)
                        self.pois.append(sp)
                        with self.rtree_lock:
                            self.poi_rtree.insert(self.next_external_poi_id, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
                            self.next_external_poi_id += 1
                except Exception as e:
                    import logging
                    logging.warning(f"Background POI fetch error: {e}")
            
            # Start Daemon background thread
            threading.Thread(target=fetch_and_inject, daemon=True).start()

        # Promptly release temporary deserialized JSON structures from JVM/Python heap
        gc.collect()

    def find_nearest_road(self, lat: float, lon: float) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Find the nearest road to (lat, lon) and return (road_dict, distance_m).
        """
        if not self.roads:
            return None, 999999.0

        radius_deg = 150.0 / 111000.0 # ~150m
        bounds = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
        min_dist = 999999.0
        best_road = None

        for item in self.road_rtree.intersection(bounds, objects=True):
            road = item.object
            geom = road["geometry"]
            if len(geom) < 2:
                continue
            
            dist_m, _, _ = find_closest_point_on_line(lat, lon, geom)
            if dist_m < min_dist:
                min_dist = dist_m
                best_road = road

        return best_road, min_dist

    def get_nearby_pois(self, lat: float, lon: float, heading_deg: float, radius_m: float = 80.0, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all POIs within radius_m sorted by distance with relative direction info.
        """
        results = []
        radius_deg = radius_m / 100000.0
        bounds = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
        with self.rtree_lock:
            for item in self.poi_rtree.intersection(bounds, objects=True):
                poi = item.object
                rel = poi.calculate_relative(lat, lon, heading_deg)
                if rel["distance_m"] <= radius_m:
                    if category is None or category.lower() in rel["category"].lower() or category.lower() in rel["name"].lower():
                        results.append(rel)

        results.sort(key=lambda x: x["distance_m"])
        
        # Deduplicate POIs by name to prevent reading the same store twice
        seen_names = set()
        unique_results = []
        for p in results:
            name = p.get("name", "")
            if not name or name not in seen_names:
                if name:
                    seen_names.add(name)
                unique_results.append(p)
                
        return unique_results

    def get_road_info(self, lat: float, lon: float, heading_deg: float) -> Dict[str, Any]:
        """
        Analyze current road, sidewalk availability, lane count, and street orientation.
        """
        road, dist_m = self.find_nearest_road(lat, lon)
        if not road:
            return {
                "street_name": "未知道路",
                "distance_to_road_m": round(dist_m, 1),
                "highway_type": "footway",
                "sidewalk": "none",
                "sidewalk_desc": "無劃設人行道（請靠邊小心通行）",
                "lanes": "1",
                "oneway": "雙向道",
                "surface": "未知路面"
            }

        sidewalk_map = {
            "both": "兩側皆有人行道",
            "left": "左側有人行道",
            "right": "右側有人行道",
            "none": "無劃設人行道（請靠邊小心通行）",
            "separate": "人行道獨立於車道外"
        }
        raw_sw = road.get("sidewalk", "none")
        sw_desc = sidewalk_map.get(raw_sw, f"人行道標示：{raw_sw}")

        return {
            "street_name": road.get("name", "無名路"),
            "distance_to_road_m": round(dist_m, 1),
            "highway_type": road.get("highway_type", "residential"),
            "sidewalk": raw_sw,
            "sidewalk_desc": sw_desc,
            "lanes": road.get("lanes", "1"),
            "oneway": "單行道" if road.get("oneway") == "yes" else "雙向道",
            "surface": road.get("surface", "柏油路面")
        }

    def get_nearby_buildings(self, lat: float, lon: float, heading_deg: float, radius_m: float = 50.0) -> List[Dict[str, Any]]:
        """
        Get nearby buildings with relative direction, height, and levels.
        """
        results = []
        radius_deg = radius_m / 100000.0
        bounds = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
        for item in self.building_rtree.intersection(bounds, objects=True):
            b = item.object
            c_lat = b["center_lat"]
            c_lon = b["center_lon"]
            dist = haversine_distance(lat, lon, c_lat, c_lon)
            if dist <= radius_m:
                t_brng = calculate_bearing(lat, lon, c_lat, c_lon)
                rel_brng = relative_bearing(heading_deg, t_brng)
                clock = bearing_to_clock_position(rel_brng)
                rel_dir = bearing_to_relative_direction(rel_brng)

                results.append({
                    "id": b["id"],
                    "name": b["name"],
                    "building_type": b["building_type"],
                    "distance_m": round(dist, 1),
                    "clock_position": clock,
                    "relative_direction": rel_dir,
                    "height": b.get("height", ""),
                    "levels": b.get("levels", "")
                })

        results.sort(key=lambda x: x["distance_m"])
        return results

    def get_nearby_crossings(self, lat: float, lon: float, heading_deg: float, radius_m: float = 50.0) -> List[Dict[str, Any]]:
        """
        Get nearby crossings (pedestrian, etc.) within radius.
        """
        results = []
        radius_deg = radius_m / 100000.0
        bounds = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
        for item in self.crossing_rtree.intersection(bounds, objects=True):
            c = item.object
            dist = haversine_distance(lat, lon, c["lat"], c["lon"])
            if dist <= radius_m:
                t_brng = calculate_bearing(lat, lon, c["lat"], c["lon"])
                rel_brng = relative_bearing(heading_deg, t_brng)
                clock = bearing_to_clock_position(rel_brng)
                rel_dir = bearing_to_relative_direction(rel_brng)

                results.append({
                    "id": c["id"],
                    "lat": c["lat"],
                    "lon": c["lon"],
                    "tactile_paving": c.get("tags", {}).get("tactile_paving", "no"),
                    "distance_m": round(dist, 1),
                    "clock_position": clock,
                    "relative_direction": rel_dir
                })

        results.sort(key=lambda x: x["distance_m"])
        return results

    def get_left_right_side_scan(self, lat: float, lon: float, heading_deg: float, radius_m: float = 60.0) -> Dict[str, Any]:
        """
        Scan left and right side house numbers, door number ranges, and alley branches
        relative to the explorer's current heading.
        """
        left_numbers = []
        right_numbers = []
        left_alleys = []
        right_alleys = []

        for h in self.house_numbers:
            dist = haversine_distance(lat, lon, h["lat"], h["lon"])
            if dist <= radius_m:
                brng = calculate_bearing(lat, lon, h["lat"], h["lon"])
                rel_b = relative_bearing(heading_deg, brng)
                clock = bearing_to_clock_position(rel_b)
                rel_dir = bearing_to_relative_direction(rel_b)
                h_num = h["housenumber"]

                item = {
                    "number": h_num,
                    "street": h.get("street", ""),
                    "distance_m": round(dist, 1),
                    "clock": clock,
                    "relative_direction": rel_dir
                }

                if rel_b < 0:
                    left_numbers.append(item)
                else:
                    right_numbers.append(item)

        left_numbers.sort(key=lambda x: x["distance_m"])
        right_numbers.sort(key=lambda x: x["distance_m"])

        for r in self.roads:
            name = r.get("name", "")
            if "巷" in name or "弄" in name:
                geom = r.get("geometry", [])
                if geom:
                    min_d = min(haversine_distance(lat, lon, pt[0], pt[1]) for pt in geom)
                    if min_d <= radius_m:
                        pt = min(geom, key=lambda p: haversine_distance(lat, lon, p[0], p[1]))
                        brng = calculate_bearing(lat, lon, pt[0], pt[1])
                        rel_b = relative_bearing(heading_deg, brng)
                        rel_dir = bearing_to_relative_direction(rel_b)
                        alley_item = {
                            "name": name,
                            "distance_m": round(min_d, 1),
                            "relative_direction": rel_dir
                        }
                        if rel_b < 0 and not any(a["name"] == name for a in left_alleys):
                            left_alleys.append(alley_item)
                        elif rel_b >= 0 and not any(a["name"] == name for a in right_alleys):
                            right_alleys.append(alley_item)

        # 格式化輸出並去除重複門牌 (保留順序)
        left_nums_str = list(dict.fromkeys(f"{x['number']}號" for x in left_numbers[:5]))
        right_nums_str = list(dict.fromkeys(f"{x['number']}號" for x in right_numbers[:5]))

        return {
            "left_side": {
                "house_numbers": left_nums_str,
                "alleys": left_alleys[:3]
            },
            "right_side": {
                "house_numbers": right_nums_str,
                "alleys": right_alleys[:3]
            }
        }

    def get_interpolated_door_numbers(self, lat: float, lon: float, heading_deg: float) -> Dict[str, str]:
        """
        Dynamically interpolate left and right door numbers along current street vector
        when sparse point tags exist (Item 1.1).
        """
        scan = self.get_left_right_side_scan(lat, lon, heading_deg, radius_m=80.0)
        left_nums = [int(re.search(r"\d+", n).group()) for n in scan["left_side"]["house_numbers"] if re.search(r"\d+", n)]
        right_nums = [int(re.search(r"\d+", n).group()) for n in scan["right_side"]["house_numbers"] if re.search(r"\d+", n)]

        left_desc = f"門牌 {min(left_nums)}~{max(left_nums)}號" if left_nums else "沿街門牌估算中"
        right_desc = f"門牌 {min(right_nums)}~{max(right_nums)}號" if right_nums else "沿街門牌估算中"

        if left_nums:
            left_type = "雙號" if all(n % 2 == 0 for n in left_nums) else ("單號" if all(n % 2 != 0 for n in left_nums) else "")
            if left_type:
                left_desc += f" ({left_type})"

        if right_nums:
            right_type = "雙號" if all(n % 2 == 0 for n in right_nums) else ("單號" if all(n % 2 != 0 for n in right_nums) else "")
            if right_type:
                right_desc += f" ({right_type})"

        # Find closest actual house number for concise speech
        closest_door = None
        closest_dist = 999.0
        for h in self.house_numbers:
            d = haversine_distance(lat, lon, h["lat"], h["lon"])
            if d < closest_dist and h.get("housenumber"):
                closest_dist = d
                closest_door = h.get("housenumber")

        concise_door = f"約 {closest_door} 號附近" if (closest_door and closest_dist <= 60.0) else ""

        return {
            "left_side_estimate": left_desc,
            "right_side_estimate": right_desc,
            "concise_door": concise_door
        }

    def get_intersection_clock_bearings(self, lat: float, lon: float, heading_deg: float, radius_m: float = 35.0) -> List[Dict[str, Any]]:
        """
        Detect 3+ multi-way intersections and roundabouts, returning 12-hour clock orientations (Item 1.2).
        """
        branches = []
        seen_roads = set()

        curr_road_info = self.get_road_info(lat, lon, heading_deg)
        curr_name = curr_road_info.get("street_name", "")

        for road in self.roads:
            name = road.get("name", "未命名道路")
            if not name or name in seen_roads:
                continue

            geom = road.get("geometry", [])
            if len(geom) < 2:
                continue

            # Find closest vertex
            min_d = min(haversine_distance(lat, lon, pt[0], pt[1]) for pt in geom)
            if min_d <= radius_m:
                closest_pt = min(geom, key=lambda pt: haversine_distance(lat, lon, pt[0], pt[1]))
                t_brng = calculate_bearing(lat, lon, closest_pt[0], closest_pt[1])
                rel_b = relative_bearing(heading_deg, t_brng)
                clock_pos = bearing_to_clock_position(rel_b)
                rel_dir = bearing_to_relative_direction(rel_b)

                seen_roads.add(name)
                branches.append({
                    "road_name": name,
                    "distance_m": round(min_d, 1),
                    "bearing": t_brng,
                    "clock_position": clock_pos,
                    "relative_direction": rel_dir,
                    "highway_type": road.get("highway_type", "road")
                })

        branches.sort(key=lambda x: x["distance_m"])
        return branches

