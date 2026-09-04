import unittest
from nmap.data.overpass import OverpassClient
from nmap.spatial.world_model import WorldModel
from nmap.spatial.sidewalk_hazards import SidewalkHazardScanner


class TestOsmMicroFacilities(unittest.TestCase):
    """
    【OSM 微型無障礙設施端到端單元測試】
    驗證項目：
    1. Overpass 查詢生成（涵蓋 barrier, entrance, steps, micro_amenities）
    2. 無店名微型設施白話解析（飲水機、長椅、無障礙廁所、車擋、大門）
    3. WorldModel 空間網格索引建置與鐘點方位查詢
    4. 車擋柱自動注入 SidewalkHazardScanner 生命安全避障雷達
    """

    def setUp(self):
        self.overpass = OverpassClient()
        self.world_model = WorldModel()

        # 模擬台北車站站前商圈周遭微型無障礙設施的 OSM 原始元素
        self.center_lat = 25.04700
        self.center_lon = 121.51700

        self.mock_osm_data = {
            "elements": [
                # 1. 道路 (供 WorldModel 構建基本路網)
                {
                    "type": "node",
                    "id": 101,
                    "lat": 25.04700,
                    "lon": 121.51700,
                    "tags": {}
                },
                {
                    "type": "node",
                    "id": 102,
                    "lat": 25.04750,
                    "lon": 121.51700,
                    "tags": {}
                },
                {
                    "type": "way",
                    "id": 201,
                    "nodes": [101, 102],
                    "tags": {
                        "highway": "pedestrian",
                        "name": "站前步行大道"
                    }
                },
                # 2. 車擋柱 (Bollard Node) - 正前方 8 公尺
                {
                    "type": "node",
                    "id": 301,
                    "lat": 25.047072, # 約向北 8 公尺
                    "lon": 121.51700,
                    "tags": {
                        "barrier": "bollard",
                        "access": "no"
                    }
                },
                # 3. 建築物真實正門 (Entrance Node) - 右前 10 公尺
                {
                    "type": "node",
                    "id": 401,
                    "lat": 25.04706,
                    "lon": 121.51708,
                    "tags": {
                        "entrance": "main",
                        "door": "automatic",
                        "wheelchair": "yes"
                    }
                },
                # 4. 微型設施：公眾飲水機 (Drinking Water Node, 無 name 標籤) - 左側 6 公尺
                {
                    "type": "node",
                    "id": 501,
                    "lat": 25.04700,
                    "lon": 121.51694,
                    "tags": {
                        "amenity": "drinking_water"
                    }
                },
                # 5. 微型設施：公共廁所 (Toilets Node, 無障礙友善) - 20 公尺
                {
                    "type": "node",
                    "id": 502,
                    "lat": 25.04718,
                    "lon": 121.51700,
                    "tags": {
                        "amenity": "toilets",
                        "wheelchair": "designated"
                    }
                },
                # 6. 微型設施：休息長椅 (Bench Node)
                {
                    "type": "node",
                    "id": 503,
                    "lat": 25.04695,
                    "lon": 121.51705,
                    "tags": {
                        "amenity": "bench"
                    }
                },
                # 7. 人行階梯 (Steps Way) - 前方 15 公尺，帶有 10 階與扶手
                {
                    "type": "node",
                    "id": 601,
                    "lat": 25.04713,
                    "lon": 121.51698,
                    "tags": {}
                },
                {
                    "type": "node",
                    "id": 602,
                    "lat": 25.04715,
                    "lon": 121.51698,
                    "tags": {}
                },
                {
                    "type": "way",
                    "id": 6001,
                    "nodes": [601, 602],
                    "tags": {
                        "highway": "steps",
                        "name": "地下街出入口階梯",
                        "step_count": "10",
                        "handrail": "yes",
                        "ramp": "yes",
                        "tactile_paving": "yes"
                    }
                },
                # 8. 行人觸控交通號誌 (Traffic Signal Node with Button) - 前方 11 公尺
                {
                    "type": "node",
                    "id": 701,
                    "lat": 25.04710,
                    "lon": 121.51700,
                    "tags": {
                        "highway": "traffic_signals",
                        "name": "站前廣場行人觸控號誌",
                        "button_operated": "yes",
                        "traffic_signals": "pedestrian"
                    }
                },
                # 9. 號誌化斑馬線 (Signalized Crossing Node with Sound) - 前方 17 公尺
                {
                    "type": "node",
                    "id": 702,
                    "lat": 25.04715,
                    "lon": 121.51705,
                    "tags": {
                        "highway": "crossing",
                        "crossing": "traffic_signals",
                        "crossing:signals": "yes",
                        "traffic_signals:sound": "yes",
                        "tactile_paving": "yes"
                    }
                }
            ]
        }

    def test_overpass_query_contains_micro_facilities(self):
        """測試 Overpass QL 查詢字串是否正確包含 barrier 與 entrance 標籤"""
        q = self.overpass.build_query(self.center_lat, self.center_lon, radius_m=200.0)
        self.assertIn('node["barrier"]', q)
        self.assertIn('way["barrier"]', q)
        self.assertIn('node["entrance"]', q)

    def test_parse_elements_extracts_all_four_categories(self):
        """測試 parse_elements 是否能完整提煉 4 類無障礙設施"""
        parsed = self.overpass.parse_elements(self.mock_osm_data, self.center_lat, self.center_lon)

        self.assertIn("barriers", parsed)
        self.assertIn("entrances", parsed)
        self.assertIn("steps", parsed)
        self.assertIn("micro_amenities", parsed)

        # 1. 驗證車擋柱
        self.assertEqual(len(parsed["barriers"]), 1)
        b = parsed["barriers"][0]
        self.assertEqual(b["barrier_type"], "bollard")
        self.assertEqual(b["name"], "車擋柱")

        # 2. 驗證大門出入口
        self.assertEqual(len(parsed["entrances"]), 1)
        ent = parsed["entrances"][0]
        self.assertEqual(ent["entrance_type"], "main")
        self.assertEqual(ent["door"], "automatic")
        self.assertEqual(ent["wheelchair"], "yes")

        # 3. 驗證階梯
        self.assertEqual(len(parsed["steps"]), 1)
        st = parsed["steps"][0]
        self.assertEqual(st["name"], "地下街出入口階梯")
        self.assertEqual(st["step_count"], "10")
        self.assertEqual(st["handrail"], "yes")
        self.assertEqual(st["ramp"], "yes")

        # 4. 驗證無店名微型設施（飲水機、公廁、長椅）
        self.assertEqual(len(parsed["micro_amenities"]), 3)
        amenity_names = [ma["name"] for ma in parsed["micro_amenities"]]
        self.assertIn("公眾飲水機", amenity_names)
        self.assertIn("無障礙公共廁所", amenity_names)
        self.assertIn("休息長椅", amenity_names)

        # 5. 驗證交通號誌提煉（含按鈕標籤與號誌化斑馬線）
        self.assertIn("traffic_signals", parsed)
        self.assertGreaterEqual(len(parsed["traffic_signals"]), 2)
        sig_btn = next((s for s in parsed["traffic_signals"] if s["id"] == 701), None)
        self.assertIsNotNone(sig_btn)
        self.assertTrue(sig_btn["has_button"])
        self.assertEqual(sig_btn["signal_type"], "行人專用號誌")
        self.assertEqual(sig_btn["name"], "站前廣場行人觸控號誌")

        sig_cross = next((s for s in parsed["traffic_signals"] if s["id"] == 702), None)
        self.assertIsNotNone(sig_cross)
        self.assertTrue(sig_cross["has_sound"])

    def test_world_model_spatial_indexing_and_queries(self):
        """測試 WorldModel 建立空間索引後，能正確回傳距離、鐘點方位與親切提示語"""
        parsed = self.overpass.parse_elements(self.mock_osm_data, self.center_lat, self.center_lon)
        self.world_model.build_from_osm(parsed, self.center_lat, self.center_lon)

        # 站在 center_lat, center_lon，面向正北 (0 度)
        heading = 0.0

        # 1. 查詢周遭車擋
        barriers = self.world_model.get_nearby_barriers(self.center_lat, self.center_lon, heading, radius_m=20.0)
        self.assertGreaterEqual(len(barriers), 1)
        self.assertEqual(barriers[0]["name"], "車擋柱")
        self.assertIn("12點鐘方向", barriers[0]["clock_position"])
        self.assertIn("車擋柱", barriers[0]["speech_prompt"])

        # 2. 查詢周遭大門出入口
        entrances = self.world_model.get_nearby_entrances(self.center_lat, self.center_lon, heading, radius_m=30.0)
        self.assertGreaterEqual(len(entrances), 1)
        self.assertIn("無障礙入口", entrances[0]["name"])
        self.assertIn("自動門", entrances[0]["name"])

        # 3. 查詢周遭階梯
        steps = self.world_model.get_nearby_steps(self.center_lat, self.center_lon, heading, radius_m=30.0)
        self.assertGreaterEqual(len(steps), 1)
        self.assertIn("共10階", steps[0]["name"])
        self.assertIn("有扶手", steps[0]["name"])
        self.assertIn("附設斜坡", steps[0]["name"])

        # 4. 查詢微型公眾設施
        amenities = self.world_model.get_nearby_micro_amenities(self.center_lat, self.center_lon, heading, radius_m=30.0)
        self.assertGreaterEqual(len(amenities), 3)

    def test_all_traffic_signals_retrieval_and_prompts(self):
        """測試全台號誌融合（現場 OSM 號誌 + 離線資料庫）與鐘點方位、按鈕導引報讀"""
        parsed = self.overpass.parse_elements(self.mock_osm_data, self.center_lat, self.center_lon)
        self.world_model.build_from_osm(parsed, self.center_lat, self.center_lon)

        # 站在 center_lat, center_lon，面向正北 (0 度)
        heading = 0.0

        signals = self.world_model.get_nearby_traffic_signals(self.center_lat, self.center_lon, heading, radius_m=30.0)
        self.assertGreaterEqual(len(signals), 2)

        # 檢驗包含帶有觸控按鈕的行人專用號誌
        btn_sigs = [s for s in signals if s.get("has_button")]
        self.assertGreaterEqual(len(btn_sigs), 1)
        btn_sig = btn_sigs[0]
        self.assertEqual(btn_sig["signal_type"], "行人觸控號誌")
        self.assertIn("12點鐘方向", btn_sig["clock_position"])
        self.assertIn("設有按鈕", btn_sig["speech_prompt"])
        self.assertTrue(btn_sig["button_guide"] != "")

        # 檢驗包含有聲號誌或號誌化設施
        aps_sigs = [s for s in signals if s.get("has_aps")]
        self.assertGreaterEqual(len(aps_sigs), 1)
        aps_sig = aps_sigs[0]
        self.assertEqual(aps_sig["signal_type"], "視障有聲號誌")
        self.assertIn("布穀鳥聲", aps_sig["speech_prompt"])

        # 檢驗路口安全號誌語音回饋
        safety = self.world_model.get_signal_safety(self.center_lat, self.center_lon, heading, radius_m=28.0)
        self.assertIsNotNone(safety)
        self.assertTrue(safety.get("is_signalized"))
        self.assertTrue("有聲號誌" in safety.get("speech_prompt", "") or "紅綠燈" in safety.get("speech_prompt", ""))

    def test_sidewalk_hazard_radar_dynamic_bollard_detection(self):
        """測試車擋柱自動注入 SidewalkHazardScanner 後，前進走廊碰撞雷達能發出繞行建議"""
        parsed = self.overpass.parse_elements(self.mock_osm_data, self.center_lat, self.center_lon)
        self.world_model.build_from_osm(parsed, self.center_lat, self.center_lon)

        # 面向正北 (0 度)，前進走廊 8 公尺處有車擋柱 (經緯度 25.047072, 121.51700)
        hazards = self.world_model.get_sidewalk_hazards(self.center_lat, self.center_lon, heading_deg=0.0, max_dist_m=12.0)
        
        bollard_hazards = [h for h in hazards if "車擋柱" in h["name"]]
        self.assertGreaterEqual(len(bollard_hazards), 1)
        hazard = bollard_hazards[0]
        self.assertEqual(hazard["hazard_level"], "WARNING")
        self.assertIn("⚠️ 注意：前方", hazard["speech_prompt"])
        self.assertIn("繞開", hazard["speech_prompt"])


if __name__ == "__main__":
    unittest.main()
