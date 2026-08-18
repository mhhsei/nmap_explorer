import random
from typing import Dict, Any, List, Set

class WorldState:
    """維護模擬的持續狀態。"""

    NPC_TYPES = ['pedestrian', 'elderly', 'child', 'runner', 'dog_walker', 'delivery', 'vendor', 'smoker', 'parent_stroller', 'tourist', 'student', 'worker']
    
    # 簡單的中文名字生成
    SURNAMES = ['陳', '林', '黃', '張', '李', '王', '吳', '劉', '蔡', '楊']
    NAMES = ['家豪', '雅婷', '冠宇', '怡君', '宗翰', '佳穎', '承翰', '詩婷', '柏宇', '鈺婷', '建宏', '佩珊', '俊傑', '欣儀']

    def __init__(self) -> None:
        self.npcs: List[Dict[str, Any]] = []
        self.active_obstacles: List[Dict[str, Any]] = []
        self.weather: Dict[str, Any] = {
            'condition': '晴天',
            'wind': '微風',
            'temperature': '舒適',
            'effects': []
        }
        self.ground_at_player: Dict[str, str] = {
            'surface': 'asphalt',
            'condition': '乾燥',
            'description': '柏油路面'
        }
        self.time_of_day: str = 'afternoon'
        self.step_count: int = 0
        self.collision_history: List[Dict[str, Any]] = []
        self.visited_pois: Set[str] = set()
        self.dangerous_spots: List[Dict[str, Any]] = []
        self.encountered_npcs: List[str] = []

    def _generate_chinese_name(self) -> str:
        return random.choice(self.SURNAMES) + random.choice(self.NAMES)

    def update_npcs(self, player_lat: float, player_lon: float, area_type: str, difficulty_settings: Dict[str, Any]) -> None:
        """更新 NPC 狀態。"""
        # 簡單的模擬：每步隨機生成或移除 NPC
        if random.random() < 0.3 * difficulty_settings.get('crowd_multiplier', 1.0):
            npc = {
                'id': f"npc_{self.step_count}_{random.randint(1000, 9999)}",
                'name': self._generate_chinese_name(),
                'lat': player_lat + random.uniform(-0.0005, 0.0005),
                'lon': player_lon + random.uniform(-0.0005, 0.0005),
                'heading': random.uniform(0, 360),
                'speed': random.uniform(0.5, 1.5),
                'type': random.choice(self.NPC_TYPES),
                'destination': 'unknown',
                'will_help': random.random() < difficulty_settings.get('npc_help_probability', 0.5),
                'description': '一位路人'
            }
            self.npcs.append(npc)
            
        # 移除過遠的 NPC
        self.npcs = [n for n in self.npcs if (abs(n['lat'] - player_lat) < 0.001 and abs(n['lon'] - player_lon) < 0.001)]

    def add_collision(self, event_dict: Dict[str, Any]) -> None:
        """記錄碰撞事件。"""
        self.collision_history.append(event_dict)

    def record_danger(self, location_dict: Dict[str, Any]) -> None:
        """記錄危險地點。"""
        self.dangerous_spots.append(location_dict)

    def set_weather(self, condition: str) -> None:
        """設定天氣狀況。"""
        self.weather['condition'] = condition

    def set_time(self, time: str) -> None:
        """設定時間。"""
        self.time_of_day = time

    def get_memory_summary(self) -> str:
        """產生玩家體驗摘要。"""
        summary = f"已經走了 {self.step_count} 步。"
        if self.collision_history:
            summary += f" 發生了 {len(self.collision_history)} 次碰撞。"
        if self.dangerous_spots:
            summary += f" 遭遇了 {len(self.dangerous_spots)} 個危險狀況。"
        return summary
