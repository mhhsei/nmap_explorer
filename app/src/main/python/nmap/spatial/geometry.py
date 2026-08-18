import math
from typing import Tuple

EARTH_RADIUS_M = 6371000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on the earth (in meters).
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
    Calculate initial bearing (azimuth) in degrees from point 1 to point 2.
    Returns 0.0 to 360.0 (0=North, 90=East, 180=South, 270=West).
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
    Calculate relative bearing in degrees (-180.0 to +180.0) relative to heading_deg.
    0 = straight ahead, +90 = right, -90 = left, +/-180 = behind.
    """
    diff = (target_bearing_deg - heading_deg + 360.0) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


def bearing_to_clock_position(relative_deg: float) -> str:
    """
    Convert relative bearing (-180 to +180) to clock position string (12點鐘方向, 3點鐘方向, etc.).
    """
    # Normalize to 0..360 where 0 is 12 o'clock
    norm_deg = (relative_deg + 360.0) % 360.0
    # Each clock hour covers 30 degrees (15 deg offset for 12 o'clock)
    hour = int(round(norm_deg / 30.0)) % 12
    if hour == 0:
        hour = 12
    return f"{hour}點鐘方向"


def bearing_to_cardinal(bearing_deg: float) -> str:
    """
    Convert bearing (0..360) to 8-point Traditional Chinese cardinal direction.
    """
    cardinals = ["正北", "東北", "正東", "東南", "正南", "西南", "正西", "西北"]
    idx = int(round(bearing_deg / 45.0)) % 8
    return cardinals[idx]


def bearing_to_relative_direction(relative_deg: float) -> str:
    """
    Convert relative bearing (-180..+180) to 8-sector relative direction string.
    """
    # Sectors centered around 0 (Ahead), 45 (Front-Right), 90 (Right), 135 (Back-Right), 180 (Behind), etc.
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
    Calculate destination point given start point (lat, lon), distance in meters, and bearing in degrees.
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
