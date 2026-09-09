import sys
import os

# 將 python 後端路徑加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/src/main/python")))

from nmap.spatial.world_model import WorldModel
from nmap.data.overpass import OverpassClient


def test_physical_building_containment():
    """驗證 Layer 1：實體建築物多邊形判定 (Point-in-Building)"""
    wm = WorldModel()
    # 建立一棟 20m x 20m 的大樓 (驚聲紀念大樓)
    bldg_geom = [
        (25.17500, 121.45000),
        (25.17520, 121.45000),
        (25.17520, 121.45020),
        (25.17500, 121.45020),
        (25.17500, 121.45000)
    ]
    parsed_data = {
        "buildings": [{
            "id": 101,
            "name": "驚聲紀念大樓",
            "building_type": "university",
            "levels": "10",
            "height": "35",
            "center_lat": 25.17510,
            "center_lon": 121.45010,
            "geometry": bldg_geom,
            "tags": {"building": "university", "name": "驚聲紀念大樓"}
        }],
        "enclosing_areas": [],
        "house_numbers": [],
        "roads": []
    }
    wm.build_from_osm(parsed_data)

    # 1. 位於大樓內部中心點
    ctx_inside = wm.get_spatial_context(25.17510, 121.45010)
    assert ctx_inside["is_inside"] is True
    assert ctx_inside["context_type"] == "building"
    assert ctx_inside["name"] == "驚聲紀念大樓"
    assert "驚聲紀念大樓" in ctx_inside["full_label"]

    containing_bldg = wm.get_containing_building(25.17510, 121.45010)
    assert containing_bldg is not None
    assert containing_bldg["name"] == "驚聲紀念大樓"

    # 2. 位於大樓外部 (北方 50m)
    ctx_outside = wm.get_spatial_context(25.17570, 121.45010)
    assert ctx_outside["is_inside"] is False
    assert ctx_outside["context_type"] == "outdoor"
    assert wm.get_containing_building(25.17570, 121.45010) is None


def test_campus_enclosing_area_containment():
    """驗證 Layer 2：大學校園封閉場域判定 (Campus Containment)"""
    wm = WorldModel()
    campus_geom = [
        (25.17000, 121.44000),
        (25.18000, 121.44000),
        (25.18000, 121.46000),
        (25.17000, 121.46000),
        (25.17000, 121.44000)
    ]
    parsed_data = {
        "buildings": [],
        "enclosing_areas": [{
            "id": 201,
            "name": "淡江大學",
            "area_type": "campus",
            "sub_type": "校園",
            "center_lat": 25.17500,
            "center_lon": 121.45000,
            "geometry": campus_geom,
            "tags": {"amenity": "university", "name": "淡江大學"}
        }],
        "house_numbers": [],
        "roads": [{
            "id": 301,
            "name": "人行步道",
            "highway_type": "footway",
            "geometry": [(25.17400, 121.45100), (25.17600, 121.45100)]
        }]
    }
    wm.build_from_osm(parsed_data)

    # 位於校園走廊內部
    ctx = wm.get_spatial_context(25.17500, 121.45100)
    assert ctx["is_inside"] is True
    assert ctx["context_type"] == "campus"
    assert "淡江大學" in ctx["name"]
    assert "淡江大學 校園" in ctx["full_label"]

    # 步道名稱自動辨識為淡江大學校園步道
    step_road_desc = wm._detect_campus_or_park_context(25.17500, 121.45100)
    assert "淡江大學" in step_road_desc or "校園步道" in step_road_desc


def test_park_enclosing_area_containment():
    """驗證 Layer 2：公園綠地場域判定 (Park Containment)"""
    wm = WorldModel()
    park_geom = [
        (25.02500, 121.53000),
        (25.03500, 121.53000),
        (25.03500, 121.54000),
        (25.02500, 121.54000),
        (25.02500, 121.53000)
    ]
    parsed_data = {
        "buildings": [],
        "enclosing_areas": [{
            "id": 401,
            "name": "大安森林公園",
            "area_type": "park",
            "sub_type": "公園",
            "center_lat": 25.03000,
            "center_lon": 121.53500,
            "geometry": park_geom,
            "tags": {"leisure": "park", "name": "大安森林公園"}
        }],
        "house_numbers": [],
        "roads": []
    }
    wm.build_from_osm(parsed_data)

    ctx = wm.get_spatial_context(25.03000, 121.53500)
    assert ctx["is_inside"] is True
    assert ctx["context_type"] == "park"
    assert "大安森林公園" in ctx["name"]
    assert "在【大安森林公園】內" in ctx["full_label"]


def test_residential_community_with_door_number():
    """
    驗證使用者街頭實測情境：
    使用者身處「淡水情歌」社區 (landuse=residential)，且 OSM 無實體 building 外框，
    但有「淡金路二段121號」門牌點。
    系統應精確判定為在「淡水情歌 社區 (淡金路二段121號)」內！
    """
    wm = WorldModel()
    community_geom = [
        (25.18050, 121.45000),
        (25.18150, 121.45000),
        (25.18150, 121.45100),
        (25.18050, 121.45100),
        (25.18050, 121.45000)
    ]
    parsed_data = {
        "buildings": [],
        "enclosing_areas": [{
            "id": 501,
            "name": "淡水情歌",
            "area_type": "residential",
            "sub_type": "社區",
            "center_lat": 25.18100,
            "center_lon": 121.45050,
            "geometry": community_geom,
            "tags": {"landuse": "residential", "name": "淡水情歌"}
        }],
        "house_numbers": [{
            "id": 601,
            "housenumber": "121",
            "street": "淡金路二段",
            "lat": 25.18090,
            "lon": 121.45040,
            "tags": {"addr:housenumber": "121", "addr:street": "淡金路二段"}
        }],
        "roads": [{
            "id": 701,
            "name": "人行步道",
            "highway_type": "footway",
            "geometry": [(25.18080, 121.45030), (25.18110, 121.45050)]
        }]
    }
    wm.build_from_osm(parsed_data)

    user_lat = 25.1809311
    user_lon = 121.4504301

    ctx = wm.get_spatial_context(user_lat, user_lon)
    assert ctx["is_inside"] is True
    assert ctx["context_type"] == "residential"
    assert "淡水情歌" in ctx["name"]
    assert "淡金路二段121號" in ctx["door_anchor"]
    assert "淡水情歌 社區" in ctx["full_label"]
    assert "淡金路二段121號" in ctx["full_label"]

    # 驗證 backward compatible 的 get_containing_building 也回傳社區名稱
    bldg = wm.get_containing_building(user_lat, user_lon)
    assert bldg is not None
    assert "淡水情歌" in bldg["name"]

    # 驗證步道名稱晉級為社區步道
    r_name = wm._detect_campus_or_park_context(user_lat, user_lon)
    assert "淡水情歌社區步道" in r_name


def test_outdoor_street_not_affected():
    """驗證室外道路不受影響 (維持室外狀態)"""
    wm = WorldModel()
    parsed_data = {
        "buildings": [],
        "enclosing_areas": [],
        "house_numbers": [{
            "id": 801,
            "housenumber": "205",
            "street": "民生路",
            "lat": 25.18000,
            "lon": 121.45000,
            "tags": {}
        }],
        "roads": [{
            "id": 901,
            "name": "民生路",
            "highway_type": "residential",
            "geometry": [(25.17900, 121.45000), (25.18200, 121.45000)]
        }]
    }
    wm.build_from_osm(parsed_data)

    # 位於民生路馬路上 (距離門牌 60m 遠)
    ctx = wm.get_spatial_context(25.18060, 121.45000)
    assert ctx["is_inside"] is False
    assert ctx["context_type"] == "outdoor"
    assert wm.get_containing_building(25.18060, 121.45000) is None


def test_overpass_relation_and_way_parsing():
    """驗證 OverpassClient 解析 relation multipolygon 與 way enclosing_areas"""
    client = OverpassClient()
    mock_raw = {
        "elements": [
            {"type": "node", "id": 1, "lat": 25.0, "lon": 121.0, "tags": {}},
            {"type": "node", "id": 2, "lat": 25.01, "lon": 121.0, "tags": {}},
            {"type": "node", "id": 3, "lat": 25.01, "lon": 121.01, "tags": {}},
            {"type": "node", "id": 4, "lat": 25.0, "lon": 121.01, "tags": {}},
            {
                "type": "way",
                "id": 10,
                "nodes": [1, 2, 3, 4, 1],
                "tags": {"amenity": "school", "name": "淡水國小"}
            },
            {
                "type": "relation",
                "id": 20,
                "members": [{"type": "way", "ref": 10, "role": "outer"}],
                "tags": {"leisure": "park", "name": "淡水紀念公園"}
            }
        ]
    }
    parsed = client.parse_elements(mock_raw, 25.005, 121.005)
    areas = parsed.get("enclosing_areas", [])
    area_names = [a["name"] for a in areas]
    assert "淡水國小" in area_names
    assert "淡水紀念公園" in area_names


if __name__ == "__main__":
    print("Running Spatial Hierarchy Tests...")
    test_physical_building_containment()
    print("PASS: test_physical_building_containment")
    test_campus_enclosing_area_containment()
    print("PASS: test_campus_enclosing_area_containment")
    test_park_enclosing_area_containment()
    print("PASS: test_park_enclosing_area_containment")
    test_residential_community_with_door_number()
    print("PASS: test_residential_community_with_door_number")
    test_outdoor_street_not_affected()
    print("PASS: test_outdoor_street_not_affected")
    test_overpass_relation_and_way_parsing()
    print("PASS: test_overpass_relation_and_way_parsing")
    print("\nALL 6 TESTS PASSED SUCCESSFULLY! (100% PASS)")

