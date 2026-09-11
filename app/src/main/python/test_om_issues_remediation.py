import unittest
import os

class TestOMIssuesRemediation(unittest.TestCase):
    def setUp(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        app_js_path = os.path.join(base_dir, "web", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            self.js_content = f.read()

        barometer_kt_path = os.path.join(base_dir, "..", "java", "com", "example", "nmapexplorer", "BarometerVerticalFilter.kt")
        with open(barometer_kt_path, "r", encoding="utf-8") as f:
            self.kt_content = f.read()

    def test_p1_junction_crossing_poi_suppression(self):
        """P1: Junction crossing POI suppression during critical listening phase"""
        self.assertIn("isCrossingCriticalListeningPhase", self.js_content)
        self.assertIn("!isCrossingCriticalListeningPhase", self.js_content)
        self.assertIn('this.currentJunctionState === "APPROACHING" || this.currentJunctionState === "PASSING"', self.js_content)

    def test_p2_destination_only_arrival(self):
        """P2: Destination only arrival notification to prevent casual shop spamming"""
        self.assertIn("isNavTarget", self.js_content)
        self.assertIn("p.distance_m <= 3.8 && isNavTarget(p)", self.js_content)

    def test_p3_road_hysteresis_and_footway_penalty(self):
        """P3: Road hysteresis buffer and footway side-suction penalty"""
        self.assertIn("isGenericPath", self.js_content)
        self.assertIn("consecutiveRoadCount >= requiredCount", self.js_content)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        wm_path = os.path.join(base_dir, "nmap", "spatial", "world_model.py")
        with open(wm_path, "r", encoding="utf-8") as f:
            wm_content = f.read()
        self.assertIn("cost *= 1.85", wm_content)
        self.assertIn("cost *= 0.50", wm_content)

    def test_p4_crossing_junction_road_freeze(self):
        """P4: Freeze road transition announcements while passing across an alley mouth"""
        self.assertIn("isJunctionCrossingActive", self.js_content)
        self.assertIn("!isJunctionCrossingActive && data.road_info", self.js_content)

    def test_p5_indoor_b1_barometer_drift_defense(self):
        """P5: Indoor B1 barometer drift defense with higher threshold and duration"""
        self.assertIn("altM <= -3.6f -> VerticalLevel.INDOOR_B1", self.kt_content)
        self.assertIn("altM >= 3.2f -> VerticalLevel.INDOOR_2F", self.kt_content)
        self.assertIn("rawTargetLevel == VerticalLevel.INDOOR_B1", self.kt_content)
        self.assertIn("6000L", self.kt_content)

if __name__ == "__main__":
    unittest.main()
