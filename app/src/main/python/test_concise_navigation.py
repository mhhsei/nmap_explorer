import sys
import unittest
import math
from nmap.spatial.geometry import (
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_relative_direction,
    haversine_distance
)
from nmap.spatial.intersection import IntersectionAnalyzer
from nmap.accessibility.reporter import NVDAReporter

class MockWorldModel:
    def __init__(self):
        import networkx as nx
        from nmap.spatial.grid_index import GridSpatialIndex
        self.road_graph = nx.MultiDiGraph()
        self.junction_rtree = GridSpatialIndex(cell_size_deg=0.005)
        self.signal_rtree = GridSpatialIndex(cell_size_deg=0.005)
        self.traffic_signal_rtree = GridSpatialIndex(cell_size_deg=0.005)
        self.crossing_rtree = GridSpatialIndex(cell_size_deg=0.005)
        self.building_rtree = GridSpatialIndex(cell_size_deg=0.005)
        self.amenity_rtree = GridSpatialIndex(cell_size_deg=0.005)
        self.hazard_rtree = GridSpatialIndex(cell_size_deg=0.005)

    def get_road_info(self, lat, lon, heading_deg):
        return {
            "street_name": "北新路一段",
            "lanes": 4,
            "oneway": "雙向"
        }

    def get_nearby_pois(self, lat, lon, heading_deg, radius_m=100.0):
        return [
            {
                "name": "7-Eleven 統一超商",
                "category": "convenience",
                "distance_m": 8.0,
                "relative_bearing_deg": 45.0,
                "relative_direction": "右前方",
                "clock_position": "2點鐘方向"
            },
            {
                "name": "康記涼麵",
                "category": "restaurant",
                "distance_m": 5.0,
                "relative_bearing_deg": -90.0,
                "relative_direction": "正左側",
                "clock_position": "9點鐘方向"
            }
        ]

    def get_nearby_buildings(self, lat, lon, heading_deg, radius_m=80.0):
        return []

    def get_left_right_side_scan(self, lat, lon, heading_deg, radius_m=60.0):
        return {"left_side": {"house_numbers": [], "alleys": []}, "right_side": {"house_numbers": [], "alleys": []}}

    def get_interpolated_door_numbers(self, lat, lon, heading_deg):
        return {"left_side_estimate": "", "right_side_estimate": "", "concise_door": ""}

    def get_sidewalk_hazards(self, lat, lon, heading_deg, max_dist_m=8.0):
        return []

    def get_mrt_accessible_exits(self, lat, lon, heading_deg, radius_m=80.0):
        return []

    def get_signal_safety(self, lat, lon, heading_deg, radius_m=28.0):
        return None

    def get_intersection_clock_bearings(self, lat, lon, heading_deg, radius_m=40.0):
        return []

class MockStreetSceneEngine:
    def analyze_scene(self, lat, lon, heading, wm, road_info=None):
        return {"full_description": "街景平整", "scene_summary": "街景"}

class MockAgent:
    def __init__(self, lat, lon, heading_deg, world_model):
        self.is_loaded = True
        self.lat = lat
        self.lon = lon
        self.heading_deg = heading_deg
        self.world_model = world_model
        self.intersection_analyzer = IntersectionAnalyzer()
        self.street_scene_engine = MockStreetSceneEngine()
        self.location_label = "測試位置"

    def get_navigation_status(self):
        return ""

class TestConciseNavigation(unittest.TestCase):
    def setUp(self):
        self.wm = MockWorldModel()
        # Setup an intersection at (25.179900, 121.451200)
        # Node 1: center intersection node
        # Node 2: North branch (北新路一段)
        # Node 3: East branch (大忠街)
        # Node 4: South branch (北新路一段 - 来时路)
        j_lat, j_lon = 25.179900, 121.451200
        self.wm.road_graph.add_node(1, lat=j_lat, lon=j_lon)
        self.wm.road_graph.add_node(2, lat=j_lat + 0.0005, lon=j_lon) # North
        self.wm.road_graph.add_node(3, lat=j_lat, lon=j_lon + 0.0005) # East (90 deg)
        self.wm.road_graph.add_node(4, lat=j_lat - 0.0005, lon=j_lon) # South (180 deg)

        self.wm.road_graph.add_edge(1, 2, key=0, name="北新路一段")
        self.wm.road_graph.add_edge(1, 3, key=0, name="大忠街")
        self.wm.road_graph.add_edge(1, 4, key=0, name="北新路一段")

        meta = {
            "is_signalized": True,
            "has_aps": True,
            "sound_desc": "鳥鳴聲 (大忠街)",
            "has_refuge_island": True,
            "signal_name": "北新路與大忠街口"
        }
        self.wm.junction_rtree.insert(1, (j_lon, j_lat, j_lon, j_lat), obj=(1, 3, j_lat, j_lon, meta))

    def test_intersection_analyzer_concise_branches(self):
        analyzer = IntersectionAnalyzer()
        # User is walking North (heading = 0 deg), 15 meters South of junction
        user_lat = 25.179900 - 0.000135 # ~15m south
        user_lon = 121.451200
        heading = 0.0

        road_info = self.wm.get_road_info(user_lat, user_lon, heading)
        result = analyzer.analyze(user_lat, user_lon, heading, self.wm, max_distance_m=50.0, curr_road_info=road_info)

        self.assertIsNotNone(result["junction_distance_m"])
        self.assertTrue(10.0 <= result["junction_distance_m"] <= 20.0)
        self.assertEqual(result["has_aps"], True)
        self.assertIn("大忠街", result["concise_branches"])
        # Approaching prompt must contain concise clock guidance and APS info
        self.assertIn("接近路口（有聲號誌）", result["concise_approaching_prompt"])
        self.assertIn("大忠街", result["concise_approaching_prompt"])
        self.assertEqual(result["concise_passing_prompt"], "正通過路口，請直線前進")

    def test_nvda_reporter_concise_report(self):
        reporter = NVDAReporter()
        user_lat = 25.179900 - 0.000135 # ~15m south
        user_lon = 121.451200
        heading = 0.0
        agent = MockAgent(user_lat, user_lon, heading, self.wm)

        report = reporter.generate_concise_report(agent)
        # Should prioritize junction approaching prompt with concise branches
        self.assertIn("接近路口（有聲號誌）", report)
        self.assertIn("大忠街", report)
        # Verify it does NOT contain geometric clutter like 'T字/岔路口'
        self.assertNotIn("T字/岔路口", report)
    def test_90_degree_corner_turn(self):
        """【風洞實驗 4：手電筒光束的 90 度直角轉彎】"""
        analyzer = IntersectionAnalyzer()
        # User is at 8 meters south of junction (dist < 12m)
        user_lat = 25.179900 - 0.000075
        user_lon = 121.451200
        
        # Heading 0 deg (North): junction is directly in front
        road_info = self.wm.get_road_info(user_lat, user_lon, 0.0)
        res_north = analyzer.analyze(user_lat, user_lon, 0.0, self.wm, max_distance_m=50.0, curr_road_info=road_info)
        self.assertIsNotNone(res_north["junction_distance_m"])

        # User reaches junction and turns 90 deg (East) towards 大忠街
        res_east = analyzer.analyze(user_lat, user_lon, 90.0, self.wm, max_distance_m=50.0, curr_road_info=road_info)
        # Within 12m, a side corner junction is captured and branches reflect the turn
        self.assertTrue(res_east["junction_type"] != "直行道路")

    def test_opposite_street_continuation(self):
        """【測試：十字路口直行對向接續路名確認】"""
        analyzer = IntersectionAnalyzer()
        # Create a new world model where North branch connects to 中正路
        wm2 = MockWorldModel()
        j_lat, j_lon = 25.179900, 121.451200
        wm2.road_graph.add_node(1, lat=j_lat, lon=j_lon)
        wm2.road_graph.add_node(2, lat=j_lat + 0.0005, lon=j_lon) # North (中正路)
        wm2.road_graph.add_node(3, lat=j_lat, lon=j_lon + 0.0005) # East (大忠街)
        wm2.road_graph.add_node(4, lat=j_lat - 0.0005, lon=j_lon) # South (北新路一段)

        wm2.road_graph.add_edge(1, 2, key=0, name="中正路")
        wm2.road_graph.add_edge(1, 3, key=0, name="大忠街")
        wm2.road_graph.add_edge(1, 4, key=0, name="北新路一段")

        meta = {"is_signalized": True, "has_aps": False, "signal_name": "北新路與大忠街口"}
        wm2.junction_rtree.insert(1, (j_lon, j_lat, j_lon, j_lat), obj=(1, 3, j_lat, j_lon, meta))

        user_lat = 25.179900 - 0.00004 # 4m from junction (PASSING state)
        user_lon = 121.451200
        road_info = {"street_name": "北新路一段"}

        res = analyzer.analyze(user_lat, user_lon, 0.0, wm2, max_distance_m=50.0, curr_road_info=road_info)
        self.assertEqual(res["straight_continuation_road"], "中正路")
        self.assertEqual(res["concise_passing_prompt"], "正通過路口，直行接【中正路】")

    def test_poi_door_number_and_cluster(self):
        """【測試：門牌自然錨定與緊鄰店家同側合併打包】"""
        reporter = NVDAReporter()
        wm_cluster = MockWorldModel()
        # Return 2 shops at 2 o'clock, within 2 meters of each other, one with housenumber
        wm_cluster.get_nearby_pois = lambda lat, lon, heading, radius_m=100.0: [
            {
                "name": "全家便利商店",
                "housenumber": "205",
                "distance_m": 8.0,
                "relative_bearing_deg": 45.0,
                "relative_direction": "右前方",
                "clock_position": "2點鐘方向"
            },
            {
                "name": "康是美",
                "housenumber": "207",
                "distance_m": 9.5,
                "relative_bearing_deg": 48.0,
                "relative_direction": "右前方",
                "clock_position": "2點鐘方向"
            }
        ]

    def test_srtm_elevation_reading(self):
        """【測試：NASA SRTM 3D 地形高程讀取與自適應地表裸地濾波 (Bare-Earth DTM)】"""
        from nmap.spatial.srtm_reader import get_elevation
        # 測試台北 101 信義商圈地面真實海拔 (已過濾 50m 摩天樓雷達回波，應落在 12~18m 之間)
        elev_101 = get_elevation(25.0339, 121.5644)
        self.assertIsNotNone(elev_101)
        self.assertTrue(10.0 <= elev_101 <= 20.0, f"Expected 10-20m, got {elev_101}")

        # 測試高雄 85 大樓港邊地面真實海拔 (已過濾 101m 高樓雷達回波，應落在 2~10m 之間)
        elev_kh = get_elevation(22.6117, 120.3005)
        self.assertIsNotNone(elev_kh)
        self.assertTrue(2.0 <= elev_kh <= 10.0, f"Expected 2-10m, got {elev_kh}")

        # 測試淡水北新路坡道海拔
        elev_tamsui = get_elevation(25.1799, 121.4512)
        self.assertIsNotNone(elev_tamsui)
        self.assertTrue(40.0 <= elev_tamsui <= 55.0, f"Expected 40-55m, got {elev_tamsui}")

        # 測試玉山主峰海拔
        elev_yushan = get_elevation(23.4700, 120.9573)
        self.assertIsNotNone(elev_yushan)
        self.assertTrue(3800.0 <= elev_yushan <= 3952.0, f"Expected 3800-3952m, got {elev_yushan}")

        # 測試 NVDAReporter 全景報讀中包含真實地表海拔
        reporter = NVDAReporter()
        agent = MockAgent(25.1799, 121.4512, 0.0, self.wm)
        agent.location_label = "淡水老街"
        full_rep = reporter.generate_full_report(agent, ground_elevation_m=elev_tamsui)
        self.assertIn("真實地形海拔", full_rep)
        self.assertIn(f"{elev_tamsui:+.1f}", full_rep)

    def test_chained_junctions_same_side(self):
        """【測試：同側連續巷弄接力播報 (Chained Junctions - Same Side)】"""
        analyzer = IntersectionAnalyzer()
        wm_chain = MockWorldModel()
        j1_lat, j1_lon = 25.179900, 121.451200
        j2_lat, j2_lon = 25.179945, 121.451200

        wm_chain.road_graph.add_node(1, lat=j1_lat, lon=j1_lon)
        wm_chain.road_graph.add_node(2, lat=j2_lat, lon=j2_lon)
        wm_chain.road_graph.add_node(10, lat=j1_lat, lon=j1_lon + 0.0005) # 182巷 (East, Right)
        wm_chain.road_graph.add_node(20, lat=j2_lat, lon=j2_lon + 0.0005) # 184巷 (East, Right)
        wm_chain.road_graph.add_node(30, lat=j1_lat - 0.0005, lon=j1_lon) # South
        wm_chain.road_graph.add_node(40, lat=j2_lat + 0.0005, lon=j2_lon) # North

        wm_chain.road_graph.add_edge(1, 10, key=0, name="北新路182巷")
        wm_chain.road_graph.add_edge(1, 30, key=0, name="北新路一段")
        wm_chain.road_graph.add_edge(1, 2, key=0, name="北新路一段")
        wm_chain.road_graph.add_edge(2, 20, key=0, name="北新路184巷")
        wm_chain.road_graph.add_edge(2, 40, key=0, name="北新路一段")

        wm_chain.junction_rtree.insert(1, (j1_lon, j1_lat, j1_lon, j1_lat), obj=(1, 3, j1_lat, j1_lon, {}))
        wm_chain.junction_rtree.insert(2, (j2_lon, j2_lat, j2_lon, j2_lat), obj=(2, 3, j2_lat, j2_lon, {}))

        user_lat = j1_lat - 0.000108 # ~12m south of j1
        user_lon = j1_lon
        road_info = {"street_name": "北新路一段"}

        # 1. 接近階段：預告同側連續巷弄
        res_app = analyzer.analyze(user_lat, user_lon, 0.0, wm_chain, max_distance_m=50.0, curr_road_info=road_info)
        self.assertTrue(res_app["has_chained_junction"])
        self.assertIn("北新路182巷", res_app["concise_approaching_prompt"])
        self.assertIn("前續 北新路184巷", res_app["concise_approaching_prompt"])

        # 2. 跨過第 1 條巷子：即時報讀通過第 1 條並預告第 2 條剩餘距離
        user_lat_pass = j1_lat - 0.000030 # ~3m from j1
        res_pass = analyzer.analyze(user_lat_pass, user_lon, 0.0, wm_chain, max_distance_m=50.0, curr_road_info=road_info)
        self.assertTrue(res_pass["has_chained_junction"])
        self.assertIn("通過【北新路182巷】", res_pass["concise_passing_prompt"])
        self.assertIn("【北新路184巷】", res_pass["concise_passing_prompt"])

    def test_chained_junctions_opposite_sides(self):
        """【測試：左右錯開連續巷弄接力播報 (Chained Junctions - Opposite Sides)】"""
        analyzer = IntersectionAnalyzer()
        wm_chain = MockWorldModel()
        j1_lat, j1_lon = 25.179900, 121.451200
        j2_lat, j2_lon = 25.179936, 121.451200 # 4m ahead

        wm_chain.road_graph.add_node(1, lat=j1_lat, lon=j1_lon)
        wm_chain.road_graph.add_node(2, lat=j2_lat, lon=j2_lon)
        wm_chain.road_graph.add_node(10, lat=j1_lat, lon=j1_lon - 0.0005) # 182巷 (West, Left)
        wm_chain.road_graph.add_node(20, lat=j2_lat, lon=j2_lon + 0.0005) # 184巷 (East, Right)
        wm_chain.road_graph.add_node(30, lat=j1_lat - 0.0005, lon=j1_lon) # South
        wm_chain.road_graph.add_node(40, lat=j2_lat + 0.0005, lon=j2_lon) # North

        wm_chain.road_graph.add_edge(1, 10, key=0, name="北新路182巷")
        wm_chain.road_graph.add_edge(1, 30, key=0, name="北新路一段")
        wm_chain.road_graph.add_edge(1, 2, key=0, name="北新路一段")
        wm_chain.road_graph.add_edge(2, 20, key=0, name="北新路184巷")
        wm_chain.road_graph.add_edge(2, 40, key=0, name="北新路一段")

        wm_chain.junction_rtree.insert(1, (j1_lon, j1_lat, j1_lon, j1_lat), obj=(1, 3, j1_lat, j1_lon, {}))
        wm_chain.junction_rtree.insert(2, (j2_lon, j2_lat, j2_lon, j2_lat), obj=(2, 3, j2_lat, j2_lon, {}))

        user_lat = j1_lat - 0.000108
        user_lon = j1_lon
        road_info = {"street_name": "北新路一段"}

        res_app = analyzer.analyze(user_lat, user_lon, 0.0, wm_chain, max_distance_m=50.0, curr_road_info=road_info)
        self.assertTrue(res_app["has_chained_junction"])
        self.assertIn("左", res_app["concise_approaching_prompt"])
        self.assertIn("右", res_app["concise_approaching_prompt"])

        user_lat_pass = j1_lat - 0.000030
        res_pass = analyzer.analyze(user_lat_pass, user_lon, 0.0, wm_chain, max_distance_m=50.0, curr_road_info=road_info)
        self.assertIn("通過【北新路182巷】", res_pass["concise_passing_prompt"])
        self.assertIn("【北新路184巷】", res_pass["concise_passing_prompt"])

    def test_taiwan_signals_database_integration(self):
        """【測試：全台灣號誌資料庫 (taiwan_signals.db) 整合檢索】"""
        from nmap.spatial.taiwan_signals import TaiwanSignalManager
        mgr = TaiwanSignalManager()
        self.assertIsNotNone(mgr._db_conn, "taiwan_signals.db should be connected")

        # 1. 查詢淡水北新路169巷口號誌
        sig_beixin = mgr.find_signal_near(25.17933, 121.45022, max_dist_m=35.0)
        self.assertIsNotNone(sig_beixin)
        self.assertTrue(sig_beixin["is_signalized"])

        # 2. 查詢板橋車站特區官方 APS 示範號誌
        sig_banciao = mgr.find_signal_near(25.01320, 121.46350, max_dist_m=25.0)
        self.assertIsNotNone(sig_banciao)
        self.assertTrue(sig_banciao["has_aps"])
        self.assertIn("縣民大道", sig_banciao["intersection_name"])

    def test_road_snapping_perpendicular_alley_rejection(self):
        """【測試：防小巷側吸 - 主幹道行走時拒絕垂直橫向小巷】"""
        from nmap.spatial.world_model import WorldModel
        wm = WorldModel()

        # 建立北新路一段 (南北向，走向約 0° / 180°)
        road_main = {
            "name": "北新路一段",
            "type": "secondary",
            "geometry": [(25.1780, 121.4500), (25.1820, 121.4500)]
        }
        # 建立 169 巷 (東西向，走向 90° / 270°)
        road_alley = {
            "name": "北新路169巷",
            "type": "residential",
            "geometry": [(25.1793, 121.4500), (25.1793, 121.4530)]
        }

        wm.roads = [road_main, road_alley]
        wm.road_rtree.insert(1, (121.449, 25.177, 121.451, 25.183), obj=road_main)
        wm.road_rtree.insert(2, (121.449, 25.179, 121.454, 25.180), obj=road_alley)

        # 行人走在北新路人行道上：緯度 25.17933，經度 121.45006
        # 距離北新路中心線約 6.5 米；距離 169 巷中心線約 4.0 米（幾何上更靠近小巷）
        # 行人前進朝向 180°（往南，沿北新路直走）
        p_lat = 25.179336
        p_lon = 121.450065

        # 帶入前進朝向與當前道路，應優先選中北新路一段，杜絕被 169 巷側吸
        best_r, dist = wm.find_nearest_road(p_lat, p_lon, user_heading=180.0, current_road_name="北新路一段")
        self.assertIsNotNone(best_r)
        self.assertEqual(best_r["name"], "北新路一段", f"Expected 北新路一段, but got {best_r['name']}")

    def test_omnidirectional_surrounding_junctions(self):
        """【測試：周遭 360 度四向象限路口探測 (Omnidirectional 4-Sector Junction Scan)】"""
        wm = MockWorldModel()
        # 建立十字與三向路網拓撲圖
        # 使用者位於 (25.1800, 121.4500)，朝向正北 0°
        # 1. 正前方路口：(25.1810, 121.4500)
        wm.road_graph.add_node("node_f", lat=25.1810, lon=121.4500)
        wm.road_graph.add_node("f_n", lat=25.1820, lon=121.4500)
        wm.road_graph.add_node("f_e", lat=25.1810, lon=121.4510)
        wm.road_graph.add_node("f_s", lat=25.1800, lon=121.4500)
        wm.road_graph.add_edge("node_f", "f_n", name="北新路一段")
        wm.road_graph.add_edge("node_f", "f_e", name="大忠街")
        wm.road_graph.add_edge("node_f", "f_s", name="北新路一段")
        wm.junction_rtree.insert(1, (121.449, 25.180, 121.451, 25.182), obj=("node_f", 3, 25.1810, 121.4500, {}))

        # 2. 右側路口：(25.1800, 121.4510)
        wm.road_graph.add_node("node_r", lat=25.1800, lon=121.4510)
        wm.road_graph.add_node("r_n", lat=25.1810, lon=121.4510)
        wm.road_graph.add_node("r_e", lat=25.1800, lon=121.4520)
        wm.road_graph.add_node("r_w", lat=25.1800, lon=121.4500)
        wm.road_graph.add_edge("node_r", "r_n", name="水源街一段")
        wm.road_graph.add_edge("node_r", "r_e", name="水源街二段")
        wm.road_graph.add_edge("node_r", "r_w", name="水源街一段")
        wm.junction_rtree.insert(2, (121.450, 25.179, 121.452, 25.181), obj=("node_r", 3, 25.1800, 121.4510, {}))

        # 3. 左側路口：(25.1800, 121.4490)
        wm.road_graph.add_node("node_l", lat=25.1800, lon=121.4490)
        wm.road_graph.add_node("l_n", lat=25.1810, lon=121.4490)
        wm.road_graph.add_node("l_w", lat=25.1800, lon=121.4480)
        wm.road_graph.add_node("l_e", lat=25.1800, lon=121.4500)
        wm.road_graph.add_edge("node_l", "l_n", name="中正東路")
        wm.road_graph.add_edge("node_l", "l_w", name="博愛街")
        wm.road_graph.add_edge("node_l", "l_e", name="中正東路")
        wm.junction_rtree.insert(3, (121.448, 25.179, 121.450, 25.181), obj=("node_l", 3, 25.1800, 121.4490, {}))

        # 4. 後方路口：(25.1790, 121.4500)
        wm.road_graph.add_node("node_b", lat=25.1790, lon=121.4500)
        wm.road_graph.add_node("b_s", lat=25.1780, lon=121.4500)
        wm.road_graph.add_node("b_e", lat=25.1790, lon=121.4510)
        wm.road_graph.add_node("b_n", lat=25.1800, lon=121.4500)
        wm.road_graph.add_edge("node_b", "b_s", name="北新路一段")
        wm.road_graph.add_edge("node_b", "b_e", name="新春街")
        wm.road_graph.add_edge("node_b", "b_n", name="北新路一段")
        wm.junction_rtree.insert(4, (121.449, 25.178, 121.451, 25.180), obj=("node_b", 3, 25.1790, 121.4500, {}))

        analyzer = IntersectionAnalyzer()
        surrounding = analyzer.analyze_surrounding_junctions(25.1800, 121.4500, 0.0, wm)
        
        self.assertTrue(surrounding["found_any"])
        sectors = surrounding["sectors"]
        self.assertIsNotNone(sectors["front"])
        self.assertIsNotNone(sectors["right"])
        self.assertIsNotNone(sectors["left"])
        self.assertIsNotNone(sectors["back"])

        self.assertIn("正前方", surrounding["report"])
        self.assertIn("右側", surrounding["report"])
        self.assertIn("左側", surrounding["report"])
        self.assertIn("後方", surrounding["report"])

        # 驗證前方分析 analyze() 也整合了周遭四向路口資訊
        analysis = analyzer.analyze(25.1800, 121.4500, 0.0, wm)
        self.assertIn("surrounding_junctions", analysis)
        self.assertIsNotNone(analysis["surrounding_junctions"])

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestConciseNavigation)
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)

