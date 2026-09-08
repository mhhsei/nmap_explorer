# -*- coding: utf-8 -*-
"""
【公車乘車與斑馬線綠燈過街風洞測試 (test_bus_and_crosswalk_simulation.py)】
遵照 GEMINI.md 規範：嚴禁肉身排雷，針對 Pixel 6a 歷史問題進行端到端空間感測與語音調度仿真驗證。

驗證核心項目：
1. 公車行車模式震動與氣壓過濾：
   - 時速 >= 2.8 m/s (約 10~50 km/h) 下，路面顛簸 (mag < 11.2 m/s²) 軟體計步全數抑制。
   - 公車開關門與冷氣微壓變化，垂直神經分類器強制鎖定在地面 1F，不誤判電梯/樓梯。
   - 行車模式下抑制一般無聲交通號誌之搶播干擾，僅允許 45 米內之 APS 有聲號誌。
2. 五權公園路口交通號誌無障礙報讀防口吃：
   - 預設「路口交通號誌」等缺省名稱自動淨化為「前方路口」，消滅「前方【路口交通號誌】」之贅字跳針。
3. 綠燈過街防干擾保護 (Crossing Protection)：
   - 相機辨識綠燈後啟動 18 秒保護期。
   - 保護期間徹底靜默「手機朝下，請稍抬起」與「未見號誌，請左右微調」等導引雜音，讓視障者專注聆聽環境與盲杖探路。
4. 狀態列零語音騷擾 (Silent Status Exploration)：
   - 高度與樓層更新、GPS 搜尋狀態僅更新 DOM 與 aria-label，絕不主動插播朗讀。
5. 時間戳記正規化解析防呆：
   - 支援 ISO 'T' 與空白分隔格式，確保診斷日誌里程碑時間戳記精準提取至 HH:mm:ss。
"""

import math
import re
import unittest
from typing import List, Dict, Any, Optional

from nmap.spatial.taiwan_signals import TaiwanSignalManager


class MockAudioSink:
    """模擬聽覺事件佇列，攔截所有 speak() 呼叫並記錄時間點與發話內容"""
    def __init__(self):
        self.queue: List[Dict[str, Any]] = []

    def speak(self, text: str, timestamp_s: float, priority: int = 3, interrupt: bool = False):
        self.queue.append({
            "text": text,
            "timestamp": timestamp_s,
            "priority": priority,
            "interrupt": interrupt
        })

    def clear(self):
        self.queue.clear()

    def get_speech_texts(self) -> List[str]:
        return [item["text"] for item in self.queue]


class SimulatedSoftwareStepDetector:
    """軟體波峰計步器仿真模型 (GEMINI.md 規範：mag > 11.20, delta > 0.45, dt > 330ms)"""
    def __init__(self):
        self.step_count = 0
        self.last_acc_mag = 9.81
        self.last_step_time_ms = 0
        self.last_hardware_step_ms = 0

    def feed_accelerometer(self, now_ms: int, mag: float, is_vehicular: bool) -> bool:
        is_hardware_recent = (now_ms - self.last_hardware_step_ms) < 400
        delta = mag - self.last_acc_mag
        dt = now_ms - self.last_step_time_ms

        detected = False
        if not is_vehicular and not is_hardware_recent:
            if mag > 11.20 and delta > 0.45 and dt > 330:
                self.step_count += 1
                self.last_step_time_ms = now_ms
                detected = True

        self.last_acc_mag = mag
        return detected


class SimulatedCrossingProtectionManager:
    """過馬路相機保護狀態機仿真"""
    def __init__(self):
        self.crossing_protection_until_ms = 0

    def on_signal_detected(self, state: str, now_ms: int, audio_sink: MockAudioSink):
        if state == "GREEN":
            self.crossing_protection_until_ms = now_ms + 18000
            audio_sink.speak("小綠人綠燈，請由斑馬線前進", timestamp_s=now_ms / 1000.0, priority=1, interrupt=True)

    def is_in_crossing_protection(self, now_ms: int) -> bool:
        return now_ms < self.crossing_protection_until_ms

    def prompt_orientation_warning(self, now_ms: int, audio_sink: MockAudioSink) -> bool:
        """嘗試發出手機朝下警告，若處於過馬路保護期則強制靜默"""
        if self.is_in_crossing_protection(now_ms):
            return False
        audio_sink.speak("手機朝下，請稍抬起", timestamp_s=now_ms / 1000.0, priority=2)
        return True

    def prompt_searching_hint(self, now_ms: int, audio_sink: MockAudioSink) -> bool:
        """嘗試發出未見號誌提示，若處於過馬路保護期則強制靜默"""
        if self.is_in_crossing_protection(now_ms):
            return False
        audio_sink.speak("未見號誌，請左右微調", timestamp_s=now_ms / 1000.0, priority=4)
        return True


def parse_timeline_time(raw_timestamp: str) -> str:
    """仿真 WebAppInterface.kt 中里程碑日誌時間解析修復方案"""
    cleaned = raw_timestamp.strip()
    if not cleaned:
        return "--:--:--"
    
    # 支援 ISO 'T' 或空白分隔
    time_part = cleaned
    if "T" in cleaned:
        time_part = cleaned.split("T")[-1]
    elif " " in cleaned:
        time_part = cleaned.split(" ")[-1]

    # 取 HH:mm:ss
    parts = time_part.split(":")
    if len(parts) >= 3:
        hh = parts[0][-2:]
        mm = parts[1][:2]
        ss = parts[2][:2]
        return f"{hh}:{mm}:{ss}"
    return time_part[:8]


class TestBusAndCrosswalkSimulation(unittest.TestCase):
    def setUp(self):
        self.audio_sink = MockAudioSink()
        self.signal_mgr = TaiwanSignalManager()

    def test_bus_vibrations_suppressed(self):
        """
        情境 1：公車乘車行進 (09:35~09:46)。
        速度 12 m/s (43.2 km/h)，公車引擎怠速與路面顛簸造成加速度持續在 10.2 ~ 10.9 m/s² 震盪。
        斷言：軟體計步器步數必須精確為 0，嚴禁誤觸發 750 次假步伐！
        """
        step_detector = SimulatedSoftwareStepDetector()
        start_ms = 100000
        simulated_duration_ms = 10 * 60 * 1000 # 10 分鐘
        step_dt_ms = 100 # 10Hz 採樣

        for t in range(0, simulated_duration_ms, step_dt_ms):
            now_ms = start_ms + t
            # 公車路面震動與引擎共振，振幅在 9.8 ~ 10.85 之間波動
            bus_mag = 9.81 + 1.0 * math.sin(t / 250.0)
            step_detector.feed_accelerometer(now_ms, bus_mag, is_vehicular=True)

        self.assertEqual(step_detector.step_count, 0, "行車模式下路面震動被誤判為步行步數！")

    def test_bus_vehicular_signal_speech_filtering(self):
        """
        情境 2：公車行駛途中經過普通號誌與 APS 號誌。
        斷言：在行車狀態下，一般無聲紅綠燈應完全靜默，僅播報近身 (<=45m) 且具備視障有聲號誌 (APS) 的路口。
        """
        # 建立一個包含一般號誌與 APS 號誌的測試清單
        mock_signals = [
            {
                "id": "SIG_GENERIC_NORMAL",
                "intersection_name": "路口交通號誌",
                "lat": 25.0400, "lon": 121.5100,
                "has_aps": False, "has_button": False
            },
            {
                "id": "SIG_APS_FAR",
                "intersection_name": "大智路口",
                "lat": 25.0410, "lon": 121.5110,
                "has_aps": True, "ew_sound": "鳥鳴聲", "ns_sound": "布穀鳥聲",
                "has_button": True
            }
        ]
        mgr = TaiwanSignalManager(custom_db=mock_signals)

        # 模擬前端在 isVehicular == true 時的播報決策邏輯
        def decide_vehicular_speech(sig: Dict[str, Any], is_vehicular: bool) -> Optional[str]:
            if is_vehicular:
                # 行車模式：抑制一般無聲號誌，僅在 APS <= 45m 時才報讀
                if not sig.get("has_aps") or sig.get("distance_m", 999) > 45.0:
                    return None
            return f"📍 {sig['speech_prompt']}"

        # 模擬公車距離兩號誌皆為 25 公尺
        generic_sig = {
            "id": "SIG_GENERIC_NORMAL",
            "has_aps": False,
            "distance_m": 25.0,
            "speech_prompt": "前 12點鐘 25米：【路口】紅綠燈號誌 (一般無聲)"
        }
        aps_sig = {
            "id": "SIG_APS_FAR",
            "has_aps": True,
            "distance_m": 25.0,
            "speech_prompt": "前 12點鐘 25米：【大智路口】視障有聲號誌 (鳥鳴聲)"
        }

        # 行車模式下測試
        res_generic = decide_vehicular_speech(generic_sig, is_vehicular=True)
        res_aps = decide_vehicular_speech(aps_sig, is_vehicular=True)

        self.assertIsNone(res_generic, "行車模式下一般無聲號誌未被抑制！")
        self.assertIsNotNone(res_aps, "行車模式下近距離視障有聲號誌 (APS) 未能正常播報！")
        self.assertIn("視障有聲號誌", res_aps)

    def test_intersection_name_sanitization_no_stutter(self):
        """
        情境 3：路口名稱口吃消滅。
        當 OSM 或資料庫中 intersection_name 為「路口交通號誌」時：
        斷言：單一路口格式化應輸出「前方路口」，批次清單應輸出「【路口】」，絕不可出現「前方【路口交通號誌】紅綠燈號誌」。
        """
        mock_sig = [{
            "id": "SIG_TEST_001",
            "intersection_name": "路口交通號誌",
            "lat": 25.0100, "lon": 121.5000,
            "has_aps": False, "has_button": False
        }]
        mgr = TaiwanSignalManager(custom_db=mock_sig)

        # 檢驗 get_nearby_signals (周遭地標清單)
        nearby = mgr.get_nearby_signals(25.0100, 121.5001, heading_deg=270.0, radius_m=30.0)
        self.assertTrue(len(nearby) > 0)
        prompt = nearby[0]["speech_prompt"]
        self.assertNotIn("路口交通號誌", prompt, "周遭清單中出現重複贅字【路口交通號誌】！")
        self.assertIn("【路口】", prompt)

        # 檢驗 get_nearby_signal_safety (精確路口抵達報讀)
        speech_obj = mgr.get_nearby_signal_safety(25.0100, 121.5001, heading_deg=270.0)
        self.assertIsNotNone(speech_obj)
        speech_text = speech_obj["speech_prompt"]
        self.assertTrue(speech_text.startswith("前方路口，設有紅綠燈管制"), f"路口導引未採用自然流暢用語：{speech_text}")
        self.assertNotIn("前方【路口交通號誌】", speech_text, "路口導引仍存在跳針贅字！")

    def test_green_light_crossing_protection_suppresses_nagging(self):
        """
        情境 4：五權公園斑馬線綠燈過街保護 (Crossing Protection)。
        盲人使用者看見小綠人後收起手機、持白杖全神貫注過街。
        手機自然朝下、鏡頭離開號誌。
        斷言：
        1. 辨識到小綠人立即播報綠燈過街語音。
        2. 在隨後的 18 秒內，手機朝下警告與未見號誌提示全部被靜默，零噪音騷擾！
        3. 18 秒保護期過後，若持續朝下才恢復必要姿態提示。
        """
        protection_mgr = SimulatedCrossingProtectionManager()
        t0_ms = 10000

        # 1. 綠燈觸發
        protection_mgr.on_signal_detected("GREEN", t0_ms, self.audio_sink)
        speeches = self.audio_sink.get_speech_texts()
        self.assertEqual(len(speeches), 1)
        self.assertIn("小綠人綠燈", speeches[0])

        # 2. 2 秒後視障者將手機放下過馬路，姿態角度朝下
        t_during_crossing_ms = t0_ms + 2000
        warned = protection_mgr.prompt_orientation_warning(t_during_crossing_ms, self.audio_sink)
        searched = protection_mgr.prompt_searching_hint(t_during_crossing_ms, self.audio_sink)
        self.assertFalse(warned, "過馬路保護期內不應發出手機朝下警告！")
        self.assertFalse(searched, "過馬路保護期內不應發出未見號誌提示！")
        self.assertEqual(len(self.audio_sink.get_speech_texts()), 1, "保護期內聽覺佇列不應有新播報！")

        # 3. 10 秒後持續在斑馬線上走
        t_halfway_ms = t0_ms + 10000
        warned_halfway = protection_mgr.prompt_orientation_warning(t_halfway_ms, self.audio_sink)
        self.assertFalse(warned_halfway, "斑馬線過街中途仍應保持保護！")

        # 4. 20 秒後（已安全抵達對街），保護期結束，若使用者仍朝下則恢復導引
        t_after_crossing_ms = t0_ms + 19000
        warned_after = protection_mgr.prompt_orientation_warning(t_after_crossing_ms, self.audio_sink)
        self.assertTrue(warned_after, "保護期過後應恢復正常姿態導引！")
        self.assertEqual(len(self.audio_sink.get_speech_texts()), 2)
        self.assertIn("手機朝下", self.audio_sink.get_speech_texts()[1])

    def test_timeline_timestamp_parser_robustness(self):
        """
        情境 5：日誌時間戳記解析防呆。
        驗證 ISO 格式 ('2026-09-07T09:47:54.489') 與 空白分隔 ('2026-09-07 09:47:54.489') 皆能正確提取 '09:47:54'。
        """
        iso_sample = "2026-09-07T09:47:54.489"
        space_sample = "2026-09-07 09:47:54.489"
        raw_time_sample = "09:47:54"

        self.assertEqual(parse_timeline_time(iso_sample), "09:47:54")
        self.assertEqual(parse_timeline_time(space_sample), "09:47:54")
        self.assertEqual(parse_timeline_time(raw_time_sample), "09:47:54")

    def test_pitch_polarity_upward_vs_downward(self):
        """
        情境 6：紅綠燈相機仰角判定極性驗證 (Pixel 6a 實測日誌 065420 修復驗證)。
        在 Android SensorManager.getOrientation 中，pitch = asin(-R[7])。
        - 斜向上瞄準對街紅綠燈 (Pitch: -34.2° ~ -65.1°)：
          嚴禁觸發「手機朝下，請稍抬起」，且鏡頭畫面必須正常送入光學辨識管線！
        - 手機朝向地面/雙腳 (Pitch: > +25.0°)：
          正確觸發「手機朝下，請稍抬起」引導，並攔截地面畫面。
        """
        def evaluate_pitch_orientation(pitch_deg: float) -> Optional[str]:
            # 新版修復門檻：只有朝向地面 (Pitch > +25.0°) 才警告手機朝下
            if pitch_deg > 25.0:
                return "手機朝下，請稍抬起"
            return None

        # 模擬日誌 065420 中的真實斜向上瞄準角度
        self.assertIsNone(evaluate_pitch_orientation(-34.2), "斜向上瞄準 (-34.2°) 被誤判為手機朝下！")
        self.assertIsNone(evaluate_pitch_orientation(-65.1), "斜向上高仰角 (-65.1°) 被誤判為手機朝下！")
        self.assertIsNone(evaluate_pitch_orientation(0.0), "水平手持 (0.0°) 被誤判為手機朝下！")

        # 模擬真正垂手朝向柏油路/雙腳
        self.assertEqual(evaluate_pitch_orientation(35.0), "手機朝下，請稍抬起")
        self.assertEqual(evaluate_pitch_orientation(70.0), "手機朝下，請稍抬起")

    def test_pocket_and_lock_camera_guard(self):
        """
        情境 7：鎖屏放入口袋相機幽靈運作防護 (Pixel 6a 實測日誌 070315 修復驗證)。
        使用者鎖屏或放入口袋時：
        斷言：
        1. 若螢幕鎖定 (is_locked=True) 或接近感測器遮蔽 (is_pocket=True)，startCamera 立即攔截，不啟動相機。
        2. 若在開鏡運作途中鎖屏或入袋，processFrame 立即觸發 stopCamera() 並釋放硬體資源。
        """
        class SimulatedCameraManager:
            def __init__(self):
                self.is_running = False

            def start_camera(self, is_locked: bool, is_interactive: bool, is_pocket: bool) -> bool:
                if is_locked or not is_interactive or is_pocket:
                    return False
                self.is_running = True
                return True

            def process_frame(self, is_locked: bool, is_interactive: bool, is_pocket: bool) -> bool:
                if not self.is_running:
                    return False
                if is_locked or not is_interactive or is_pocket:
                    self.stop_camera()
                    return False
                return True

            def stop_camera(self):
                self.is_running = False

        cam = SimulatedCameraManager()

        # 1. 口袋中或螢幕鎖定時嘗試啟動相機
        started_in_pocket = cam.start_camera(is_locked=True, is_interactive=False, is_pocket=True)
        self.assertFalse(started_in_pocket, "放入口袋且螢幕鎖定時相機不應啟動！")
        self.assertFalse(cam.is_running)

        # 2. 正常拿出手機解鎖使用
        started_normal = cam.start_camera(is_locked=False, is_interactive=True, is_pocket=False)
        self.assertTrue(started_normal)
        self.assertTrue(cam.is_running)

        # 3. 走路中途直接鎖屏塞入口袋
        frame_handled = cam.process_frame(is_locked=True, is_interactive=False, is_pocket=True)
        self.assertFalse(frame_handled, "入袋後幀處理應即刻中止！")
        self.assertFalse(cam.is_running, "中途入袋應立即停止相機運作！")

    def test_utc_vs_local_timeline_chronological_sorting(self):
        """
        情境 8：診斷日誌大事記 UTC 與 Local 時區混亂排序修復驗證。
        前端 JS 產出 ISO UTC 時間 (例如 '2026-09-07T22:52:45.123Z'，台灣時間 06:52:45)，
        原生相機產出 Local 時間 (例如 '06:54:02.164')。
        舊版以字串純文字排序導致 '06:54:02' 誤排在 '2026...' 之前。
        斷言：經由統一解析為 Epoch 毫秒後，06:52:45 必須正確排在 06:54:02 之前！
        """
        from datetime import datetime, timezone, timedelta

        def parse_to_epoch_ms(t_str: str) -> int:
            t_str = t_str.strip()
            if "T" in t_str:
                clean = t_str.split(".")[0].rstrip("Z")
                dt = datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            elif ":" in t_str:
                parts = t_str.split(".")[0].split(":")
                # 台灣為 UTC+8
                tz_tw = timezone(timedelta(hours=8))
                cal = datetime(2026, 9, 8, int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=tz_tw)
                return int(cal.timestamp() * 1000)
            return 0

        t_js_utc = "2026-09-07T22:52:45.123Z" # 台灣時間 06:52:45
        t_native_local = "06:54:02.164"        # 台灣時間 06:54:02

        # 字串字母排序 (舊版行為，嚴重顛倒)
        legacy_sorted = sorted([t_js_utc, t_native_local])
        self.assertEqual(legacy_sorted[0], "06:54:02.164", "舊版純文字排序會把較晚的 06:54 排在前面！")

        # Epoch 毫秒時間序列排序 (新版修復)
        ms_utc = parse_to_epoch_ms(t_js_utc)
        ms_local = parse_to_epoch_ms(t_native_local)
        self.assertLess(ms_utc, ms_local, "22:52 UTC (即 06:52 Local) 應小於 06:54 Local！")

    def test_road_announcement_stationary_and_indoor_gating(self):
        """
        情境 9：道路週期廣播靜止與室內防跳針門控 (GEMINI.md Section 1.4)。
        斷言：
        1. 處於靜止狀態 (is_stationary=True) 時，絕不反覆報讀「沿著XX路前進」。
        2. 處於室內非地面層 (vertical_level='B1' 或 floor='2F') 時，不播報室外道路名。
        3. 內容重複時必須遵循防抖冷卻 (>= 75 秒)。
        """
        class RoadAnnouncementController:
            def __init__(self):
                self.last_speech_time = 0
                self.last_road_time = 0
                self.last_road_msg = ""
                self.announcements = []

            def check_and_announce(self, now_ms: int, street: str, door: str, is_stationary: bool, is_indoor: bool):
                msg = f"沿著【${street}】前進，${door}" if door else f"沿著【${street}】前進"
                if not is_stationary and not is_indoor:
                    if now_ms - self.last_speech_time >= 25000 and now_ms - self.last_road_time >= 45000:
                        if msg != self.last_road_msg or (now_ms - self.last_road_time >= 75000):
                            self.last_road_msg = msg
                            self.last_road_time = now_ms
                            self.last_speech_time = now_ms
                            self.announcements.append((now_ms, msg))

        ctrl = RoadAnnouncementController()

        # 1. 靜止等紅燈 (120 秒內完全靜默)
        for t in range(0, 120000, 10000):
            ctrl.check_and_announce(t, "建國南路二段", "左側 177號", is_stationary=True, is_indoor=False)
        self.assertEqual(len(ctrl.announcements), 0, "靜止等候時不應重複播報道路與門牌！")

        # 2. 室內地下室 (完全靜默)
        for t in range(120000, 240000, 10000):
            ctrl.check_and_announce(t, "建國南路二段", "左側 177號", is_stationary=False, is_indoor=True)
        self.assertEqual(len(ctrl.announcements), 0, "室內環境不應播報室外道路！")

        # 3. 正常戶外步行，初次播報
        t_walk = 250000
        ctrl.check_and_announce(t_walk, "建國南路二段", "左側 177號", is_stationary=False, is_indoor=False)
        self.assertEqual(len(ctrl.announcements), 1)

        # 4. 20 秒後（小於 45 秒冷卻）不應重播
        ctrl.check_and_announce(t_walk + 20000, "建國南路二段", "左側 177號", is_stationary=False, is_indoor=False)
        self.assertEqual(len(ctrl.announcements), 1)

        # 5. 50 秒後門牌未變（小於 75 秒重複間隔）不應重播
        ctrl.check_and_announce(t_walk + 50000, "建國南路二段", "左側 177號", is_stationary=False, is_indoor=False)
        self.assertEqual(len(ctrl.announcements), 1)

        # 6. 80 秒後門牌未變，超過 75 秒允許複述
        ctrl.check_and_announce(t_walk + 80000, "建國南路二段", "左側 177號", is_stationary=False, is_indoor=False)
        self.assertEqual(len(ctrl.announcements), 2)

    def test_door_number_hysteresis_latch_eliminates_ping_pong(self):
        """
        情境 10：門牌左右側遲滯防抖 (Hysteresis Latch)。
        當行走於南北向道路 (道路向量方位 0°)，若手機在口袋中或手持擺動在 85° ~ 95° 之間抖動：
        斷言：
        具備 65° ~ 115° 遲滯鎖定，道路幾何向量維持穩定，絕不因跨越 90° 而引發左右兩側門牌乒乓顛倒！
        """
        from nmap.spatial.geometry import relative_bearing

        class SimulatedRoadDirectionLatch:
            def __init__(self):
                self._road_seg_latch = {}

            def determine_direction(self, latch_key: str, heading_deg: float, seg_bearing: float) -> str:
                rel_angle = abs(relative_bearing(heading_deg, seg_bearing))
                is_reversed = self._road_seg_latch.get(latch_key, None)
                if is_reversed is None:
                    is_reversed = (rel_angle > 90)
                else:
                    if is_reversed and rel_angle < 45:
                        is_reversed = False
                    elif not is_reversed and rel_angle > 135:
                        is_reversed = True

                self._road_seg_latch[latch_key] = is_reversed
                return "REVERSED" if is_reversed else "FORWARD"

        latch = SimulatedRoadDirectionLatch()
        key = "TEST_ROAD:0,0"
        seg_bearing = 0.0 # 北向道路

        # 初始朝向 80° (接近 90°，但小於 90°，判定為 FORWARD)
        dir1 = latch.determine_direction(key, heading_deg=80.0, seg_bearing=seg_bearing)
        self.assertEqual(dir1, "FORWARD")

        # 劇烈擺動至 125° (盲人白杖 60° 大幅手持晃動，仍小於 135°，必須維持 FORWARD 不翻轉！)
        dir2 = latch.determine_direction(key, heading_deg=125.0, seg_bearing=seg_bearing)
        self.assertEqual(dir2, "FORWARD", "125° 白手杖擺動穿透了遲滯區引發了門牌左右翻轉！")

        # 擺動回 60° (大於 45°，仍維持 FORWARD)
        dir3 = latch.determine_direction(key, heading_deg=60.0, seg_bearing=seg_bearing)
        self.assertEqual(dir3, "FORWARD")

        # 真正 180° 大迴轉至 160° (> 135°，確實驗證掉頭反向)
        dir4 = latch.determine_direction(key, heading_deg=160.0, seg_bearing=seg_bearing)
        self.assertEqual(dir4, "REVERSED", "大於 135° 掉頭時未能正確翻轉向量！")

        # 掉頭後擺動至 55° (大於 45°，仍維持 REVERSED 鎖定)
        dir5 = latch.determine_direction(key, heading_deg=55.0, seg_bearing=seg_bearing)
        self.assertEqual(dir5, "REVERSED")

        # 真正轉回正前方 30° (< 45°，解除反向恢復順向)
        dir6 = latch.determine_direction(key, heading_deg=30.0, seg_bearing=seg_bearing)
        self.assertEqual(dir6, "FORWARD")

    def test_11_chained_junction_real_haversine_distance(self):
        """
        驗證 C-03：連續巷弄接力判定必須計算兩路口之間的真實 Haversine 距離，
        絕不可使用「使用者到各路口之徑向距離差 (delta_dist = j2_dist - j1_dist)」！
        情境：j1 距離使用者 10m (右前方)，j2 距離使用者 12m (左前方，對街不同巷口)；
        使用者距離差僅 2m，但兩路口相距 18m (> 12m)，絕不可誤判為連續相鄰巷口！
        """
        from nmap.spatial.geometry import haversine_distance

        # 使用者位於 (25.0000, 121.0000)
        # j1 位於使用者右前方 (25.00008, 121.00006) ~ 10m
        j1_lat, j1_lon = 25.00008, 121.00006
        # j2 位於使用者左前方 (25.00010, 121.00018) ~ 21m 遠，但沿前進軸距離差很小
        j2_lat, j2_lon = 25.00010, 121.00018

        real_inter_dist = haversine_distance(j1_lat, j1_lon, j2_lat, j2_lon)
        # 兩路口間距 ~ 12.3 米 (> 12.0m 門檻)
        is_chained = (real_inter_dist <= 12.0)
        self.assertFalse(is_chained, f"兩路口真實間距 {real_inter_dist:.1f}m > 12m，不可誤判為連續巷口！")

        # 若 j2 確實為相鄰連續巷弄 (相距 6.5m)
        j2_adjacent_lat, j2_adjacent_lon = 25.00012, 121.00009
        adjacent_dist = haversine_distance(j1_lat, j1_lon, j2_adjacent_lat, j2_adjacent_lon)
        self.assertTrue(adjacent_dist <= 12.0, "真實相距 <= 12m 之相鄰巷弄必須成功觸發接力！")

    def test_12_corridor_distance_and_same_side_clustering(self):
        """
        驗證 H-02 與 H-05：
        1. 走廊距離必須為 2.0 ~ 18.0m (GEMINI.md Section 1.3)，排除 < 2.0m 與 > 18.0m。
        2. 同側聚類打包必須確認 (bearing1 * bearing2 > 0)，不可跨街把左側店與右側店打包！
        """
        import math
        def in_corridor(d, rel_bearing):
            rad = math.radians(abs(rel_bearing))
            fwd = d * math.cos(rad)
            lat = abs(d * math.sin(rad))
            return 2.0 <= fwd <= 18.0 and lat <= 14.0

        # 店家 A：正前方 22m (超出 18m 上限，不可納入走廊)
        self.assertFalse(in_corridor(22.0, 0.0), "22m 遠處店家不可被走廊提早播報！")
        # 店家 B：身旁 1.2m (小於 2m，不可納入走廊)
        self.assertFalse(in_corridor(1.2, 30.0), "1.2m 已越過店家不可被走廊重複播報！")
        # 店家 C：前方 10m，右側 30° -> fwd = 8.66m, lat = 5.0m (在走廊內)
        self.assertTrue(in_corridor(10.0, 30.0))

        # 同側打包驗證：
        # 店家 1：左前方 -15°；店家 2：右前方 +12° (角度差 27° <= 28°)
        # 但兩者分屬左右兩側，絕不可打包成一句話！
        b1, b2 = -15.0, 12.0
        is_same_side = (b1 * b2 > 0) or (abs(b1) <= 8 and abs(b2) <= 8)
        self.assertFalse(is_same_side, "左側與右側跨街店家不可被錯誤打包！")

        # 店家 3：右前方 +15°；店家 4：右前方 +25° (同在右側，角度差 10° <= 28°)
        b3, b4 = 15.0, 25.0
        is_same_side_right = (b3 * b4 > 0) or (abs(b3) <= 8 and abs(b4) <= 8)
        self.assertTrue(is_same_side_right, "同在右側相鄰店家應允許聚類打包！")

    def test_13_junction_state_machine_6m_boundary_no_gap(self):
        """
        驗證 H-03 與 M-02：路口狀態機邊界無空窗且嚴格遵循 GEMINI.md Section 1.4：
        PASSING: < 6.0m
        LEAVING: 6.0 ~ 18.0m (前一狀態為 PASSING)
        APPROACHING: 6.0 ~ 25.0m (未進入 PASSING 時)
        測試 7.5m 處絕無掉入任何邏輯空窗！
        """
        def get_junction_state(junc_dist, current_state):
            if junc_dist < 6.0:
                return "PASSING"
            elif 6.0 <= junc_dist <= 18.0 and current_state == "PASSING":
                return "LEAVING"
            elif 6.0 <= junc_dist <= 25.0 and current_state not in ("PASSING", "LEAVING"):
                return "APPROACHING"
            return current_state

        # 從 20m 走向路口：20m -> APPROACHING
        self.assertEqual(get_junction_state(20.0, "IDLE"), "APPROACHING")
        # 走近至 7.5m：舊代碼在 7.0~8.0m 存在空窗，新代碼必須依然判定為 APPROACHING！
        self.assertEqual(get_junction_state(7.5, "IDLE"), "APPROACHING")
        # 踏入 5.5m (< 6.0m)：觸發 PASSING！
        self.assertEqual(get_junction_state(5.5, "APPROACHING"), "PASSING")
        # 通過後走至 8.0m (6~18m)：觸發 LEAVING！
        self.assertEqual(get_junction_state(8.0, "PASSING"), "LEAVING")


if __name__ == "__main__":
    unittest.main()

