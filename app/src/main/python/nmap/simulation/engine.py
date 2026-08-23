"""
定向行動模擬核心總指揮引擎 (Simulation Engine Core)

作用：
協調整個模擬系統的子模組運作：
1. 區域分類 (AreaClassifier)
2. 虛擬 NPC 路人更新 (WorldState)
3. 突發事件生成 (EventGenerator)
4. 白手杖前向探測 (WhiteCaneSimulator)
5. 環境聲景音效 (SoundscapeGenerator)
6. 風險等級評估與 NVDA 報讀報告產出 (SimulationReporter)
"""
from typing import Dict, Any
from .world_state import WorldState
from .events import EventGenerator
from .area_classifier import AreaClassifier
from .difficulty import DifficultyManager
from .white_cane import WhiteCaneSimulator
from .soundscape import SoundscapeGenerator
from .reporter import SimulationReporter


class SimulationEngine:
    """
    主模擬引擎
    """

    def __init__(self) -> None:
        self.enabled: bool = False
        self.world_state: WorldState = WorldState()
        self.event_generator: EventGenerator = EventGenerator()
        self.area_classifier: AreaClassifier = AreaClassifier()
        self.difficulty: DifficultyManager = DifficultyManager()
        self.cane_sim: WhiteCaneSimulator = WhiteCaneSimulator()
        self.soundscape: SoundscapeGenerator = SoundscapeGenerator()
        self.reporter: SimulationReporter = SimulationReporter()

    def start(self, difficulty: str = 'normal') -> None:
        """
        【啟動定向模擬訓練】
        """
        self.difficulty.set_difficulty(difficulty)
        self.enabled = True
        self.world_state = WorldState()

    def stop(self) -> None:
        """
        【關閉定向模擬訓練】
        """
        self.enabled = False

    def process_step(self, agent: Any) -> Dict[str, Any]:
        """
        【處理探索者移動的每一步】
        作用：推演區域特性、更新 NPC、生成路況事件、模擬白手杖敲擊、播放環境音與評估風險。
        """
        if not self.enabled:
            return {}


        self.world_state.step_count += 1
        
        # 1. 區域分類
        area_info = self.area_classifier.classify(agent.world_model, agent.lat, agent.lon, agent.heading_deg)
        area_type = area_info['area_type']
        
        # 2. 更新 NPC
        self.world_state.update_npcs(agent.lat, agent.lon, area_type, self.difficulty.get_settings())
        
        # 3. 產生事件
        events = self.event_generator.generate_step_events(
            area_type, area_info, self.difficulty.get_settings(), 
            self.world_state.weather, self.world_state.time_of_day, 
            agent.heading_deg, agent.world_model, agent.lat, agent.lon
        )
        
        # 4. 白手杖模擬
        cane_result = {'description': '尚未使用白手杖', 'danger_level': 'none'}
        if self.difficulty.get_settings().get('auto_cane'):
            cane_result = self.cane_sim.tap_ahead(agent.lat, agent.lon, agent.heading_deg, agent.world_model, self.world_state.active_obstacles)
            
        # 5. 聲景產生
        pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg) if hasattr(agent.world_model, 'get_nearby_pois') else []
        ambient_sounds = self.soundscape.generate_ambient(
            area_type, self.world_state.weather, self.world_state.time_of_day, pois, agent.lat, agent.lon, agent.heading_deg
        )
        
        # 6. 評估風險
        risk_level = 'safe'
        if any(e.get('danger_level') == 'high' for e in events) or cane_result.get('danger_level') == 'high':
            risk_level = 'high'
        elif any(e.get('danger_level') == 'low' for e in events):
            risk_level = 'low'
            
        # 7. 產生報告
        narration = self.reporter.generate_step_report(
            events, ambient_sounds, cane_result, risk_level, 
            self.world_state.weather, self.world_state.ground_at_player, 
            area_info, self.difficulty.get_settings(), self.world_state.get_memory_summary()
        )

        return {
            'narration': narration,
            'events': events,
            'risk_level': risk_level,
            'weather': self.world_state.weather,
            'area_type': area_type,
            'ground': self.world_state.ground_at_player,
            'npc_count': len(self.world_state.npcs),
            'obstacle_count': len(self.world_state.active_obstacles),
            'memory_summary': self.world_state.get_memory_summary()
        }

    def process_action(self, action: str, agent: Any) -> Dict[str, Any]:
        """處理玩家特定動作。"""
        if action == 'use_cane':
            result = self.cane_sim.tap_ahead(agent.lat, agent.lon, agent.heading_deg, agent.world_model, self.world_state.active_obstacles)
            return {'result': result['description']}
        return {'result': '未知的動作'}

    def get_status(self) -> Dict[str, Any]:
        """取得系統狀態。"""
        return {
            'enabled': self.enabled,
            'difficulty': self.difficulty.current_preset,
            'step_count': self.world_state.step_count
        }

    def update_settings(self, settings: Dict[str, Any]) -> None:
        """更新設定。"""
        self.difficulty.update_custom(**settings)
