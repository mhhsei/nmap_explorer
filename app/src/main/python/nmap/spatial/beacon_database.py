# -*- coding: utf-8 -*-
"""
【台灣公共交通與視障友善藍牙 iBeacon 定錨資料庫 (beacon_database.py)】

生活化比喻（小學生都看得懂）：
就像一本「室內燈塔目錄」。
在室內沒有 GPS 衛星的地方，這份資料庫標記了各大車站、地下街與視障友善機構所架設的藍牙信標。
當手機接收到信標的專屬身分證字號（UUID, Major, Minor）時，
就能立刻翻開這本目錄，精確找到信標的經緯度與樓層，一秒完成「室內精準定位」！
"""

from typing import List, Dict, Any, Optional
from nmap.spatial.pure_geometry import haversine_distance

# 台灣重要公眾場站與視障導引 Beacon 清單
TAIWAN_PUBLIC_BEACONS: List[Dict[str, Any]] = [
    # 1. 台北車站站前地下街 (Z 區)
    {
        "id": "TPE_Z4",
        "name": "台北車站 站前地下街 Z4 出口 (新光三越/電梯)",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 4,
        "lat": 25.04631,
        "lon": 121.51465,
        "level": "UNDERGROUND",
        "description": "直通新光三越前方，右側設有無障礙直通電梯。"
    },
    {
        "id": "TPE_Z2",
        "name": "台北車站 站前地下街 Z2 出口 (館前路口)",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 2,
        "lat": 25.04635,
        "lon": 121.51520,
        "level": "UNDERGROUND",
        "description": "連通館前路人行步道與重慶南路書店街。"
    },
    {
        "id": "TPE_K_ESLITE",
        "name": "台北車站 K 區誠品生活地下街",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 10,
        "lat": 25.04680,
        "lon": 121.51600,
        "level": "UNDERGROUND",
        "description": "誠品地下商場走廊，平整地面，兩側設有導盲導引。"
    },
    # 2. 台北車站地面一樓大廳 (1F Ground)
    {
        "id": "TPE_1F_CENTER",
        "name": "台北車站 1F 中央多功能展演中庭",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 100,
        "lat": 25.04780,
        "lon": 121.51700,
        "level": "GROUND",
        "description": "台北車站一樓黑白棋盤格中庭大廳。"
    },
    {
        "id": "TPE_1F_EAST1",
        "name": "台北車站 1F 東一門出入口",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 101,
        "lat": 25.04790,
        "lon": 121.51780,
        "level": "GROUND",
        "description": "鄰近排班計程車招呼站與公車轉運站。"
    },
    {
        "id": "TPE_1F_WEST1",
        "name": "台北車站 1F 西一門出入口",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 102,
        "lat": 25.04780,
        "lon": 121.51620,
        "level": "GROUND",
        "description": "通往台北轉運站與市民大道人行步道。"
    },
    # 3. 台北車站地下一樓與地下二樓穿堂 (B1 / B2)
    {
        "id": "TPE_B1_TRA_HSR",
        "name": "台北車站 B1 台鐵與高鐵剪票穿堂層",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 201,
        "lat": 25.04780,
        "lon": 121.51700,
        "level": "UNDERGROUND",
        "description": "台鐵高鐵進站剪票閘門，前進方向有語音導引服務鈴。"
    },
    {
        "id": "TPE_B2_MRT_CONCOURSE",
        "name": "捷運台北車站 B2 捷運大廳穿堂 (板南線/淡水信義線)",
        "uuid": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
        "major": 1,
        "minor": 301,
        "lat": 25.04700,
        "lon": 121.51650,
        "level": "UNDERGROUND_B2",
        "description": "捷運轉乘大廳，右側設有專屬無障礙諮詢櫃台。"
    },
    # 4. 板橋車站 (Banqiao Station)
    {
        "id": "BQC_B1_LINK",
        "name": "板橋車站 B1 高鐵/台鐵/捷運三鐵共構連通道",
        "uuid": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825",
        "major": 2,
        "minor": 1,
        "lat": 25.01350,
        "lon": 121.46270,
        "level": "UNDERGROUND",
        "description": "直通新北市政府與大遠百地下走廊。"
    },
    # 5. 高雄美麗島站 (Formosa Boulevard)
    {
        "id": "FMD_B1_DOME",
        "name": "捷運美麗島站 B1 光之穹頂大廳",
        "uuid": "B9407F30-F5F8-466E-AFF9-25556B57FE6D",
        "major": 7,
        "minor": 1,
        "lat": 22.63140,
        "lon": 120.30190,
        "level": "UNDERGROUND",
        "description": "美麗島站紅橘線轉乘核心大廳。"
    }
]


class TaiwanBeaconDatabase:
    """
    公眾 Beacon 索引與定錨管理器
    """

    @classmethod
    def match_beacon_by_id(cls, uuid_str: str, major: int, minor: int) -> Optional[Dict[str, Any]]:
        """
        依據 UUID, Major, Minor 尋找已註冊之公眾信標
        """
        uuid_clean = uuid_str.replace("-", "").upper()
        for b in TAIWAN_PUBLIC_BEACONS:
            b_uuid_clean = b["uuid"].replace("-", "").upper()
            if b["major"] == major and b["minor"] == minor and b_uuid_clean == uuid_clean:
                return b
        return None

    @classmethod
    def find_nearest_registered_beacon(cls, lat: float, lon: float, max_dist_m: float = 12.0) -> Optional[Dict[str, Any]]:
        """
        以物理座標尋找最近的已知 Beacon
        """
        best_b = None
        min_dist = max_dist_m
        for b in TAIWAN_PUBLIC_BEACONS:
            d = haversine_distance(lat, lon, b["lat"], b["lon"])
            if d < min_dist:
                min_dist = d
                best_b = dict(b)
                best_b["dist_m"] = round(d, 1)
        return best_b

    @classmethod
    def format_anchor_announcement(cls, beacon: Dict[str, Any], dist_m: float) -> str:
        """
        產生視障 NVDA / TalkBack 語音定錨提示（省話模式）
        """
        dist_str = f"約 {round(dist_m)} 公尺" if dist_m > 1.0 else "正身旁"
        name = beacon.get("name", "公眾信標")
        desc = beacon.get("description", "")
        desc_part = f"，{desc}" if desc else ""
        return f"📡 偵測到【{name}】({dist_str}){desc_part}，室內定位已精準定錨！"
