# -*- coding: utf-8 -*-
"""
【三度空間立體樓層與垂直高度管理模組 (vertical_level.py)】

生活化比喻（小學生都看得懂）：
就像百貨公司或捷運站裡的「立體電梯樓層嚮導」。
一般的地圖都是平面的，只管前後左右；但人在走天橋時，頭頂只有天空，腳下是呼嘯而過的車流；
在地下街時，頭頂是天花板，四周是地下商場。
這座模組能精準依據氣壓計計算出來的高程，為視障朋友自動切換對應樓層的設施與出口，
絕不在天橋上唸橋下的水煎包店，也不在地下道唸地面上的公車亭！
"""

from typing import List, Dict, Any, Optional

# 支援之立體高度層級定義
LEVEL_GROUND = "GROUND"              # 地面層 (0m)
LEVEL_OVERPASS = "OVERPASS"          # 人行天橋 / 二樓空橋 (+3.5m ~ +7.0m)
LEVEL_UNDERGROUND = "UNDERGROUND"    # 地下連通道 / 地下街 B1 (-2.5m ~ -5.0m)
LEVEL_UNDERGROUND_B2 = "UNDERGROUND_B2" # 捷運月台 / 穿堂層 B2 (-5.5m ~ -12.0m)

LEVEL_DISPLAY_NAMES = {
    LEVEL_GROUND: "地面層",
    LEVEL_OVERPASS: "人行天橋/二樓空橋",
    LEVEL_UNDERGROUND: "地下連通道/地下街B1",
    LEVEL_UNDERGROUND_B2: "捷運大廳/月台層B2"
}


class VerticalLevelManager:
    """
    立體三度空間樓層與設施過濾器
    """

    @staticmethod
    def format_transition_speech(old_level: str, new_level: str, altitude_m: float) -> str:
        """
        生成樓層變更的語音播報內容（省話模式，1秒內理解）
        """
        alt_str = f"{altitude_m:+.1f}米" if altitude_m != 0.0 else "±0米"

        if new_level == LEVEL_OVERPASS:
            return f"📍 偵測已登上【人行天橋】(高度 {alt_str})，已為您切換為天橋導航圖資。"
        elif new_level == LEVEL_UNDERGROUND:
            return f"📍 偵測已進入【地下連通道/地下街】(高度 {alt_str})，已為您切換為地下層圖資。"
        elif new_level == LEVEL_UNDERGROUND_B2:
            return f"📍 偵測已下抵【捷運大廳/月台層】(高度 {alt_str})，已切換為深層地下圖資。"
        elif new_level == LEVEL_GROUND:
            if old_level == LEVEL_OVERPASS:
                return f"📍 走下天橋，已返回【地面層】。"
            elif old_level in (LEVEL_UNDERGROUND, LEVEL_UNDERGROUND_B2):
                return f"📍 走出地下道，已重返【地面層】。"
            else:
                return f"📍 目前位於【地面層】。"
        return f"📍 垂直高程切換至【{LEVEL_DISPLAY_NAMES.get(new_level, '地面')}】。"

    @staticmethod
    def filter_and_prioritize_pois(pois: List[Dict[str, Any]], current_level: str) -> List[Dict[str, Any]]:
        """
        依據使用者當前的立體高程 (current_level)，對周遭店家設施進行智慧過濾與層級標籤化。
        
        過濾策略：
        1. OVERPASS (天橋)：
           - 優先突出天橋專屬階梯、斜坡、電梯、對街出口、天橋標牌。
           - 對位於天橋下方地面層的店家自動加上【地面層】標記，且在簡短報讀中降權，避免聽覺轟炸。
        2. UNDERGROUND (地下連通道/地下街)：
           - 優先突出地下街出口代號 (如 Z4, K8)、捷運進出站閘門、無障礙電梯、詢問處與地下商鋪。
           - 自動抑制上方路面無關建築。
        3. GROUND (地面層)：
           - 正常報讀地面騎樓與街道店家。
        """
        if not pois:
            return []

        if current_level == LEVEL_GROUND:
            return pois

        elevated_keywords = {"天橋", "人行天橋", "陸橋", "空橋", "二樓", "2f", "2樓", "電梯", "昇降梯", "手扶梯"}
        underground_keywords = {"地下街", "地下道", "連通道", "捷運", "月台", "剪票", "閘門", "b1", "b2", "地下", "出入口", "諮詢", "服務處"}

        prioritized = []
        regular = []

        for p in pois:
            name = p.get("name", "")
            cat = p.get("category", "")
            floor = p.get("floor", "1F")

            if current_level == LEVEL_OVERPASS:
                is_elevated = (
                    any(k in name for k in elevated_keywords) or 
                    any(k in cat for k in elevated_keywords) or 
                    floor in ("2F", "3F", "2", "3")
                )
                if is_elevated:
                    p_copy = dict(p)
                    p_copy["level_tag"] = "🌁 天橋層"
                    prioritized.append(p_copy)
                else:
                    p_copy = dict(p)
                    p_copy["level_tag"] = "地面層 (橋下)"
                    regular.append(p_copy)

            elif current_level in (LEVEL_UNDERGROUND, LEVEL_UNDERGROUND_B2):
                is_underground = (
                    any(k in name for k in underground_keywords) or 
                    any(k in cat for k in underground_keywords) or 
                    floor in ("B1", "B2", "-1", "-2", "地下街")
                )
                if is_underground:
                    p_copy = dict(p)
                    p_copy["level_tag"] = "🚇 地下層"
                    prioritized.append(p_copy)
                else:
                    p_copy = dict(p)
                    p_copy["level_tag"] = "路面層 (上方)"
                    regular.append(p_copy)

        # 優先回傳當前樓層的目標，次要目標排在後方
        return prioritized + regular
