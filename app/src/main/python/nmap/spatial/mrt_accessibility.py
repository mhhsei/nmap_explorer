"""
【捷運立體無障礙出入口與專屬電梯導引庫 (MrtAccessibilityDirectory)】

生活化比喻：
大型捷運站就像一座繁複的地下宮殿，地面上往往散落著 6 到 8 個出口。
如果沒有精準指引，視障者好不容易摸到一個出口，走進去才發現是一整段又長又陡的 60 階水泥樓梯，既危險又吃力；
而真正寬敞、安全的「無障礙直通電梯」，往往隱藏在隔壁 30 公尺處的特定出口（例如台北車站 M1、忠孝復興 2號出口）。
本模組專門維護捷運立體無障礙空間資料：
將每個出口的「電梯、雙向電扶梯、無障礙斜坡與無障礙廁所」精確標定，
當使用者前往捷運站時，演算法「優先鎖定專屬無障礙電梯」，守護每一次進出站的平穩與安全！
"""

from typing import List, Dict, Any, Optional
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_relative_direction
)

MAX_MRT_SEARCH_RADIUS_METERS = 300.0

# 台灣代表性捷運樞紐站（台北捷運、高雄捷運）立體無障礙出入口資料庫
# 包含台北車站、西門、忠孝復興、市政府、板橋、美麗島等大站
DEFAULT_MRT_ACCESSIBLE_EXITS = [
    # 台北捷運 台北車站 (含板南線/淡水信義線)
    {
        "station_name": "台北車站",
        "system": "TRTC",
        "exit_name": "出口 M1 (無障礙電梯專用)",
        "lat": 25.04685,
        "lon": 121.51652,
        "has_elevator": True,
        "has_escalator_up": True,
        "has_escalator_down": True,
        "has_ramp": True,
        "restroom_info": "B1穿堂層近M1設有無障礙通用廁所",
        "accessibility_badge": "🛗 無障礙電梯專用直通"
    },
    {
        "station_name": "台北車站",
        "system": "TRTC",
        "exit_name": "出口 M4 (電扶梯出口)",
        "lat": 25.04588,
        "lon": 121.51695,
        "has_elevator": False,
        "has_escalator_up": True,
        "has_escalator_down": False,
        "has_ramp": False,
        "restroom_info": "",
        "accessibility_badge": "🪜 僅上行電扶梯與樓梯"
    },
    {
        "station_name": "台北車站",
        "system": "TRTC",
        "exit_name": "出口 M5 (純階梯出口)",
        "lat": 25.04595,
        "lon": 121.51590,
        "has_elevator": False,
        "has_escalator_up": False,
        "has_escalator_down": False,
        "has_ramp": False,
        "restroom_info": "",
        "accessibility_badge": "⚠️ 純樓梯 (不建議通行)"
    },
    {
        "station_name": "台北車站",
        "system": "TRTC",
        "exit_name": "出口 M8 (公園路/許昌街近端)",
        "lat": 25.04505,
        "lon": 121.51730,
        "has_elevator": False,
        "has_escalator_up": True,
        "has_escalator_down": True,
        "has_ramp": True,
        "restroom_info": "近B1詢問處有無障礙化妝室",
        "accessibility_badge": "📶 雙向電扶梯與坡道"
    },

    # 台北捷運 西門站
    {
        "station_name": "西門站",
        "system": "TRTC",
        "exit_name": "出口 4 (衡陽路無障礙電梯)",
        "lat": 25.04225,
        "lon": 121.50915,
        "has_elevator": True,
        "has_escalator_up": True,
        "has_escalator_down": True,
        "has_ramp": True,
        "restroom_info": "B1大廳層設有獨立無障礙廁所",
        "accessibility_badge": "🛗 無障礙電梯專用直通"
    },
    {
        "station_name": "西門站",
        "system": "TRTC",
        "exit_name": "出口 6 (西門徒步區/成都路)",
        "lat": 25.04265,
        "lon": 121.50790,
        "has_elevator": False,
        "has_escalator_up": True,
        "has_escalator_down": False,
        "has_ramp": False,
        "restroom_info": "",
        "accessibility_badge": "🪜 上行電扶梯與樓梯"
    },

    # 高雄捷運 美麗島站
    {
        "station_name": "美麗島站",
        "system": "KRTC",
        "exit_name": "出口 1 (光之穹頂無障礙電梯)",
        "lat": 25.04550, # 若未自訂座標時之示範
        "lon": 121.51500,
        "has_elevator": True,
        "has_escalator_up": True,
        "has_escalator_down": True,
        "has_ramp": True,
        "restroom_info": "光之穹頂大廳西側設有無障礙廁所",
        "accessibility_badge": "🛗 無障礙電梯專用直通"
    }
]


class MrtAccessibilityDirectory:
    """
    【捷運立體無障礙出入口與專屬電梯導引庫】
    """

    def __init__(self, custom_exits: Optional[List[Dict[str, Any]]] = None):
        self.exits_database = custom_exits if custom_exits is not None else DEFAULT_MRT_ACCESSIBLE_EXITS

    def get_nearby_mrt_exits(
        self,
        lat: float,
        lon: float,
        heading_deg: float,
        radius_m: float = MAX_MRT_SEARCH_RADIUS_METERS,
        only_accessible: bool = False
    ) -> List[Dict[str, Any]]:
        """
        【搜尋周遭捷運出入口，並主動優先標記無障礙電梯出口】
        
        @param lat 行人當前緯度
        @param lon 行人當前經度
        @param heading_deg 行人面對真北朝向
        @param radius_m 搜尋半徑 (預設 300 公尺)
        @param only_accessible 是否只回傳具備無障礙電梯之出口
        @return 捷運出入口清單（無障礙電梯優先排在最前，次按距離排序）
        """
        results = []

        for item in self.exits_database:
            dist = haversine_distance(lat, lon, item["lat"], item["lon"])
            if dist > radius_m:
                continue

            if only_accessible and not item["has_elevator"]:
                continue

            t_bearing = calculate_bearing(lat, lon, item["lat"], item["lon"])
            rel_deg = relative_bearing(heading_deg, t_bearing)
            clock = bearing_to_clock_position(rel_deg)
            direction_name = bearing_to_relative_direction(rel_deg)

            if item["has_elevator"]:
                speech_prompt = f"🛗 捷運{item['station_name']}【{item['exit_name']}】({direction_name} {round(dist)}公尺)，設有直通電梯。"
            else:
                speech_prompt = f"捷運{item['station_name']}【{item['exit_name']}】({direction_name} {round(dist)}公尺)。"

            results.append({
                "station_name": item["station_name"],
                "exit_name": item["exit_name"],
                "system": item["system"],
                "distance_m": round(dist, 1),
                "clock_position": clock,
                "relative_direction": direction_name,
                "has_elevator": item["has_elevator"],
                "has_escalator_up": item["has_escalator_up"],
                "has_escalator_down": item["has_escalator_down"],
                "has_ramp": item["has_ramp"],
                "accessibility_badge": item["accessibility_badge"],
                "restroom_info": item["restroom_info"],
                "speech_prompt": speech_prompt
            })

        # 排序規則：具備無障礙電梯 (has_elevator=True) 者強行置頂，其餘按距離遞增排序
        results.sort(key=lambda x: (not x["has_elevator"], x["distance_m"]))
        return results
