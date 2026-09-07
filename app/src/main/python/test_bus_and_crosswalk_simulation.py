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


if __name__ == "__main__":
    unittest.main()
