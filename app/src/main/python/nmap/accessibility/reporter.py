from typing import Dict, Any, List, Optional
from nmap.agent.explorer import ExplorerAgent
from nmap.spatial.geometry import bearing_to_cardinal


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

    def generate_concise_report(
        self,
        agent: ExplorerAgent,
        road_info: Optional[Dict[str, Any]] = None,
        pois: Optional[List[Dict[str, Any]]] = None,
        intersection: Optional[Dict[str, Any]] = None
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

        # 1. 道路變更提醒（走進新路時報讀）
        if street_name != self.last_street:
            parts.append(f"進入【{street_name}】。")
            self.last_street = street_name

        # 2. 路口動態接近與經過提醒（6.0m ~ 28.0m 提前預警，< 6.0m 提示正通過）
        is_intersection = intersection.get('junction_type') not in ["直行道路", None]
        has_junc_alert = False
        if is_intersection:
            dist = intersection.get('junction_distance_m', 0)
            jtype = intersection.get('junction_type', '路口')
            if dist is not None and dist < 6.0:
                parts.append(f"📍 正通過【{jtype}】。")
                has_junc_alert = True
            elif dist is not None and dist <= 28.0:
                parts.append(f"前方 {round(dist)} 公尺有【{jtype}】。")
                has_junc_alert = True

        # 3. 前方前進走廊左右店家提醒（限制前方 1.5 ~ 25.0 公尺，排除後方店家，提前 20 秒預警）
        corridor_pois = [p for p in pois if p.get("distance_m", 999) <= 25.0 and p.get("distance_m", 0) >= 1.5 and "後方" not in p.get("relative_direction", "")]
        
        has_poi_alert = False
        if corridor_pois:
            corridor_pois.sort(key=lambda x: x["distance_m"])
            poi_texts = [f"{p['name']} ({p.get('relative_direction', '')} {round(p['distance_m'])}公尺)" for p in corridor_pois[:2]]
            parts.append(f"前進路上：{'、'.join(poi_texts)}。")
            has_poi_alert = True

        if not has_junc_alert and not has_poi_alert and street_name == self.last_street:
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
        scene: Optional[Dict[str, Any]] = None
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
        
        nav_status = agent.get_navigation_status()
        if nav_status:
            lines.append(nav_status)
            lines.append("")

        # Section 1: Current State
        lines.append(f"【目前位置】{agent.location_label}")
        lines.append(f"• GPS座標：({round(agent.lat, 5)}, {round(agent.lon, 5)})")
        lines.append(f"• 朝向：面向{cardinal} (方位角 {int(agent.heading_deg)}°)")

        # Section 1.5: Real-World Physical Street Scene Architecture & Infrastructure
        if scene is None:
            scene = agent.street_scene_engine.analyze_scene(agent.lat, agent.lon, agent.heading_deg, agent.world_model, road_info=road_info)
        scene_desc = scene.get('full_description') or scene.get('scene_summary') or '街景資料解析完成。'
        lines.append("\n【真實街道場景風貌】")
        lines.append(f"• 街道風貌：{scene_desc}")

        # Section 2: Road & Sidewalk Status
        lines.append("\n【道路與人行道】")
        lines.append(f"• 當前道路：{road_info['street_name']} ({road_info['oneway']}，{road_info['lanes']} 車道)")
        lines.append(f"• 人行道：{road_info['sidewalk_desc']}")

        # Section 2.5: Left/Right Side House Numbers & Alleys
        side_scan = agent.world_model.get_left_right_side_scan(agent.lat, agent.lon, agent.heading_deg, radius_m=60.0)
        if door_estimates is None:
            door_estimates = agent.world_model.get_interpolated_door_numbers(agent.lat, agent.lon, agent.heading_deg)
        lines.append("\n【左右側門牌與巷弄掃描】")
        left_h = f" (門牌: {', '.join(side_scan['left_side']['house_numbers'])})" if side_scan['left_side']['house_numbers'] else f" ({door_estimates['left_side_estimate']})"
        left_a = f" (巷弄: {', '.join(a['name'] for a in side_scan['left_side']['alleys'])})" if side_scan['left_side']['alleys'] else ""
        lines.append(f"• 左側 (Left Side)：{left_h}{left_a}")

        right_h = f" (門牌: {', '.join(side_scan['right_side']['house_numbers'])})" if side_scan['right_side']['house_numbers'] else f" ({door_estimates['right_side_estimate']})"
        right_a = f" (巷弄: {', '.join(a['name'] for a in side_scan['right_side']['alleys'])})" if side_scan['right_side']['alleys'] else ""
        lines.append(f"• 右側 (Right Side)：{right_h}{right_a}")

        # Section 3: Intersection & Crossing Safety with 12-Hour Clock Bearings
        lines.append("\n【路口與過馬路資訊】")
        lines.append(f"• 前方路口型態：{intersection_analysis['junction_type']}")
        lines.append(f"• 過馬路評估：{intersection_analysis['safety_summary']}")

        clock_branches = agent.world_model.get_intersection_clock_bearings(agent.lat, agent.lon, agent.heading_deg, radius_m=40.0)
        if clock_branches:
            lines.append("• 鐘點方位路口分支：")
            for b in clock_branches[:4]:
                lines.append(f"  - 位於 {b['clock_position']} ({b['relative_direction']}) {b['distance_m']}m：{b['road_name']}")

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
