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

    def get_sidewalk_hazards(self, lat, lon, heading_deg, max_dist_m=8.0):
        return []

    def get_mrt_accessible_exits(self, lat, lon, heading_deg, radius_m=80.0):
        return []

    def get_signal_safety(self, lat, lon, heading_deg, radius_m=28.0):
        return None

class MockAgent:
    def __init__(self, lat, lon, heading_deg, world_model):
        self.is_loaded = True
        self.lat = lat
        self.lon = lon
        self.heading_deg = heading_deg
        self.world_model = world_model
        self.intersection_analyzer = IntersectionAnalyzer()

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

        agent = MockAgent(25.170000, 121.450000, 0.0, wm_cluster)
        report = reporter.generate_concise_report(agent)
        # Should cluster into: 2點鐘方向 9米：全家便利商店 (205號)、康是美 (207號)
        self.assertIn("全家便利商店 (205號)", report)
        self.assertIn("康是美 (207號)", report)
        self.assertIn("2點鐘方向", report)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestConciseNavigation)
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)

