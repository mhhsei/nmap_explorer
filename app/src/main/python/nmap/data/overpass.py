"""
OpenStreetMap 與 Overpass API 即時空間圖資下載客戶端 (Overpass Client)

作用：
1. 建立 Overpass QL 語法查詢周遭 100% 真實設施（道路、店家、人行道、斑馬線、紅綠燈、導盲磚、大樓、門牌號）。
2. 雙重下載機制：優先呼叫官方 OSM Main API (< 1.5s)，失敗時自動由多組 Overpass 鏡像伺服器平行競速下載。
3. 將 XML/JSON 原始資料解析為結構化地圖元素（道路網、POI、過馬路設施、建物拓撲）。
"""
import requests
from typing import Optional, Dict, Any, List, Tuple
from nmap.data.cache import CacheManager
from nmap.spatial.geometry import haversine_distance

OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter"
]
DEFAULT_USER_AGENT = "nmap-blind-world-explorer/1.0 (accessibility-gis-engine)"


class OverpassClient:
    """
    OSM / Overpass 空間圖資客戶端
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.cache = cache_manager or CacheManager()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})

    def build_query(self, lat: float, lon: float, radius_m: float) -> str:
        """
        【構建完整的 Overpass QL 空間查詢語法】
        作用：一次性抓取方圓半徑內的道路 (highway)、店家 (shop)、設施 (amenity)、辦公室 (office)、
        醫療 (healthcare)、大樓外框 (building)、公車站牌與斑馬線。
        """
        r = int(radius_m)
        query = f"""
        [out:json][timeout:5];
        (
          way["highway"](around:{r},{lat},{lon});
          node["highway"](around:{r},{lat},{lon});
          node["amenity"](around:{r},{lat},{lon});
          way["amenity"](around:{r},{lat},{lon});
          node["shop"](around:{r},{lat},{lon});
          way["shop"](around:{r},{lat},{lon});
          node["office"](around:{r},{lat},{lon});
          way["office"](around:{r},{lat},{lon});
          node["craft"](around:{r},{lat},{lon});
          node["tourism"](around:{r},{lat},{lon});
          node["leisure"](around:{r},{lat},{lon});
          node["healthcare"](around:{r},{lat},{lon});
          way["healthcare"](around:{r},{lat},{lon});
          node["service"](around:{r},{lat},{lon});
          node["name"](around:{r},{lat},{lon});
          way["name"](around:{r},{lat},{lon});
          node["public_transport"](around:{r},{lat},{lon});
          node["railway"](around:{r},{lat},{lon});
          way["building"](around:{r},{lat},{lon});
          node["barrier"](around:{r},{lat},{lon});
          way["barrier"](around:{r},{lat},{lon});
          node["entrance"](around:{r},{lat},{lon});
        );
        out body;
        >;
        out skel qt;
        """
        return query

    def fetch_area_data(self, lat: float, lon: float, radius_m: float = 200.0) -> Dict[str, Any]:
        """
        【下載指定經緯度周遭的地圖圖資】
        
        策略：
        1. 優先檢查本機 SQLite 快取，命中時 0 秒回傳。
        2. 第一通道：呼叫官方 OSM XML API（速度最快 < 1.5s）。
        3. 第二通道：若官方 API 失敗，使用 ThreadPool 同時請求 3 組 Overpass 鏡像，誰先回傳就用誰。
        """
        grid_lat = round(lat, 3)
        grid_lon = round(lon, 3)
        cache_key = f"overpass:{grid_lat},{grid_lon}"

        cached = self.cache.get_overpass(cache_key)
        if cached:
            return cached

        # 1. 第一通道：官方 OpenStreetMap 資料庫 API (XML 格式)
        try:
            effective_r = min(radius_m, 180.0)
            d_deg = effective_r / 111000.0
            min_lon, max_lon = lon - d_deg, lon + d_deg
            min_lat, max_lat = lat - d_deg, lat + d_deg
            osm_url = f"https://api.openstreetmap.org/api/0.6/map?bbox={min_lon:.5f},{min_lat:.5f},{max_lon:.5f},{max_lat:.5f}"
            
            resp = self.session.get(osm_url, timeout=3.5)
            if resp.status_code == 200 and len(resp.content) > 100:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                elements = []

                for node in root.findall("node"):
                    n_id = int(node.attrib["id"])
                    n_lat = float(node.attrib["lat"])
                    n_lon = float(node.attrib["lon"])
                    tags = {t.attrib["k"]: t.attrib["v"] for t in node.findall("tag")}
                    elements.append({"type": "node", "id": n_id, "lat": n_lat, "lon": n_lon, "tags": tags})

                for way in root.findall("way"):
                    w_id = int(way.attrib["id"])
                    nodes = [int(nd.attrib["ref"]) for nd in way.findall("nd")]
                    tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
                    elements.append({"type": "way", "id": w_id, "nodes": nodes, "tags": tags})

                res = {"elements": elements}
                if len(elements) > 0:
                    self.cache.set_overpass(cache_key, res)
                    return res
        except Exception as e:
            pass

        # 2. 第二通道備援：平行多鏡像 Overpass 競速
        query = self.build_query(lat, lon, radius_m)

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fetch_endpoint(ep: str):
            try:
                resp = self.session.post(ep, data={"data": query}, timeout=(1.0, 2.5))
                if resp.status_code == 200:
                    data = resp.json()
                    if "elements" in data and len(data["elements"]) > 0:
                        return data
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=len(OVERPASS_ENDPOINTS)) as executor:
            futures = [executor.submit(_fetch_endpoint, ep) for ep in OVERPASS_ENDPOINTS]
            try:
                for future in as_completed(futures, timeout=2.8):
                    res = future.result()
                    if res:
                        self.cache.set_overpass(cache_key, res)
                        return res
            except Exception:
                pass

        return {"elements": []}

    def parse_elements(self, raw_data: Dict[str, Any], center_lat: float, center_lon: float) -> Dict[str, List[Dict[str, Any]]]:
        """
        【解析 OSM 原始元素並分類整理】
        
        輸出結構：
        - roads: 道路列表（含車道數、單行道、人行道鋪面）
        - pois: 店家與設施列表（含營業時間、電話、輪椅無障礙標籤）
        - crossings: 行人斑馬線與號誌節點
        - transit_stops: 公車站牌與捷運站出口
        - buildings: 建築物幾何輪廓與樓層
        - house_numbers: 沿街門牌號碼
        """

        elements = raw_data.get("elements", [])
        
        nodes_dict: Dict[int, Tuple[float, float, Dict[str, str]]] = {}
        for elem in elements:
            if elem.get("type") == "node":
                nodes_dict[elem["id"]] = (elem["lat"], elem["lon"], elem.get("tags", {}))

        roads = []
        pois = []
        crossings = []
        traffic_signals = []
        transit_stops = []
        buildings = []
        house_numbers = []
        barriers = []
        entrances = []
        steps = []
        micro_amenities = []

        # Parse nodes for standalone POIs, crossings, transit, and house numbers
        for node_id, (lat, lon, tags) in nodes_dict.items():
            if "addr:housenumber" in tags or "addr:street" in tags:
                street = tags.get("addr:street", "")
                place = tags.get("addr:place", "")
                if "巷" in place or "弄" in place:
                    street = street + place if street else place
                elif not street:
                    street = place

                house_numbers.append({
                    "id": node_id,
                    "housenumber": tags.get("addr:housenumber", ""),
                    "street": street,
                    "lat": lat,
                    "lon": lon,
                    "tags": tags
                })

            hw = tags.get("highway")
            if hw == "crossing":
                crossing_signals = tags.get("crossing:signals", "no")
                is_sig_crossing = crossing_signals in ("yes", "traffic_signals") or tags.get("crossing") == "traffic_signals"
                crossings.append({
                    "id": node_id,
                    "lat": lat,
                    "lon": lon,
                    "crossing_type": tags.get("crossing", "unspecified"),
                    "crossing_signals": "yes" if is_sig_crossing else crossing_signals,
                    "tactile_paving": tags.get("tactile_paving", "unknown"),
                    "tags": tags
                })
                # 若斑馬線明確設有行人紅綠燈號誌，同步納入交通號誌列表
                if is_sig_crossing:
                    has_sound = tags.get("traffic_signals:sound") in ("yes", "acoustic", "buzzer") or tags.get("sound") in ("yes", "acoustic", "buzzer")
                    has_btn = tags.get("button_operated") == "yes" or tags.get("traffic_signals:button") == "yes"
                    traffic_signals.append({
                        "id": node_id,
                        "name": tags.get("name") or "行人專用號誌 (斑馬線)",
                        "lat": lat,
                        "lon": lon,
                        "sound": "yes" if has_sound else tags.get("sound", "unknown"),
                        "has_sound": has_sound,
                        "has_button": has_btn,
                        "signal_type": "行人專用號誌",
                        "tags": tags
                    })
            elif hw == "traffic_signals":
                has_sound = tags.get("traffic_signals:sound") in ("yes", "acoustic", "buzzer") or tags.get("sound") in ("yes", "acoustic", "buzzer")
                has_btn = tags.get("button_operated") == "yes" or tags.get("traffic_signals:button") == "yes"
                sig_type = "閃光號誌" if tags.get("traffic_signals") == "blink" or tags.get("flashing") == "yes" else \
                           ("行人專用號誌" if tags.get("traffic_signals") == "pedestrian" else "紅綠燈號誌")
                traffic_signals.append({
                    "id": node_id,
                    "name": tags.get("name") or "路口交通號誌",
                    "lat": lat,
                    "lon": lon,
                    "sound": "yes" if has_sound else tags.get("sound", "unknown"),
                    "has_sound": has_sound,
                    "has_button": has_btn,
                    "signal_type": sig_type,
                    "tags": tags
                })
            elif hw == "bus_stop" or tags.get("railway") == "subway_entrance" or tags.get("public_transport") in ["platform", "stop_position"]:
                name = tags.get("name") or tags.get("name:zh") or tags.get("ref") or "公共運輸站"
                transit_type = "捷運出口" if tags.get("railway") == "subway_entrance" else "公車站"
                transit_stops.append({
                    "id": node_id,
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "transit_type": transit_type,
                    "ref": tags.get("ref", ""),
                    "tags": tags
                })

            # 【微型無障礙設施 1】：車擋柱、柵欄與閘門等實體路障 (Node Barriers)
            if "barrier" in tags:
                b_type = tags.get("barrier", "")
                b_name = self._translate_barrier(b_type)
                barriers.append({
                    "id": node_id,
                    "lat": lat,
                    "lon": lon,
                    "barrier_type": b_type,
                    "name": b_name,
                    "access": tags.get("access", ""),
                    "wheelchair": tags.get("wheelchair", ""),
                    "tags": tags
                })

            # 【微型無障礙設施 2】：建築物與店家實體出入口 (Node Entrances)
            if "entrance" in tags:
                e_type = tags.get("entrance", "yes")
                e_name = self._translate_entrance(e_type)
                entrances.append({
                    "id": node_id,
                    "lat": lat,
                    "lon": lon,
                    "entrance_type": e_type,
                    "name": e_name,
                    "door": tags.get("door", ""),
                    "wheelchair": tags.get("wheelchair", ""),
                    "tags": tags
                })

            # 【微型無障礙設施 3】：公眾飲水機、長椅、公廁、郵筒、噴泉 (Micro Amenities)
            micro_type = self._check_micro_amenity(tags)
            if micro_type:
                m_name = tags.get("name") or tags.get("name:zh") or self._translate_micro_amenity(micro_type, tags)
                micro_amenities.append({
                    "id": node_id,
                    "lat": lat,
                    "lon": lon,
                    "amenity_type": micro_type,
                    "name": m_name,
                    "wheelchair": tags.get("wheelchair", ""),
                    "fee": tags.get("fee", ""),
                    "tags": tags
                })

            # 【微型無障礙設施 4】：獨立階梯/單階台階節點 (Node Steps)
            if hw in ("steps", "step"):
                steps.append({
                    "id": node_id,
                    "name": tags.get("name") or "台階/階梯",
                    "step_count": tags.get("step_count", ""),
                    "handrail": tags.get("handrail", "unknown"),
                    "ramp": tags.get("ramp") or tags.get("ramp:wheelchair", "unknown"),
                    "surface": tags.get("surface", "石階/水泥"),
                    "tactile_paving": tags.get("tactile_paving", "unknown"),
                    "incline": tags.get("incline", ""),
                    "center_lat": lat,
                    "center_lon": lon,
                    "geometry": [(lat, lon)],
                    "tags": tags
                })

            # Check if standalone POI
            category = self._extract_poi_category(tags)
            if category and "name" in tags:
                pois.append({
                    "id": node_id,
                    "name": tags.get("name"),
                    "category": category,
                    "lat": lat,
                    "lon": lon,
                    "phone": tags.get("phone") or tags.get("contact:phone", ""),
                    "website": tags.get("website") or tags.get("contact:website", ""),
                    "opening_hours": tags.get("opening_hours", ""),
                    "wheelchair": tags.get("wheelchair", "unknown"),
                    "level": tags.get("level") or tags.get("layer", ""),
                    "cuisine": tags.get("cuisine", ""),
                    "brand": tags.get("brand") or tags.get("brand:zh", ""),
                    "payment": tags.get("payment:easycard") or tags.get("payment:cash", ""),
                    "takeaway": tags.get("takeaway", ""),
                    "tags": tags
                })

        # Parse ways for roads, buildings, way POIs
        for elem in elements:
            if elem.get("type") == "way":
                way_id = elem["id"]
                tags = elem.get("tags", {})
                node_ids = elem.get("nodes", [])
                
                # Reconstruct geometry
                geom = []
                for nid in node_ids:
                    if nid in nodes_dict:
                        geom.append((nodes_dict[nid][0], nodes_dict[nid][1]))

                if not geom:
                    continue

                # Center lat/lon for way
                avg_lat = sum(p[0] for p in geom) / len(geom)
                avg_lon = sum(p[1] for p in geom) / len(geom)

                if "highway" in tags:
                    roads.append({
                        "id": way_id,
                        "name": tags.get("name") or tags.get("name:zh") or tags.get("alt_name") or tags.get("ref") or "無名路",
                        "highway_type": tags["highway"],
                        "geometry": geom,
                        "node_ids": node_ids,
                        "sidewalk": tags.get("sidewalk", "none"),
                        "lanes": tags.get("lanes", "1"),
                        "oneway": tags.get("oneway", "no"),
                        "surface": tags.get("surface", "unknown"),
                        "tags": tags
                    })

                    # 【微型無障礙設施 4】：路網階梯結構 (Way Steps)
                    if tags["highway"] == "steps":
                        steps.append({
                            "id": way_id,
                            "name": tags.get("name") or "人行階梯",
                            "step_count": tags.get("step_count", ""),
                            "handrail": tags.get("handrail", "unknown"),
                            "ramp": tags.get("ramp") or tags.get("ramp:wheelchair", "unknown"),
                            "surface": tags.get("surface", "石階/水泥"),
                            "tactile_paving": tags.get("tactile_paving", "unknown"),
                            "incline": tags.get("incline", ""),
                            "center_lat": avg_lat,
                            "center_lon": avg_lon,
                            "geometry": geom,
                            "tags": tags
                        })

                if "barrier" in tags:
                    b_type = tags.get("barrier", "")
                    barriers.append({
                        "id": way_id,
                        "lat": avg_lat,
                        "lon": avg_lon,
                        "barrier_type": b_type,
                        "name": self._translate_barrier(b_type),
                        "access": tags.get("access", ""),
                        "wheelchair": tags.get("wheelchair", ""),
                        "geometry": geom,
                        "tags": tags
                    })

                if "building" in tags:
                    name = tags.get("name") or tags.get("building")
                    buildings.append({
                        "id": way_id,
                        "name": name if name != "yes" else "建築物",
                        "building_type": tags.get("building", "yes"),
                        "height": tags.get("height", ""),
                        "levels": tags.get("building:levels", ""),
                        "center_lat": avg_lat,
                        "center_lon": avg_lon,
                        "geometry": geom,
                        "tags": tags
                    })

                # 【方案 A 核心】：解析多邊形建築物上的真實門牌與街名
                # 台灣大量著名大樓（如壽德大樓、大創、新光三越）在 OSM 中是以 way 呈現，必須提取其幾何質心與門牌
                if "addr:housenumber" in tags or "addr:street" in tags:
                    street = tags.get("addr:street", "")
                    place = tags.get("addr:place", "")
                    if "巷" in place or "弄" in place:
                        street = street + place if street else place
                    elif not street:
                        street = place

                    clean_hn = tags.get("addr:housenumber", "")
                    if clean_hn:
                        house_numbers.append({
                            "id": way_id,
                            "housenumber": clean_hn,
                            "street": street,
                            "lat": avg_lat,
                            "lon": avg_lon,
                            "name": tags.get("name") or tags.get("name:zh") or "",
                            "tags": tags
                        })

                category = self._extract_poi_category(tags)
                if category and ("name" in tags or tags.get("amenity") or tags.get("shop")):
                    pois.append({
                        "id": way_id,
                        "name": tags.get("name") or self._translate_category(category),
                        "category": category,
                        "lat": avg_lat,
                        "lon": avg_lon,
                        "phone": tags.get("phone") or tags.get("contact:phone", ""),
                        "website": tags.get("website") or tags.get("contact:website", ""),
                        "opening_hours": tags.get("opening_hours", ""),
                        "wheelchair": tags.get("wheelchair", "unknown"),
                        "level": tags.get("level") or tags.get("layer", ""),
                        "cuisine": tags.get("cuisine", ""),
                        "brand": tags.get("brand") or tags.get("brand:zh", ""),
                        "payment": tags.get("payment:easycard") or tags.get("payment:cash", ""),
                        "takeaway": tags.get("takeaway", ""),
                        "tags": tags
                    })

        # Post-process: Infer unnamed roads from nearby house numbers
        for road in roads:
            if road["name"] == "無名路":
                inferred_names = {}
                road_geom = road.get("geometry", [])
                
                # Check each segment point of the road
                for r_lat, r_lon in road_geom:
                    for hn in house_numbers:
                        if hn["street"]:
                            # Simple distance approximation
                            d = haversine_distance(r_lat, r_lon, hn["lat"], hn["lon"])
                            if d < 20.0:  # Within 20 meters of the road node
                                inferred_names[hn["street"]] = inferred_names.get(hn["street"], 0) + 1
                                
                if inferred_names:
                    # Pick the most common street name nearby
                    best_name = max(inferred_names.items(), key=lambda x: x[1])[0]
                    road["name"] = best_name

        return {
            "nodes_dict": nodes_dict,
            "roads": roads,
            "pois": pois,
            "crossings": crossings,
            "traffic_signals": traffic_signals,
            "transit_stops": transit_stops,
            "buildings": buildings,
            "house_numbers": house_numbers,
            "barriers": barriers,
            "entrances": entrances,
            "steps": steps,
            "micro_amenities": micro_amenities
        }

    def _extract_poi_category(self, tags: Dict[str, str]) -> Optional[str]:
        if "amenity" in tags:
            return tags["amenity"]
        if "shop" in tags:
            return f"shop:{tags['shop']}"
        if "office" in tags:
            return f"office:{tags['office']}"
        if "craft" in tags:
            return f"craft:{tags['craft']}"
        if "tourism" in tags:
            return f"tourism:{tags['tourism']}"
        if "healthcare" in tags:
            return f"healthcare:{tags['healthcare']}"
        if "leisure" in tags:
            return f"leisure:{tags['leisure']}"
        if "bank" in tags or tags.get("amenity") == "bank":
            return "bank"
        if "atm" in tags or tags.get("amenity") == "atm":
            return "atm"
        if "name" in tags and not tags.get("highway"):
            return "poi"
        return None

    def _translate_category(self, category: str) -> str:
        translations = {
            "convenience": "便利商店", "supermarket": "超市", "restaurant": "餐廳",
            "fast_food": "速食店", "cafe": "咖啡店", "bank": "銀行",
            "atm": "ATM提款機", "pharmacy": "藥局", "hospital": "醫院",
            "clinic": "診所", "dentist": "牙醫診所", "police": "警察局",
            "post_office": "郵局", "school": "學校", "park": "公園",
            "library": "圖書館", "bus_station": "公車站", "bus_stop": "公車站牌",
            "subway_entrance": "捷運出口", "subway_station": "捷運站", "train_station": "火車站",
            "buddhist_temple": "寺廟", "temple": "寺廟", "church": "教堂", "place_of_worship": "宗教場所",
            "beauty_salon": "美容美睫", "beauty": "美容院", "hairdresser": "美髮店",
            "french_restaurant": "法式餐廳", "korean_restaurant": "韓式料理", "japanese_restaurant": "日式料理",
            "breakfast_and_brunch_restaurant": "早餐店", "discount_store": "生活百貨",
            "musical_instrument_store": "樂器行/音樂教室", "landmark_and_historical_building": "歷史建築/地標",
            "landmark": "地標", "poi": "地點"
        }
        raw_key = (category or "").split(":")[-1].lower()
        return translations.get(raw_key, raw_key.replace("_", " "))

    def _translate_barrier(self, barrier_type: str) -> str:
        """
        【路障設施白話中文對照 (Barrier Dictionary)】
        生活化比喻：人行道上的「路障」就像防守球員，
        車擋柱防機車但也容易絆倒視障者，清楚報讀名稱才能提早做出繞行反應。
        """
        b_map = {
            "bollard": "車擋柱",
            "cycle_barrier": "自行車阻擋欄",
            "block": "水泥路阻",
            "fence": "防護圍欄",
            "gate": "出入通道門",
            "wall": "矮牆/圍牆",
            "turnstile": "旋轉閘門",
            "lift_gate": "升降擋桿",
            "retaining_wall": "擋土牆",
            "stile": "階梯式過欄",
            "chain": "防護阻隔鍊條"
        }
        return b_map.get((barrier_type or "").lower(), f"{barrier_type}路障")

    def _translate_entrance(self, entrance_type: str) -> str:
        """
        【建築出入口類型對照 (Entrance Dictionary)】
        生活化比喻：找到建築物就像找到大西瓜，但「瓜蒂門口在哪裡」才是視障者最渴望知道的！
        """
        e_map = {
            "main": "大樓正門入口",
            "yes": "建築出入口",
            "wheelchair": "無障礙專用入口",
            "staircase": "樓梯間出入口",
            "service": "後門/服務出入口",
            "emergency": "緊急逃生出口",
            "exit": "專用出口",
            "entrance": "專用入口"
        }
        return e_map.get((entrance_type or "").lower(), f"{entrance_type}出入口")

    def _check_micro_amenity(self, tags: Dict[str, str]) -> Optional[str]:
        """檢查是否為公共微型設施（飲水機、長椅、公廁、郵筒、野餐桌等）"""
        amenity = tags.get("amenity")
        if amenity in ("drinking_water", "bench", "toilets", "waste_basket", "fountain", "post_box", "shelter"):
            return amenity
        leisure = tags.get("leisure")
        if leisure in ("picnic_table", "fitness_station"):
            return leisure
        return None

    def _translate_micro_amenity(self, micro_type: str, tags: Dict[str, str]) -> str:
        """
        【微型公眾設施生活化名稱轉換】
        """
        if micro_type == "drinking_water":
            return "公眾飲水機"
        elif micro_type == "bench":
            return "休息長椅"
        elif micro_type == "toilets":
            is_wheelchair = tags.get("wheelchair") in ("yes", "designated")
            return "無障礙公共廁所" if is_wheelchair else "公共廁所"
        elif micro_type == "waste_basket":
            return "公用垃圾桶"
        elif micro_type == "fountain":
            return "景觀噴水池"
        elif micro_type == "post_box":
            return "中華郵政郵筒"
        elif micro_type == "shelter":
            return "遮雨涼亭/候車亭"
        elif micro_type == "picnic_table":
            return "戶外野餐桌椅"
        elif micro_type == "fitness_station":
            return "公園體健運動設施"
        return micro_type.replace("_", " ")

