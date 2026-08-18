import math
from typing import Dict, Any, List

class StreetSceneEngine:
    """
    Real-World Physical Street Scene Engine.
    Analyzes physical road geometry, building architecture, street infrastructure (trees, lamps, arcades, benches),
    and environmental atmosphere to paint a 100% realistic street scene picture.
    """

    def analyze_scene(self, lat: float, lon: float, heading_deg: float, world_model: Any) -> Dict[str, Any]:
        pois = world_model.pois
        buildings = world_model.buildings

        # 1. Classify Physical Street Layout
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

        # 2. Extract Street Physical Infrastructure (Trees, Lamps, Benches, Arcades)
        tree_count = 0
        lamp_count = 0
        bench_count = 0
        arcade_found = False

        for raw_p in pois:
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

        # 3. Analyze Building Architecture & Height Profile
        b_heights = []
        for b in buildings:
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
