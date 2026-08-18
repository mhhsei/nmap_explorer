import math
from typing import Optional, Dict, Any, Tuple, List
from nmap.spatial.geometry import destination_point, bearing_to_cardinal, relative_bearing, haversine_distance, calculate_bearing
from nmap.spatial.world_model import WorldModel
from nmap.spatial.intersection import IntersectionAnalyzer
from nmap.data.overpass import OverpassClient
from nmap.data.geocoders import NominatimClient
from nmap.data.cache import CacheManager
from nmap.accessibility.audio import SoundManager
from nmap.spatial.navigation import Navigator


from nmap.spatial.street_scene import StreetSceneEngine


class ExplorerAgent:
    """
    【視障探索者核心代理 (Explorer Agent Core)】
    這是整個系統的主心骨，負責追蹤使用者的絕對 GPS 座標與面向角度 (Heading)。
    為什麼需要一個 Agent？
    因為我們不是在做「靜態地圖」，而是「第一人稱 3D 空間漫遊」。
    每次呼叫 move() 或 turn() 時，這個 Agent 就像是遊戲引擎裡面的 Camera/Player，
    會與 WorldModel (場景資料) 進行碰撞檢測、幾何投影與音效觸發。
    """

    CARDINAL_MAP = {
        "north": 0.0, "北": 0.0, "北方": 0.0, "正北": 0.0,
        "northeast": 45.0, "東北": 45.0, "東北方": 45.0,
        "east": 90.0, "東": 90.0, "東方": 90.0, "正東": 90.0,
        "southeast": 135.0, "東南": 135.0, "東南方": 135.0,
        "south": 180.0, "南": 180.0, "南方": 180.0, "正南": 180.0,
        "southwest": 225.0, "西南": 225.0, "西南方": 225.0,
        "west": 270.0, "西": 270.0, "西方": 270.0, "正西": 270.0,
        "northwest": 315.0, "西北": 315.0, "西北方": 315.0
    }

    def __init__(self, cache_manager: Optional[CacheManager] = None, enable_sound: bool = True):
        self.cache = cache_manager or CacheManager()
        self.geocoder = NominatimClient(self.cache)
        self.overpass = OverpassClient(self.cache)
        self.world_model = WorldModel()
        self.navigator = Navigator(self.world_model.road_graph)
        self.sound_manager = SoundManager(enabled=enable_sound)
        
        # Navigation state
        self.active_navigation: Optional[Dict[str, Any]] = None
        self.intersection_analyzer = IntersectionAnalyzer()
        self.street_scene_engine = StreetSceneEngine()

        # Explorer State
        self.lat: float = 25.0601
        self.lon: float = 121.5332
        self.tile_center_lat: float = 25.0601
        self.tile_center_lon: float = 121.5332
        self.heading_deg: float = 0.0  # 0 = North
        self.location_label: str = "未初始化位置"
        self.step_size_m: float = 1.0
        self.step_count: int = 0
        self.history: List[Tuple[float, float, float, str]] = []
        self.is_loaded: bool = False

    def teleport(self, location_input: str, radius_m: float = 250.0) -> Tuple[bool, str]:
        """
        Teleport explorer to address, coordinates, or Google Maps URL.
        Fetches OSM spatial features and constructs WorldModel.
        """
        lat, lon, label = self.geocoder.parse_input(location_input)
        if lat is None or lon is None:
            return False, f"無法定位位置：'{location_input}'，請提供明確的地址、座標或 Google 地圖連結。"

        self.lat = lat
        self.lon = lon
        self.tile_center_lat = lat
        self.tile_center_lon = lon
        self.location_label = label
        self.heading_deg = 0.0  # Default facing North
        self.step_count = 0
        
        # Load Overpass data & build WorldModel
        raw_osm = self.overpass.fetch_area_data(lat, lon, radius_m)
        parsed = self.overpass.parse_elements(raw_osm, lat, lon)
        self.world_model.build_from_osm(parsed, lat, lon)
        self.navigator = Navigator(self.world_model.road_graph)
        self.active_navigation = None
        self.is_loaded = True

        self.history = [{
            "step": 0,
            "action": f"定位起點: {label}",
            "lat": lat,
            "lon": lon,
            "heading_deg": 0.0,
            "location_label": label,
            "poi_count": len(self.world_model.pois)
        }]

        # Play arrival sound
        self.sound_manager.play_arrival()

        return True, f"已成功移至 起始點：{label} (GPS: {round(lat, 5)}, {round(lon, 5)})，面向正北。"

    def move(self, direction: str = "forward", distance_m: Optional[float] = None) -> Tuple[bool, str]:
        """
        Move explorer forward, backward, left, or right by distance_m.
        Includes building/obstacle collision detection and footstep sound effects.
        """
        if not self.is_loaded:
            return False, "尚未初始化地圖。請先使用 start <地址/座標> 進入起點。"

        dist = distance_m if distance_m is not None else self.step_size_m
        direction_lower = direction.lower()

        # Calculate movement angle
        if direction_lower in ["forward", "前進", "前", "f"]:
            move_angle = self.heading_deg
            dir_label = "向前"
        elif direction_lower in ["back", "backward", "後退", "後", "b"]:
            move_angle = (self.heading_deg + 180.0) % 360.0
            dir_label = "向後"
        elif direction_lower in ["left", "向左", "左", "l"]:
            move_angle = (self.heading_deg - 90.0) % 360.0
            dir_label = "向左"
        elif direction_lower in ["right", "向右", "右", "r"]:
            move_angle = (self.heading_deg + 90.0) % 360.0
            dir_label = "向右"
        else:
            return False, f"未知的移動方向：'{direction}'。可使用：前進, 後退, 向左, 向右。"

        new_lat, new_lon = destination_point(self.lat, self.lon, dist, move_angle)

        # Collision Check: Check if moving directly into a building within 3m
        buildings = self.world_model.get_nearby_buildings(self.lat, self.lon, move_angle, radius_m=15.0)
        for b in buildings:
            # Check if building is directly ahead in move direction (< 25 deg angle offset) and very close (< 4.0 meters)
            t_brng = calculate_bearing(self.lat, self.lon, b["distance_m"], 0) # approximation
            rel = relative_bearing(move_angle, calculate_bearing(self.lat, self.lon, self.lat, self.lon))
            if b["distance_m"] <= 3.5 and "正前" in b["relative_direction"]:
                self.sound_manager.play_bump_collision()
                return False, f"⚠️ 【撞擊/碰壁提示】「扣咚！」前方 {b['distance_m']} 公尺處有建築物/牆面牆壁 ({b['name']})，撞到障礙物無法前進！請右轉或左轉繞行。"

        # Play footstep sound effect
        num_sound_steps = max(2, int(dist / 5.0))
        self.sound_manager.play_footsteps(steps=num_sound_steps)

        # Update position
        self.lat = new_lat
        self.lon = new_lon
        self.step_count += 1

        # Calculate distance from current tile center
        tile_dist = haversine_distance(self.tile_center_lat, self.tile_center_lon, new_lat, new_lon)

        # 【記憶體快取與邊界預加載機制 (AOT Prefetching)】
        # 為什麼要這樣寫？
        # 視障者在一直走的時候，最怕突然卡頓（會以為系統當掉或自己走丟了）。
        # 我們設定一個 120 公尺的快取網格。
        import threading
        if tile_dist <= 120.0:
            # 如果距離中心已經超過 70 公尺 (快要走出邊界了)，
            # 系統會立刻開啟一個 Daemon Thread (背景執行緒)，去把下一個網格的資料偷偷抓下來。
            # 這就是傳說中的 Ahead-of-Time (AOT) 預加載，達成 0 延遲。
            if tile_dist >= 70.0:
                ahead_lat, ahead_lon = destination_point(new_lat, new_lon, 150.0, self.heading_deg)
                def _bg_prefetch():
                    raw = self.overpass.fetch_area_data(ahead_lat, ahead_lon, 250.0)
                threading.Thread(target=_bg_prefetch, daemon=True).start()
        else:
            # 如果真的走出了網格（例如瞬間傳送或走太快），才需要阻塞主線程重新建立世界模型。
            raw_osm = self.overpass.fetch_area_data(new_lat, new_lon, 250.0)
            parsed = self.overpass.parse_elements(raw_osm, new_lat, new_lon)
            self.world_model.build_from_osm(parsed)
            self.navigator = Navigator(self.world_model.road_graph)
            self.tile_center_lat = new_lat
            self.tile_center_lon = new_lon

        self.history.append({
            "step": self.step_count,
            "action": f"{dir_label}{dist}公尺",
            "lat": new_lat,
            "lon": new_lon,
            "heading_deg": self.heading_deg,
            "location_label": self.location_label,
            "poi_count": len(self.world_model.pois)
        })

        cardinal = bearing_to_cardinal(self.heading_deg)
        return True, f"踏步移動中... 已{dir_label}步行 {dist} 公尺。目前位置 GPS: ({round(new_lat, 5)}, {round(new_lon, 5)})，面向{cardinal} (heading: {int(self.heading_deg)}°)。"

    def update_gps_position(self, lat: float, lon: float, heading_deg: Optional[float] = None, accuracy: float = 10.0) -> Tuple[bool, str]:
        """
        Handle real GPS location updates from mobile device sensors.
        Automatically reloads the OSM world tile if user moved out of the current tile (> 100m),
        or teleports if not yet loaded. Real GPS updates are NEVER rejected by virtual collision checks.
        """
        if not self.is_loaded:
            ok, msg = self.teleport(f"{lat},{lon}")
            if heading_deg is not None and heading_deg >= 0:
                self.heading_deg = heading_deg
            return ok, msg

        # Calculate distance from current tile center
        tile_dist = haversine_distance(self.tile_center_lat, self.tile_center_lon, lat, lon)
        
        # If user moved > 100m away from current tile center, rebuild world model at new location
        if tile_dist > 100.0:
            ok, msg = self.teleport(f"{lat},{lon}")
            if heading_deg is not None and heading_deg >= 0:
                self.heading_deg = heading_deg
            return ok, f"已移至新區域：{msg}"

        # Adaptive road snapping: wide roads snap to sidewalk, narrow alleys snap to centerline
        best_road, dist_to_road = self.world_model.find_nearest_road(lat, lon)
        if best_road and dist_to_road > 1.5 and dist_to_road <= 22.0:
            from nmap.spatial.pure_geometry import snap_pedestrian_to_road
            geom = best_road.get("geometry", [])
            if geom and len(geom) >= 2:
                last_side = getattr(self, "_current_road_side", None)
                _, snap_lat, snap_lon, side = snap_pedestrian_to_road(lat, lon, geom, best_road, last_side)
                self._current_road_side = side
                lat = snap_lat
                lon = snap_lon

        # Update position
        self.lat = lat
        self.lon = lon
        if heading_deg is not None and heading_deg >= 0:
            self.heading_deg = heading_deg

        # AOT Prefetch if nearing edge of tile (> 60m)
        if tile_dist >= 60.0:
            import threading
            ahead_lat, ahead_lon = destination_point(lat, lon, 150.0, self.heading_deg)
            def _bg_prefetch():
                self.overpass.fetch_area_data(ahead_lat, ahead_lon, 250.0)
            threading.Thread(target=_bg_prefetch, daemon=True).start()

        return True, f"GPS 位置已同步 ({round(lat, 5)}, {round(lon, 5)})"

    def sync_position(self, lat: float, lon: float, heading_deg: float, distance_moved: float) -> Tuple[bool, str]:
        """
        Client-side prediction sync endpoint.
        """
        if not self.is_loaded:
            return self.teleport(f"{lat},{lon}")
            
        tile_dist = haversine_distance(self.tile_center_lat, self.tile_center_lon, lat, lon)
        if tile_dist > 100.0:
            return self.teleport(f"{lat},{lon}")

        best_road, dist_to_road = self.world_model.find_nearest_road(lat, lon)

        # Adaptive road snapping: wide roads snap to sidewalk, narrow alleys snap to centerline
        if best_road and dist_to_road > 1.5 and dist_to_road <= 22.0:
            from nmap.spatial.pure_geometry import snap_pedestrian_to_road
            geom = best_road.get("geometry", [])
            if geom and len(geom) >= 2:
                last_side = getattr(self, "_current_road_side", None)
                _, snap_lat, snap_lon, side = snap_pedestrian_to_road(lat, lon, geom, best_road, last_side)
                self._current_road_side = side
                lat = snap_lat
                lon = snap_lon

        self.lat = lat
        self.lon = lon
        self.heading_deg = heading_deg
        
        # approximate steps (only increment when actually moved)
        if distance_moved > 0.1:
            self.step_count += max(1, int(distance_moved / self.step_size_m))

        import threading
        if tile_dist >= 60.0:
            ahead_lat, ahead_lon = destination_point(lat, lon, 150.0, heading_deg)
            def _bg_prefetch():
                self.overpass.fetch_area_data(ahead_lat, ahead_lon, 250.0)
            threading.Thread(target=_bg_prefetch, daemon=True).start()

        self.history.append({
            "step": self.step_count,
            "action": f"連續移動 {round(distance_moved, 1)}公尺",
            "lat": lat,
            "lon": lon,
            "heading_deg": heading_deg,
            "location_label": self.location_label,
            "poi_count": len(self.world_model.pois)
        })

        return True, "位置已同步。"

    def jump_to_next_intersection(self) -> Tuple[bool, str]:
        """
        Scheme 3: Raycast fast-travel to next intersection or obstacle.
        """
        if not self.is_loaded:
            return False, "尚未初始化地圖。"
        
        max_jump_m = 150.0  # Limit to 150m to stay reasonably within the 250m loaded radius
        step_m = 5.0
        jumped_dist = 0.0
        
        curr_lat, curr_lon = self.lat, self.lon
        msg = ""
        
        while jumped_dist < max_jump_m:
            new_lat, new_lon = destination_point(curr_lat, curr_lon, step_m, self.heading_deg)
            jumped_dist += step_m
            curr_lat, curr_lon = new_lat, new_lon
            
            # 1. Check building collision
            buildings = self.world_model.get_nearby_buildings(curr_lat, curr_lon, self.heading_deg, radius_m=5.0)
            hit_building = False
            for b in buildings:
                if b["distance_m"] <= 3.5 and "正前" in b["relative_direction"]:
                    hit_building = True
                    break
            if hit_building:
                self.lat, self.lon = curr_lat, curr_lon
                self.step_count += int(jumped_dist / self.step_size_m)
                self.sound_manager.play_bump_collision()
                msg = f"唰——！時空跳躍 {int(jumped_dist)} 公尺。前方遭遇障礙物阻擋。"
                break
                
            # 2. Check intersection
            branches = self.world_model.get_intersection_clock_bearings(curr_lat, curr_lon, self.heading_deg, radius_m=12.0)
            has_cross_road = False
            for br in branches:
                c = br["clock_position"]
                if "3點" in c or "9點" in c or "2點" in c or "10點" in c:
                    has_cross_road = True
                    break
            
            if has_cross_road and jumped_dist > 15.0:
                self.lat, self.lon = curr_lat, curr_lon
                self.step_count += int(jumped_dist / self.step_size_m)
                msg = f"唰——！時空跳躍 {int(jumped_dist)} 公尺，抵達下一個路口。"
                break
                
        if not msg:
            # Reached max distance
            self.lat, self.lon = curr_lat, curr_lon
            self.step_count += int(jumped_dist / self.step_size_m)
            msg = f"唰——！沿直線快轉了 {int(jumped_dist)} 公尺，未遇到明顯路口。"

        # Ensure world_model stays loaded for the new location
        tile_dist = haversine_distance(self.tile_center_lat, self.tile_center_lon, self.lat, self.lon)
        import threading
        if tile_dist <= 120.0:
            if tile_dist >= 70.0:
                ahead_lat, ahead_lon = destination_point(self.lat, self.lon, 150.0, self.heading_deg)
                def _bg_prefetch():
                    self.overpass.fetch_area_data(ahead_lat, ahead_lon, 250.0)
                threading.Thread(target=_bg_prefetch, daemon=True).start()
        else:
            raw_osm = self.overpass.fetch_area_data(self.lat, self.lon, 250.0)
            parsed = self.overpass.parse_elements(raw_osm, self.lat, self.lon)
            self.world_model.build_from_osm(parsed)
            self.navigator = Navigator(self.world_model.road_graph)
            self.tile_center_lat = self.lat
            self.tile_center_lon = self.lon
            
        return True, msg

    def snap_to_branch(self, direction: str) -> Tuple[bool, str]:
        """
        Scheme 3: Clock-snapping. Instantly align heading to the nearest left/right branching road.
        """
        if not self.is_loaded:
            return False, "尚未初始化地圖。"
            
        branches = self.world_model.get_intersection_clock_bearings(self.lat, self.lon, self.heading_deg, radius_m=20.0)
        
        candidates = []
        for br in branches:
            rel = (br['bearing'] - self.heading_deg + 360) % 360
            if direction == "right" and 5 < rel < 175:
                candidates.append((rel, br))
            elif direction == "left" and 185 < rel < 355:
                candidates.append((360 - rel, br))
                
        if not candidates:
            return True, f"附近沒有可向{ '右' if direction == 'right' else '左' }對齊的岔路。"
            
        candidates.sort(key=lambda x: x[0])
        best_branch = candidates[0][1]
        
        self.heading_deg = best_branch['bearing']
        return True, f"喀搭！自動對齊 {best_branch['clock_position']} 方向的 {best_branch['road_name']}。"

    def turn(self, degrees_or_dir: str) -> Tuple[bool, str]:
        """
        Turn facing direction by relative degrees or left/right.
        Triggers rotation sound cue.
        """
        val_lower = str(degrees_or_dir).lower()
        if val_lower in ["left", "左", "左轉"]:
            delta = -45.0
        elif val_lower in ["right", "右", "右轉"]:
            delta = 45.0
        elif val_lower in ["left90", "左轉90"]:
            delta = -90.0
        elif val_lower in ["right90", "右轉90"]:
            delta = 90.0
        elif val_lower in ["u-turn", "迴轉"]:
            delta = 180.0
        else:
            try:
                delta = float(val_lower)
            except ValueError:
                return False, f"無法辨識旋轉角度：'{degrees_or_dir}'。請輸入角度數字 (例如 45 或 -90) 或 左轉/右轉。"

        self.heading_deg = (self.heading_deg + delta + 360.0) % 360.0
        self.sound_manager.play_turn()
        cardinal = bearing_to_cardinal(self.heading_deg)
        return True, f"已轉向。目前面向 {cardinal} ({int(self.heading_deg)}°)。"

    def face(self, target: str) -> Tuple[bool, str]:
        """
        Set facing direction to an absolute cardinal direction (north/east/south/west) or degree.
        Triggers rotation sound cue.
        """
        target_lower = str(target).lower().strip()
        if target_lower in self.CARDINAL_MAP:
            self.heading_deg = self.CARDINAL_MAP[target_lower]
        else:
            try:
                self.heading_deg = float(target_lower) % 360.0
            except ValueError:
                return False, f"無法辨識面向目標：'{target}'。請使用：北方, 東方, 南方, 西方 或 0~360 角度。"

        self.sound_manager.play_turn()
        cardinal = bearing_to_cardinal(self.heading_deg)
        return True, f"已調整朝向。目前面向 {cardinal} ({int(self.heading_deg)}°)。"

    def navigate_to(self, destination: str) -> Tuple[bool, str]:
        """Start turn-by-turn navigation to a destination query."""
        if not self.is_loaded:
            return False, "尚未初始化地圖，請先定位起點。"
        
        # 1. Geocode destination
        lat, lon, label = self.geocoder.parse_input(destination)
        if lat is None:
            return False, f"無法找到目標：{destination}"
            
        # 2. Update map if target is outside
        dist = haversine_distance(self.lat, self.lon, lat, lon)
        if dist > 500:
            return False, f"目的地距離太遠（{dist:.0f}公尺），目前系統限制 500 公尺內的步行導航。"
            
        # 3. Calculate route
        route = self.navigator.calculate_route(self.lat, self.lon, self.heading_deg, lat, lon, label)
        if not route.get("success"):
            return False, route.get("message", "導航失敗。")
            
        self.active_navigation = route
        return True, route.get("message", "導航已啟動。")

    def get_navigation_status(self) -> str:
        if not self.active_navigation:
            return ""
        
        insts = self.active_navigation.get("instructions", [])
        if not insts:
            return "導航已結束。"
            
        # Here we just return the first active instruction for now
        # In a real step-by-step engine, we would track progress
        return f"\n【導航提示】{insts[0]['text']}"
