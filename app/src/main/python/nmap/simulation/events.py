import random
from typing import Dict, Any, List

class EventGenerator:
    """產生情境事件。包含超過100個事件樣板。"""

    def __init__(self) -> None:
        self.pedestrian_templates = [
            # 一般行人
            "有人從右邊快步走過", "一位老先生拄著拐杖緩慢走在前方", "有小朋友在左邊追逐嬉鬧",
            "一位外送員快速從左後方騎過", "有人在前方突然停下來滑手機", "一群學生從對面走來",
            "有人推著嬰兒車從右前方經過", "有人牽著狗從左邊走來，狗鏈可能絆到腳", "一位行人站在人行道中央講電話",
            "有人拖著行李箱從後方追上", "一對情侶牽手從左方擦肩而過", "有人邊走邊喝飲料從右側經過",
            "前方有人不小心掉落了物品", "有人從對向奔跑過來", "一群阿姨在左前方停下來聊天",
            "一位慢跑者從後方喘著氣跑過", "有人拿著雨傘不小心戳到你的方向", "前方有人倒車步出店家",
            "有人騎著滑板車從右前方滑過", "一位盲人朋友拿著白手杖從左側經過", "前方有人大聲咳嗽",
            "有人邊走邊聽音樂，腳步聲很大", "一群遊客在右前方拍照", "有人推著資源回收車緩慢前進",
            "一位媽媽牽著小孩從前方走過"
        ]

        self.vehicle_templates = [
            # 車輛
            "左前方有機車引擎聲逐漸靠近", "右邊有公車進站的煞車聲", "前方路口傳來大量車流聲",
            "後方有汽車喇叭聲", "右邊有腳踏車鈴聲", "遠處有救護車鳴笛聲由遠漸近",
            "一輛大卡車從左方轟隆隆駛過", "有汽車在右前方怠速運轉", "左邊傳來機車排氣管的改裝聲",
            "前方有車輛倒車雷達的嗶嗶聲", "右後方有電動機車悄然靠近", "一輛計程車在左前方急煞",
            "遠處傳來警車的鳴笛聲", "有垃圾車播放著音樂從前方開過", "右側有車輛駛過水坑的濺水聲",
            "一輛重型機車從後方呼嘯而過", "前方路口有交通警察吹哨子指揮", "左前方有汽車車門關上的碰一聲"
        ]

        self.obstacle_templates = [
            # 障礙物
            "前方2公尺有一排機車停放，擋住人行道", "右邊有一個大型招牌突出到走道上", "左前方有施工圍籬",
            "路面上有一個三角錐", "前方有盆栽擺放在人行道上", "右邊有垃圾桶",
            "前方有電線桿", "路邊有YouBike停車柱", "左前方有郵筒",
            "前方有一堆廢棄紙箱", "右邊有變電箱佔據了一半的路面", "前方有路樹的樹枝垂得很低",
            "左邊有一輛違停的汽車", "前方有流動攤販的推車", "右前方有消防栓",
            "路中間有一個未加蓋的小坑洞", "前方有商家堆放的貨物", "左側有一面廣告旗幟在風中飄動",
            "前方有一段鐵鍊拉成的封鎖線", "右邊有住家曬的衣服懸掛在路邊", "前方有一個被隨意丟棄的購物車"
        ]

        self.ground_templates = [
            # 地面狀況
            "腳下從柏油路面變成磁磚地", "前方有一段導盲磚", "注意：導盲磚在此處中斷",
            "前方地面有高低差，大約5公分", "路面有積水", "前方有水溝蓋",
            "腳下感覺到路面不平整的碎石", "地面上有濕滑的落葉", "前方有一段斜坡往下",
            "前方有一段斜坡往上", "腳下踩到了柔軟的草地", "前方有一小階台階",
            "路面有坑洞，請小心", "地面材質變成木棧道", "前方有減速丘的隆起"
        ]

        self.sound_templates = [
            # 聲音事件
            "左邊傳來商店播放的音樂", "右前方有人在叫賣", "後方傳來施工的電鑽聲",
            "遠方有教堂鐘聲", "前方有鳥叫聲", "右邊有冷氣機滴水的聲音",
            "左前方傳來電視機的新聞播報聲", "右側有小狗在吠叫", "上方傳來飛機飛過的轟鳴聲",
            "前方傳來小學裡的鐘聲和喧鬧聲", "左後方有鐵門拉下的聲音", "右邊傳來便利商店開門的叮咚聲",
            "前方有噴水池的水聲", "左側傳來炒菜鍋的匡噹聲", "右前方有街頭藝人在彈吉他",
            "遠處傳來火車經過的鐵軌聲"
        ]

        self.weather_templates = [
            # 天氣事件
            "開始下起小雨，路面變得濕滑", "一陣強風從右邊吹來", "太陽很大，感覺很熱",
            "天空傳來悶雷聲", "突然颳起一陣陣涼風", "雨勢變大，周圍有躲雨的腳步聲",
            "感覺到空氣變得潮濕悶熱", "有一片雲遮住太陽，感覺變涼了"
        ]

        self.danger_templates = [
            # 危險事件
            "⚠️ 注意！你正在接近馬路邊緣", "⚠️ 前方有施工區域，地面不穩", "⚠️ 左邊有車輛快速通過",
            "⚠️ 前方路面有大坑洞", "⚠️ 右側有不明物體掉落的聲音", "⚠️ 前方機車突然衝上人行道",
            "⚠️ 腳下地面突然下陷", "⚠️ 前方有正在倒車的大型車輛", "⚠️ 注意！導盲磚指向一根電線桿",
            "⚠️ 左前方有未牽繩的大狗靠近"
        ]

    def _create_event(self, category: str, description: str, danger_level: str = 'low', requires_action: bool = False) -> Dict[str, Any]:
        positions = ['正前方', '右前方', '左前方', '右邊', '左邊', '右後方', '左後方', '正後方']
        return {
            'category': category,
            'description': description,
            'clock_position': random.choice(positions),
            'distance_m': round(random.uniform(1.0, 10.0), 1),
            'danger_level': danger_level,
            'requires_action': requires_action,
            'suggested_action': '請放慢腳步並使用白手杖確認前方狀況。' if requires_action else ''
        }

    def generate_step_events(self, area_type: str, area_info: Dict[str, Any], difficulty_settings: Dict[str, Any], weather: Dict[str, Any], time_of_day: str, player_heading: float, world_model: Any, lat: float, lon: float) -> List[Dict[str, Any]]:
        """根據情境與真實地理特徵產生事件。"""
        events = []
        freq = difficulty_settings.get('event_frequency', 0.5)

        # 1. 行人事件：根據人群密度調整機率
        crowd_density = area_info.get('crowd_density', 0.5)
        if random.random() < freq * difficulty_settings.get('crowd_multiplier', 1.0) * crowd_density * 2:
            template = random.choice(self.pedestrian_templates)
            # 特殊情境過濾
            if '夜市' in area_type and random.random() < 0.5:
                template = "前方有人排隊買東西，隊伍排到了路中間"
            elif '學校' in area_type and random.random() < 0.5:
                template = "一群學生嬉鬧著從前方跑過"
            events.append(self._create_event('pedestrian', template))

        # 2. 車輛事件：根據車流量調整機率
        vehicle_traffic = area_info.get('vehicle_traffic', 0.5)
        if random.random() < freq * difficulty_settings.get('vehicle_multiplier', 1.0) * vehicle_traffic * 2:
            template = random.choice(self.vehicle_templates)
            if area_type == 'transit_hub' and random.random() < 0.5:
                template = "右前方有公車進站，發出巨大的氣壓煞車聲"
            events.append(self._create_event('vehicle', template))

        # 3. 障礙物事件：根據 OSM 真實 POI 增強
        if random.random() < freq * difficulty_settings.get('obstacle_multiplier', 1.0):
            template = random.choice(self.obstacle_templates)
            # 如果附近有餐廳/超商，增加機車違停和招牌機率
            pois = getattr(world_model, 'get_nearby_pois', lambda l, ln, h, r_m=80.0: [])(lat, lon, player_heading, radius_m=20)
            if any('restaurant' in getattr(p, 'category', '') for p in pois):
                template = "前方有外送員的機車隨意停放在人行道上"
            events.append(self._create_event('obstacle', template, requires_action=True))

        # 4. 地面事件：根據周遭建築或設施
        if random.random() < freq * 0.5:
            events.append(self._create_event('ground', random.choice(self.ground_templates)))

        # 5. 聲音事件：結合 area_info 的噪音程度
        noise_level = area_info.get('noise_level', 0.5)
        if random.random() < freq * noise_level * 2:
            template = random.choice(self.sound_templates)
            events.append(self._create_event('sound', template))

        # 6. 天氣
        if random.random() < freq * 0.2:
            events.append(self._create_event('weather', random.choice(self.weather_templates)))

        # 7. 危險事件：只有困難模式或特定危險區域才容易發生
        if random.random() < freq * 0.1 * difficulty_settings.get('obstacle_multiplier', 1.0):
            events.append(self._create_event('danger', random.choice(self.danger_templates), danger_level='high', requires_action=True))

        return events
