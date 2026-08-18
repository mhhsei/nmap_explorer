from typing import Dict, Any, List
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

    def generate_concise_report(self, agent: ExplorerAgent) -> str:
        """
        Generate an ultra-concise VoiceVista-style spatial announcement for fast stepping.
        Focuses on clear clock-face directions and passing landmarks without spamming.
        """
        if not agent.is_loaded:
            return "提示：尚未載入起點。"

        cardinal = bearing_to_cardinal(agent.heading_deg)
        road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
        pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=100.0)
        intersection = agent.intersection_analyzer.analyze(
            agent.lat, agent.lon, agent.heading_deg, agent.world_model, max_distance_m=50.0
        )

        street_name = road_info.get("street_name", "道路")
        
        parts = []

        # 1. Street changes
        if street_name != self.last_street:
            parts.append(f"進入【{street_name}】。")
            self.last_street = street_name

        # 2. Intersections
        is_intersection = intersection['junction_type'] not in ["直行道路"]
        has_junc_alert = False
        if is_intersection:
            dist = intersection.get('junction_distance_m', 0)
            if dist <= 10.0:
                parts.append("📍 正經過十字路口。")
                has_junc_alert = True
            elif dist <= 30.0:
                parts.append(f"前方 {dist} 公尺有路口。")
                has_junc_alert = True

        # 3. Approaching POIs (Filter out passed ones)
        # Passed POIs have "後方" in relative_direction (e.g. 左後方, 右後方, 正後方)
        approaching_pois = [p for p in pois if p["distance_m"] <= 50.0 and "後方" not in p.get("relative_direction", "")]
        
        has_poi_alert = False
        if approaching_pois:
            approaching_pois.sort(key=lambda x: x["distance_m"])
            poi_texts = [f"{p['name']} ({p.get('relative_direction', '')} {p['distance_m']}公尺)" for p in approaching_pois[:3]]
            parts.append(f"接近中：{'、'.join(poi_texts)}。")
            has_poi_alert = True

        if not has_junc_alert and not has_poi_alert and street_name == self.last_street:
            pass # Removed unnecessary street description per user request


        return " ".join(parts).strip()

    def generate_full_report(self, agent: ExplorerAgent) -> str:
        """
        Generate a complete spatial exploration report of current position, surroundings,
        road conditions, crosswalk safety, and nearby POIs (up to 150m radius).
        """
        if not agent.is_loaded:
            return "提示：尚未載入地圖起點。請先使用 start 指令定位起點。"

        cardinal = bearing_to_cardinal(agent.heading_deg)
        road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
        pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=150.0)
        buildings = agent.world_model.get_nearby_buildings(agent.lat, agent.lon, agent.heading_deg, radius_m=80.0)
        intersection_analysis = agent.intersection_analyzer.analyze(
            agent.lat, agent.lon, agent.heading_deg, agent.world_model, max_distance_m=60.0
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
        scene = agent.street_scene_engine.analyze_scene(agent.lat, agent.lon, agent.heading_deg, agent.world_model)
        lines.append("\n【真實街道場景風貌】")
        lines.append(f"• 街道風貌：{scene['full_description']}")

        # Section 2: Road & Sidewalk Status
        lines.append("\n【道路與人行道】")
        lines.append(f"• 當前道路：{road_info['street_name']} ({road_info['oneway']}，{road_info['lanes']} 車道)")
        lines.append(f"• 人行道：{road_info['sidewalk_desc']}")

        # Section 2.5: Left/Right Side House Numbers & Alleys
        side_scan = agent.world_model.get_left_right_side_scan(agent.lat, agent.lon, agent.heading_deg, radius_m=60.0)
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
                return f"  • {p['name']}：位於 {p['clock_position']} ({p['relative_direction']})，距離 {p['distance_m']} 公尺{flag_str}"

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
