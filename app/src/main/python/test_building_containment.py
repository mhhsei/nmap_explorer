# -*- coding: utf-8 -*-
"""
單元測試：建築物多邊形判定與進出狀態機 (test_building_containment.py)

針對 NMap Explorer 的純 Python 幾何多邊形包含演算 (is_point_in_polygon)、
WorldModel 建築物空間檢索 (get_containing_building) 以及
視障語音報讀器 (NVDAReporter) 進行完整閉環驗證。
"""

import unittest
import sys
import os

# 加入 nmap 模組路徑
sys.path.insert(0, os.path.dirname(__file__))

from nmap.spatial.pure_geometry import is_point_in_polygon
from nmap.spatial.world_model import WorldModel
from nmap.accessibility.reporter import NVDAReporter
from nmap.spatial.grid_index import GridSpatialIndex


class MockStreetSceneEngine:
    def analyze_scene(self, lat, lon, heading, wm, road_info=None):
        return {"full_description": "街景平整", "scene_summary": "街景"}


class MockAgent:
    """模擬導航 Agent 用於測試報讀器"""
    def __init__(self, lat=25.0335, lon=121.5645, heading=0.0, world_model=None):
        self.lat = lat
        self.lon = lon
        self.heading_deg = heading
        self.is_loaded = True
        self.world_model = world_model or WorldModel()
        from nmap.spatial.intersection import IntersectionAnalyzer
        self.intersection_analyzer = IntersectionAnalyzer()
        self.street_scene_engine = MockStreetSceneEngine()
        self.location_label = "人行步道"

    def get_navigation_status(self):
        return ""



class TestPointInPolygon(unittest.TestCase):
    """測試純 Python 奇偶射線法多邊形包含演算"""

    def setUp(self):
        # 定義一個標準矩形多邊形（緯度 25.0330~25.0340, 經度 121.5640~121.5650）
        self.rect_poly = [
            (25.0330, 121.5640),
            (25.0340, 121.5640),
            (25.0340, 121.5650),
            (25.0330, 121.5650),
            (25.0330, 121.5640),  # 首尾閉合
        ]

        # 定義一個 L 型凹多邊形
        # (0,0) -> (0,2) -> (1,2) -> (1,1) -> (2,1) -> (2,0) -> (0,0)
        self.l_poly = [
            (25.0, 121.0),
            (25.0, 121.2),
            (25.1, 121.2),
            (25.1, 121.1),
            (25.2, 121.1),
            (25.2, 121.0),
            (25.0, 121.0),
        ]

    def test_rect_inside(self):
        """測試矩形正中心點"""
        inside_pt = (25.0335, 121.5645)
        self.assertTrue(is_point_in_polygon(inside_pt[0], inside_pt[1], self.rect_poly))

    def test_rect_outside_far(self):
        """測試矩形外遠處點（觸發 BBox 快速拒絕）"""
        outside_pt = (25.0500, 121.5800)
        self.assertFalse(is_point_in_polygon(outside_pt[0], outside_pt[1], self.rect_poly))

    def test_rect_outside_near(self):
        """測試矩形外附近點"""
        outside_pt = (25.0345, 121.5645)
        self.assertFalse(is_point_in_polygon(outside_pt[0], outside_pt[1], self.rect_poly))

    def test_concave_l_shape(self):
        """測試 L 型凹多邊形：凹缺處雖在 BBox 內，但幾何上在建物外面"""
        # 凹缺處座標 (25.15, 121.15) 在外接矩形內，但不在 L 型內
        notch_pt = (25.15, 121.15)
        self.assertFalse(is_point_in_polygon(notch_pt[0], notch_pt[1], self.l_poly))

        # 翼部內部點 A (25.05, 121.15) 在第一段翼內
        wing_pt_a = (25.05, 121.15)
        self.assertTrue(is_point_in_polygon(wing_pt_a[0], wing_pt_a[1], self.l_poly))

        # 翼部內部點 B (25.15, 121.05) 在第二段翼內
        wing_pt_b = (25.15, 121.05)
        self.assertTrue(is_point_in_polygon(wing_pt_b[0], wing_pt_b[1], self.l_poly))

    def test_invalid_polygons(self):
        """測試異常頂點數量（少於 3 點）"""
        self.assertFalse(is_point_in_polygon(25.0, 121.0, []))
        self.assertFalse(is_point_in_polygon(25.0, 121.0, [(25.0, 121.0)]))
        self.assertFalse(is_point_in_polygon(25.0, 121.0, [(25.0, 121.0), (25.1, 121.1)]))


class TestWorldModelBuildingContainment(unittest.TestCase):
    """測試 WorldModel.get_containing_building 建築物包含檢索"""

    def setUp(self):
        self.wm = WorldModel()
        # 清空並自定義 building_rtree 用於確定性測試
        self.wm.building_rtree = GridSpatialIndex(cell_size_deg=0.005)

        # 注入一棟知名大樓「台北 101 大樓」
        self.poly_101 = [
            (25.0330, 121.5640),
            (25.0345, 121.5640),
            (25.0345, 121.5655),
            (25.0330, 121.5655),
            (25.0330, 121.5640),
        ]
        self.bldg_101 = {
            "id": "bldg_101",
            "name": "台北 101 大樓",
            "building": "commercial",
            "levels": 101,
            "geometry": self.poly_101,
            "lat": 25.03375,
            "lon": 121.56475,
        }
        self.wm.building_rtree.insert(
            1,
            (121.5640, 25.0330, 121.5655, 25.0345),
            self.bldg_101
        )

        # 注入一棟無名但有門牌的建築「信義路五段7號」
        self.poly_addr = [
            (25.0350, 121.5640),
            (25.0355, 121.5640),
            (25.0355, 121.5645),
            (25.0350, 121.5645),
            (25.0350, 121.5640),
        ]
        self.bldg_addr = {
            "id": "bldg_addr",
            "name": "",
            "tags": {
                "addr:street": "信義路五段",
                "addr:housenumber": "7號",
                "building": "yes",
                "building:levels": "5",
            },
            "geometry": self.poly_addr,
            "lat": 25.03525,
            "lon": 121.56425,
        }
        self.wm.building_rtree.insert(
            2,
            (121.5640, 25.0350, 121.5645, 25.0355),
            self.bldg_addr
        )

        self.wm.buildings = [self.bldg_101, self.bldg_addr]

    def test_inside_known_building(self):
        """使用者走進台北 101"""
        res = self.wm.get_containing_building(25.0337, 121.5647)
        self.assertIsNotNone(res)
        self.assertEqual(res["name"], "台北 101 大樓")
        self.assertEqual(res["levels"], 101)

    def test_inside_address_building(self):
        """使用者走進無名但有門牌的建築"""
        res = self.wm.get_containing_building(25.0352, 121.5642)
        self.assertIsNotNone(res)
        self.assertIn("信義路五段7號", res["name"])
        self.assertEqual(res["levels"], "5")

    def test_outside_on_street(self):
        """使用者走在馬路上，不在任何建築物內"""
        res = self.wm.get_containing_building(25.0348, 121.5642)
        self.assertIsNone(res)


class TestReporterBuildingSpeech(unittest.TestCase):
    """測試 NVDAReporter 建築物進出語音報讀邏輯"""

    def setUp(self):
        self.reporter = NVDAReporter()
        self.agent = MockAgent()

    def test_building_entry_and_exit_announcement(self):
        """驗證進入建築、建築內移動（不跳針）、走出建築之語音流程"""
        bldg_101 = {
            "id": "bldg_101",
            "name": "台北 101 大樓",
            "levels": 101,
            "building_type": "commercial"
        }
        road_xinyi = {"street_name": "信義路五段"}

        # 1. 使用者走進台北 101
        report_enter = self.reporter.generate_concise_report(
            self.agent,
            road_info=road_xinyi,
            pois=[],
            current_building=bldg_101
        )
        self.assertIn("進入【台北 101 大樓】", report_enter)

        # 2. 使用者在 101 內部走動，不應重複報讀「進入」
        report_stay = self.reporter.generate_concise_report(
            self.agent,
            road_info=road_xinyi,
            pois=[],
            current_building=bldg_101
        )
        self.assertNotIn("進入【台北 101 大樓】", report_stay)

        # 3. 使用者走出 101 回到信義路五段
        report_exit = self.reporter.generate_concise_report(
            self.agent,
            road_info=road_xinyi,
            pois=[],
            current_building=None
        )
        self.assertIn("走出【台北 101 大樓】", report_exit)
        self.assertIn("回到【信義路五段】", report_exit)

    def test_full_report_current_location_building(self):
        """驗證【目前位置】在建築內與室外/騎樓的精確區分"""
        bldg_101 = {
            "id": "bldg_101",
            "name": "台北 101 大樓",
            "levels": 101,
            "building_type": "commercial"
        }
        road_walkway = {"street_name": "人行步道"}

        # 情況 A：人在建築物內（點擊目前位置）
        full_report_inside = self.reporter.generate_full_report(
            self.agent,
            road_info=road_walkway,
            current_building=bldg_101,
            floor="1F"
        )
        self.assertIn("【目前位置】在【台北 101 大樓】(1F) 內，鄰近【人行步道】", full_report_inside)

        # 情況 B：人在室外人行步道或騎樓（current_building 為 None）
        full_report_outside = self.reporter.generate_full_report(
            self.agent,
            road_info=road_walkway,
            current_building=None,
            floor="1F"
        )
        # 室外或騎樓時不受影響，維持原有位置標籤
        self.assertIn(f"【目前位置】{self.agent.location_label}", full_report_outside)
        self.assertNotIn("在【台北 101 大樓】", full_report_outside)


if __name__ == "__main__":
    unittest.main()

