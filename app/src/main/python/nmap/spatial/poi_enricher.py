import random
from typing import Dict, Any, List
from nmap.spatial.geometry import haversine_distance, destination_point

class PoiEnricher:
    """
    動態店家補完引擎 (Dynamic POI Enricher)
    負責在 OSM 資料稀疏的街道上，利用真實世界的台灣店家命名分佈，
    以程序化 (Procedural Generation) 的方式注入具有空間一致性的虛擬真實店家，
    讓視障者能體驗到充滿生活感的「逛街」體驗。
    """
    
    CATEGORIES = {
        "convenience": ["7-ELEVEN", "全家便利商店", "萊爾富", "OK便利商店", "美廉社"],
        "supermarket": ["全聯福利中心", "家樂福超市", "大潤發", "寶雅", "小北百貨", "屈臣氏", "康是美"],
        "drinks": ["50嵐", "清心福全", "可不可熟成紅茶", "迷客夏", "茶的魔手", "麻古茶坊", "大苑子", "珍煮丹", "COCO都可", "龜記", "天仁茗茶", "鮮茶道"],
        "fast_food": ["麥當勞", "肯德基", "摩斯漢堡", "頂呱呱", "漢堡王", "拿坡里", "達美樂", "必勝客", "八方雲集", "四海遊龍", "三商巧福"],
        "cafe": ["星巴克", "路易莎咖啡", "85度C", "cama cafe", "伯朗咖啡", "多那之"],
        "local_food": ["阿明豬心冬粉", "正忠排骨飯", "悟饕池上飯包", "鬍鬚張魯肉飯", "梁社漢排骨", "老董牛肉麵", "三媽臭臭鍋", "大呼過癮", "六扇門", "孫東寶", "阿Q桶麵", "永和豆漿", "四海豆漿", "阿亮香雞排", "派克脆皮雞排", "胖老爹", "炸雞洋行"],
        "local_random": [
            "{surname}媽媽早餐店", "老{surname}牛肉麵", "{surname}記麵館", "{surname}家滷肉飯", "阿{name}意麵", "正宗{place}羊肉爐",
            "{surname}記水餃", "香香臭豆腐", "大眾食堂", "好客自助餐", "味香快炒", "古早味冰店", "無名麵攤", "傳統菜市場",
            "第一家鹽酥雞", "{surname}師傅便當", "在地人海產", "老字號肉圓"
        ],
        "retail": ["燦坤3C", "全國電子", "金石堂書店", "誠品", "大樹藥局", "丁丁藥局", "杏一醫療用品", "長庚生技", "機車行", "傳統五金行", "10元商店", "鎖匙行", "修改衣服"],
        "services": ["家庭理髮", "曼都髮型", "小林髮廊", "洗衣店", "加水站", "彩券行", "郵局", "玉山銀行", "中國信託", "國泰世華", "富邦銀行", "診所", "牙醫診所", "中醫診所", "動物醫院"]
    }

    SURNAMES = ["陳", "林", "黃", "張", "李", "王", "吳", "劉", "蔡", "楊", "許", "鄭", "謝", "郭", "洪", "曾", "邱", "廖", "賴", "徐"]
    NAMES = ["財", "明", "珠", "嬌", "榮", "華", "雄", "春", "福", "花"]
    PLACES = ["台南", "台北", "台中", "高雄", "岡山", "彰化", "新竹", "嘉義", "屏東"]

    def __init__(self):
        self.enriched_roads = set()

    def generate_random_name(self, category: str, rand: random.Random) -> str:
        if category != "local_random":
            return rand.choice(self.CATEGORIES[category])
        
        template = rand.choice(self.CATEGORIES["local_random"])
        return template.format(
            surname=rand.choice(self.SURNAMES),
            name=rand.choice(self.NAMES),
            place=rand.choice(self.PLACES)
        )

    def determine_density(self, highway_type: str) -> int:
        """決定每100公尺應該有多少店家"""
        if highway_type in ["pedestrian", "footway", "living_street"]:
            return 30  # 夜市/徒步區密度極高
        elif highway_type in ["primary", "secondary"]:
            return 20  # 主要幹道密度高
        elif highway_type in ["tertiary", "residential"]:
            return 10  # 住宅區巷弄中等
        return 5

    def enrich_road(self, road_id: str, road_name: str, highway_type: str, coords: List[tuple], world_model_rtree, next_poi_id: int) -> int:
        """
        對指定道路進行店家補完。
        為了確保空間記憶的一致性，使用 road_id 作為 Random Seed。
        """
        if road_id in self.enriched_roads or not road_name:
            return next_poi_id
        self.enriched_roads.add(road_id)

        # Use the road ID (or name) to seed the random generator so it's consistent
        seed_str = f"enrich_{road_name}_{road_id}"
        rand = random.Random(hash(seed_str))

        density_per_100m = self.determine_density(highway_type)
        if density_per_100m == 0:
            return next_poi_id

        # Calculate total road length
        total_length = 0
        segments = []
        for i in range(len(coords) - 1):
            lat1, lon1 = coords[i]
            lat2, lon2 = coords[i+1]
            dist = haversine_distance(lat1, lon1, lat2, lon2)
            total_length += dist
            segments.append((lat1, lon1, lat2, lon2, dist))

        if total_length < 10:
            return next_poi_id

        target_shop_count = max(2, int((total_length / 100.0) * density_per_100m))
        
        cats = list(self.CATEGORIES.keys())
        
        added_pois = []
        for _ in range(target_shop_count):
            # Pick a random segment weighted by length
            seg_val = rand.uniform(0, total_length)
            accum = 0
            chosen_seg = segments[0]
            for seg in segments:
                accum += seg[4]
                if accum >= seg_val:
                    chosen_seg = seg
                    break
            
            lat1, lon1, lat2, lon2, dist = chosen_seg
            
            # Interpolate a point on the segment
            fraction = rand.uniform(0.1, 0.9)
            center_lat = lat1 + (lat2 - lat1) * fraction
            center_lon = lon1 + (lon2 - lon1) * fraction
            
            # Offset left or right (randomly) by 3-10 meters to simulate storefronts
            import math
            angle_rad = math.atan2(lon2 - lon1, lat2 - lat1)
            offset_dist = rand.uniform(3.0, 10.0)
            is_left = rand.choice([True, False])
            angle_offset = -math.pi / 2 if is_left else math.pi / 2
            
            final_angle = angle_rad + angle_offset
            final_angle_deg = (math.degrees(final_angle) + 360) % 360
            
            p_lat, p_lon = destination_point(center_lat, center_lon, offset_dist, final_angle_deg)
            
            # Select category and name
            cat = rand.choice(cats)
            name = self.generate_random_name(cat, rand)
            
            house_num = int(rand.uniform(1, 300))
            if is_left:
                house_num = house_num if house_num % 2 != 0 else house_num + 1
            else:
                house_num = house_num if house_num % 2 == 0 else house_num + 1
                
            poi = {
                "id": f"enriched_{next_poi_id}",
                "lat": p_lat,
                "lon": p_lon,
                "tags": {
                    "name": name,
                    "amenity": cat,
                    "addr:housenumber": str(house_num),
                    "addr:street": road_name,
                    "source": "enricher"
                }
            }
            
            # Insert into R-tree
            from nmap.spatial.world_model import SpatialPOI
            point_poi = SpatialPOI(poi)
            world_model_rtree.insert(next_poi_id, (p_lon, p_lat, p_lon, p_lat), obj=point_poi)
            next_poi_id += 1

        return next_poi_id
