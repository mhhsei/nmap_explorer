# -*- coding: utf-8 -*-
"""
【HMM 隱馬爾可夫地圖匹配風洞測試 (test_hmm_map_matching.py)】
驗證目標：
1. 嚴格重播都市平行巷弄（相距 12 米且互不相通），當 GPS 雜訊向隔壁巷子暴跳 10 米時，
   HMM 維特比演算法必須死鎖在原巷弄，嚴禁橫向穿牆跳針！
2. 當使用者真正走到連通的十字路口並轉向時，HMM 必須在 1 步內平滑切換至接續道路。
"""

import unittest
from nmap.spatial.hmm_matcher import HmmMapMatcher


class TestHmmMapMatching(unittest.TestCase):

    def setUp(self):
        self.matcher = HmmMapMatcher(sigma_z=4.5, beta=5.0, window_size=4)

        # 建立兩條平行但不相通的小巷弄（例如：北新路 169 巷 vs 182 巷）
        # 巷弄 A：經度 121.4480，南北向 (緯度 25.1740 -> 25.1750)
        self.road_169 = {
            "id": "road_169_alley",
            "name": "北新路169巷",
            "geometry": [(25.1740, 121.4480), (25.1750, 121.4480)]
        }

        # 巷弄 B：經度 121.44812 (相距約 12 米)，南北向 (緯度 25.1740 -> 25.1750)
        self.road_182 = {
            "id": "road_182_alley",
            "name": "北新路182巷",
            "geometry": [(25.1740, 121.44812), (25.1750, 121.44812)]
        }

        # 橫向大道：大忠街 (在北端 25.1750 與 169 巷連通)
        self.dazhong_st = {
            "id": "dazhong_street",
            "name": "大忠街",
            "geometry": [(25.1750, 121.4470), (25.1750, 121.4480), (25.1750, 121.4490)]
        }

    def test_parallel_alley_ping_pong_rejection(self):
        """測試 1：平行巷弄 GPS 側向大跳躍時，HMM 拒絕穿牆橫跳"""
        candidates = [self.road_169, self.road_182]

        # Step 1: 正常走在 169 巷
        r1, lat1, lon1, _ = self.matcher.match(25.1741, 121.4480, user_heading=0.0, candidate_roads=candidates)
        self.assertEqual(r1["name"], "北新路169巷")

        # Step 2: 繼續前進 10 米
        r2, lat2, lon2, _ = self.matcher.match(25.1742, 121.4480, user_heading=0.0, candidate_roads=candidates)
        self.assertEqual(r2["name"], "北新路169巷")

        # Step 3: 【極端都市峽谷雜訊】GPS 瞬間向右跳了 9 公尺（經度 121.44808，離 182 巷僅 4m，離 169 巷 8m）
        # 傳統貪婪吸附會立刻誤判為「北新路182巷」
        # HMM 因跨巷路網轉移機率斷崖暴跌，必須堅持鎖定在「北新路169巷」！
        r3, lat3, lon3, _ = self.matcher.match(25.1743, 121.44808, user_heading=0.0, candidate_roads=candidates)
        self.assertEqual(r3["name"], "北新路169巷", "HMM 必須防住平行巷弄雜訊橫跳！")

        # Step 4: GPS 雜訊回彈回 169 巷
        r4, lat4, lon4, _ = self.matcher.match(25.1744, 121.4480, user_heading=0.0, candidate_roads=candidates)
        self.assertEqual(r4["name"], "北新路169巷")

    def test_real_intersection_turning(self):
        """測試 2：使用者走到路口連通處並轉向時，HMM 流暢切換至新道路"""
        candidates = [self.road_169, self.dazhong_st]

        # 走近大忠街路口
        self.matcher.match(25.1748, 121.4480, user_heading=0.0, candidate_roads=candidates)
        self.matcher.match(25.17495, 121.4480, user_heading=0.0, candidate_roads=candidates)

        # 在路口向東右轉進入大忠街 (heading=90度)
        r_turn, _, _, _ = self.matcher.match(25.1750, 121.4482, user_heading=90.0, candidate_roads=candidates)
        self.assertEqual(r_turn["name"], "大忠街", "連通路口轉向後應正確切換至大忠街！")


if __name__ == "__main__":
    unittest.main()
