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
    LEVEL_GROUND: "地面層 (1樓)",
    LEVEL_OVERPASS: "人行天橋/二樓空橋",
    LEVEL_UNDERGROUND: "地下連通道/地下街B1",
    LEVEL_UNDERGROUND_B2: "捷運大廳/月台層B2",
    "INDOOR_1F": "1樓",
    "INDOOR_2F": "2樓",
    "INDOOR_3F": "3樓",
    "INDOOR_4F": "4樓",
    "INDOOR_5F": "5樓",
    "INDOOR_6F": "6樓",
    "INDOOR_7F": "7樓",
    "INDOOR_8F": "8樓",
    "INDOOR_9F": "9樓",
    "INDOOR_10F": "10樓",
    "INDOOR_11F": "11樓",
    "INDOOR_12F": "12樓",
    "INDOOR_13F": "13樓",
    "INDOOR_14F": "14樓",
    "INDOOR_15F": "15樓",
    "INDOOR_B1": "地下1樓",
    "INDOOR_B2": "地下2樓",
    "INDOOR_B3": "地下3樓",
    "INDOOR_B4": "地下4樓",
    "INDOOR_B5": "地下5樓",
}


def to_spoken_floor(floor_name: str) -> str:
    """將 3F / B1 轉為更適合語音朗讀的人話（如 3樓、地下1樓）"""
    if not floor_name:
        return "1樓"
    f = str(floor_name).strip().upper()
    if f in ("1F", "1", "1樓", "地面", "地面層", "GROUND"):
        return "1樓"
    if f.startswith("B"):
        num = f[1:]
        return f"地下{num}樓" if num else "地下室"
    if f.endswith("F") and f[:-1].isdigit():
        return f"{f[:-1]}樓"
    return f


def floor_to_level(floor_str: str) -> str:
    """將樓層字串 (如 '2F', 'B1') 轉換為標準內部層級標籤"""
    if not floor_str:
        return LEVEL_GROUND
    f = str(floor_str).strip().upper()
    if f in ("1F", "1", "1樓", "地面", "地面層"):
        return LEVEL_GROUND
    if f.startswith("B"):
        key = f"INDOOR_{f}"
        return key if key in LEVEL_DISPLAY_NAMES else "INDOOR_B1"
    num = "".join(ch for ch in f if ch.isdigit())
    if num:
        key = f"INDOOR_{num}F"
        return key if key in LEVEL_DISPLAY_NAMES else "INDOOR_2F"
    return LEVEL_GROUND


def level_to_floor(level_str: str) -> str:
    """將標準內部層級標籤轉換為人類最直覺的樓層字串 (如 '1F', '3F', 'B2')"""
    if not level_str or level_str == LEVEL_GROUND:
        return "1F"
    if level_str == LEVEL_OVERPASS:
        return "2F"
    if level_str == LEVEL_UNDERGROUND:
        return "B1"
    if level_str == LEVEL_UNDERGROUND_B2:
        return "B2"
    if level_str.startswith("INDOOR_"):
        return level_str.replace("INDOOR_", "")
    return "1F"


class VerticalLevelManager:
    """
    立體三度空間樓層與設施過濾器
    """

    @staticmethod
    def format_transition_speech(old_level: str, new_level: str, altitude_m: float, floor_str: str = "") -> str:
        """
        生成樓層變更的語音播報內容（省話模式，1秒內理解，優先報讀人話樓層）
        """
        alt_str = f"{altitude_m:+.1f}米" if altitude_m != 0.0 else "±0米"
        target_floor = floor_str or level_to_floor(new_level)
        spoken_floor = to_spoken_floor(target_floor)

        if new_level == LEVEL_OVERPASS:
            return f"📍 偵測已登上【人行天橋】(高度 {alt_str})，已切換為天橋導航圖資。"
        elif new_level == LEVEL_UNDERGROUND:
            return f"📍 偵測已進入【地下連通道/地下街】(高度 {alt_str})，已切換為地下層圖資。"
        elif new_level == LEVEL_UNDERGROUND_B2:
            return f"📍 偵測已下抵【捷運大廳/月台層】(高度 {alt_str})，已切換為深層地下圖資。"
        elif new_level == LEVEL_GROUND:
            if old_level == LEVEL_OVERPASS:
                return f"📍 走下天橋，已返回【1樓地面】。"
            elif old_level in (LEVEL_UNDERGROUND, LEVEL_UNDERGROUND_B2) or "INDOOR_B" in old_level:
                return f"📍 走出地下層，已重返【1樓地面】。"
            else:
                return f"📍 目前位於【1樓地面】。"
        elif new_level.startswith("INDOOR_"):
            return f"📍 垂直樓層切換至【{spoken_floor}】（高度差 {alt_str}）。"
        return f"📍 垂直高程切換至【{LEVEL_DISPLAY_NAMES.get(new_level, spoken_floor)}】。"

    @staticmethod
    def filter_and_prioritize_pois(
        pois: List[Dict[str, Any]], 
        current_level: str,
        target_floor: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        依據使用者當前的立體高程 (current_level) 與指定目標樓層 (target_floor)，
        對周遭店家設施進行智慧過濾與層級標籤化。
        """
        if not pois:
            return []

        active_floor = (target_floor or level_to_floor(current_level)).upper()

        if current_level == LEVEL_GROUND and (not target_floor or target_floor.upper() in ("1F", "1", "1樓", "地面")):
            return pois

        elevated_keywords = {"天橋", "人行天橋", "陸橋", "空橋", "二樓", "2f", "2樓", "電梯", "昇降梯", "手扶梯"}
        underground_keywords = {"地下街", "地下道", "連通道", "捷運", "月台", "剪票", "閘門", "b1", "b2", "地下", "出入口", "諮詢", "服務處"}

        prioritized = []
        regular = []

        for p in pois:
            name = p.get("name", "")
            cat = p.get("category", "")
            floor = (p.get("floor") or "1F").upper()
            dist = float(p.get("distance_m", 999.0))

            # 近身店家豁免條款 (距離 <= 5.0m)：
            if dist <= 5.0:
                p_copy = dict(p)
                p_copy["level_tag"] = "📍 門前近處"
                prioritized.append(p_copy)
                continue

            if active_floor and active_floor not in ("1F", "1", "1樓"):
                if floor == active_floor:
                    p_copy = dict(p)
                    p_copy["level_tag"] = f"🏢 同在{active_floor}"
                    prioritized.append(p_copy)
                else:
                    p_copy = dict(p)
                    p_copy["level_tag"] = f"位於 {floor}"
                    regular.append(p_copy)
                continue

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

            elif current_level in (LEVEL_UNDERGROUND, LEVEL_UNDERGROUND_B2) or "INDOOR_B" in current_level:
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
            else:
                prioritized.append(p)

        return prioritized + regular


# 模組級別別名保持相容性
format_transition_speech = VerticalLevelManager.format_transition_speech
