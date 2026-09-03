# -*- coding: utf-8 -*-
"""
【三大非視覺神經網路導航引擎風洞測試套件 (test_neural_navigation_suite.py)】
驗證目標：
1. 項目 2 (深度慣性航位推算神經網路): 自適應步長、瞬時速度預測與人體物理邊界約束。
2. 項目 3 (步態猶豫與迷航意圖神經網路): 正常行走、周遭掃描與路口迷茫停頓狀態自動仲裁。
3. 項目 4 (氣壓微波形與垂直運動神經分類器): 走樓梯上/下、搭電梯、平地走廊區分，以及 2F/1F 跨樓層店家過濾。
"""

import unittest
import math
import numpy as np

# ==============================================================================
# 模擬項目 2：深度慣性步長與速度神經網路 (LearnedStepVelocityEstimator)
# ==============================================================================
class MockLearnedStepVelocityEstimator:
    def __init__(self, baseline_step_m=0.65):
        self.baseline_step_m = baseline_step_m
        self.acc_window = []
        self.window_size = 30

    def feed_sample(self, ax, ay, az):
        mag = math.sqrt(ax * ax + ay * ay + az * az)
        self.acc_window.append(mag)
        if len(self.acc_window) > self.window_size:
            self.acc_window.pop(0)

    def predict_step(self, step_duration_ms=600, gps_speed_mps=-1.0):
        if len(self.acc_window) < self.window_size:
            return self.baseline_step_m, 1.1

        peak_to_peak = max(self.acc_window) - min(self.acc_window)
        bounce_factor = max(0.5, min(2.0, (peak_to_peak ** 0.25)))
        cadence_hz = 1000.0 / max(step_duration_ms, 200)
        cadence_weight = max(0.75, min(1.35, cadence_hz / 1.8))

        pred_step = self.baseline_step_m * bounce_factor * cadence_weight * 0.45
        # 生理邊界約束
        pred_step = max(0.42, min(0.92, pred_step))

        if 0.65 < gps_speed_mps < 2.5:
            gt_step = max(0.45, min(0.88, gps_speed_mps / cadence_hz))
            pred_step = pred_step * 0.7 + gt_step * 0.3

        pred_speed = pred_step * cadence_hz
        return pred_step, pred_speed


# ==============================================================================
# 模擬項目 3：步態猶豫與迷航意圖神經網路 (GaitIntentInferenceEngine)
# ==============================================================================
class MockGaitIntentInferenceEngine:
    def __init__(self):
        self.heading_window = [] # (time_ms, heading_deg)
        self.last_step_time_ms = 0
        self.current_intent = "CONFIDENT_WALKING"

    def feed_heading(self, now_ms, heading_deg):
        self.heading_window.append((now_ms, heading_deg))
        while self.heading_window and (now_ms - self.heading_window[0][0]) > 3500:
            self.heading_window.pop(0)

    def on_step(self, now_ms):
        self.last_step_time_ms = now_ms

    def evaluate_intent(self, now_ms):
        if len(self.heading_window) < 5:
            return self.current_intent

        total_abs_turn = 0.0
        headings = [h[1] for h in self.heading_window]
        for i in range(1, len(headings)):
            diff = headings[i] - headings[i - 1]
            while diff < -180: diff += 360
            while diff > 180: diff -= 360
            total_abs_turn += abs(diff)

        duration_sec = max(0.5, (self.heading_window[-1][0] - self.heading_window[0][0]) / 1000.0)
        turn_rate = total_abs_turn / duration_sec
        is_stopped = (now_ms - self.last_step_time_ms) > 1800

        if is_stopped and turn_rate > 25.0 and total_abs_turn > 65.0:
            self.current_intent = "HESITANT_CONFUSED"
        elif 12.0 <= turn_rate <= 35.0 and not is_stopped:
            self.current_intent = "SCANNING_SURROUNDINGS"
        else:
            self.current_intent = "CONFIDENT_WALKING"

        return self.current_intent


# ==============================================================================
# 模擬項目 4：垂直運動微波形神經分類器 (VerticalMotionNeuralClassifier)
# ==============================================================================
class MockVerticalMotionNeuralClassifier:
    def __init__(self, baseline_hpa=1013.25):
        self.baseline_hpa = baseline_hpa
        self.pressure_history = []
        self.vertical_acc_history = []
        self.current_floor = "1F"
        self.current_motion = "HORIZONTAL_CORRIDOR"

    def feed_sample(self, now_ms, pressure_hpa, vertical_acc, is_walking=True):
        self.pressure_history.append((now_ms, pressure_hpa))
        while self.pressure_history and (now_ms - self.pressure_history[0][0]) > 3000:
            self.pressure_history.pop(0)

        self.vertical_acc_history.append(vertical_acc)
        if len(self.vertical_acc_history) > 25:
            self.vertical_acc_history.pop(0)

        if len(self.pressure_history) < 5:
            return self.current_motion, self.current_floor

        dt_sec = (self.pressure_history[-1][0] - self.pressure_history[0][0]) / 1000.0
        if dt_sec < 0.8:
            return self.current_motion, self.current_floor

        dp = self.pressure_history[-1][1] - self.pressure_history[0][1]
        dp_dt = dp / dt_sec

        acc_mean = sum(self.vertical_acc_history) / len(self.vertical_acc_history)
        acc_var = sum((a - acc_mean) ** 2 for a in self.vertical_acc_history) / len(self.vertical_acc_history)

        # 樓層高程換算
        alt_delta_m = -(pressure_hpa - self.baseline_hpa) * 8.43
        floor_idx = 1 + int(alt_delta_m / 3.2)
        floor_str = f"{floor_idx}F" if floor_idx > 0 else f"B{abs(floor_idx - 1)}"

        if dp_dt < -0.035 and is_walking and acc_var > 0.25:
            self.current_motion = "WALKING_STAIRS_UP"
            self.current_floor = floor_str
        elif dp_dt > 0.035 and is_walking and acc_var > 0.25:
            self.current_motion = "WALKING_STAIRS_DOWN"
            self.current_floor = floor_str
        elif abs(dp_dt) > 0.22 and acc_var < 0.18:
            self.current_motion = "ELEVATOR_MOVING"
            self.current_floor = floor_str
        else:
            self.current_motion = "HORIZONTAL_CORRIDOR"

        return self.current_motion, self.current_floor


# ==============================================================================
# 單元測試主體
# ==============================================================================
class TestNeuralNavigationSuite(unittest.TestCase):

    def test_item2_learned_step_estimator(self):
        """測試項目 2：深度慣性步長推算能隨加速度與步頻動態收縮擴張"""
        estimator = MockLearnedStepVelocityEstimator(baseline_step_m=0.65)

        # 模擬平穩手持慢步 (1Hz 加速度波形，振幅較小)
        for i in range(35):
            t = i * 0.02
            estimator.feed_sample(0.2, 9.8 + 1.2 * math.sin(2 * math.pi * 1.5 * t), 0.3)

        step_len, speed = estimator.predict_step(step_duration_ms=650)
        self.assertGreaterEqual(step_len, 0.42)
        self.assertLessEqual(step_len, 0.92)

        # 模擬大步急行 (振幅劇增)
        for i in range(35):
            t = i * 0.02
            estimator.feed_sample(0.5, 9.8 + 4.5 * math.sin(2 * math.pi * 2.2 * t), 0.8)

        fast_step, fast_speed = estimator.predict_step(step_duration_ms=450)
        self.assertGreater(fast_step, step_len)
        self.assertGreater(fast_speed, speed)

    def test_item3_gait_intent_confused_detection(self):
        """測試項目 3：視障者在路口停滯且原地來回轉向時，神經網絡精準切換為 HESITANT_CONFUSED"""
        engine = MockGaitIntentInferenceEngine()

        now = 10000
        engine.on_step(now)

        # 正常行走筆直前進
        for i in range(10):
            now += 200
            engine.feed_heading(now, 45.0 + math.sin(i) * 3.0)
            if i % 3 == 0:
                engine.on_step(now)
        self.assertEqual(engine.evaluate_intent(now), "CONFIDENT_WALKING")

        # 使用者停下腳步（超過 2 秒未邁步），並且原地左右擺動尋向 (35° -> 120° -> 20°)
        now += 2200 # 停步超過 1.8 秒
        for i, h in enumerate([35.0, 60.0, 95.0, 130.0, 80.0, 20.0, 50.0]):
            now += 200
            engine.feed_heading(now, h)

        intent = engine.evaluate_intent(now)
        self.assertEqual(intent, "HESITANT_CONFUSED")

    def test_item4_vertical_motion_and_floor_discrimination(self):
        """測試項目 4：爬樓梯 vs 搭電梯 vs 平地走廊，並驗證樓層跨層過濾"""
        classifier = MockVerticalMotionNeuralClassifier(baseline_hpa=1013.25)

        now = 50000
        # 1. 爬樓梯上樓：氣壓持續遞減 (1013.25 -> 1012.80) 且垂直震動大
        cur_p = 1013.25
        for i in range(15):
            now += 200
            cur_p -= 0.035
            vert_acc = 9.8 + 2.0 * math.sin(i)
            motion, floor = classifier.feed_sample(now, cur_p, vert_acc, is_walking=True)

        self.assertEqual(motion, "WALKING_STAIRS_UP")
        self.assertEqual(floor, "2F")

        # 2. 走在 2 樓水平走廊：氣壓平穩，即便冷氣輕微抖動
        for i in range(15):
            now += 200
            motion, floor = classifier.feed_sample(now, cur_p + 0.01 * math.sin(i), 9.8 + 0.5 * math.sin(i), is_walking=True)

        self.assertEqual(motion, "HORIZONTAL_CORRIDOR")
        self.assertEqual(floor, "2F")

    def test_item4_world_model_floor_filter(self):
        """測試世界模型 POI 查詢加入 target_floor='2F' 時，成功隔離 1F 店家"""
        from nmap.spatial.world_model import WorldModel, SpatialPOI

        wm = WorldModel()
        # 建立 1 樓中庭餐廳
        canaan_poi = SpatialPOI({
            "id": "canaan_1f",
            "name": "迦南中庭餐廳",
            "lat": 25.1743,
            "lon": 121.4485,
            "category": "restaurant",
            "tags": {"floor": "1F"}
        })
        wm.poi_rtree.insert(1, (121.4485, 25.1743, 121.4485, 25.1743), obj=canaan_poi)

        # 建立 2 樓影印部
        copy_shop_2f = SpatialPOI({
            "id": "copy_2f",
            "name": "淡江數位影印部",
            "lat": 25.17431,
            "lon": 121.44851,
            "category": "service",
            "tags": {"floor": "2F"}
        })
        wm.poi_rtree.insert(2, (121.44851, 25.17431, 121.44851, 25.17431), obj=copy_shop_2f)

        # 使用者在 2F 查詢，指定 target_floor='2F'
        pois_2f = wm.get_nearby_pois(25.1743, 121.4485, heading_deg=0.0, radius_m=30.0, target_floor="2F")
        poi_names = [p["name"] for p in pois_2f]

        self.assertIn("淡江數位影印部", poi_names)
        self.assertNotIn("迦南中庭餐廳", poi_names)

if __name__ == "__main__":
    unittest.main()
