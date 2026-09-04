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
        self.is_overseas: bool = False

    def is_in_taiwan(self, lat: float, lon: float) -> bool:
        """
        【檢查經緯度是否位於台灣本島及周邊離島範圍】
        經緯度邊界：緯度 21.8°N ~ 26.4°N，經度 118.0°E ~ 122.1°E。
        若超出此範圍，系統會自動判定為「海外地區」並切換至 OSM 全球圖資。
        """
        return (21.8 <= lat <= 26.4) and (118.0 <= lon <= 122.1)

    def virtual_pan(self, forward_m: float = 30.0, side_m: float = 0.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        【雙指手勢虛擬視角平移 (Touch-to-Explore Virtual Pan)】
        
        作用：視障者在手機螢幕上雙指上滑時，不需要真的走動，
        就能「將探索視角向前推進 30 公尺」，提早獲知前方路況、店家與路口。
        """
        if not self.is_loaded:
            return False, "尚未初始化地圖起點。", {}

        # 1. 前向投影計算 (沿著目前朝向推算未來座標)
        pan_lat, pan_lon = self.lat, self.lon
        if forward_m != 0.0:
            pan_lat, pan_lon = destination_point(pan_lat, pan_lon, abs(forward_m), self.heading_deg if forward_m > 0 else (self.heading_deg + 180) % 360)
        
        # 2. 側向投影計算 (垂直於朝向左右平移)
        if side_m != 0.0:
            side_bearing = (self.heading_deg + 90.0) % 360.0 if side_m > 0 else (self.heading_deg - 90.0) % 360.0
            pan_lat, pan_lon = destination_point(pan_lat, pan_lon, abs(side_m), side_bearing)

        # 3. 分析平移點周遭的空間場景（道路、店家、路口）
        road_info = self.world_model.get_road_info(pan_lat, pan_lon, self.heading_deg)
        nearby_pois = self.world_model.get_nearby_pois(pan_lat, pan_lon, self.heading_deg, radius_m=40.0)
        intersections = self.intersection_analyzer.analyze(pan_lat, pan_lon, self.heading_deg, self.world_model)

        road_name = road_info.get("name") or "周遭巷弄"
        poi_summary = f"，附近有 {nearby_pois[0]['name']}" if nearby_pois else ""
        action_msg = f"探索視角平移至前方 {int(forward_m)} 公尺：【{road_name}】{poi_summary}"

        return True, action_msg, {
            "pan_lat": pan_lat,
            "pan_lon": pan_lon,
            "road_name": road_name,
            "road_info": road_info,
            "pois": nearby_pois,
            "intersection": intersections
        }

    def get_poi_detail(self, poi_id: str) -> Optional[Dict[str, Any]]:
        """
        【透過 ID 查詢單一店家的豐富資訊】
        """
        for poi in self.world_model.pois:
            if str(poi.id) == str(poi_id):
                return poi.calculate_relative(self.lat, self.lon, self.heading_deg)
        return None

    def teleport(self, location_input: str, radius_m: float = 250.0) -> Tuple[bool, str]:
        """
        【時空跳躍 / 起點定位 (Teleport)】
        
        作用：
        1. 解析輸入的地址、地標或經緯度座標。
        2. 取得座標後，透過 Overpass / 離線 SQLite 載入方圓 250 公尺的道路與店家。
        3. 建構 WorldModel 空間拓撲圖，並播放到達音效。
        """
        lat, lon, label = self.geocoder.parse_input(location_input)
        if lat is None or lon is None:
            return False, f"無法定位位置：'{location_input}'，請提供明確的地址、座標或 Google 地圖連結。"

        self.lat = lat
        self.lon = lon
        self.tile_center_lat = lat
        self.tile_center_lon = lon
        self.location_label = label
        self.heading_deg = 0.0  # 預設面向正北
        self.step_count = 0
        self.is_overseas = not self.is_in_taiwan(lat, lon)
        
        # 載入圖資並建置空間模型
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

        # 播放抵達音效
        self.sound_manager.play_arrival()

        overseas_note = "⚠️ 偵測到您位於海外地區。已自動切換為 OpenStreetMap 全球線上圖資模式。" if self.is_overseas else ""
        msg = f"{overseas_note}已成功移至 起始點：{label} (GPS: {round(lat, 5)}, {round(lon, 5)})，面向正北。"
        return True, msg.strip()

    def move(self, direction: str = "forward", distance_m: Optional[float] = None) -> Tuple[bool, str]:
        """
        【虛擬踏步移動 (Move Forward/Back/Left/Right)】
        
        作用：
        1. 根據目前朝向計算目標經緯度。
        2. 碰撞檢測：若前方 3.5 公尺內有大樓牆面，發出碰壁低頻音並阻擋前進。
        3. 播放腳步聲，並在接近網格邊緣時由背景執行緒自動預先下載 (AOT Prefetch) 下一個網格圖資。
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

        # Collision Check: Check if moving directly into a building within 3.5m
        buildings = self.world_model.get_nearby_buildings(self.lat, self.lon, move_angle, radius_m=15.0)
        for b in buildings:
            # get_nearby_buildings 傳入 move_angle，relative_direction 已相對於移動朝向
            if b["distance_m"] <= 3.5 and "正前" in b.get("relative_direction", ""):
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
        【接收手機實體真實 GPS 座標更新】
        
        作用：
        1. 接收手機傳來的高頻 GPS 定位數據。真實 GPS 資料「絕不被虛擬碰壁機制阻擋」。
        2. 自適應道路吸附：大馬路（寬度 >= 8m）自動吸附至路側人行道；小巷弄（寬度 < 8m）吸附至中心線，防止左右橫跳。
        3. 跨區自動重載：若使用者搭車或移動超過 100 公尺，自動重新載入新區域圖資。
        """
        if not self.is_loaded:
            ok, msg = self.teleport(f"{lat},{lon}")
            if heading_deg is not None and heading_deg >= 0:
                self.heading_deg = heading_deg
            return ok, msg

        # 計算與目前圖資中心點的距離
        tile_dist = haversine_distance(self.tile_center_lat, self.tile_center_lon, lat, lon)
        
        # 若移出目前圖資範圍超過 100 公尺，在全新地點重新建立世界模型
        if tile_dist > 100.0:
            ok, msg = self.teleport(f"{lat},{lon}")
            if heading_deg is not None and heading_deg >= 0:
                self.heading_deg = heading_deg
            return ok, f"已移至新區域：{msg}"

        # 隱馬爾可夫拓撲地圖匹配 (HMM Map Matching，維特比轉移機率徹底消除平行巷弄橫跳)
        cur_h = heading_deg if (heading_deg is not None and heading_deg >= 0) else self.heading_deg
        best_road, snap_lat, snap_lon, side = self.world_model.match_road_hmm(lat, lon, user_heading=cur_h)
        if best_road:
            dist_to_snap = haversine_distance(lat, lon, snap_lat, snap_lon)
            if 1.5 < dist_to_snap <= 24.0:
                self._current_road_side = side
                lat = snap_lat
                lon = snap_lon
                self._current_road_name = best_road.get("name", "")

        # 更新座標與朝向
        self.lat = lat
        self.lon = lon
        if heading_deg is not None and heading_deg >= 0:
            self.heading_deg = heading_deg

        # AOT 預加載：若靠近邊緣（> 60m）則背景預抓前方圖資
        if tile_dist >= 60.0:
            import threading
            ahead_lat, ahead_lon = destination_point(lat, lon, 150.0, self.heading_deg)
            def _bg_prefetch():
                self.overpass.fetch_area_data(ahead_lat, ahead_lon, 250.0)
            threading.Thread(target=_bg_prefetch, daemon=True).start()

        return True, f"GPS 位置已同步 ({round(lat, 5)}, {round(lon, 5)})"

    def sync_position(self, lat: float, lon: float, heading_deg: float, distance_moved: float) -> Tuple[bool, str]:
        """
        【客戶端平滑預測位置同步】
        """
        if not self.is_loaded:
            return self.teleport(f"{lat},{lon}")
            
        tile_dist = haversine_distance(self.tile_center_lat, self.tile_center_lon, lat, lon)
        if tile_dist > 100.0:
            return self.teleport(f"{lat},{lon}")

        # 隱馬爾可夫拓撲地圖匹配 (HMM Map Matching，維特比轉移機率徹底消除平行巷弄橫跳)
        best_road, snap_lat, snap_lon, side = self.world_model.match_road_hmm(lat, lon, user_heading=heading_deg)
        if best_road:
            dist_to_snap = haversine_distance(lat, lon, snap_lat, snap_lon)
            if 1.5 < dist_to_snap <= 24.0:
                self._current_road_side = side
                lat = snap_lat
                lon = snap_lon
                self._current_road_name = best_road.get("name", "")

        self.lat = lat
        self.lon = lon
        self.heading_deg = heading_deg
        
        # 累加步數
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
        【光線投射路口時空跳躍 (Raycast Fast-Travel)】
        
        作用：像發射一條雷射光一樣向前掃描（最遠 150 公尺），
        沿途若偵測到橫向岔路，直接將視角瞬移至該路口；若遇到障礙物則停在障礙物前。
        """
        if not self.is_loaded:
            return False, "尚未初始化地圖。"
        
        max_jump_m = 150.0  # 最大跳躍距離
        step_m = 5.0
        jumped_dist = 0.0
        
        curr_lat, curr_lon = self.lat, self.lon
        msg = ""
        
        while jumped_dist < max_jump_m:
            new_lat, new_lon = destination_point(curr_lat, curr_lon, step_m, self.heading_deg)
            jumped_dist += step_m
            curr_lat, curr_lon = new_lat, new_lon
            
            # 1. 檢查是否撞到建築物
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
                
            # 2. 檢查是否抵達路口
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
            # 達到最大跳躍距離
            self.lat, self.lon = curr_lat, curr_lon
            self.step_count += int(jumped_dist / self.step_size_m)
            msg = f"唰——！沿直線快轉了 {int(jumped_dist)} 公尺，未遇到明顯路口。"

        # 確保新位置的空間模型維持載入
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
        【自動對齊路口分支方向 (Snap to Branch)】
        
        作用：在十字路口想要左轉或右轉時，自動尋找最接近 90 度的岔路幾何角度，一鍵精準對齊。
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
        【相對角度轉向 (Turn Left/Right/Degrees)】
        作用：改變探索者朝向並播放轉向音效。
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
        【絕對方位定向 (Face North/East/South/West)】
        作用：直接將朝向調整為絕對正北、正東、正南或正西。
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
        """
        【啟動步行動態路徑導航】
        """
        if not self.is_loaded:
            return False, "尚未初始化地圖，請先定位起點。"
        
        # 1. 地理編碼目標地址
        lat, lon, label = self.geocoder.parse_input(destination)
        if lat is None:
            return False, f"無法找到目標：{destination}"
            
        # 2. 距離合理性檢查（限制 500 公尺內步行導航）
        dist = haversine_distance(self.lat, self.lon, lat, lon)
        if dist > 500:
            return False, f"目的地距離太遠（{dist:.0f}公尺），目前系統限制 500 公尺內的步行導航。"
            
        # 3. 計算最佳無障礙路徑
        route = self.navigator.calculate_route(self.lat, self.lon, self.heading_deg, lat, lon, label)
        if not route.get("success"):
            return False, route.get("message", "導航失敗。")
            
        self.active_navigation = route
        return True, route.get("message", "導航已啟動。")

    def get_navigation_status(self) -> str:
        """
        【取得當前導航指引文字】
        """
        if not self.active_navigation:
            return ""
        
        insts = self.active_navigation.get("instructions", [])
        if not insts:
            return "導航已結束。"
            
        return f"\n【導航提示】{insts[0]['text']}"

    def reload_real_pois(self, radius_deg: float = 0.008) -> int:
        """
        【手動重新載入離線資料庫地標】
        """
        if not self.is_loaded:
            return 0
        return self.world_model.reload_real_pois(self.lat, self.lon, radius_deg=radius_deg)


