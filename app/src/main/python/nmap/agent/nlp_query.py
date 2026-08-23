"""
自然語言空間語意解析與問答引擎 (NLP Spatial Query Engine)

作用：讓視障者能用最自然的日常對話詢問周遭環境：
1. 方向性查詢：「左邊有什麼？」、「前面有什麼？」
2. 特定店家查詢：「最近的便利商店在哪？」、「附近有 ATM 嗎？」
3. 路口與過馬路安全性：「前面的路口好走嗎？」、「有斑馬線嗎？」
4. 語意生活需求匹配：「我想買早餐」、「肚子餓想吃麵」
"""
import re
from typing import Dict, Any, List, Optional
from nmap.agent.explorer import ExplorerAgent
from nmap.spatial.geometry import bearing_to_cardinal
from nmap.spatial.semantic_radar import SemanticRadar


class NLPQueryEngine:
    """
    自然語言空間問答引擎
    """
    def __init__(self):
        self.semantic_radar = SemanticRadar()
        # 非同步初始化向量語意雷達模型
        self.semantic_radar.initialize()

    def process_query(self, query: str, agent: ExplorerAgent) -> str:
        """
        處理使用者的自然語言提問，並產出適合 NVDA 朗讀的清晰文字
        """
        if not agent.is_loaded:
            return "請先使用 start 指令定位目標地址或座標以開啟世界地圖。"

        query_clean = query.strip().lower()

        # 1. 方位性查詢：左邊 / 右邊 / 前面 / 後面 有什麼
        if "左邊" in query_clean or "左側" in query_clean:
            return self._query_directional(agent, sector_filter="左")
        if "右邊" in query_clean or "右側" in query_clean:
            return self._query_directional(agent, sector_filter="右")
        if "前面" in query_clean or "前方" in query_clean:
            return self._query_directional(agent, sector_filter="前")
        if "後面" in query_clean or "後方" in query_clean:
            return self._query_directional(agent, sector_filter="後")

        # 2. 特定店家與設施關鍵字比對（超商、公車、捷運、ATM、藥局、廁所等）
        poi_targets = {
            "便利商店": ["convenience", "7-11", "全家", "萊爾富", "ok", "711"],
            "超商": ["convenience", "7-11", "全家"],
            "公車": ["bus_stop", "公車"],
            "捷運": ["subway_entrance", "捷運"],
            "ATM": ["atm", "bank"],
            "提款機": ["atm"],
            "銀行": ["bank"],
            "藥局": ["pharmacy"],
            "醫院": ["hospital", "clinic", "診所"],
            "診所": ["clinic"],
            "廁所": ["toilet"],
            "餐廳": ["restaurant", "fast_food", "food"],
            "早餐店": ["bakery", "fast_food", "breakfast"],
            "咖啡": ["cafe"],
            "公園": ["park"]
        }

        matched_category = None
        for keyword, tags in poi_targets.items():
            if keyword in query_clean:
                matched_category = (keyword, tags)
                break

        if matched_category:
            kw, tags = matched_category
            return self._query_specific_poi(agent, kw, tags)

        # 3. 路口與過馬路安全性查詢（斑馬線、號誌、安全嗎）
        if any(w in query_clean for w in ["路口", "斑馬線", "號誌", "安全嗎", "過馬路"]):
            return self._query_intersection_safety(agent)

        # 4. 人行道通行無障礙評估（好走嗎、人行道、騎樓、車道）
        if any(w in query_clean for w in ["好走嗎", "人行道", "車道", "騎樓", "施工"]):
            return self._query_sidewalk_accessibility(agent)
            
        # 5. 語意雷達意圖匹配（例如：「想吃熱呼呼的湯麵」、「需要領錢」）
        if any(w in query_clean for w in ["想", "買", "找", "需要", "哪裡有"]):
            radar_result = self._query_semantic_intent(agent, query)
            if radar_result:
                return radar_result

        # 6. 通用預設回退：周遭 50 公尺總體環境概述
        return self._query_general_surroundings(agent)

    def _query_directional(self, agent: ExplorerAgent, sector_filter: str) -> str:
        """過濾指定方位（左/右/前/後）方圓 80 公尺內的店家"""
        pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=80.0)
        filtered = [p for p in pois if sector_filter in p["relative_direction"]]

        if not filtered:
            return f"在你的【{sector_filter}側】80 公尺內，目前沒有登錄特別的店家或設施。"

        lines = [f"【{sector_filter}側周遭設施】（共 {len(filtered)} 個）："]
        for p in filtered[:6]:
            lines.append(f"• {p['name']} ({p['category']})：距離 {p['distance_m']} 公尺，位於 {p['clock_position']} ({p['relative_direction']})")

        return "\n".join(lines)

    def _query_specific_poi(self, agent: ExplorerAgent, keyword: str, tags: List[str]) -> str:
        """搜尋特定類型的店家（如便利商店、公車站），列出鐘點方位與距離"""
        all_pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=150.0)
        matches = []
        for p in all_pois:
            p_cat = p["category"].lower()
            p_name = p["name"].lower()
            if any(t.lower() in p_cat or t.lower() in p_name for t in tags):
                matches.append(p)

        if not matches:
            return f"在方圓 150 公尺內，未找到附近的【{keyword}】。"

        lines = [f"【附近 {keyword} 搜尋結果】（最近的 {len(matches[:3])} 個）："]
        for p in matches[:3]:
            lines.append(
                f"• {p['name']}：距離 {p['distance_m']} 公尺，位於 {p['clock_position']} ({p['relative_direction']} / {p['cardinal_direction']})"
            )
            if p.get("opening_hours"):
                lines.append(f"  營業時間：{p['opening_hours']}")
            if p.get("phone"):
                lines.append(f"  電話：{p['phone']}")

        return "\n".join(lines)

    def _query_intersection_safety(self, agent: ExplorerAgent) -> str:
        """分析前方路口安全性、斑馬線與行人號誌配置"""
        analysis = agent.intersection_analyzer.analyze(agent.lat, agent.lon, agent.heading_deg, agent.world_model, max_distance_m=60.0)
        lines = [
            f"【路口與過馬路安全分析】",
            f"前方型態：{analysis['junction_type']}" + (f" (約 {analysis['junction_distance_m']} 公尺)" if analysis['junction_distance_m'] else ""),
            f"安全摘要：{analysis['safety_summary']}"
        ]

        if analysis["crossings"]:
            lines.append("【行人穿越道細節】:")
            for c in analysis["crossings"][:2]:
                sig = "有號誌" if c["crossing_signals"] != "no" else "無號誌"
                tac = "有導盲磚" if c["tactile_paving"] == "yes" else "無導盲磚"
                lines.append(f"• 距離 {c['distance_m']} 公尺 ({c['clock_position']})：{sig}、{tac}")

        return "\n".join(lines)

    def _query_sidewalk_accessibility(self, agent: ExplorerAgent) -> str:
        """分析道路人行道品質、鋪面與車道數量"""
        road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
        lines = [
            f"【道路與人行道通行評估】",
            f"目前道路：{road_info['street_name']} ({road_info['oneway']}，{road_info['lanes']} 車道)",
            f"人行道狀況：{road_info['sidewalk_desc']}",
            f"路面材質：{road_info['surface']}"
        ]
        return "\n".join(lines)

    def _query_semantic_intent(self, agent: ExplorerAgent, intent: str) -> Optional[str]:
        """利用語意雷達模型匹配使用者的生活需求意圖"""
        pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=200.0)
        matches = self.semantic_radar.search_intent(intent, pois, top_k=2, threshold=0.6)
        
        if not matches:
            return None # 若無語意匹配則回退為一般環境查詢
            
        lines = [f"【AI語意分析：為您找到適合「{intent}」的去處】"]
        for p, score in matches:
            lines.append(f"• {p['name']} ({p['category']})：位於 {p['clock_position']} ({p['relative_direction']})，距離 {p['distance_m']} 公尺")
            if p.get("opening_hours"):
                lines.append(f"  營業時間：{p['opening_hours']}")
            
        return "\n".join(lines)

    def _query_general_surroundings(self, agent: ExplorerAgent) -> str:
        """查詢周遭 50 公尺一般概況"""
        pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=50.0)
        if not pois:
            return "在目前位置方圓 50 公尺內，環境較為平靜，無特別登錄的設施。"

        lines = [f"【周遭 50 公尺環境資訊】（共 {len(pois)} 處）："]
        for p in pois[:5]:
            lines.append(f"• {p['name']} ({p['category']})：位於 {p['clock_position']} ({p['relative_direction']})，距離 {p['distance_m']} 公尺")
        return "\n".join(lines)

