"""
定向模擬資訊播報轉換器 (Simulation NVDA Reporter)

作用：
將複雜的多維度模擬數據（天氣、地質、障礙、NPC、白手杖、聲景）整理為最適合 NVDA 螢幕報讀軟體朗讀的文字串。
黃金播報優先級設計（無障礙最高原則）：
1. ⚠️ 緊急狀況與致命危險最優先（車道邊緣、深坑）
2. 🦯 白手杖觸覺反饋（導盲磚紋理、牆壁敲擊聲）
3. ❗ 周遭動態突發事件（行人擦肩、機車靠近）
4. 📍 腳下路況與地面材質（碎石、積水、台階）
5. 🔊 環境聲景方位（便利商店開門聲、公車進站聲）
6. 🌤️ 大環境宏觀資訊（區域型態、天候）
"""
from typing import Dict, Any, List


class SimulationReporter:
    """
    模擬數據 NVDA 報表產生器
    """

    def __init__(self) -> None:
        pass

    def generate_step_report(self, events: List[Dict[str, Any]], ambient_sounds: List[Dict[str, Any]], cane_result: Dict[str, Any], risk_level: str, weather: Dict[str, Any], ground: Dict[str, str], area_info: Dict[str, Any], difficulty_settings: Dict[str, Any], player_memory: str) -> str:
        """
        【產生每一步的 NVDA 語音報讀文字】
        """
        
        area_desc = area_info.get('description', '未知區域')
        weather_desc = weather.get('condition', '晴天')
        ground_desc = ground.get('description', '一般路面')
        cane_desc = cane_result.get('description', '未偵測到特殊狀況')
        
        risk_map = {
            'safe': '安全', 'low': '低風險', 'medium': '中等風險', 'high': '高風險', 'critical': '極度危險'
        }
        risk_desc = risk_map.get(risk_level, '未知')

        # 重構播報順序：以重度視障者需求為核心，將最重要/最危險的資訊排在最前面
        report = ""

        
        # 1. ⚠️緊急/危險最優先 (安全第一)
        if risk_level in ['high', 'critical'] or risk_desc != '安全':
            report += f"⚠️【緊急狀況】{risk_desc}\n"
            
        # 2. 🦯白手杖回饋 (最貼近身體的觸覺)
        if difficulty_settings.get('auto_cane', False):
            if cane_desc != '未偵測到特殊狀況':
                report += f"🦯【白手杖】{cane_desc}\n"
            
        # 3. ❗周遭突發事件 (動態物體：車輛、行人、障礙)
        if events:
            report += "❗【周遭事件】\n"
            for e in events:
                report += f"• {e['description']}\n"
                if difficulty_settings.get('hint_level', 1) > 1 and e.get('suggested_action'):
                    report += f"  (提示: {e['suggested_action']})\n"
                    
        # 4. 📍路況與地面 (靜態實體環境)
        report += f"📍【路況】{ground_desc}\n"
        
        # 5. 🔊聲景 (遠處環境聽覺路標)
        if ambient_sounds:
            sounds_str = "、".join([s['description'] for s in ambient_sounds])
            report += f"🔊【環境音】{sounds_str}\n"
            
        # 6. 🌤️大環境 (非緊急的大範圍資訊放最後)
        report += f"🌤️【大環境】{area_desc}，{weather_desc}"
        
        return report

    def generate_situation_report(self, world_state: Any) -> str:
        """產生詳細情況報告。"""
        return f"詳細情況報告：\n{world_state.get_memory_summary()}"
