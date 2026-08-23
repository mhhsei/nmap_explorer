"""
非視覺街景感知合成器 (Non-Visual Street View Synthesizer)

作用：
為視障者將空間圖資轉譯為生動的街景意象（例如：「面向正北的北新路街景：兩側店家林立，道路寬敞，設有劃設人行道」）。
"""
from typing import Dict, Any
from nmap.spatial.geometry import bearing_to_cardinal


class StreetViewAnalyzer:
    """
    非視覺街景合成器
    """

    def analyze_scene(self, lat: float, lon: float, heading_deg: float, world_model) -> Dict[str, Any]:
        """
        【合成目前朝向的非視覺街景摘要】
        """
        road_info = world_model.get_road_info(lat, lon, heading_deg)
        pois = world_model.get_nearby_pois(lat, lon, heading_deg, radius_m=50.0)
        buildings = world_model.get_nearby_buildings(lat, lon, heading_deg, radius_m=40.0)
        cardinal = bearing_to_cardinal(heading_deg)

        # 街景特徵分類（店家、樹木、騎樓）
        has_stores = len([p for p in pois if p['category'] in ['convenience', 'restaurant', 'shop', 'cafe']]) > 0
        has_trees = len([p for p in pois if 'park' in p['category'] or 'tree' in p['category']]) > 0
        has_arcade = "騎樓" in road_info.get("sidewalk_desc", "") or "騎樓" in road_info.get("surface", "")
        
        scene_tags = []
        if has_stores:
            scene_tags.append("兩側店家林立")
        if road_info.get("lanes", "1") != "1":
            scene_tags.append("道路寬敞")
        if "兩側" in road_info.get("sidewalk_desc", ""):
            scene_tags.append("設有劃設人行道")
        else:
            scene_tags.append("車道與人行混合")
        if has_trees:
            scene_tags.append("帶有行道樹綠意")

        scene_summary = f"面向{cardinal}的{road_info['street_name']}街景：" + "，".join(scene_tags)

        return {
            "scene_summary": scene_summary,
            "scene_tags": scene_tags,
            "heading_cardinal": cardinal,
            "street_name": road_info['street_name'],
            "has_stores": has_stores,
            "has_arcade": has_arcade
        }

