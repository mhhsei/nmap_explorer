from typing import Dict, Any, List
import random

class SoundscapeGenerator:
    """產生環境聲景。"""

    def __init__(self) -> None:
        pass

    def generate_ambient(self, area_type: str, weather: Dict[str, Any], time_of_day: str, pois: List[Any], lat: float, lon: float, heading_deg: float) -> List[Dict[str, Any]]:
        """根據區域類型與時間產生環境音效。"""
        sounds = []
        
        base_sounds = {
            'commercial': ['商店音樂', '人群交談', '收銀機聲音'],
            'night_market': ['叫賣聲', '油炸食物滋滋聲', '人群嘈雜', '遊戲機台音效'],
            'residential': ['鳥叫聲', '電視機聲音', '冷氣機運轉聲', '遠處狗吠'],
            'transit_hub': ['公車引擎聲', '捷運進站廣播', '人群急促腳步聲'],
            'park': ['蟲鳴聲', '樹葉沙沙聲', '小孩玩耍笑聲'],
            'school_zone': ['上課鐘聲', '學生嬉鬧聲', '導護志工吹哨聲'],
            'hospital_zone': ['救護車怠速聲', '廣播叫號聲']
        }
        
        area_sounds = base_sounds.get(area_type, ['微風聲', '遠處車流聲'])
        
        # 隨機選擇1到3個環境音
        num_sounds = random.randint(1, 3)
        selected_sounds = random.sample(area_sounds, min(num_sounds, len(area_sounds)))
        
        for sound in selected_sounds:
            sounds.append({
                'description': sound,
                'clock_position': random.choice(['12點鐘', '3點鐘', '6點鐘', '9點鐘']),
                'distance_category': random.choice(['near', 'medium', 'far']),
                'intensity': random.choice(['quiet', 'moderate', 'loud'])
            })
            
        return sounds
