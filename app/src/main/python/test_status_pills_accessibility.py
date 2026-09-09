"""
【狀態徽章無障礙規格與防騷擾回歸測試】
驗證目的：
1. 依據視障使用者要求，GPS 與樓層高程狀態變化時，TalkBack / NVDA 絕不自動搶播朗讀。
2. 頂部狀態膠囊 (diff-status-pill, vertical-status-pill, beacon-status-pill) 不得含有 role="status" 或 aria-live 屬性（消滅即時動態區域觸發）。
3. 頂部狀態膠囊必須具備 tabindex="0" 與 aria-label，確保視障者手動滑動或觸控探索時能自行查驗朗讀。
"""

import unittest
import os
import re


class TestStatusPillsAccessibility(unittest.TestCase):
    def setUp(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.html_path = os.path.join(current_dir, "web", "index.html")
        self.js_path = os.path.join(current_dir, "web", "app.js")
        self.assertTrue(os.path.exists(self.html_path), "index.html 必須存在")
        self.assertTrue(os.path.exists(self.js_path), "app.js 必須存在")
        with open(self.html_path, "r", encoding="utf-8") as f:
            self.html_content = f.read()
        with open(self.js_path, "r", encoding="utf-8") as f:
            self.js_content = f.read()

    def test_status_pills_have_no_aria_live(self):
        """驗證頂部狀態徽章不可含有 aria-live，防止背景定位或樓層數值抖動時自動搶播騷擾"""
        pill_ids = ["diff-status-pill", "vertical-status-pill", "beacon-status-pill"]
        for pid in pill_ids:
            pattern = rf'<span[^>]*id=["\']{pid}["\'][^>]*>'
            match = re.search(pattern, self.html_content)
            self.assertIsNotNone(match, f"必須在 index.html 找到 id='{pid}' 的元素")
            tag_str = match.group(0)
            
            self.assertNotIn("aria-live", tag_str, f"{pid} 不可含有 aria-live 屬性")
            self.assertNotIn('role="status"', tag_str, f"{pid} 不可含有 role='status' 隱含即時廣播")
            self.assertNotIn("role='status'", tag_str, f"{pid} 不可含有 role='status' 隱含即時廣播")

    def test_status_pills_have_tabindex_and_aria_label(self):
        """驗證頂部狀態徽章具備 tabindex='0' 與 aria-label，保障使用者手動觸控探索時能讀取"""
        pill_ids = ["diff-status-pill", "vertical-status-pill", "beacon-status-pill"]
        for pid in pill_ids:
            pattern = rf'<span[^>]*id=["\']{pid}["\'][^>]*>'
            match = re.search(pattern, self.html_content)
            self.assertIsNotNone(match)
            tag_str = match.group(0)
            
            self.assertIn('tabindex="0"', tag_str, f"{pid} 必須具備 tabindex='0' 供 TalkBack 焦點停留手動查驗")
            self.assertIn("aria-label=", tag_str, f"{pid} 必須具備初始 aria-label 供語音報讀")

    def test_app_js_manual_pill_click_listeners(self):
        """驗證 app.js 中已綁定狀態徽章之點擊與鍵盤查驗事件"""
        self.assertIn("diff-status-pill", self.js_content)
        self.assertIn("vertical-status-pill", self.js_content)
        self.assertIn("bindPillSpeak", self.js_content, "app.js 必須綁定手動點擊/雙擊報讀邏輯")

    def test_stream_focus_lock_2s_configured(self):
        """驗證依使用者明確指示：焦點鎖定保護期嚴格設定為 2.0 秒 (2000ms)"""
        self.assertIn("this.streamFocusLockMs = 2000;", self.js_content, "焦點鎖定保護期必須設定為 2000ms")
        self.assertIn("markStreamInteraction", self.js_content, "必須有標記互動的 markStreamInteraction 方法")
        self.assertIn("isUserBrowsingStreamList", self.js_content, "必須有判定正在瀏覽清單的 isUserBrowsingStreamList 方法")
        self.assertIn("flushPendingStreamCards", self.js_content, "必須有平滑批次注入的 flushPendingStreamCards 方法")

    def test_stream_in_place_reconciliation(self):
        """驗證同店家原地更新架構 (In-Place Reconciliation)，絕不位移 DOM 節點導致 TalkBack 卡住"""
        self.assertIn("data-poi-key", self.js_content, "卡片必須標記唯一 data-poi-key 供比對")
        self.assertIn("_updatePoiData", self.js_content, "卡片必須支援原地資料更新 _updatePoiData")

    def test_horizontal_swipe_protection(self):
        """驗證水平左右滑動保護：防止 TalkBack 換項手勢被誤判為垂直滑桿手勢"""
        self.assertIn("Math.abs(dx) > Math.abs(dy)", self.js_content, "必須過濾水平換項手勢，絕不干擾 TalkBack 左右滑動")

    def test_no_undefined_jdist_in_junction_state_machine(self):
        """驗證路口狀態機中已將 4 處筆誤 jDist 改為合法變數 juncDist，徹底消滅 ReferenceError"""
        # 步行模式下的路口狀態機中，不得在無宣告 jDist 的區塊引用 jDist
        matches = re.findall(r'JUNCTION_STATE_TRANSITION.*?distance_m:\s*Math\.round\((\w+)\s*\*\s*10\)', self.js_content, re.DOTALL)
        self.assertTrue(len(matches) >= 3, "必須找到至少 3 處路口狀態轉換日誌記錄")
        for var_name in matches:
            self.assertEqual(var_name, "juncDist", f"路口狀態日誌中距離變數必須為 juncDist 而非 {var_name}")

    def test_hazard_priority_before_throttle(self):
        """驗證 Priority 1 人行道障礙物在 1800ms 防剪音節流閥之前執行，確保生命安全絕對最高優先"""
        hazard_idx = self.js_content.find("data.sidewalk_hazards && data.sidewalk_hazards.length > 0")
        throttle_idx = self.js_content.find("if (now - (this.lastSpeechTime || 0) < 1800) return;")
        self.assertNotEqual(hazard_idx, -1, "必須包含人行道障礙物檢查")
        self.assertNotEqual(throttle_idx, -1, "必須包含 1800ms 防剪音節流閥")
        self.assertLess(hazard_idx, throttle_idx, "Priority 1 人行道障礙物檢查必須嚴格位於 1800ms 節流閥之前")

    def test_poi_cluster_same_side_and_front_corridor(self):
        """驗證同側與正前方走廊店家聚類打包邏輯，不單純依賴符號二分，允許正前方相鄰店家合併"""
        self.assertIn("isSameSideOrFront", self.js_content, "必須採用包含正前方同走廊的聚類判定")
        self.assertIn("Math.abs(b1) <= 25 && Math.abs(b2) <= 25", self.js_content, "必須支援正前方走廊視野相鄰打包")

    def test_corridor_poi_cooldown_40s(self):
        """驗證走廊店家播報冷卻時間依據 GEMINI.md 規範嚴格設定為 40 秒 (40000ms)"""
        self.assertIn("now - lastLeft > 40000 && now - lastRight > 40000", self.js_content, "雙側走廊冷卻必須為 40000ms")
        self.assertIn("now - lastTime > 40000", self.js_content, "單店走廊冷卻必須為 40000ms")

    def test_guidance_status_pill_in_html_and_js(self):
        """驗證頂部狀態徽章列具備可直接點擊關閉導引的 guidance-status-pill 按鈕"""
        self.assertIn('id="guidance-status-pill"', self.html_content, "index.html 必須包含 guidance-status-pill")
        self.assertIn('guidanceStatusPill.addEventListener("click"', self.js_content, "app.js 必須綁定點擊關閉事件")

    def test_no_duplicate_beacon_methods_in_app_js(self):
        """驗證 app.js 中無重複宣告的 startBeaconToTarget 類別方法，杜絕致命方法覆蓋與無聲 Bug"""
        matches = re.findall(r'^\s*startBeaconToTarget\s*\([^)]*\)\s*\{', self.js_content, re.MULTILINE)
        self.assertEqual(len(matches), 1, f"startBeaconToTarget 類別方法定義必須只宣告 1 次，實際找到 {len(matches)} 次")
        
        stop_matches = re.findall(r'^\s*stopBeaconGuidance\s*\([^)]*\)\s*\{', self.js_content, re.MULTILINE)
        self.assertEqual(len(stop_matches), 1, f"stopBeaconGuidance 類別方法定義必須只宣告 1 次，實際找到 {len(stop_matches)} 次")

    def test_play_beacon_sound_design_scaling(self):
        """驗證 3D 空間導引聲音設計：遠處微弱柔和、近處響亮清脆，小於 8 米觸發雙音"""
        self.assertIn("distM <= 4.0) volume = 0.95;", self.js_content, "近身 4 米內音量必須達到 0.95")
        self.assertIn("distM <= 8.0", self.js_content, "8 米內必須觸發 Double-pip 急迫副音")
        self.assertIn("distM <= 3.8", self.js_content, "3.8 米抵達門檻必須自動觸發 handleArrivalAtTarget")


if __name__ == "__main__":
    unittest.main()


