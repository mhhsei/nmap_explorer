"""
【全國人行道安全雷達與台電公共箱體防撞引擎 (SidewalkHazardScanner)】

生活化比喻：
視障者手上的白手杖，就像地面的雷達觸鬚，能靈敏探測「地面 20 公分以內」的一草一木（如導盲磚、台階、坑洞）。
但人行道上常常有「懸在腰部或胸口高度的巨大台電變電箱、消防栓、或是路樹凸出的粗枝」，
這些空中路障白杖往往敲不到，使用者常不慎以肩膀或額頭撞上，造成嚴重受傷。
本模組就像一支「無形的立體電子避障導航杖」：
持續掃描行進前方 2.0 ~ 12.0 公尺的人行道，一旦發現變電箱或狹窄段，
立即在 4 公尺前發出輕柔提示，並親切指示「請微靠左」或「請微靠右」平滑繞行！
"""

import math
from typing import List, Dict, Any, Optional
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_relative_direction
)

# 障礙物掃描走廊幾何常數 (消滅魔法數字)
MIN_HAZARD_DISTANCE_METERS = 0.0   # 【安全鐵律】：下限必須為 0.0m！即將撞上的最後 1.5m 內絕不可停止偵測
MAX_HAZARD_DISTANCE_METERS = 12.0  # 超過 12m 暫不打擾
MAX_LATERAL_TOLERANCE_METERS = 2.2 # 側向 2.2 公尺內視為碰撞威脅走廊

# 台灣代表性市區人行道大型實體障礙物資料庫 (變電箱、消防栓、人行道狹窄路頸)
# 資料源自台電公共箱體開放資料與國土管理署人行道基本調查
DEFAULT_SIDEWALK_HAZARDS = [
    {
        "id": "HAZ_TPE_BOX_01",
        "name": "台電大型雙門變電箱",
        "hazard_type": "UTILITY_BOX",
        "hazard_level": "WARNING",
        "lat": 25.04512,
        "lon": 121.51520,
        "description": "位於許昌街人行道中央偏右，寬約 1.2 公尺"
    },
    {
        "id": "HAZ_TPE_BOX_02",
        "name": "台電高壓配電箱",
        "hazard_type": "UTILITY_BOX",
        "hazard_level": "WARNING",
        "lat": 25.04502,
        "lon": 121.51430,
        "description": "許昌街騎樓出口右側外推箱體"
    },
    {
        "id": "HAZ_TPE_HYDRANT_01",
        "name": "地上型紅色雙向消防栓",
        "hazard_type": "FIRE_HYDRANT",
        "hazard_level": "CAUTION",
        "lat": 25.04507,
        "lon": 121.51640,
        "description": "人行道路緣石凸起消防栓"
    },
    {
        "id": "HAZ_TPE_STEP_01",
        "name": "騎樓高低落差階梯 (一坎段差)",
        "hazard_type": "STEP_LEVEL_CHANGE",
        "hazard_level": "WARNING",
        "lat": 25.04506,
        "lon": 121.51550,
        "description": "騎樓交界處約 15 公分高階梯段差"
    },
    {
        "id": "HAZ_TPE_CHOKE_01",
        "name": "人行道施工縮減狹窄瓶頸",
        "hazard_type": "SIDEWALK_CHOKEPOINT",
        "hazard_level": "ALERT",
        "lat": 25.04580,
        "lon": 121.51580,
        "description": "施工圍籬導致淨寬僅剩 80 公分"
    }
]


class SidewalkHazardScanner:
    """
    【全國人行道安全雷達與台電公共箱體防撞引擎】
    """

    def __init__(self, custom_hazards: Optional[List[Dict[str, Any]]] = None):
        self.base_hazards = list(custom_hazards if custom_hazards is not None else DEFAULT_SIDEWALK_HAZARDS)
        self.dynamic_hazards: List[Dict[str, Any]] = []
        self.hazards_database = list(self.base_hazards)

    def set_dynamic_hazards(self, barriers: List[Dict[str, Any]]):
        """
        【動態注入 OSM 現場人行道障礙物 (車擋柱、防護欄、路阻)】
        作用：將 Overpass 現場抓到的真實實體障礙物注入生命安全避障雷達，
        與台電變電箱、消防栓合併進行前向碰撞預警。
        """
        self.dynamic_hazards = []
        seen_coords = {(round(h["lat"], 5), round(h["lon"], 5)) for h in self.base_hazards}

        for b in barriers:
            b_lat = b.get("lat")
            b_lon = b.get("lon")
            if b_lat is None or b_lon is None:
                continue

            coord_key = (round(b_lat, 5), round(b_lon, 5))
            if coord_key in seen_coords:
                continue
            seen_coords.add(coord_key)

            b_type = (b.get("barrier_type") or "").lower()
            # 優先對車擋柱、自行車阻擋欄、水泥路阻、矮牆等具有碰撞絆倒危險的設施進行防護
            hazard_level = "WARNING" if b_type in ("bollard", "cycle_barrier", "block", "turnstile") else "CAUTION"
            b_name = b.get("name") or "路面障礙物"

            self.dynamic_hazards.append({
                "id": f"OSM_HAZ_{b.get('id', len(self.dynamic_hazards))}",
                "name": b_name,
                "hazard_type": f"BARRIER_{b_type.upper()}" if b_type else "BARRIER",
                "hazard_level": hazard_level,
                "lat": b_lat,
                "lon": b_lon,
                "description": f"OSM 標註之現場設施：{b_name}"
            })

        self.hazards_database = self.base_hazards + self.dynamic_hazards

    def scan_forward_corridor(
        self,
        lat: float,
        lon: float,
        heading_deg: float,
        max_dist_m: float = MAX_HAZARD_DISTANCE_METERS
    ) -> List[Dict[str, Any]]:
        """
        【掃描行進前方安全走廊內的實體障礙物】
        
        @param lat 行人當前緯度
        @param lon 行人當前經度
        @param heading_deg 行人行進真北朝向
        @return 前方走廊威脅障礙物列表（依距離近到遠排序）
        """
        detected_hazards = []

        for h in self.hazards_database:
            dist = haversine_distance(lat, lon, h["lat"], h["lon"])
            if dist < MIN_HAZARD_DISTANCE_METERS or dist > max_dist_m:
                continue

            t_bearing = calculate_bearing(lat, lon, h["lat"], h["lon"])
            rel_deg = relative_bearing(heading_deg, t_bearing)

            # 只檢查前方 ±60 度視野角內的設施
            if abs(rel_deg) > 60.0:
                continue

            # 計算橫向偏移距離 (lateral offset)
            rad_rel = math.radians(abs(rel_deg))
            lateral_offset_m = dist * math.sin(rad_rel)

            if lateral_offset_m <= MAX_LATERAL_TOLERANCE_METERS:
                clock = bearing_to_clock_position(rel_deg)
                direction_name = bearing_to_relative_direction(rel_deg)

                # 生成親切繞行避障建議
                if rel_deg > 5.0: # 偏右
                    bypass_advice = "請稍微靠左側前進"
                elif rel_deg < -5.0: # 偏左
                    bypass_advice = "請稍微靠右側前進"
                else: # 正前方
                    bypass_advice = "請減速並向左側繞開"

                speech_prompt = f"⚠️ 注意：前方 {round(dist)}公尺有【{h['name']}】，{bypass_advice}。"

                detected_hazards.append({
                    "id": h["id"],
                    "name": h["name"],
                    "hazard_type": h["hazard_type"],
                    "hazard_level": h["hazard_level"],
                    "distance_m": round(dist, 1),
                    "lateral_offset_m": round(lateral_offset_m, 1),
                    "clock_position": clock,
                    "relative_direction": direction_name,
                    "bypass_advice": bypass_advice,
                    "speech_prompt": speech_prompt
                })

        detected_hazards.sort(key=lambda x: x["distance_m"])
        return detected_hazards
