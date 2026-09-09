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


if __name__ == "__main__":
    unittest.main()
