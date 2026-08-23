"""
情境模擬區域型態自動分類器 (Area Classifier)

作用：
根據目前座標周圍 50 公尺內的真實店家類型（餐飲、超商、車站、公園、學校、醫院）與道路等級，
自動判定當前屬於哪種生活場景（住宅區、商業街、夜市、交通樞紐、學區等），動態設定人流密度、車流音量與噪音水平。
"""
from typing import Dict, Any, List


class AreaClassifier:
    """
    區域型態分類器
    """

    def __init__(self) -> None:
        pass

    def classify(self, world_model: Any, lat: float, lon: float, heading_deg: float) -> Dict[str, Any]:
        """
        【分類當前區域特徵與生活場景型態】
        作用：計算 POI 類別分佈與道路等級，輸出人潮密度 (crowd_density) 與車流量 (vehicle_traffic)。
        """
        pois = world_model.get_nearby_pois(lat, lon, heading_deg, radius_m=50) if hasattr(world_model, 'get_nearby_pois') else []
        roads = world_model.get_road_info(lat, lon, heading_deg) if hasattr(world_model, 'get_road_info') else []
        
        counts: Dict[str, int] = {
            'food': 0, 'shop': 0, 'transit': 0, 'leisure': 0, 'health': 0, 'education': 0
        }

        
        for poi in pois:
            cat = getattr(poi, 'category', '').lower()
            if 'restaurant' in cat or 'cafe' in cat or 'food' in cat:
                counts['food'] += 1
            elif 'shop' in cat or 'convenience' in cat or 'supermarket' in cat:
                counts['shop'] += 1
            elif 'bus' in cat or 'subway' in cat or 'station' in cat or 'transit' in cat:
                counts['transit'] += 1
            elif 'park' in cat or 'leisure' in cat:
                counts['leisure'] += 1
            elif 'hospital' in cat or 'clinic' in cat or 'health' in cat:
                counts['health'] += 1
            elif 'school' in cat or 'university' in cat or 'education' in cat:
                counts['education'] += 1
                
        poi_total = len(pois)
        area_type = 'residential'
        description = '住宅區，環境相對安靜'
        crowd = 0.2
        noise = 0.2
        
        if counts['food'] > 3 and counts['shop'] > 2 and 'night_market' in str(pois):
            area_type = 'night_market'
            description = '夜市區，人潮擁擠，攤販林立'
            crowd = 0.9
            noise = 0.8
        elif counts['food'] + counts['shop'] > 5:
            area_type = 'commercial'
            description = '商業區，店家多，行人來往頻繁'
            crowd = 0.7
            noise = 0.6
        elif counts['transit'] > 0:
            area_type = 'transit_hub'
            description = '交通樞紐，人潮進出頻繁'
            crowd = 0.8
            noise = 0.7
        elif counts['leisure'] > 1:
            area_type = 'park'
            description = '公園休閒區，環境寬敞'
            crowd = 0.4
            noise = 0.3
        elif counts['education'] > 0:
            area_type = 'school_zone'
            description = '學區，上下學時間人潮較多'
            crowd = 0.5
            noise = 0.5
        elif counts['health'] > 0:
            area_type = 'hospital_zone'
            description = '醫院周邊，可能有救護車進出'
            crowd = 0.4
            noise = 0.4
            
        vehicle_traffic = 0.3
        if roads:
            primary_roads = [r for r in roads if getattr(r, 'highway_type', '') in ['primary', 'secondary', 'trunk']]
            if primary_roads:
                vehicle_traffic = 0.8
                noise = min(1.0, noise + 0.3)
                description += '，臨近主要幹道，車流量大'

        return {
            'area_type': area_type,
            'crowd_density': crowd,
            'vehicle_traffic': vehicle_traffic,
            'noise_level': noise,
            'description': description
        }
