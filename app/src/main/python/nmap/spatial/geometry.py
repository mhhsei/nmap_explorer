"""
球體大地測量與無障礙空間幾何運算模組 (Spherical Geodesy & Spatial Math)

作用：提供 GPS 經緯度之間的距離計算、方位角、相對鐘點方位與前向投影。
針對視障者空間認知特別設計：
1. 鐘點方位 (Clock Position)：將相對角度轉化為「12點鐘方向」、「3點鐘方向」等最直觀的定向語言。
2. 16 方位羅盤 (16-Point Cardinal)：提供「正北」、「北北東」、「東北」等精確絕對方位。
3. 8 扇區方位 (8-Sector Relative)：提供「左前方」、「右側」、「正後方」等直覺方位。
"""
import math
from typing import Tuple

EARTH_RADIUS_M = 6371000.0  # 地球平均半徑（公尺）


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    【半正矢公式 (Haversine Formula) 計算大圓球面距離（公尺）】
    作用：精確計算地球表面兩點經緯度之間的實際直線距離。
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    【計算從起點到終點的大地方位角 (Bearing / Azimuth)】
    回傳值：0.0° ~ 360.0°（0°=正北, 90°=正東, 180°=正南, 270°=正西）。
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)

    bearing_rad = math.atan2(y, x)
    bearing_deg = (math.degrees(bearing_rad) + 360.0) % 360.0
    return bearing_deg


def relative_bearing(heading_deg: float, target_bearing_deg: float) -> float:
    """
    【計算相對於探索者朝向的相對角度】
    回傳值：-180.0° ~ +180.0°（0°=正前方, +90°=正右方, -90°=正左方, ±180°=正後方）。
    """
    diff = (target_bearing_deg - heading_deg + 360.0) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


def bearing_to_clock_position(relative_deg: float) -> str:
    """
    【將相對角度轉換為 12 小時制鐘點方位】
    例如：0° -> "12點鐘方向", 90° -> "3點鐘方向", -90° -> "9點鐘方向"。
    """
    norm_deg = (relative_deg + 360.0) % 360.0
    hour = int(round(norm_deg / 30.0)) % 12
    if hour == 0:
        hour = 12
    return f"{hour}點鐘方向"


def bearing_to_cardinal(bearing_deg: float) -> str:
    """
    【將絕對方位角 (0°~360°) 轉換為 16 方位繁體中文羅盤方位】
    例如：0° -> "正北", 45° -> "東北", 90° -> "正東"。
    """
    cardinals_16 = [
        "正北", "北北東", "東北", "東北東",
        "正東", "東南東", "東南", "南南東",
        "正南", "南南西", "西南", "西南西",
        "正西", "西北西", "西北", "北北西"
    ]
    idx = int(round(((bearing_deg % 360.0) + 360.0) % 360.0 / 22.5)) % 16
    return cardinals_16[idx]


def bearing_to_relative_direction(relative_deg: float) -> str:
    """
    【將相對角度轉換為 8 扇區直覺中文方位】
    例如："正前方", "右前方", "右側", "右後方", "正後方", "左後方", "左側", "左前方"。
    """
    norm_deg = (relative_deg + 360.0) % 360.0
    sectors = [
        "正前方",   # 337.5° - 22.5°
        "右前方",   # 22.5° - 67.5°
        "右側",     # 67.5° - 112.5°
        "右後方",   # 112.5° - 157.5°
        "正後方",   # 157.5° - 202.5°
        "左後方",   # 202.5° - 247.5°
        "左側",     # 247.5° - 292.5°
        "左前方"    # 292.5° - 337.5°
    ]
    idx = int(round(norm_deg / 45.0)) % 8
    return sectors[idx]


def destination_point(lat: float, lon: float, distance_m: float, bearing_deg: float) -> Tuple[float, float]:
    """
    【前向推算目標點經緯度 (Dead Reckoning Projection)】
    作用：給予起始點經緯度、前進距離（公尺）與朝向角度，精確計算抵達的新經緯度。
    """
    dr = distance_m / EARTH_RADIUS_M
    brng = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(dr) +
        math.cos(lat1) * math.sin(dr) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(dr) * math.cos(lat1),
        math.cos(dr) - math.sin(lat1) * math.sin(lat2)
    )

    return math.degrees(lat2), math.degrees(lon2)

