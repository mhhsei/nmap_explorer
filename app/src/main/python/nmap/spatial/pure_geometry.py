import math
import re
from typing import Tuple, List, Optional
from nmap.spatial.geometry import haversine_distance

def point_to_segment_distance_squared(px: float, py: float, vx: float, vy: float, wx: float, wy: float) -> Tuple[float, float, float]:
    """
    Return minimum distance squared between point (px,py) and segment (vx,vy)-(wx,wy),
    and the closest point on the segment.
    """
    l2 = (wx - vx)**2 + (wy - vy)**2
    if l2 == 0:
        return (px - vx)**2 + (py - vy)**2, vx, vy
    
    t = max(0, min(1, ((px - vx) * (wx - vx) + (py - vy) * (wy - vy)) / l2))
    proj_x = vx + t * (wx - vx)
    proj_y = vy + t * (wy - vy)
    return (px - proj_x)**2 + (py - proj_y)**2, proj_x, proj_y

def find_closest_point_on_line(lat: float, lon: float, geom: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    """
    Given a point (lat, lon) and a line geometry (list of [lat, lon]), 
    returns the minimum distance in meters and the closest (lat, lon) on the line.
    """
    min_dist = float('inf')
    best_lat = lat
    best_lon = lon

    # geom is list of (lat, lon)
    for i in range(len(geom) - 1):
        lat1, lon1 = geom[i]
        lat2, lon2 = geom[i+1]
        
        avg_lat = math.radians((lat1 + lat2 + lat) / 3.0)
        cos_lat = math.cos(avg_lat)
        
        px = lon * cos_lat
        py = lat
        vx = lon1 * cos_lat
        vy = lat1
        wx = lon2 * cos_lat
        wy = lat2
        
        _, proj_x_adj, proj_y = point_to_segment_distance_squared(px, py, vx, vy, wx, wy)
        proj_x = proj_x_adj / cos_lat
        
        dist_m = haversine_distance(lat, lon, proj_y, proj_x)
        if dist_m < min_dist:
            min_dist = dist_m
            best_lat = proj_y
            best_lon = proj_x
            
    return min_dist, best_lat, best_lon

def estimate_road_width_m(road: dict) -> float:
    """
    Estimate road width in meters based on OSM attributes.
    """
    if not isinstance(road, dict):
        return 6.0

    tags = road.get("tags", {})
    if "width" in tags:
        try:
            val = float(re.sub(r"[^\d.]", "", str(tags["width"])))
            if val > 0:
                return val
        except Exception:
            pass
    if "lanes" in tags:
        try:
            lanes = int(re.sub(r"\D", "", str(tags["lanes"])))
            if lanes > 0:
                return lanes * 3.5
        except Exception:
            pass

    highway = tags.get("highway", road.get("type", "residential"))
    if highway in ("motorway", "trunk", "primary"):
        return 16.0
    elif highway == "secondary":
        return 12.0
    elif highway == "tertiary":
        return 8.5
    elif highway in ("residential", "unclassified"):
        return 6.0
    elif highway in ("service", "living_street", "pedestrian", "footway", "path", "track"):
        return 4.0
    return 6.0

def snap_pedestrian_to_road(
    lat: float,
    lon: float,
    geom: List[Tuple[float, float]],
    road: dict,
    last_side: Optional[str] = None
) -> Tuple[float, float, float, str]:
    """
    Adaptive Pedestrian Snapping:
    - Narrow Street (width < 8m, e.g. alleys, small lanes): Snap directly to Centerline.
    - Wide Road (width >= 8m, e.g. multi-lane avenues): Snap to Sidewalk / Arcade on corresponding Left or Right side.
    Returns: (distance_m, snapped_lat, snapped_lon, side)
    """
    if not geom or len(geom) < 2:
        return 0.0, lat, lon, "center"

    min_dist = float('inf')
    best_proj_lat = lat
    best_proj_lon = lon
    best_seg_idx = 0
    best_t = 0.0

    avg_lat = math.radians(lat)
    cos_lat = math.cos(avg_lat)
    m_per_deg_lat = 111139.0
    m_per_deg_lon = 111139.0 * cos_lat

    for i in range(len(geom) - 1):
        lat1, lon1 = geom[i]
        lat2, lon2 = geom[i+1]

        px = (lon - lon1) * m_per_deg_lon
        py = (lat - lat1) * m_per_deg_lat
        vx = (lon2 - lon1) * m_per_deg_lon
        vy = (lat2 - lat1) * m_per_deg_lat

        l2 = vx * vx + vy * vy
        if l2 == 0:
            dist = math.sqrt(px * px + py * py)
            t = 0.0
        else:
            t = max(0.0, min(1.0, (px * vx + py * vy) / l2))
            proj_x = t * vx
            proj_y = t * vy
            dist = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)

        if dist < min_dist:
            min_dist = dist
            best_seg_idx = i
            best_t = t
            best_proj_lat = lat1 + t * (lat2 - lat1)
            best_proj_lon = lon1 + t * (lon2 - lon1)

    road_width = estimate_road_width_m(road)

    # 1. Narrow Street (< 8.0m): Snap directly to centerline (Center)
    if road_width < 8.0:
        return min_dist, best_proj_lat, best_proj_lon, "center"

    # 2. Wide Road (>= 8.0m): Compute Side & Sidewalk Offset
    lat1, lon1 = geom[best_seg_idx]
    lat2, lon2 = geom[best_seg_idx + 1]

    vx = (lon2 - lon1) * m_per_deg_lon
    vy = (lat2 - lat1) * m_per_deg_lat
    seg_len = math.sqrt(vx * vx + vy * vy)
    if seg_len == 0:
        return min_dist, best_proj_lat, best_proj_lon, "center"

    px = (lon - lon1) * m_per_deg_lon
    py = (lat - lat1) * m_per_deg_lat

    cross = vx * py - vy * px
    raw_side = "left" if cross > 0 else "right"
    lateral_dist = abs(cross) / seg_len

    current_side = raw_side
    if lateral_dist < 1.5 and last_side in ("left", "right"):
        current_side = last_side

    sidewalk_offset_m = min(max(road_width / 2.0 - 1.0, 2.5), 18.0)

    if current_side == "right":
        nx = vy / seg_len
        ny = -vx / seg_len
    else:
        nx = -vy / seg_len
        ny = vx / seg_len

    offset_lat = best_proj_lat + (ny * sidewalk_offset_m) / m_per_deg_lat
    offset_lon = best_proj_lon + (nx * sidewalk_offset_m) / m_per_deg_lon

    return min_dist, offset_lat, offset_lon, current_side

def get_line_bounds(geom: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Returns (min_lon, min_lat, max_lon, max_lat)"""
    min_lat = min(pt[0] for pt in geom)
    max_lat = max(pt[0] for pt in geom)
    min_lon = min(pt[1] for pt in geom)
    max_lon = max(pt[1] for pt in geom)
    return (min_lon, min_lat, max_lon, max_lat)
