"""
真實街景風貌與公共基礎設施分析引擎 (Street Scene & Infrastructure Engine)

作用：
1. 街景型態判別：結合道路屬性分析目前是「行人徒步商圈」、「寬敞幹道大馬路」還是「清靜生活巷弄」。
2. 公共基礎設施掃描：統計行道樹 (tree)、路燈 (lamp)、休憩座椅 (bench) 與騎樓 (arcade)。
3. 建築天際線高度分析：估算周遭大樓平均樓層（摩天商辦、現代公寓、傳統騎樓），描繪立體的真實街景。
"""
import math
from typing import Dict, Any, List, Optional


class StreetSceneEngine:
    """
    街道場景風貌分析引擎
    """

    def analyze_scene(self, lat: float, lon: float, heading_deg: float, world_model: Any, road_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        【分析當前位置的街道風貌與周遭環境氛圍】
        作用：透過空間網格僅查詢周遭 100 公尺內的實體設施與建物，消除全表掃描開銷。
        """
        if road_info is None:
            road_info = world_model.get_road_info(lat, lon, heading_deg)
        highway_type = road_info.get("highway_type", "unclassified")
        street_name = road_info.get("street_name", "街道")

        if highway_type in ["pedestrian", "footway"]:
            scene_type = "行人徒步商圈"
            atmosphere = "徒步徒步區，兩側店家熱鬧鼎沸，無車輛通行"
        elif highway_type in ["primary", "secondary", "trunk"]:
            scene_type = "寬敞幹道大馬路"
            atmosphere = "多車道主要幹道，兩側人行道寬廣，車流絡繹不絕"
        elif highway_type in ["residential", "living_street", "service"]:
            scene_type = "清靜巷弄街道"
            atmosphere = "溫馨台式巷弄，兩側為民宅與鄰里小店"
        else:
            scene_type = "繁華都市街道"
            atmosphere = "典型都市街景，車流與行人交織"

        # 2. 空間網格提取街道公共設施 (行道樹、路燈、長椅、騎樓)
        tree_count = 0
        lamp_count = 0
        bench_count = 0
        arcade_found = False

        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = 100.0 / (111139.0 * cos_lat)
        radius_deg_lat = 100.0 / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)

        for item in world_model.poi_rtree.intersection(bounds, objects=True):
            raw_p = item.object
            tags = getattr(raw_p, "tags", {})
            cat = getattr(raw_p, "category", "")
            if tags.get("natural") == "tree" or cat == "tree":
                tree_count += 1
            if tags.get("highway") == "street_lamp" or cat == "street_lamp":
                lamp_count += 1
            if tags.get("amenity") == "bench" or cat == "bench":
                bench_count += 1
            if tags.get("covered") == "yes" or tags.get("building") == "arcade":
                arcade_found = True

        # 3. 空間網格分析周遭建築天際線高度 (Building Architecture & Height Profile)
        b_heights = []
        for item in world_model.building_rtree.intersection(bounds, objects=True):
            b = item.object
            h = b.get("height") or b.get("levels")
            if h:
                try:
                    b_heights.append(int(float(h)))
                except ValueError:
                    pass

        avg_levels = round(sum(b_heights) / len(b_heights)) if b_heights else 4
        if avg_levels >= 10:
            arch_style = f"高聳摩天商辦大樓群 (平均 {avg_levels} 層樓)"
        elif avg_levels >= 5:
            arch_style = f"現代都市公寓與商辦 (平均 {avg_levels} 層樓)"
        else:
            arch_style = f"傳統騎樓與中低層建築 (平均 {avg_levels} 層樓)"

        # 4. Synthesize Real-World Scene Description
        infra_items = []
        if arcade_found: infra_items.append("遮陽避雨騎樓通道")
        if tree_count > 0: infra_items.append(f"綠意行道樹 ({tree_count} 棵)")
        if lamp_count > 0: infra_items.append(f"造型街燈 ({lamp_count} 盞)")
        if bench_count > 0: infra_items.append(f"休憩座椅 ({bench_count} 張)")

        infra_str = "；沿途設有" + "、".join(infra_items) if infra_items else ""

        full_description = f"【街景型態】{street_name} ({scene_type})，{atmosphere}。【建築風貌】{arch_style}{infra_str}。"

        return {
            "street_name": street_name,
            "scene_type": scene_type,
            "atmosphere": atmosphere,
            "architecture_style": arch_style,
            "infrastructure": infra_items,
            "arcade_found": arcade_found,
            "tree_count": tree_count,
            "lamp_count": lamp_count,
            "full_description": full_description
        }
