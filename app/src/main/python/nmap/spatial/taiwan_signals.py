"""
【台灣路口視障有聲號誌 (APS)、即時秒數 (SPaT) 與行人按鈕導引引擎 (TaiwanSignalManager)】

生活化比喻：
1. 有聲號誌是「會唱歌的導航鳥」：
   - 東西向綠燈：清脆鳥鳴聲 (啾啾啾)
   - 南北向綠燈：沉穩布穀鳥聲 (咕咕～咕咕)
2. 行人觸動按鈕在哪裡？
   - 很多視障朋友站在路口摸不到按鈕，甚至不知道該摸哪根桿子！
   - 依據台灣交通部與內政部無障礙法規標準：
     * 【安裝位置】：斑馬線路緣斜坡起點的「右側號誌桿」
     * 【安裝高度】：離地面「100 至 120 公分」（剛好在手自然下垂抬起的腰部高度）
     * 【觸覺特徵】：按鍵正下方有指向對街的「凸起實體定向箭頭」，摸箭頭方向就能校正身體角度！
3. 即時秒數機制：
   - 只要路口具備官方即時連線 (TDX SPaT / 智慧交控)，立即精準報讀當前秒數。
   - 若無官方連線，則絕不虛構秒數，誠實回報物理路況！
"""

import os
import math
import time
import sqlite3
from typing import List, Dict, Any, Optional
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_relative_direction
)

MAX_SIGNAL_DETECT_RADIUS_METERS = 28.0
BUTTON_ALERT_MAX_DISTANCE_METERS = 12.0

# 台灣代表性重點號誌化與視障有聲號誌 (APS) 路口資料庫（雙北、桃竹苗、中彰投、南高屏）
DEFAULT_TAIWAN_SIGNAL_DATABASE = [
    # --- 新北市淡水區 (視障者高頻生活圈) ---
    {
        "id": "SIG_NTP_TS_001",
        "intersection_name": "北新路一段與中正東路口",
        "lat": 25.17420, "lon": 121.44450,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向)", "ns_sound": "布穀鳥聲 (南北向北新路)",
        "has_button": True, "button_pole": "右側號誌桿腰部", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_002",
        "intersection_name": "北新路一段與大忠街口",
        "lat": 25.17885, "lon": 121.44960,
        "has_aps": True, "ew_sound": "鳥鳴聲 (大忠街)", "ns_sound": "布穀鳥聲 (北新路一段)",
        "has_button": False, "button_pole": "", "button_height_cm": 0, "has_tactile_arrow": False,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_003",
        "intersection_name": "北新路一段與水源街二段口",
        "lat": 25.18070, "lon": 121.45290,
        "has_aps": True, "ew_sound": "鳥鳴聲 (水源街)", "ns_sound": "布穀鳥聲 (北新路)",
        "has_button": True, "button_pole": "斑馬線右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_004",
        "intersection_name": "中正路與鼻頭街口 (淡水捷運站前)",
        "lat": 25.16850, "lon": 121.44520,
        "has_aps": True, "ew_sound": "鳥鳴聲 (鼻頭街)", "ns_sound": "布穀鳥聲 (中正東路)",
        "has_button": True, "button_pole": "1號出口斑馬線右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_005",
        "intersection_name": "中正路與文化路口 (淡水老街圓環)",
        "lat": 25.17250, "lon": 121.43680,
        "has_aps": True, "ew_sound": "鳥鳴聲 (中正路老街)", "ns_sound": "布穀鳥聲 (文化路)",
        "has_button": False, "button_pole": "", "button_height_cm": 0, "has_tactile_arrow": False,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_006",
        "intersection_name": "中山路與原德路口",
        "lat": 25.17180, "lon": 121.44350,
        "has_aps": False, "ew_sound": "", "ns_sound": "",
        "has_button": False, "button_pole": "", "button_height_cm": 0, "has_tactile_arrow": False,
        "has_refuge_island": False, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_007",
        "intersection_name": "北新路二段與新市一路三段口",
        "lat": 25.18430, "lon": 121.44850,
        "has_aps": True, "ew_sound": "鳥鳴聲 (新市一路)", "ns_sound": "布穀鳥聲 (北新路二段)",
        "has_button": True, "button_pole": "右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_TS_008",
        "intersection_name": "淡金路與北新路口 (淡金北新輕軌站)",
        "lat": 25.17820, "lon": 121.45890,
        "has_aps": True, "ew_sound": "鳥鳴聲 (北新路)", "ns_sound": "布穀鳥聲 (淡金路)",
        "has_button": True, "button_pole": "月台旁右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },

    # --- 新北市板橋特區 (智慧有聲號誌示範區) ---
    {
        "id": "SIG_NTP_BAN_001",
        "intersection_name": "縣民大道與新府路口 (板橋車站南側)",
        "lat": 25.01320, "lon": 121.46350,
        "has_aps": True, "ew_sound": "鳥鳴聲 (縣民大道)", "ns_sound": "布穀鳥聲 (新府路)",
        "has_button": True, "button_pole": "右側號誌桿腰部", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_NTP_BAN_002",
        "intersection_name": "縣民大道與新站路口 (大遠百前)",
        "lat": 25.01250, "lon": 121.46520,
        "has_aps": True, "ew_sound": "鳥鳴聲 (縣民大道)", "ns_sound": "布穀鳥聲 (新站路)",
        "has_button": True, "button_pole": "右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_NTP_BAN_003",
        "intersection_name": "文化路一段與漢生東路口",
        "lat": 25.01850, "lon": 121.46480,
        "has_aps": True, "ew_sound": "鳥鳴聲 (漢生東路)", "ns_sound": "布穀鳥聲 (文化路一段)",
        "has_button": True, "button_pole": "斑馬線右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_NTP_BAN_004",
        "intersection_name": "府中路與縣民大道口 (捷運府中站)",
        "lat": 25.00890, "lon": 121.45880,
        "has_aps": True, "ew_sound": "鳥鳴聲 (縣民大道)", "ns_sound": "布穀鳥聲 (府中路)",
        "has_button": True, "button_pole": "1號出口旁右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },

    # --- 新北市中和/永和區 (國立台灣圖書館視障專區) ---
    {
        "id": "SIG_NTP_ZH_001",
        "intersection_name": "中和路與安平路口",
        "lat": 25.00080, "lon": 121.51150,
        "has_aps": True, "ew_sound": "鳥鳴聲 (安平路)", "ns_sound": "布穀鳥聲 (中和路)",
        "has_button": True, "button_pole": "國圖旁右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_NTP_ZH_002",
        "intersection_name": "安平路與中安街口 (四號公園角)",
        "lat": 24.99950, "lon": 121.51280,
        "has_aps": True, "ew_sound": "鳥鳴聲 (中安街)", "ns_sound": "布穀鳥聲 (安平路)",
        "has_button": True, "button_pole": "公園入口右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": False, "is_signalized": True, "is_connected_spat": True
    },

    # --- 新北市新莊區 (盲人重建院專區) ---
    {
        "id": "SIG_NTP_XJ_001",
        "intersection_name": "中正路盲人重建院前號誌",
        "lat": 25.03360, "lon": 121.44580,
        "has_aps": True, "ew_sound": "蟋蟀聲 (重建院行人穿越)", "ns_sound": "布穀鳥聲 (中正路幹線)",
        "has_button": True, "button_pole": "盲人重建院大門右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_NTP_XJ_002",
        "intersection_name": "中正路與瓊泰路口",
        "lat": 25.03290, "lon": 121.44750,
        "has_aps": True, "ew_sound": "鳥鳴聲 (瓊泰路)", "ns_sound": "布穀鳥聲 (中正路)",
        "has_button": True, "button_pole": "斑馬線右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },

    # --- 台北市中正區 (台北車站、重慶南路、館前路) ---
    {
        "id": "SIG_TPE_001",
        "intersection_name": "忠孝西路與館前路口",
        "lat": 25.04631, "lon": 121.51582,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向忠孝西路)", "ns_sound": "布穀鳥聲 (南北向館前路)",
        "has_button": True, "button_pole": "斑馬線右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True, "base_cycle_sec": 120
    },
    {
        "id": "SIG_TPE_002",
        "intersection_name": "館前路與許昌街口",
        "lat": 25.04505, "lon": 121.51578,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向許昌街)", "ns_sound": "布穀鳥聲 (南北向館前路)",
        "has_button": True, "button_pole": "許昌街斑馬線右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": False, "is_signalized": True, "is_connected_spat": True, "base_cycle_sec": 90
    },
    {
        "id": "SIG_TPE_003",
        "intersection_name": "重慶南路與許昌街口",
        "lat": 25.04508, "lon": 121.51352,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向許昌街)", "ns_sound": "布穀鳥聲 (南北向重慶南路)",
        "has_button": True, "button_pole": "右側號誌桿腰部", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": False, "is_signalized": True, "is_connected_spat": True, "base_cycle_sec": 90
    },
    {
        "id": "SIG_TPE_004",
        "intersection_name": "公園路與許昌街口",
        "lat": 25.04498, "lon": 121.51735,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向許昌街)", "ns_sound": "布穀鳥聲 (南北向公園路)",
        "has_button": True, "button_pole": "捷運8號出口前右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True, "base_cycle_sec": 100
    },
    {
        "id": "SIG_TPE_005",
        "intersection_name": "忠孝西路與重慶南路口",
        "lat": 25.04642, "lon": 121.51348,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向忠孝西路)", "ns_sound": "布穀鳥聲 (南北向重慶南路)",
        "has_button": True, "button_pole": "斑馬線右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True, "base_cycle_sec": 120
    },
    {
        "id": "SIG_TPE_006",
        "intersection_name": "常德街與中山南路口 (台大醫院大門前)",
        "lat": 25.04190, "lon": 121.51780,
        "has_aps": True, "ew_sound": "鳥鳴聲 (常德街)", "ns_sound": "布穀鳥聲 (中山南路)",
        "has_button": True, "button_pole": "台大醫院前右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },

    # --- 台北市大安/信義/松山 (東區主要路廊) ---
    {
        "id": "SIG_TPE_DA_001",
        "intersection_name": "忠孝東路四段與復興南路一段路口 (SOGO前)",
        "lat": 25.04180, "lon": 121.54350,
        "has_aps": True, "ew_sound": "鳥鳴聲 (忠孝東路)", "ns_sound": "布穀鳥聲 (復興南路)",
        "has_button": True, "button_pole": "捷運2號出口前右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_TPE_DA_002",
        "intersection_name": "信義路四段與復興南路二段路口 (大安站)",
        "lat": 25.03320, "lon": 121.54360,
        "has_aps": True, "ew_sound": "鳥鳴聲 (信義路)", "ns_sound": "布穀鳥聲 (復興南路)",
        "has_button": True, "button_pole": "右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_TPE_XY_001",
        "intersection_name": "市府路與松壽路口 (台北市政府旁)",
        "lat": 25.03680, "lon": 121.56450,
        "has_aps": True, "ew_sound": "鳥鳴聲 (松壽路)", "ns_sound": "布穀鳥聲 (市府路)",
        "has_button": True, "button_pole": "市政大樓南側右桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },

    # --- 台北市士林/北投 (啟明學校、榮總專區) ---
    {
        "id": "SIG_TPE_SL_001",
        "intersection_name": "忠誠路二段與天母東路口 (台北啟明學校前)",
        "lat": 25.11890, "lon": 121.53350,
        "has_aps": True, "ew_sound": "鳥鳴聲 (天母東路)", "ns_sound": "布穀鳥聲 (忠誠路二段)",
        "has_button": True, "button_pole": "啟明學校校門右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },
    {
        "id": "SIG_TPE_BT_001",
        "intersection_name": "石牌路二段與裕民六路口 (台北榮民總醫院大門)",
        "lat": 25.12050, "lon": 121.51850,
        "has_aps": True, "ew_sound": "鳥鳴聲 (裕民六路)", "ns_sound": "布穀鳥聲 (石牌路二段)",
        "has_button": True, "button_pole": "榮總急診側右桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True
    },

    # --- 桃竹苗、中彰投、南高屏主要交通樞紐 ---
    {
        "id": "SIG_TYN_001",
        "intersection_name": "復興路與中正路口 (桃園火車站前)",
        "lat": 24.98950, "lon": 121.31350,
        "has_aps": True, "ew_sound": "鳥鳴聲 (復興路)", "ns_sound": "布穀鳥聲 (中正路)",
        "has_button": True, "button_pole": "站前右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_HC_001",
        "intersection_name": "中正路與中華路二段路口 (新竹火車站前)",
        "lat": 24.80180, "lon": 120.97150,
        "has_aps": True, "ew_sound": "鳥鳴聲 (中正路)", "ns_sound": "布穀鳥聲 (中華路)",
        "has_button": True, "button_pole": "車站出口右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_TXG_001",
        "intersection_name": "台灣大道一段與建國路口 (台中火車站前)",
        "lat": 24.13720, "lon": 120.68650,
        "has_aps": True, "ew_sound": "鳥鳴聲 (台灣大道)", "ns_sound": "布穀鳥聲 (建國路)",
        "has_button": True, "button_pole": "站前廣場右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_TNN_001",
        "intersection_name": "成功路與中山路口 (台南火車站前圓環)",
        "lat": 22.99720, "lon": 120.21280,
        "has_aps": True, "ew_sound": "鳥鳴聲 (成功路)", "ns_sound": "布穀鳥聲 (中山路)",
        "has_button": True, "button_pole": "圓環斑馬線右側桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True
    },
    {
        "id": "SIG_KHH_001",
        "intersection_name": "美麗島站 中山一路與中正四路口",
        "lat": 22.63138, "lon": 120.30195,
        "has_aps": True, "ew_sound": "鳥鳴聲 (東西向中正路)", "ns_sound": "布穀鳥聲 (南北向中山路)",
        "has_button": True, "button_pole": "1號出口旁右側號誌桿", "button_height_cm": 110, "has_tactile_arrow": True,
        "has_refuge_island": True, "is_signalized": True, "is_connected_spat": True, "base_cycle_sec": 100
    }
]


class TaiwanSignalManager:
    """
    【台灣路口視障有聲號誌 (APS)、即時秒數與行人按鈕導引管理器】
    採用純 Python 空間網格索引 (GridSpatialIndex)，支援百毫秒高並發檢索與動態擴展。
    """

    def __init__(self, custom_db: Optional[List[Dict[str, Any]]] = None):
        from nmap.spatial.grid_index import GridSpatialIndex
        self.signal_database = list(custom_db if custom_db is not None else DEFAULT_TAIWAN_SIGNAL_DATABASE)
        self.spatial_index = GridSpatialIndex(cell_size_deg=0.003)
        self._live_spat_cache: Dict[str, Dict[str, Any]] = {}
        self._db_conn = None
        self._rebuild_index()
        self._init_sqlite_db()

    def _init_sqlite_db(self):
        """尋找並連接全台 56,000 筆號誌離線資料庫 (taiwan_signals.db)"""
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "taiwan_signals.db"),
            os.path.join(os.getcwd(), "data", "taiwan_signals.db"),
            os.path.join(os.getcwd(), "app", "src", "main", "python", "data", "taiwan_signals.db"),
            "/sdcard/Android/data/com.example.nmapexplorer/files/data/taiwan_signals.db",
            "/storage/emulated/0/Android/data/com.example.nmapexplorer/files/data/taiwan_signals.db",
            "/data/user/0/com.example.nmapexplorer/files/data/taiwan_signals.db",
            "/data/data/com.example.nmapexplorer/files/data/taiwan_signals.db"
        ]
        for p in candidates:
            if os.path.exists(p):
                try:
                    self._db_conn = sqlite3.connect(p, check_same_thread=False)
                    break
                except Exception:
                    pass

    def _rebuild_index(self):
        """為資料庫建立空間網格索引"""
        for idx, item in enumerate(self.signal_database):
            lat, lon = item["lat"], item["lon"]
            self.spatial_index.insert(idx, (lon, lat, lon, lat), obj=item)

    def add_signal(self, signal_data: Dict[str, Any]):
        """動態吸收由 OSM 或外部圖資發現的號誌設施"""
        idx = len(self.signal_database)
        self.signal_database.append(signal_data)
        lat, lon = signal_data["lat"], signal_data["lon"]
        self.spatial_index.insert(idx, (lon, lat, lon, lat), obj=signal_data)

    def find_signal_near(self, lat: float, lon: float, max_dist_m: float = 32.0) -> Optional[Dict[str, Any]]:
        """在指定座標半徑內搜尋最近的號誌化資料庫節點（經度依緯度餘弦補正）"""
        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        r_deg_lon = max_dist_m / (111139.0 * cos_lat)
        r_deg_lat = max_dist_m / 111139.0
        bounds = (lon - r_deg_lon, lat - r_deg_lat, lon + r_deg_lon, lat + r_deg_lat)
        best_sig = None
        min_dist = max_dist_m

        # 1. 優先查記憶體內 32 筆高品質視障示範有聲號誌 (APS)
        for item in self.spatial_index.intersection(bounds, objects=True):
            sig = item.object
            dist = haversine_distance(lat, lon, sig["lat"], sig["lon"])
            if dist < min_dist:
                min_dist = dist
                best_sig = sig

        if best_sig is not None:
            return best_sig

        # 2. 若記憶體無精細 APS，查詢全台灣 56,000 座號誌離線 SQLite 資料庫
        if self._db_conn is not None:
            try:
                cur = self._db_conn.cursor()
                cur.execute("""
                    SELECT id, lat, lon, is_signalized, has_sound, has_button, crossing_type, name, tags
                    FROM taiwan_signals
                    WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                """, (lat - r_deg_lat, lat + r_deg_lat, lon - r_deg_lon, lon + r_deg_lon))
                rows = cur.fetchall()
                for row in rows:
                    r_id, r_lat, r_lon, r_is_sig, r_sound, r_btn, r_cross, r_name, r_tags_str = row
                    dist = haversine_distance(lat, lon, r_lat, r_lon)
                    if dist < min_dist:
                        min_dist = dist
                        best_sig = {
                            "id": r_id,
                            "intersection_name": r_name or f"交通號誌 ({r_cross or '路口'})",
                            "lat": r_lat,
                            "lon": r_lon,
                            "has_aps": bool(r_sound),
                            "ew_sound": "鳥鳴聲",
                            "ns_sound": "布穀鳥聲",
                            "has_button": bool(r_btn),
                            "button_pole": "右側號誌桿",
                            "button_height_cm": 110,
                            "has_tactile_arrow": False,
                            "has_refuge_island": False,
                            "is_signalized": True,
                            "is_connected_spat": False
                        }
            except Exception:
                pass

        return best_sig

    def update_live_spat(self, signal_id: str, light_status: str, remaining_seconds: int):
        """【注入交控即時秒數】"""
        self._live_spat_cache[signal_id] = {
            "light_status": light_status,
            "remaining_seconds": remaining_seconds,
            "updated_at": time.time()
        }

    def get_nearby_signal_safety(
        self,
        lat: float,
        lon: float,
        heading_deg: float,
        radius_m: float = MAX_SIGNAL_DETECT_RADIUS_METERS
    ) -> Optional[Dict[str, Any]]:
        """
        【評估前方路口號誌安全性、實體按鈕位置與即時秒數】
        """
        closest_signal = self.find_signal_near(lat, lon, max_dist_m=radius_m)
        if not closest_signal:
            return None

        min_dist = haversine_distance(lat, lon, closest_signal["lat"], closest_signal["lon"])

        # 計算相對方位角與時鐘方向
        t_bearing = calculate_bearing(lat, lon, closest_signal["lat"], closest_signal["lon"])
        rel_deg = relative_bearing(heading_deg, t_bearing)
        clock = bearing_to_clock_position(rel_deg)
        direction_name = bearing_to_relative_direction(rel_deg)

        # 判定行人行走方向（東西向 vs 南北向）
        norm_head = heading_deg % 360.0
        is_walking_east_west = (45.0 <= norm_head <= 135.0) or (225.0 <= norm_head <= 315.0)

        target_sound = closest_signal.get("ew_sound", "鳥鳴聲") if is_walking_east_west else closest_signal.get("ns_sound", "布穀鳥聲")

        # 1. 取得即時秒數 (Live SPaT)
        has_live_seconds = False
        light_status = ""
        remaining_seconds = 0
        sig_id = closest_signal["id"]

        # 1. 取得即時連線號誌秒數 (Live SPaT)
        # 【生命安全鐵律】：絕不虛構秒數！只有當收到交通局/交控中心真實推播且更新時間在 5 秒內時，才標記 has_live_seconds = True
        # 嚴禁使用 (time.time() % cycle) 進行任何偽造推算，防止視障者在真實紅燈時誤入車道！
        if sig_id in self._live_spat_cache:
            cache_entry = self._live_spat_cache[sig_id]
            if time.time() - cache_entry["updated_at"] <= 5.0:
                has_live_seconds = True
                light_status = cache_entry["light_status"]
                remaining_seconds = cache_entry["remaining_seconds"]

        # 2. 取得行人觸動按鈕位置導引
        has_button = closest_signal.get("has_button", False)
        button_guide = ""
        if has_button:
            pole_info = closest_signal.get("button_pole", "右側號誌桿")
            h_cm = closest_signal.get("button_height_cm", 110)
            arrow_str = "，下方有指向對街的凸起定向箭頭" if closest_signal.get("has_tactile_arrow") else ""
            button_guide = f"【按鈕位置】：位於{pole_info}約 {h_cm}公分高腰部{arrow_str}。"

        # 3. 組織精簡無障礙語音提示
        speech_parts = []
        speech_parts.append(f"前方【{closest_signal['intersection_name']}】")

        if closest_signal.get("has_aps"):
            speech_parts.append(f"設有【{target_sound}】有聲號誌")

        if closest_signal.get("has_refuge_island"):
            speech_parts.append("中央設有行人庇護島")

        if has_live_seconds:
            light_zh = "綠燈" if light_status == "GREEN" else ("黃燈" if light_status == "AMBER" else "紅燈")
            speech_parts.append(f"即時秒數：{light_zh}剩 {remaining_seconds}秒")
            if light_status == "GREEN" and remaining_seconds < 8:
                speech_parts.append("（秒數不足請等候）")

        if min_dist <= BUTTON_ALERT_MAX_DISTANCE_METERS and has_button:
            speech_parts.append(f"右側桿高110公分處有按鈕與前進箭頭")

        speech_prompt = "，".join(speech_parts) + "。"

        return {
            "id": closest_signal["id"],
            "intersection_name": closest_signal["intersection_name"],
            "distance_m": round(min_dist, 1),
            "clock_position": clock,
            "relative_direction": direction_name,
            "has_aps": closest_signal.get("has_aps", False),
            "target_sound": target_sound,
            "has_refuge_island": closest_signal.get("has_refuge_island", False),
            "has_live_seconds": has_live_seconds,
            "light_status": light_status,
            "remaining_seconds": remaining_seconds,
            "has_button": has_button,
            "button_guide": button_guide,
            "speech_prompt": speech_prompt
        }
