"""
定向行動模擬訓練難度管理器 (Simulation Difficulty Manager)

作用：
1. 提供「初學模式（高提示、人車少、自動白手杖）」、「一般模式」與「專家模式（高突發事件、複雜障礙）」。
2. 支援自訂人潮倍率、車流倍率、障礙物頻率與路人主動協助機率。
"""
from typing import Dict, Any


class DifficultyManager:
    """
    模擬難度管理器
    """
    
    PRESETS = {
        'beginner': {
            'name': '初學模式',
            'hint_level': 3,
            'crowd_multiplier': 0.3,
            'vehicle_multiplier': 0.3,
            'obstacle_multiplier': 0.3,
            'event_frequency': 0.3,
            'npc_help_probability': 0.8,
            'auto_cane': True
        },
        'normal': {
            'name': '一般模式',
            'hint_level': 2,
            'crowd_multiplier': 1.0,
            'vehicle_multiplier': 1.0,
            'obstacle_multiplier': 1.0,
            'event_frequency': 0.6,
            'npc_help_probability': 0.4,
            'auto_cane': False
        },
        'expert': {
            'name': '專家模式',
            'hint_level': 1,
            'crowd_multiplier': 1.5,
            'vehicle_multiplier': 1.5,
            'obstacle_multiplier': 1.5,
            'event_frequency': 0.8,
            'npc_help_probability': 0.2,
            'auto_cane': False
        },
        'custom': {
            'name': '自訂模式',
            'hint_level': 2,
            'crowd_multiplier': 1.0,
            'vehicle_multiplier': 1.0,
            'obstacle_multiplier': 1.0,
            'event_frequency': 0.5,
            'npc_help_probability': 0.5,
            'auto_cane': False
        }
    }

    def __init__(self, preset_name: str = 'normal') -> None:
        self.current_preset: str = preset_name
        self.settings: Dict[str, Any] = self.PRESETS.get(preset_name, self.PRESETS['normal']).copy()

    def get_settings(self) -> Dict[str, Any]:
        """取得當前難度設定參數字典"""
        return self.settings

    def set_difficulty(self, name: str) -> None:
        """切換難度預設模式（beginner / normal / expert / custom）"""

        if name in self.PRESETS:
            self.current_preset = name
            self.settings = self.PRESETS[name].copy()
        else:
            raise ValueError(f"未知的難度模式: {name}")

    def update_custom(self, **kwargs: Any) -> None:
        """更新自訂難度設定。"""
        self.current_preset = 'custom'
        self.settings['name'] = '自訂模式'
        for key, value in kwargs.items():
            if key in self.settings:
                self.settings[key] = value
