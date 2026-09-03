from typing import Dict, Any, List, Optional
from nmap.agent.explorer import ExplorerAgent
from nmap.spatial.geometry import bearing_to_cardinal
from nmap.spatial.vertical_level import VerticalLevelManager, LEVEL_DISPLAY_NAMES
from nmap.spatial.beacon_database import TaiwanBeaconDatabase


class NVDAReporter:
    """
    【NVDA 無障礙語音報讀器 (Accessibility Reporter)】
    
    為什麼要特別獨立出這個模組？
    1. 雙模態分離 (Dual-Modal Separation)：前端 (app.js) 負責使用 Web Audio API 發出「空間立體聲 (3D Audio)」，
       而這個模組專注於「文字報讀 (TTS)」。聽覺是視障者的第一感官，我們將冰冷的經緯度轉化為自然語言。
    2. VoiceVista (Soundscape) 哲學：在 generate_concise_report 中，我們不囉嗦地重複當前路名，
       而是只在「經過店家」或「靠近路口」時，給予清晰的相對方位提示（如：7-ELEVEN，3點鐘方向）。
       這避免了 NVDA 的語音佇列塞車，讓視障者能保持空間心智模型的連續性。
    3. 狀態記憶：利用 set 記錄已經報讀過的 POI，避免原地踏步時反覆轟炸使用者耳朵。
    """
    
    def __init__(self):
        self.announced_pois = set()
        self.last_street = ""
        self.last_junc_alert = ""
        self.last_vertical_level = "GROUND"
        self.last_beacon_id = ""

    def generate_concise_report(
        self,
        agent: ExplorerAgent,
        road_info: Optional[Dict[str, Any]] = None,
        pois: Optional[List[Dict[str, Any]]] = None,
        intersection: Optional[Dict[str, Any]] = None,
        vertical_level: str = "GROUND",
        altitude_m: float = 0.0,
        beacon_anchor: Optional[Dict[str, Any]] = None,
        ground_elevation_m: float = 0.0,
        **kwargs: Any
    ) -> str:
        """
        【產生極簡「省話模式」即時播報 (VoiceVista-Style Concise Announcement)】
        
        作用：在視障者快速連續踏步前進時使用。
        1. 避免冗長廢話（例如不重複唸「你現在走在...」）。
        2. 只在「換了一條新路」、「即將經過路口」或「前方有新店家接近」時，用 1 秒內能唸完的極簡語句提醒。
        """
        if not agent.is_loaded:
            return "提示：尚未載入起點。"

        cardinal = bearing_to_cardinal(agent.heading_deg)
        if road_info is None:
            road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
        if pois is None:
            pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=100.0)
        if intersection is None:
            intersection = agent.intersection_analyzer.analyze(
                agent.lat, agent.lon, agent.heading_deg, agent.world_model, max_distance_m=50.0, curr_road_info=road_info
            )

        street_name = road_info.get("street_name", "道路")
        
        parts = []

        # 0. 室內公眾 Beacon / Wi-Fi 定錨回饋 (最高優先級，讓視障者即時確認自己已被精準定錨)
        if beacon_anchor and beacon_anchor.get("id") != self.last_beacon_id:
            parts.append(TaiwanBeaconDatabase.format_anchor_announcement(beacon_anchor, beacon_anchor.get("dist_m", 2.0)))
            self.last_beacon_id = beacon_anchor.get("id", "")

        # 0.1 垂直高程與樓層切換提醒 (天橋/地下道/地面)
        if vertical_level != self.last_vertical_level:
            parts.append(VerticalLevelManager.format_transition_speech(self.last_vertical_level, vertical_level, altitude_m))
            self.last_vertical_level = vertical_level

        # 1. 道路變更提醒（走進新路時報讀）
        if street_name != self.last_street:
            parts.append(f"進入【{street_name}】。")
            self.last_street = street_name

        # 2. 人行道實體障礙物安全防撞雷達 (Scheme 3: 變電箱/消防栓/段差) - 第一優先警示！
        hazards = agent.world_model.get_sidewalk_hazards(agent.lat, agent.lon, agent.heading_deg, max_dist_m=8.0)
        has_hazard_alert = False
        if hazards:
            h = hazards[0]
            parts.append(h["speech_prompt"])
            has_hazard_alert = True

        # 3. 捷運專屬無障礙電梯出口提示 (Scheme 4: 捷運電梯)
        mrt_exits = agent.world_model.get_mrt_accessible_exits(agent.lat, agent.lon, agent.heading_deg, radius_m=80.0)
        has_mrt_alert = False
        if mrt_exits and mrt_exits[0]["distance_m"] <= 35.0 and mrt_exits[0]["has_elevator"]:
            m = mrt_exits[0]
            parts.append(f"{m['speech_prompt']}")
            has_mrt_alert = True

        # 4. 路口接近與過馬路走向導引 (安全第一，動態鐘點分支走向與對向接續路名)
        is_intersection = intersection.get('junction_type') not in ["直行道路", None]
        has_junc_alert = False
        if is_intersection:
            dist = intersection.get('junction_distance_m', 0)
            if dist is not None and dist < 6.0:
                passing_prompt = intersection.get("concise_passing_prompt", "正通過路口，請直線前進")
                parts.append(f"📍 {passing_prompt}。")
                has_junc_alert = True
            elif dist is not None and dist <= 28.0:
                approaching_prompt = intersection.get("concise_approaching_prompt")
                if approaching_prompt:
                    parts.append(f"📍 {approaching_prompt}。")
                else:
                    j_name = intersection.get("junction_name", "路口")
                    parts.append(f"📍 接近路口，{j_name}。")
                has_junc_alert = True

        # 5. 前方前進走廊左右店家提醒（緊鄰店家合併打包與門牌自然錨定）
        filtered_pois = VerticalLevelManager.filter_and_prioritize_pois(pois or [], vertical_level)
        corridor_pois = [p for p in filtered_pois if p.get("distance_m", 999) <= 25.0 and p.get("distance_m", 0) >= 1.5 and "後方" not in p.get("relative_direction", "")]
        
        has_poi_alert = False
        if corridor_pois and not has_junc_alert:
            corridor_pois.sort(key=lambda x: x["distance_m"])
            
            # 檢查緊鄰店家群組 (同側/同鐘點 且距離差 <= 6m)
            if len(corridor_pois) >= 2:
                p1, p2 = corridor_pois[0], corridor_pois[1]
                dir1 = p1.get("clock_position") or p1.get("relative_direction", "")
                dir2 = p2.get("clock_position") or p2.get("relative_direction", "")
                dist_diff = abs(p1.get("distance_m", 0) - p2.get("distance_m", 0))
                
                # 同方位近鄰群組打包
                if dir1 == dir2 and dist_diff <= 6.0:
                    hn1 = f" ({p1['housenumber']}號)" if p1.get("housenumber") else ""
                    hn2 = f" ({p2['housenumber']}號)" if p2.get("housenumber") else ""
                    avg_d = round((p1.get("distance_m", 0) + p2.get("distance_m", 0)) / 2.0)
                    parts.append(f"前進路上：{dir1} {avg_d}米：{p1['name']}{hn1}、{p2['name']}{hn2}。")
                    has_poi_alert = True
            
            if not has_poi_alert:
                poi_texts = []
                for p in corridor_pois[:2]:
                    tag = f"[{p['level_tag']}] " if "level_tag" in p else ""
                    clock_or_dir = p.get("clock_position") or p.get("relative_direction", "")
                    hn = f" ({p['housenumber']}號)" if p.get("housenumber") else ""
                    poi_texts.append(f"{tag}{p['name']}{hn} ({clock_or_dir} {round(p['distance_m'])}米)")
                parts.append(f"前進路上：{'、'.join(poi_texts)}。")
                has_poi_alert = True

        if not has_hazard_alert and not has_mrt_alert and not has_junc_alert and not has_poi_alert and street_name == self.last_street:
            pass # 靜默保持安靜，留給使用者聽環境音的空間

        return " ".join(parts).strip()

    def generate_full_report(
        self,
        agent: ExplorerAgent,
        road_info: Optional[Dict[str, Any]] = None,
        pois: Optional[List[Dict[str, Any]]] = None,
        buildings: Optional[List[Dict[str, Any]]] = None,
        intersection_analysis: Optional[Dict[str, Any]] = None,
        door_estimates: Optional[Dict[str, Any]] = None,
        scene: Optional[Dict[str, Any]] = None,
        vertical_level: str = "GROUND",
        altitude_m: float = 0.0,
        beacon_anchor: Optional[Dict[str, Any]] = None,
        ground_elevation_m: float = 0.0,
        **kwargs: Any
    ) -> str:
        """
        【產生 360 度周遭全景探索報告 (Full Spatial Exploration Report)】
        
        作用：當使用者按下【空白鍵】或輸入 look 時觸發。
        完整梳理 150 公尺內的所有環境細節：
        1. 當前 GPS 座標、方位角與街道風貌。
        2. 道路車道數、人行道鋪面與單行道屬性。
        3. 左右兩側門牌號碼估算與相鄰巷弄。
        4. 前方路口分支、鐘點方位與過馬路安全性。
        5. 分門別類（餐飲、超商、交通、醫療）列出周遭店家與大樓。
        """
        if not agent.is_loaded:
            return "提示：尚未載入地圖起點。請先使用 start 指令定位起點。"

        cardinal = bearing_to_cardinal(agent.heading_deg)
        if road_info is None:
            road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
        if pois is None:
            pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=150.0)
        if buildings is None:
            buildings = agent.world_model.get_nearby_buildings(agent.lat, agent.lon, agent.heading_deg, radius_m=80.0)
        if intersection_analysis is None:
            intersection_analysis = agent.intersection_analyzer.analyze(
                agent.lat, agent.lon, agent.heading_deg, agent.world_model, max_distance_m=60.0, curr_road_info=road_info
            )

        lines = []

        # 自動校準地面真實海拔 (若傳入 0.0 則動態向 SRTM 查詢最新 GPS 座標之高程)
        if (ground_elevation_m == 0.0 or ground_elevation_m is None) and getattr(agent, "lat", None):
            try:
                import nmap.spatial.srtm_reader as srtm
                dyn_elev = srtm.get_elevation(agent.lat, agent.lon)
                if dyn_elev is not None:
                    ground_elevation_m = dyn_elev
                    agent.current_ground_elevation = dyn_elev
            except Exception:
                pass
        
        nav_status = agent.get_navigation_status()
        if nav_status:
            lines.append(nav_status)
            lines.append("")

        # Section 1: Current State
        lines.append(f"【目前位置】{agent.location_label}")
        lines.append(f"• GPS座標：({round(agent.lat, 5)}, {round(agent.lon, 5)})")
        lines.append(f"• 朝向：面向{bearing_to_cardinal(agent.heading_deg)} (方位角 {int(agent.heading_deg)}°)")

        # Section 1.2: 3D 垂直空間高程與公眾 Beacon 定錨
        level_name = LEVEL_DISPLAY_NAMES.get(vertical_level, "地面層")
        alt_str = f"{altitude_m:+.1f} 公尺" if altitude_m != 0.0 else "±0.0 公尺"
        lines.append(f"\n【3D 垂直空間與地形高程】")
        lines.append(f"• 所在立體層級：{level_name}")
        lines.append(f"• 相對地面高程：{alt_str}")
        lines.append(f"• 真實地形海拔：{ground_elevation_m:+.1f} 公尺 (由 SRTM 3D 地形庫提供)")
        if beacon_anchor:
            dist_val = beacon_anchor.get('dist_m', 2.0)
            lines.append(f"• 📡 公眾 Beacon 定錨：{beacon_anchor.get('name')} (距離約 {round(dist_val)} 公尺)")
            if beacon_anchor.get("description"):
                lines.append(f"  導引指引：{beacon_anchor.get('description')}")

        # Section 1.5: Real-World Physical Street Scene Architecture & Infrastructure
        if scene is None:
            scene = agent.street_scene_engine.analyze_scene(agent.lat, agent.lon, agent.heading_deg, agent.world_model, road_info=road_info)
        scene_desc = scene.get('full_description') or scene.get('scene_summary') or '街景資料解析完成。'
        lines.append("\n【真實街道場景風貌】")
        lines.append(f"• 街道風貌：{scene_desc}")

        # Section 2: Road & Sidewalk Status
        lines.append("\n【道路與人行道】")
        sname = road_info.get('street_name', '未知道路')
        oneway = road_info.get('oneway', '雙向')
        lanes = road_info.get('lanes', 2)
        sw_desc = road_info.get('sidewalk_desc', '兩側平整人行道與騎樓')
        lines.append(f"• 當前道路：{sname} ({oneway}，{lanes} 車道)")
        lines.append(f"• 人行道：{sw_desc}")

        # Section 2.5: Left/Right Side Real House Numbers & Alleys (方案 A + C)
        side_scan = agent.world_model.get_left_right_side_scan(agent.lat, agent.lon, agent.heading_deg, radius_m=60.0)
        if door_estimates is None:
            door_estimates = agent.world_model.get_interpolated_door_numbers(agent.lat, agent.lon, agent.heading_deg)
        lines.append("\n【左右側實體門牌與巷弄掃描】")
        left_h = f" (門牌: {', '.join(side_scan['left_side']['house_numbers'])})" if side_scan['left_side']['house_numbers'] else (f" ({door_estimates['left_side_estimate']})" if door_estimates.get('left_side_estimate') else "")
        left_a = f" (巷弄: {', '.join(a['name'] for a in side_scan['left_side']['alleys'])})" if side_scan['left_side']['alleys'] else ""
        lines.append(f"• 左側 (Left Side)：{left_h}{left_a}" if (left_h or left_a) else "• 左側 (Left Side)：無實體門牌")

        right_h = f" (門牌: {', '.join(side_scan['right_side']['house_numbers'])})" if side_scan['right_side']['house_numbers'] else (f" ({door_estimates['right_side_estimate']})" if door_estimates.get('right_side_estimate') else "")
        right_a = f" (巷弄: {', '.join(a['name'] for a in side_scan['right_side']['alleys'])})" if side_scan['right_side']['alleys'] else ""
        lines.append(f"• 右側 (Right Side)：{right_h}{right_a}" if (right_h or right_a) else "• 右側 (Right Side)：無實體門牌")

        # Section 3: Intersection & Crossing Safety with 12-Hour Clock Bearings
        lines.append("\n【路口與過馬路資訊】")
        lines.append(f"• 前方路口型態：{intersection_analysis['junction_type']}")
        lines.append(f"• 過馬路評估：{intersection_analysis['safety_summary']}")

        clock_branches = agent.world_model.get_intersection_clock_bearings(agent.lat, agent.lon, agent.heading_deg, radius_m=40.0)
        if clock_branches:
            lines.append("• 鐘點方位路口分支：")
            for b in clock_branches[:4]:
                lines.append(f"  - 位於 {b['clock_position']} ({b['relative_direction']}) {b['distance_m']}m：{b['road_name']}")

        # Section 3.2: Traffic Signal, APS & Pedestrian Button (Scheme 1)
        sig_safety = agent.world_model.get_signal_safety(agent.lat, agent.lon, agent.heading_deg, radius_m=35.0)
        lines.append("\n【交通號誌、有聲導引與按鈕情報】")
        if sig_safety:
            if sig_safety.get("has_aps"):
                lines.append(f"• 有聲號誌：{sig_safety['target_sound']}")
            if sig_safety.get("has_live_seconds"):
                lines.append(f"• 即時秒數：{sig_safety['light_status']} 剩 {sig_safety['remaining_seconds']} 秒")
            if sig_safety.get("has_button"):
                lines.append(f"• 行人觸動按鈕：{sig_safety['button_guide']}")
        else:
            lines.append("• 號誌設施：此路口無實體有聲號誌，請依車流平行音確認起步通行。")

        # Section 3.5: Sidewalk Hazards Radar (Scheme 3)
        sidewalk_hazards = agent.world_model.get_sidewalk_hazards(agent.lat, agent.lon, agent.heading_deg, max_dist_m=15.0)
        if sidewalk_hazards:
            lines.append("\n【人行道安全防撞雷達 (變電箱/障礙物)】")
            for h in sidewalk_hazards[:3]:
                lines.append(f"• {h['speech_prompt']}")

        # Section 3.8: MRT Accessible Elevator Exits (Scheme 4)
        mrt_exits = agent.world_model.get_mrt_accessible_exits(agent.lat, agent.lon, agent.heading_deg, radius_m=200.0)
        if mrt_exits:
            lines.append("\n【捷運站立體無障礙出入口 (專屬電梯優先)】")
            for m in mrt_exits[:3]:
                lines.append(f"• {m['speech_prompt']} ({m['accessibility_badge']})")

        # Section 4: Categorized POIs (Categorized by Type for easy NVDA navigation)
        lines.append(f"\n【周遭 POI 與店家設施】（150公尺內共 {len(pois)} 處）")
        if pois:
            # Group POIs into categories
            food_list = [p for p in pois if any(k in p['category'] for k in ['restaurant', 'fast_food', 'food', 'bakery'])]
            shop_list = [p for p in pois if any(k in p['category'] for k in ['convenience', 'supermarket', 'shop', 'mall', 'chemist'])]
            transit_list = [p for p in pois if any(k in p['category'] for k in ['subway', 'bus', 'station', 'transit', 'rental'])]
            other_list = [p for p in pois if p not in food_list and p not in shop_list and p not in transit_list]

            def format_poi_item(p):
                extra_flags = []
                if p.get("level"):
                    extra_flags.append(f"位於{p['level']}樓")
                if p.get("wheelchair") == "yes":
                    extra_flags.append("無障礙通路")
                if p.get("opening_hours"):
                    extra_flags.append(f"營業時間:{p['opening_hours']}")
                if p.get("phone"):
                    extra_flags.append(f"電話:{p['phone']}")
                flag_str = f" [{', '.join(extra_flags)}]" if extra_flags else ""
                clock_str = p.get("clock_position") or p.get("clock_direction") or "前方"
                rel_dir_str = p.get("relative_direction") or "前方"
                poi_name = p.get("name") or "未命名設施"
                dist_str = p.get("distance_m", 0)
                return f"  • {poi_name}：位於 {clock_str} ({rel_dir_str})，距離 {dist_str} 公尺{flag_str}"

            if food_list:
                lines.append(f"\n🍔 餐飲美食 ({len(food_list)} 處)：")
                for p in food_list[:5]:
                    lines.append(format_poi_item(p))

            if shop_list:
                lines.append(f"\n🏪 超商門市與購物 ({len(shop_list)} 處)：")
                for p in shop_list[:5]:
                    lines.append(format_poi_item(p))

            if transit_list:
                lines.append(f"\n🚌 交通轉乘與站牌出口 ({len(transit_list)} 處)：")
                for p in transit_list[:4]:
                    lines.append(format_poi_item(p))

            if other_list:
                lines.append(f"\n🏬 醫療、金融與其他設施 ({len(other_list)} 處)：")
                for p in other_list[:4]:
                    lines.append(format_poi_item(p))
        else:
            lines.append("• 150 公尺內無特別登錄的設施。")

        # Section 5: Nearby Buildings
        if buildings:
            lines.append("\n【周遭建築物與大樓】")
            for b in buildings[:4]:
                level_str = f" {b['levels']}層" if b['levels'] else ""
                lines.append(f"• {b['name']} ({b['building_type']}{level_str})：位於 {b['clock_position']} ({b['relative_direction']})，距離 {b['distance_m']} 公尺")

        return "\n".join(lines)
