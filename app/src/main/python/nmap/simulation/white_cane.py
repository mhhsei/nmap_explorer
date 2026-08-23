"""
白手杖觸覺反饋與前向探測模擬器 (White Cane Simulator)

作用：
1. 模擬前方 0.5m ~ 1.5m 的白手杖左右擺動掃描 (Two-point touch / Constant contact technique)。
2. 真實反饋導盲磚直條導引紋路、路口圓點警示磚、牆面硬質叩叩聲、人行道路緣石 (Curb) 高低差危險與違停障礙物碰撞。
"""
from typing import Dict, Any, List


class WhiteCaneSimulator:
    """
    白手杖探測模擬器
    """

    def __init__(self) -> None:
        pass

    def tap_ahead(self, lat: float, lon: float, heading_deg: float, world_model: Any, active_obstacles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        【模擬白手杖向前探測與材質反饋】
        優先級排序：導盲磚/斑馬線 > 建築外牆 > 道路材質與路緣 > 違停障礙物。
        """
        # 1. 檢查周遭真實的 OSM 設施與地面
        pois = getattr(world_model, 'get_nearby_pois', lambda l, ln, h, r_m=80.0: [])(lat, lon, heading_deg, radius_m=5)
        roads = getattr(world_model, 'get_road_info', lambda l, ln, h: [])(lat, lon, heading_deg)
        buildings = getattr(world_model, 'get_nearby_buildings', lambda l, ln, h, r_m=50.0: [])(lat, lon, heading_deg, radius_m=5)
        crossings = getattr(world_model, 'get_nearby_crossings', lambda l, ln, h, r_m=50.0: [])(lat, lon, heading_deg, radius_m=5)


        detected = False
        object_type = 'none'
        description = '白手杖沒有碰到任何障礙物，前方暢通'
        sound = 'tap_concrete'
        danger_level = 'none'

        # 優先級 1: 導盲磚 / 行人穿越道
        if crossings:
            crossing = crossings[0]
            detected = True
            object_type = 'tactile_paving'
            sound = 'sweep_tactile'
            if getattr(crossing, 'tactile_paving', '') == 'yes':
                description = '白手杖掃過標準導盲磚，感受到明顯的直條紋路，指示可以直行'
            else:
                description = '白手杖掃到路口邊緣的警示磚，有圓點突起，提醒即將進入斑馬線'
            
        # 優先級 2: 建築物牆面
        elif buildings:
            detected = True
            object_type = 'wall'
            description = f'白手杖碰到硬質牆面（{buildings[0].name or "建築物"}），發出清脆的「叩叩」聲'
            sound = 'tap_wall'

        # 優先級 3: 道路材質與邊界
        elif roads:
            surface = getattr(roads[0], 'surface', 'asphalt')
            highway = getattr(roads[0], 'highway_type', '')
            
            if surface == 'paving_stones' or surface == 'cobblestone':
                detected = True
                object_type = 'ground'
                description = '白手杖敲擊在拼接地磚上，發出輕微的摩擦與喀拉聲'
                sound = 'tap_concrete'
            elif highway in ['primary', 'secondary', 'tertiary']:
                # 邊緣危險警告
                detected = True
                object_type = 'curb'
                description = '白手杖探出人行道邊緣，感覺到路緣石的高低落差，前方是車道'
                sound = 'tap_concrete'
                danger_level = 'high'
            
        # 優先級 4: 模擬器動態障礙物
        elif active_obstacles:
            obs = active_obstacles[0]
            detected = True
            object_type = obs.get('type', 'obstacle')
            description = f"白手杖碰到前方的{obs.get('description', '障礙物')}"
            sound = 'tap_metal' if '機車' in description or '招牌' in description else 'tap_concrete'

        return {
            'detected': detected,
            'object_type': object_type,
            'description': description,
            'sound': sound,
            'danger_level': danger_level
        }
