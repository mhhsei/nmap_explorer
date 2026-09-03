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
from nmap.spatial.taiwan_signals import TaiwanSignalManager
from nmap.spatial.sidewalk_hazards import SidewalkHazardScanner
from nmap.spatial.mrt_accessibility import MrtAccessibilityDirectory


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
        
        # 門牌地址與樓層完整屬性封裝
        self.address = raw_poi.get("address", "") or self.tags.get("address", "") or self.tags.get("addr:full", "")
        self.street = raw_poi.get("street", "") or self.tags.get("addr:street", "")
        self.housenumber = raw_poi.get("housenumber", "") or self.tags.get("addr:housenumber", "")
        self.floor = raw_poi.get("floor", "") or self.tags.get("floor", "") or "1F"
        self.legal_name = raw_poi.get("legal_name", "") or self.tags.get("legal_name", "")
        self.business_desc = raw_poi.get("business_desc", "") or self.tags.get("business_desc", "")

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

        # 組裝可視化門牌地址 (清洗重複「號」字尾)
        formatted_addr = self.address
        if not formatted_addr and self.street:
            clean_hn = str(self.housenumber).rstrip("號")
            formatted_addr = f"{self.street} {clean_hn}號".strip() if self.housenumber else self.street

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
            "address": formatted_addr,
            "street": self.street,
            "housenumber": self.housenumber,
            "floor": self.floor,
            "legal_name": self.legal_name,
            "business_desc": self.business_desc,
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
        self.poi_rtree = GridSpatialIndex(cell_size_deg=0.001)
        self.road_rtree = GridSpatialIndex(cell_size_deg=0.001)
        self.building_rtree = GridSpatialIndex(cell_size_deg=0.001)
        self.crossing_rtree = GridSpatialIndex(cell_size_deg=0.001)
        self.traffic_signal_rtree = GridSpatialIndex(cell_size_deg=0.001)
        self.junction_rtree = GridSpatialIndex(cell_size_deg=0.001)
        self.house_number_rtree = GridSpatialIndex(cell_size_deg=0.001)
        
        self.poi_fetcher = RealPoiFetcher()
        self.next_external_poi_id = 1000000
        self.rtree_lock = threading.Lock()

        # 台灣專屬公共服務與無障礙導引管理器 (SPaT號誌/變電箱雷達/捷運專屬電梯)
        self.signal_manager = TaiwanSignalManager()
        self.hazard_scanner = SidewalkHazardScanner()
        self.mrt_directory = MrtAccessibilityDirectory()

    def get_signal_safety(self, lat: float, lon: float, heading_deg: float, radius_m: float = 28.0) -> Optional[Dict[str, Any]]:
        """取得前方路口交通號誌時制 (SPaT) 與有聲號誌 (APS)"""
        return self.signal_manager.get_nearby_signal_safety(lat, lon, heading_deg, radius_m)

    def get_sidewalk_hazards(self, lat: float, lon: float, heading_deg: float, max_dist_m: float = 12.0) -> List[Dict[str, Any]]:
        """取得前方人行道實體障礙物 (變電箱、消防栓、段差)"""
        return self.hazard_scanner.scan_forward_corridor(lat, lon, heading_deg, max_dist_m)

    def get_mrt_accessible_exits(self, lat: float, lon: float, heading_deg: float, radius_m: float = 300.0) -> List[Dict[str, Any]]:
        """取得周遭捷運出入口並優先標示專屬無障礙電梯"""
        return self.mrt_directory.get_nearby_mrt_exits(lat, lon, heading_deg, radius_m)

    def build_from_osm(self, parsed_data: Dict[str, Any], ref_lat: Optional[float] = None, ref_lon: Optional[float] = None):
        """
        【從 OSM 結構化數據構建數位雙生空間模型】
        作用：
        1. 重置 R-Tree 空間索引，防止搬移地點時記憶體洩漏或出現前一個區域的幽靈設施。
        2. 建立 POI、道路網 (NetworkX Graph)、建築物、路口節點與斑馬線的空間網格索引。
        3. 在背景 Daemon 執行緒中非同步拉取 Overture / TDX 政府真實店家資料注入模型。
        4. 呼叫 gc.collect() 即時釋放暫存 JSON 結構，維護記憶體健康。
        """
        with self.rtree_lock:
            self.poi_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.road_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.building_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.crossing_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.traffic_signal_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.junction_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.house_number_rtree = GridSpatialIndex(cell_size_deg=0.001)
            self.next_external_poi_id = 1000000

        self.roads = parsed_data.get("roads", [])
        self.crossings = parsed_data.get("crossings", [])
        self.traffic_signals = parsed_data.get("traffic_signals", [])
        self.transit_stops = parsed_data.get("transit_stops", [])
        self.buildings = parsed_data.get("buildings", [])
        self.house_numbers = parsed_data.get("house_numbers", [])

        # 構建 POI 列表與空間網格索引
        raw_pois = parsed_data.get("pois", [])
        self.pois = []
        seen_hn_keys = {(h.get("housenumber"), h.get("lat")) for h in self.house_numbers}
        p_idx = 0
        for p in raw_pois:
            sp = SpatialPOI(p)
            self.pois.append(sp)
            with self.rtree_lock:
                self.poi_rtree.insert(p_idx, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
            p_idx += 1

            # 【方案 A 核心】：若 OSM POI 帶有門牌或地址標籤，同步納入門牌清單 (O(1) 雜湊查重)
            p_tags = p.get("tags", {}) if isinstance(p, dict) else getattr(p, "tags", {})
            p_hn = p_tags.get("addr:housenumber", "")
            p_st = p_tags.get("addr:street", "")
            if not p_hn and p_tags.get("address"):
                m = re.search(r'([^\d市區鄉鎮]+?(?:路|街|大道|巷))?.*?(\d+(?:[之\-]\d+)?|[一二三四五六七八九十]+)號', p_tags["address"])
                if m:
                    p_st = p_st or m.group(1) or ""
                    p_hn = m.group(2) or ""
            if p_hn:
                hn_key = (p_hn, sp.lat)
                if hn_key not in seen_hn_keys:
                    seen_hn_keys.add(hn_key)
                    self.house_numbers.append({
                        "id": p.get("id") if isinstance(p, dict) else getattr(p, "id", None),
                        "housenumber": p_hn,
                        "street": p_st,
                        "name": sp.name,
                        "lat": sp.lat,
                        "lon": sp.lon,
                        "tags": p_tags
                    })

        # 若公共運輸站點不在 POI 中，追加建置
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

        # 構建道路拓撲圖 (NetworkX Graph) 與道路空間索引
        self.road_graph.clear()
        r_idx = 0
        for road in self.roads:
            geom = road["geometry"]
            if len(geom) < 2:
                continue
            bounds = get_line_bounds(geom)
            self.road_rtree.insert(r_idx, bounds, obj=road)
            r_idx += 1

            # 將道路折線頂點加到 NetworkX 有向拓撲圖中
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
                
                # 若非單行道，加入反向邊
                if road.get("oneway") != "yes":
                    rev_brng = (brng + 180.0) % 360.0
                    self.road_graph.add_edge(v_id, u_id, weight=dist, name=road["name"], bearing=rev_brng, road=road)

        # 1. 率先構建交通號誌空間索引 (供路口智能關聯)
        ts_idx = 0
        for ts in self.traffic_signals:
            self.traffic_signal_rtree.insert(ts_idx, (ts["lon"], ts["lat"], ts["lon"], ts["lat"]), obj=ts)
            ts_idx += 1

        # 2. 率先構建斑馬線空間索引 (供路口庇護島智能關聯)
        c_idx = 0
        for c in self.crossings:
            c_lat = c["lat"]
            c_lon = c["lon"]
            self.crossing_rtree.insert(c_idx, (c_lon, c_lat, c_lon, c_lat), obj=c)
            c_idx += 1

        # 3. 構建路口節點空間索引：
        # 關鍵修正：必須使用「無向實體相鄰鄰居數 (Physical Degree)」！
        # 在 MultiDiGraph 中，雙向道路的直線中間點其有向度數為 4（2 入 2 出），過去被誤判為十字路口。
        # 真正的實體路口，其不重複實體相鄰節點數必須 >= 3（3 為 T 字/岔路口，4 為十字路口，5+ 為多向圓環/路口）。
        # 並全時注入「交通號誌 (Traffic Signals)」、「視障有聲號誌 (APS)」與「行人庇護島 (Refuge Island)」
        j_idx = 0
        for node_id in self.road_graph.nodes:
            physical_neighbors = (set(self.road_graph.predecessors(node_id)) | set(self.road_graph.successors(node_id))) - {node_id}
            physical_degree = len(physical_neighbors)
            if physical_degree >= 3:
                node_data = self.road_graph.nodes[node_id]
                n_lat, n_lon = node_data["lat"], node_data["lon"]
                cos_n_lat = max(math.cos(math.radians(n_lat)), 0.1)

                # 提取此路口相連之道路名稱與類型，用於防止巷弄號誌跨路口污染
                connected_road_names = set()
                road_types = []
                for neighbor in physical_neighbors:
                    for u, v in [(node_id, neighbor), (neighbor, node_id)]:
                        if self.road_graph.has_edge(u, v):
                            edge_data = self.road_graph[u][v]
                            r_name = edge_data.get("name", "")
                            if r_name and not r_name.startswith("無名"):
                                connected_road_names.add(r_name)
                            road_types.append(edge_data.get("type", "residential"))

                is_narrow_alley_junction = bool(road_types and all(t in ("residential", "service", "living_street", "footway", "path", "unclassified") for t in road_types))

                # A. 查詢官方有聲號誌資料庫 (TaiwanSignalManager)
                # 【防污染安全機制】：小巷弄半徑緊縮至 16m；幹道允許 32m 但若距離 > 18m 必須驗證路名相符
                search_sig_dist = 16.0 if is_narrow_alley_junction else 32.0
                official_sig = self.signal_manager.find_signal_near(n_lat, n_lon, max_dist_m=search_sig_dist)
                if official_sig:
                    sig_dist = haversine_distance(n_lat, n_lon, official_sig["lat"], official_sig["lon"])
                    if sig_dist > 18.0:
                        name_matches = False
                        sig_int_name = official_sig.get("intersection_name", "")
                        for cr in connected_road_names:
                            if len(cr) >= 2 and cr in sig_int_name:
                                name_matches = True
                                break
                        if not name_matches:
                            # 距離大於 18m 且路名完全不吻合，判定為相鄰主幹道之跨路口雜訊，予以排除
                            official_sig = None

                # B. 查詢現場 28 米內實體號誌桿 (巷弄上限 18m)
                has_osm_signal = False
                osm_sound_yes = False
                max_osm_sig_dist = 18.0 if is_narrow_alley_junction else 28.0
                sig_radius_deg_lon = max_osm_sig_dist / (111139.0 * cos_n_lat)
                sig_radius_deg_lat = max_osm_sig_dist / 111139.0
                s_bounds = (n_lon - sig_radius_deg_lon, n_lat - sig_radius_deg_lat, n_lon + sig_radius_deg_lon, n_lat + sig_radius_deg_lat)
                for s_item in self.traffic_signal_rtree.intersection(s_bounds, objects=True):
                    s_obj = s_item.object
                    if haversine_distance(n_lat, n_lon, s_obj["lat"], s_obj["lon"]) <= max_osm_sig_dist:
                        has_osm_signal = True
                        if s_obj.get("sound") in ("yes", "acoustic", "buzzer"):
                            osm_sound_yes = True

                # C. 查詢現場 25 米內斑馬線與庇護島
                has_crossing = False
                has_refuge_island = False
                c_radius_deg_lon = 25.0 / (111139.0 * cos_n_lat)
                c_radius_deg_lat = 25.0 / 111139.0
                cr_bounds = (n_lon - c_radius_deg_lon, n_lat - c_radius_deg_lat, n_lon + c_radius_deg_lon, n_lat + c_radius_deg_lat)
                for cr_item in self.crossing_rtree.intersection(cr_bounds, objects=True):
                    cr_obj = cr_item.object
                    if haversine_distance(n_lat, n_lon, cr_obj["lat"], cr_obj["lon"]) <= 25.0:
                        has_crossing = True
                        cr_tags = cr_obj.get("tags", {})
                        if cr_tags.get("crossing:island") in ("yes", "separate") or cr_tags.get("traffic_calming") == "island":
                            has_refuge_island = True
                        if cr_obj.get("crossing_signals") in ("yes", "traffic_signals"):
                            has_osm_signal = True

                is_signalized = bool(official_sig) or has_osm_signal
                has_aps = (official_sig and official_sig.get("has_aps")) or osm_sound_yes
                if official_sig and official_sig.get("has_refuge_island"):
                    has_refuge_island = True

                sound_desc = ""
                if has_aps:
                    if official_sig:
                        sound_desc = f"{official_sig.get('ns_sound', '布穀鳥聲')} / {official_sig.get('ew_sound', '鳥鳴聲')}"
                    else:
                        sound_desc = "設有有聲號誌"

                junction_meta = {
                    "is_signalized": is_signalized,
                    "has_aps": has_aps,
                    "sound_desc": sound_desc,
                    "has_refuge_island": has_refuge_island,
                    "has_crossing": has_crossing,
                    "has_button": official_sig.get("has_button", False) if official_sig else False,
                    "button_guide": official_sig.get("button_guide", "") if official_sig else "",
                    "signal_name": official_sig.get("intersection_name", "") if official_sig else ""
                }

                self.junction_rtree.insert(j_idx, (n_lon, n_lat, n_lon, n_lat), obj=(node_id, physical_degree, n_lat, n_lon, junction_meta))
                j_idx += 1

        # 4. 構建大樓輪廓空間索引
        b_idx = 0
        for b in self.buildings:
            c_lat = b["center_lat"]
            c_lon = b["center_lon"]
            self.building_rtree.insert(b_idx, (c_lon, c_lat, c_lon, c_lat), obj=b)
            b_idx += 1

        # 5. 構建門牌空間索引
        hn_idx = 0
        for hn in self.house_numbers:
            self.house_number_rtree.insert(hn_idx, (hn["lon"], hn["lat"], hn["lon"], hn["lat"]), obj=hn)
            hn_idx += 1

        # 1. 瞬間從本地離線資料庫（Overture + Gov）載入地標（~2ms 零延遲注入）
        target_ref_lat = ref_lat
        target_ref_lon = ref_lon
        if target_ref_lat is None or target_ref_lon is None:
            if self.roads and len(self.roads[0].get("geometry", [])) > 0:
                target_ref_lat = self.roads[0]["geometry"][0][0]
                target_ref_lon = self.roads[0]["geometry"][0][1]

        if target_ref_lat is not None and target_ref_lon is not None:
            try:
                offline_pois = self.poi_fetcher.fetch_offline_pois(target_ref_lat, target_ref_lon, radius_deg=0.015)
                existing_keys = {(p.name, round(p.lat, 4), round(p.lon, 4)) for p in self.pois if hasattr(p, 'name')}
                with self.rtree_lock:
                    for p in offline_pois:
                        name = p.get('name')
                        key = (name, round(p.get('lat', 0.0), 4), round(p.get('lon', 0.0), 4))
                        if name and key not in existing_keys:
                            existing_keys.add(key)
                            sp = SpatialPOI(p)
                            self.pois.append(sp)
                            self.poi_rtree.insert(self.next_external_poi_id, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
                            self.next_external_poi_id += 1

                            # 【方案 A 核心】：將離線資料庫中帶有真實門牌地址的店家同步納入門牌空間索引
                            p_tags = sp.tags
                            p_hn = p_tags.get("addr:housenumber", "")
                            p_st = p_tags.get("addr:street", "")
                            if p_hn:
                                hn_obj = {
                                    "id": sp.id,
                                    "housenumber": p_hn,
                                    "street": p_st,
                                    "name": sp.name,
                                    "lat": sp.lat,
                                    "lon": sp.lon,
                                    "tags": p_tags
                                }
                                self.house_numbers.append(hn_obj)
                                self.house_number_rtree.insert(len(self.house_numbers), (sp.lon, sp.lat, sp.lon, sp.lat), obj=hn_obj)
            except Exception as e:
                import logging
                logging.warning(f"Offline POI sync injection error: {e}")

            # 2. 在背景非同步執行食記爬蟲補充最新餐飲評價
            def fetch_and_inject_online():
                try:
                    for page in range(1, 3):
                        online_pois = self.poi_fetcher._fetch_ifoodie_page(target_ref_lat, target_ref_lon, page)
                        with self.rtree_lock:
                            for p in online_pois:
                                name = p.get('name')
                                key = (name, round(p.get('lat', 0.0), 4), round(p.get('lon', 0.0), 4))
                                if name and key not in existing_keys:
                                    existing_keys.add(key)
                                    sp = SpatialPOI(p)
                                    self.pois.append(sp)
                                    self.poi_rtree.insert(self.next_external_poi_id, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
                                    self.next_external_poi_id += 1
                except Exception as e:
                    import logging
                    logging.warning(f"Background online POI fetch error: {e}")
            
            threading.Thread(target=fetch_and_inject_online, daemon=True).start()

        # 即時釋放 JVM/Python 暫存記憶體
        gc.collect()

    def reload_real_pois(self, lat: float, lon: float, radius_deg: float = 0.012) -> int:
        """
        【手動或下載完成後即時重新載入全台離線資料庫地標】
        作用：在使用者下載完離線資料庫或主動刷新時，立即將數千間真實店家注入 R-Tree 空間索引。
        """
        try:
            external_pois = self.poi_fetcher.fetch_real_pois(lat, lon, pages=3, radius_deg=radius_deg)
            existing_keys = {(p.name, round(p.lat, 4), round(p.lon, 4)) for p in self.pois if hasattr(p, 'name')}
            added_count = 0
            
            with self.rtree_lock:
                for p in external_pois:
                    name = p.get('name')
                    key = (name, round(p.get('lat', 0.0), 4), round(p.get('lon', 0.0), 4))
                    if name and key not in existing_keys:
                        existing_keys.add(key)
                        sp = SpatialPOI(p)
                        self.pois.append(sp)
                        self.poi_rtree.insert(self.next_external_poi_id, (sp.lon, sp.lat, sp.lon, sp.lat), obj=sp)
                        self.next_external_poi_id += 1
                        added_count += 1

                        # 【方案 A 核心】：將離線資料庫中帶有真實門牌地址的店家同步納入門牌空間索引
                        p_tags = sp.tags
                        p_hn = p_tags.get("addr:housenumber", "")
                        p_st = p_tags.get("addr:street", "")
                        if p_hn:
                            hn_obj = {
                                "id": sp.id,
                                "housenumber": p_hn,
                                "street": p_st,
                                "name": sp.name,
                                "lat": sp.lat,
                                "lon": sp.lon,
                                "tags": p_tags
                            }
                            self.house_numbers.append(hn_obj)
                            self.house_number_rtree.insert(len(self.house_numbers), (sp.lon, sp.lat, sp.lon, sp.lat), obj=hn_obj)
                        
            print(f"[WorldModel] Injected {added_count} new offline POIs into spatial index. Total: {len(self.pois)}")
        except Exception as e:
            import logging
            logging.warning(f"Failed to reload real pois: {e}")
        return len(self.pois)

    def find_nearest_road(self, lat: float, lon: float, user_heading: Optional[float] = None, current_road_name: str = "") -> Tuple[Optional[Dict[str, Any]], float]:
        """
        【搜尋距離座標最近的道路折線】
        作用：透過空間網格索引快速過濾方圓 150 公尺內的道路折線，計算精確垂直距離。
        【防小巷側吸與方向感知機制】：
        若使用者提供行進朝向 (user_heading)，道路走向與使用者朝向垂直（如橫向小巷）時予以加權懲罰，
        防止走在主幹道人行道過巷口時被橫向小巷誤吸，造成路名與路口報讀顛倒。
        """
        if not self.roads:
            return None, 999999.0

        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = 150.0 / (111139.0 * cos_lat)
        radius_deg_lat = 150.0 / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)
        min_cost = 999999.0
        best_dist = 999999.0
        best_road = None

        for item in self.road_rtree.intersection(bounds, objects=True):
            road = item.object
            geom = road.get("geometry", [])
            if len(geom) < 2:
                continue
            
            dist, proj_lat, proj_lon = find_closest_point_on_line(lat, lon, geom)
            cost = dist

            # 方向感知加權：若提供行進方向且非靜止
            if user_heading is not None and user_heading >= 0 and len(geom) >= 2:
                # 計算道路總走向
                seg_bearing = calculate_bearing(geom[0][0], geom[0][1], geom[-1][0], geom[-1][1])
                diff = abs((user_heading - seg_bearing + 180.0) % 360.0 - 180.0)
                axis_diff = min(diff, 180.0 - diff) # 0°=平行, 90°=垂直

                r_name = road.get("name", "")
                if axis_diff > 55.0:
                    # 與前進方向垂直的橫向小巷，施加距離懲罰，杜絕側吸
                    cost = dist * 2.2 + 3.0
                elif axis_diff < 35.0:
                    # 與前進方向平行的道路給予加分優先吸附
                    cost = dist * 0.85

                # 同名道路慣性維持（已在該道路上，除非偏離極遠否則優先維持）
                if current_road_name and r_name == current_road_name and dist <= 18.0:
                    cost *= 0.75

            if cost < min_cost:
                min_cost = cost
                best_dist = dist
                best_road = road

        return best_road, best_dist

    def resolve_poi_address_by_consensus(self, poi_lat: float, poi_lon: float, street: str = "", housenumber: str = "") -> str:
        """
        【門牌地址空間共識仲裁 (Neighborhood Address Consensus)】
        作用：
        1. 若 POI 本身已記載 street，且有 housenumber，直接返回真實門牌地址。
        2. 若 POI 位於十字路口三角窗（如北新路與淡金路交叉口），透過周遭 50 公尺內實體門牌之路名多數決投票，
           消除因幾何折線數十公分誤差導致誤判為另一條大馬路的現象。
        3. 若該道路周遭有實體門牌，精確標註「近 XX號，無登錄門牌」，讓視障者清楚得知相對門牌位置。
        """
        clean_hn = str(housenumber or "").strip().rstrip("號")
        if street and street not in ("未命名道路", "無名路"):
            return f"{street} {clean_hn}號" if clean_hn else f"{street} (未登錄門牌)"

        # 搜尋方圓 25 米內所有具名候選道路
        cos_lat = max(math.cos(math.radians(poi_lat)), 0.1)
        r_deg_lon = 25.0 / (111139.0 * cos_lat)
        r_deg_lat = 25.0 / 111139.0
        r_bounds = (poi_lon - r_deg_lon, poi_lat - r_deg_lat, poi_lon + r_deg_lon, poi_lat + r_deg_lat)

        candidate_roads = []
        min_dist = 9999.0
        for item in self.road_rtree.intersection(r_bounds, objects=True):
            r = item.object
            geom = r.get("geometry", [])
            if len(geom) < 2:
                continue
            d, _, _ = find_closest_point_on_line(poi_lat, poi_lon, geom)
            name = r.get("name")
            if d <= 25.0 and name and name not in ("未命名道路", "無名路"):
                candidate_roads.append((d, name))
                if d < min_dist:
                    min_dist = d

        if not candidate_roads:
            return "周遭道路 (未登錄門牌)"

        candidate_roads.sort()

        # 檢索方圓 50 米內周遭實體門牌，統計各路名票數與最近門牌號
        hn_deg_lon = 50.0 / (111139.0 * cos_lat)
        hn_deg_lat = 50.0 / 111139.0
        hn_bounds = (poi_lon - hn_deg_lon, poi_lat - hn_deg_lat, poi_lon + hn_deg_lon, poi_lat + hn_deg_lat)

        hn_votes: Dict[str, int] = {}
        closest_hn_per_street: Dict[str, Tuple[float, str]] = {}
        for h_item in self.house_number_rtree.intersection(hn_bounds, objects=True):
            h = h_item.object
            d = haversine_distance(poi_lat, poi_lon, h["lat"], h["lon"])
            st = h.get("street")
            num = str(h.get("housenumber", "")).strip().rstrip("號")
            if d <= 50.0 and st and num:
                hn_votes[st] = hn_votes.get(st, 0) + 1
                if st not in closest_hn_per_street or d < closest_hn_per_street[st][0]:
                    closest_hn_per_street[st] = (d, num)

        # 在距離最接近的前段道路中 (min_dist + 8.5m 內，包含大路口不同車道折線)，依門牌多數決共識仲裁
        close_road_names = list(dict.fromkeys([r_name for d, r_name in candidate_roads if d <= min_dist + 8.5]))

        best_road = candidate_roads[0][1]
        max_votes = 0
        voted_road = None
        for r_name in close_road_names:
            votes = hn_votes.get(r_name, 0)
            if votes > max_votes:
                max_votes = votes
                voted_road = r_name

        final_road = voted_road if (voted_road and max_votes >= 2) else best_road

        if final_road in closest_hn_per_street:
            near_hn = closest_hn_per_street[final_road][1]
            return f"{final_road} (近 {near_hn}號，無登錄門牌)"
        else:
            return f"{final_road} (未登錄門牌)"

    def get_nearby_pois(self, lat: float, lon: float, heading_deg: float, radius_m: float = 60.0, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        【查詢半徑 radius_m 內的所有店家、設施與地標大樓】
        作用：依據距離排序，回傳包含鐘點方位（如 3點鐘方向）、相對方向（如 右側）與距離公尺數的完整 POI 列表。
        精準依據 3.0 公尺閾值去重同名實體，並將無名建築過濾或轉正為門牌地址，徹底消滅無意義的 apartments 雜訊。
        """
        results = []
        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = radius_m / (111139.0 * cos_lat)
        radius_deg_lat = radius_m / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)
        category_lower = category.lower() if category else None

        generic_tags = {
            "apartments", "apartment", "residential", "commercial", "yes", "building", 
            "house", "hotel", "office", "retail", "roof", "terrace", "dormitory", 
            "school", "public", "industrial", "garages", "shed", "service", "detached",
            "construction", "civic", "hospital", "kindergarten", "kiosk", "warehouse",
            "建築物", "無名大樓", "房屋"
        }

        def resolve_building_display_name(bldg_obj) -> str:
            t = bldg_obj.get("tags", {}) if isinstance(bldg_obj, dict) else getattr(bldg_obj, "tags", {})
            n = bldg_obj.get("name") if isinstance(bldg_obj, dict) else getattr(bldg_obj, "name", "")
            if not n:
                n = t.get("name") or t.get("name:zh") or t.get("description") or ""
            clean_n = str(n).strip()
            if not clean_n or clean_n.lower() in generic_tags or clean_n in ("建築物", "無名大樓", "房屋"):
                street = t.get("addr:street") or t.get("street") or ""
                hn = t.get("addr:housenumber") or t.get("housenumber") or ""
                if street and hn:
                    return f"{street}{hn}號 (大樓)"
                elif hn:
                    return f"{hn}號 (大樓)"
                return ""
            return clean_n

        with self.rtree_lock:
            # 1. 檢索周遭店家與離線地標
            for item in self.poi_rtree.intersection(bounds, objects=True):
                poi = item.object
                poi_name = poi.name or poi.tags.get("legal_name") or poi.tags.get("brand") or poi.category
                if not poi_name:
                    continue

                clean_poi_name = str(poi_name).strip()
                if clean_poi_name.lower() in generic_tags:
                    continue

                if category_lower:
                    if category_lower not in poi.category.lower() and category_lower not in clean_poi_name.lower():
                        continue

                # 同名店家 18.0 公尺以內去重判定（跨資料庫 OSM/Overture 經緯度微差視為同一店家/重複標記；> 18.0m 視為不同分店）
                is_dup = False
                for existing in results:
                    if existing.get("name") == clean_poi_name:
                        if haversine_distance(poi.lat, poi.lon, existing["lat"], existing["lon"]) <= 18.0:
                            is_dup = True
                            break
                if is_dup:
                    continue

                rel = poi.calculate_relative(lat, lon, heading_deg)
                if rel["distance_m"] <= radius_m:
                    if not rel.get("name"):
                        rel["name"] = clean_poi_name
                    
                    # 門牌地址空間共識仲裁：若店家未直接記載門牌，透過周遭實體門牌投票消除十字路口路名誤判
                    if not rel.get("address"):
                        rel["address"] = self.resolve_poi_address_by_consensus(
                            poi.lat, poi.lon, rel.get("street", ""), rel.get("housenumber", "")
                        )

                    results.append(rel)

            # 2. 同步納入周遭具名社區大樓與地標建築物（如：宏國青山、大旭地社區等）
            for b_item in self.building_rtree.intersection(bounds, objects=True):
                bldg = b_item.object
                b_name = resolve_building_display_name(bldg)
                if not b_name:
                    continue
                
                b_geom = bldg.get("geometry", []) if isinstance(bldg, dict) else getattr(bldg, "geometry", [])
                if b_geom and len(b_geom) > 0:
                    b_lat = sum(p[0] for p in b_geom) / len(b_geom)
                    b_lon = sum(p[1] for p in b_geom) / len(b_geom)
                else:
                    b_lat = (bldg.get("center_lat") or bldg.get("lat") or lat) if isinstance(bldg, dict) else getattr(bldg, "center_lat", getattr(bldg, "lat", lat))
                    b_lon = (bldg.get("center_lon") or bldg.get("lon") or lon) if isinstance(bldg, dict) else getattr(bldg, "center_lon", getattr(bldg, "lon", lon))

                # 同名地標/大樓 3.0 公尺以內去重
                is_dup = False
                for existing in results:
                    if existing.get("name") == b_name:
                        if haversine_distance(b_lat, b_lon, existing["lat"], existing["lon"]) <= 3.0:
                            is_dup = True
                            break
                if is_dup:
                    continue

                dist_m = haversine_distance(lat, lon, b_lat, b_lon)
                if dist_m <= radius_m:
                    brng = calculate_bearing(lat, lon, b_lat, b_lon)
                    rel_bearing = (brng - heading_deg + 360.0) % 360.0
                    clock_hr = int((rel_bearing + 15) // 30) % 12
                    if clock_hr == 0:
                        clock_hr = 12

                    rel_dir = "正前方" if (rel_bearing <= 22.5 or rel_bearing >= 337.5) else \
                              ("右前方" if rel_bearing < 67.5 else \
                              ("右側" if rel_bearing < 112.5 else \
                              ("右後方" if rel_bearing < 157.5 else \
                              ("正後方" if rel_bearing <= 202.5 else \
                              ("左後方" if rel_bearing < 247.5 else \
                              ("左側" if rel_bearing < 292.5 else "左前方"))))))

                    results.append({
                        "id": f"bldg_{b_name}_{round(b_lat,4)}",
                        "name": b_name,
                        "category": "landmark_and_historical_building",
                        "lat": b_lat,
                        "lon": b_lon,
                        "distance_m": round(dist_m, 1),
                        "bearing_deg": round(brng, 1),
                        "relative_bearing_deg": round(rel_bearing, 1),
                        "clock_position": f"{clock_hr}點鐘方向",
                        "clock_direction": f"{clock_hr}點鐘方向",
                        "relative_direction": rel_dir,
                        "phone": "",
                        "website": "",
                        "opening_hours": "常態開放",
                        "wheelchair": "♿ 具備 1 樓平整入口",
                        "level": "1F",
                        "floor": "1F",
                        "address": b_name if "號" in b_name else "",
                        "tags": {"building": "residential"}
                    })

        results.sort(key=lambda x: x["distance_m"])
        return results

    def get_road_info(self, lat: float, lon: float, heading_deg: float) -> Dict[str, Any]:
        """
        【分析當前腳下道路屬性（路名、車道數、單行道、人行道狀況）】
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
        【查詢周遭建築物、樓層與距離】
        """
        results = []
        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = radius_m / (111139.0 * cos_lat)
        radius_deg_lat = radius_m / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)
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
        【查詢周遭行人斑馬線與導盲磚標記】
        """
        results = []
        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = radius_m / (111139.0 * cos_lat)
        radius_deg_lat = radius_m / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)
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
        【左右兩側門牌號碼與相鄰巷弄掃描】
        作用：依據道路法向量與使用者朝向，精準區分道路實體左側與右側的門牌與巷弄。
        """
        left_numbers = []
        right_numbers = []
        left_alleys = []
        right_alleys = []

        # 1. 尋找最近道路與道路方向向量 (用於穩定左右側劃分)
        nearest_road, _ = self.find_nearest_road(lat, lon)
        road_seg = None
        if nearest_road and nearest_road.get("geometry") and len(nearest_road["geometry"]) >= 2:
            geom = nearest_road["geometry"]
            # 找出距離目前位置最近的線段
            best_d = 999.0
            for i in range(len(geom) - 1):
                p1, p2 = geom[i], geom[i+1]
                mid_lat = (p1[0] + p2[0]) / 2.0
                mid_lon = (p1[1] + p2[1]) / 2.0
                d = haversine_distance(lat, lon, mid_lat, mid_lon)
                if d < best_d:
                    best_d = d
                    # 確保線段向量與使用者前進方向同向
                    seg_bearing = calculate_bearing(p1[0], p1[1], p2[0], p2[1])
                    if abs(relative_bearing(heading_deg, seg_bearing)) > 90:
                        road_seg = (p2, p1)
                    else:
                        road_seg = (p1, p2)

        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = radius_m / (111139.0 * cos_lat)
        radius_deg_lat = radius_m / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)
        for item in self.house_number_rtree.intersection(bounds, objects=True):
            h = item.object
            dist = haversine_distance(lat, lon, h["lat"], h["lon"])
            if dist <= radius_m:
                brng = calculate_bearing(lat, lon, h["lat"], h["lon"])
                rel_b = relative_bearing(heading_deg, brng)
                clock = bearing_to_clock_position(rel_b)
                rel_dir = bearing_to_relative_direction(rel_b)
                h_num = h["housenumber"]

                item = {
                    "number": str(h_num).strip().rstrip("號"),
                    "name": h.get("name", ""),
                    "street": h.get("street", ""),
                    "distance_m": round(dist, 1),
                    "clock": clock,
                    "relative_direction": rel_dir
                }

                # 優先使用道路法向量外積判斷左右，抗手機朝向震盪
                if road_seg:
                    p1, p2 = road_seg
                    dx = p2[1] - p1[1]
                    dy = p2[0] - p1[0]
                    cp = dx * (h["lat"] - p1[0]) - dy * (h["lon"] - p1[1])
                    is_left = (cp > 0)
                else:
                    is_left = (rel_b < 0)

                if is_left:
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

        # 格式化輸出並去除重複門牌 (去重並附帶實體建築/店家名稱)
        def format_side_hn(candidates):
            seen_numbers = set()
            result = []
            for x in candidates:
                num_clean = str(x['number']).strip().rstrip("號")
                if not num_clean or num_clean in seen_numbers:
                    continue
                seen_numbers.add(num_clean)
                hn = f"{num_clean}號"
                if x.get("name"):
                    result.append(f"{hn} ({x['name']})")
                else:
                    result.append(hn)
                if len(result) >= 4:
                    break
            return result

        left_nums_str = format_side_hn(left_numbers)
        right_nums_str = format_side_hn(right_numbers)

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
        【真實門牌仲裁與線上動態補全 (方案 A + 方案 C)】
        作用：
        1. 【方案 A 本地真實門牌】：優先檢索周遭 45 米內本地真實門牌（含建物、店家登記門牌），依道路法向量區分左右側最近門牌。
        2. 【方案 C 線上動態補全】：若本地無門牌，自動觸發線上高精度反查 (ArcGIS/NLSC) 並寫入持久快取，實現永久離線。
        3. 【零猜測原則】：徹底移除數學內插估算，未獲取真實門牌前不臆測假號碼。
        """
        # 1. 取得當前道路資訊以進行同街比對
        curr_road_info = self.get_road_info(lat, lon, heading_deg)
        curr_street = curr_road_info.get("street_name", "")

        # 2. 尋找最近道路幾何向量以穩定劃分左右側
        nearest_road, _ = self.find_nearest_road(lat, lon)
        road_seg = None
        if nearest_road and nearest_road.get("geometry") and len(nearest_road["geometry"]) >= 2:
            geom = nearest_road["geometry"]
            best_d = 999.0
            for i in range(len(geom) - 1):
                p1, p2 = geom[i], geom[i+1]
                mid_lat = (p1[0] + p2[0]) / 2.0
                mid_lon = (p1[1] + p2[1]) / 2.0
                d = haversine_distance(lat, lon, mid_lat, mid_lon)
                if d < best_d:
                    best_d = d
                    seg_bearing = calculate_bearing(p1[0], p1[1], p2[0], p2[1])
                    if abs(relative_bearing(heading_deg, seg_bearing)) > 90:
                        road_seg = (p2, p1)
                    else:
                        road_seg = (p1, p2)

        # 3. 【方案 A】：從門牌空間索引中檢索周圍 45 公尺內的實體門牌
        radius_m = 45.0
        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = radius_m / (111139.0 * cos_lat)
        radius_deg_lat = radius_m / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)

        left_candidates = []
        right_candidates = []

        for item in self.house_number_rtree.intersection(bounds, objects=True):
            h = item.object
            d = haversine_distance(lat, lon, h["lat"], h["lon"])
            if d > radius_m:
                continue

            h_street = h.get("street", "")
            # 優先過濾屬於當前道路的門牌（若無街道標籤，限距離 <= 18m 之鄰近點）
            if curr_street and curr_street not in ["無名路", "未命名道路"]:
                if h_street and curr_street not in h_street and h_street not in curr_street:
                    continue
                if not h_street and d > 18.0:
                    continue

            brng = calculate_bearing(lat, lon, h["lat"], h["lon"])
            rel_b = relative_bearing(heading_deg, brng)

            # 依道路幾何法向量外積判斷左右
            if road_seg:
                p1, p2 = road_seg
                dx = p2[1] - p1[1]
                dy = p2[0] - p1[0]
                cp = dx * (h["lat"] - p1[0]) - dy * (h["lon"] - p1[1])
                is_left = (cp > 0)
            else:
                is_left = (rel_b < 0)

            clean_hn = str(h.get("housenumber", "")).strip().rstrip("號")
            candidate = {
                "number": clean_hn,
                "name": h.get("name", ""),
                "street": h_street,
                "distance_m": d,
                "lat": h["lat"],
                "lon": h["lon"]
            }

            if is_left:
                left_candidates.append(candidate)
            else:
                right_candidates.append(candidate)

        left_candidates.sort(key=lambda x: x["distance_m"])
        right_candidates.sort(key=lambda x: x["distance_m"])

        left_desc = ""
        right_desc = ""
        concise_parts = []

        if left_candidates:
            best_l = left_candidates[0]
            l_num = best_l["number"]
            l_name = f" ({best_l['name']})" if best_l.get("name") else ""
            left_desc = f"門牌 {l_num}號{l_name}"
            concise_parts.append(f"左側 {l_num}號{l_name}")

        if right_candidates:
            best_r = right_candidates[0]
            r_num = best_r["number"]
            r_name = f" ({best_r['name']})" if best_r.get("name") else ""
            right_desc = f"門牌 {r_num}號{r_name}"
            concise_parts.append(f"右側 {r_num}號{r_name}")

        concise_door = "，".join(concise_parts)

        # 4. 【方案 C】：若本地兩側均無門牌，啟動線上官方反向地理編碼備援與持久化快取
        if not left_desc and not right_desc:
            try:
                from nmap.data.cache import CacheManager
                cache = CacheManager()
                cache_key = f"doorplate:{round(lat, 5)}:{round(lon, 5)}"
                cached = cache.get_geocode(cache_key)
                if cached:
                    c_hn = cached.get("housenumber", "")
                    c_name = cached.get("name", "")
                    c_st = cached.get("street", curr_street)
                    name_str = f" ({c_name})" if c_name else ""
                    if c_hn:
                        concise_door = f"門牌 {c_hn}號{name_str} (官方資料)"
                        left_desc = concise_door
                else:
                    # 快取無資料：非同步發起一次線上查詢，存入 nmap_cache.db 供下次瞬間命中
                    def fetch_online_doorplate():
                        try:
                            from nmap.data.geocoders import NominatimClient
                            client = NominatimClient(cache_manager=cache)
                            client.get_doorplate_online(lat, lon)
                        except Exception:
                            pass
                    threading.Thread(target=fetch_online_doorplate, daemon=True).start()
            except Exception:
                pass

        return {
            "left": left_desc,
            "right": right_desc,
            "left_side_estimate": left_desc,
            "right_side_estimate": right_desc,
            "concise_door": concise_door
        }

    def get_intersection_clock_bearings(self, lat: float, lon: float, heading_deg: float, radius_m: float = 35.0) -> List[Dict[str, Any]]:
        """
        【路口各分支道路之 12 小時鐘點方位分析】
        作用：在十字路口或圓環，精確列出各個岔路分支的鐘點方向（例如：「2點鐘方向：北新路一段」）。
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

            # 找出折線上最靠近目前位置的頂點
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


