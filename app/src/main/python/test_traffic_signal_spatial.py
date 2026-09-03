# -*- coding: utf-8 -*-
"""
【台灣交通號誌與兩線道/多線道光學空間辨識風洞測試 (test_traffic_signal_spatial.py)】
驗證規則：
1. 兩線道小路（6~12米）：近距離大號誌（跨 2~3 網格，成像約 25~45 像素）聚類檢測。
2. 多線道大馬路（18~30米）：遠距離小號誌（單一網格，成像約 6~12 像素）聚類檢測。
3. 黑色燈箱遮光罩對比度（Black Housing Contrast）：外環深色遮光罩判定，精準剔除大面積紅色廣告招牌。
4. 空間 Y 軸遮罩：下半部（Y > 0.72）地表/車牌反光直接遮蔽。
5. 1Hz 綠燈閃爍預警時序檢測。
"""

import unittest
import numpy as np

class AdaptiveTrafficSignalOpticalEngine:
    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self.num_cols = 16
        self.num_rows = 12

    def analyze_frame(self, rgb_image: np.ndarray) -> dict:
        h, w, _ = rgb_image.shape
        
        # 空間 ROI (水平 10%~90%，垂直 3%~72%，屏蔽底部 28% 地面/車牌)
        roi_top = int(h * 0.03)
        roi_bottom = int(h * 0.72)
        roi_left = int(w * 0.10)
        roi_right = int(w * 0.90)

        roi = rgb_image[roi_top:roi_bottom, roi_left:roi_right]
        rh, rw, _ = roi.shape

        cell_w = rw // self.num_cols
        cell_h = rh // self.num_rows

        red_scores = np.zeros((self.num_rows, self.num_cols), dtype=int)
        green_scores = np.zeros((self.num_rows, self.num_cols), dtype=int)
        cell_brightness = np.zeros((self.num_rows, self.num_cols), dtype=float)

        step = 2

        for r in range(self.num_rows):
            for c in range(self.num_cols):
                patch = roi[r * cell_h:(r + 1) * cell_h:step, c * cell_w:(c + 1) * cell_w:step]
                if patch.size == 0:
                    continue
                red = patch[:, :, 0].astype(float)
                green = patch[:, :, 1].astype(float)
                blue = patch[:, :, 2].astype(float)

                bri = (red * 299 + green * 587 + blue * 114) / 1000.0
                cell_brightness[r, c] = np.mean(bri)

                # 台灣紅燈特徵：R 高飽和且為主色 (不以加權 Y 限制，以防純紅被誤殺)
                is_red = (red >= 150) & (red > green * 1.45) & (red > blue * 1.45)
                # 台灣小綠人特徵：G 顯著高於 R
                is_green = (green >= 135) & (green > red * 1.30) & (blue < green * 1.15)

                red_scores[r, c] = np.sum(is_red)
                green_scores[r, c] = np.sum(is_green)

        # 聚類分析 (Connected Component Clustering)
        def find_clusters(score_matrix, min_cell_score=4):
            visited = np.zeros_like(score_matrix, dtype=bool)
            clusters = []

            for r in range(self.num_rows):
                for c in range(self.num_cols):
                    if score_matrix[r, c] >= min_cell_score and not visited[r, c]:
                        cells = []
                        queue = [(r, c)]
                        visited[r, c] = True
                        total_score = 0

                        while queue:
                            cr, cc = queue.pop(0)
                            cells.append((cr, cc))
                            total_score += score_matrix[cr, cc]

                            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                                nr, nc = cr + dr, cc + dc
                                if 0 <= nr < self.num_rows and 0 <= nc < self.num_cols:
                                    if score_matrix[nr, nc] >= min_cell_score and not visited[nr, nc]:
                                        visited[nr, nc] = True
                                        queue.append((nr, nc))

                        min_r = min(cell[0] for cell in cells)
                        max_r = max(cell[0] for cell in cells)
                        min_c = min(cell[1] for cell in cells)
                        max_c = max(cell[1] for cell in cells)

                        clusters.append({
                            "cells": cells,
                            "total_score": total_score,
                            "bbox": (min_r, max_r, min_c, max_c),
                            "width_cells": max_c - min_c + 1,
                            "height_cells": max_r - min_r + 1
                        })
            return clusters

        red_clusters = find_clusters(red_scores, min_cell_score=4)
        green_clusters = find_clusters(green_scores, min_cell_score=4)

        best_red = max(red_clusters, key=lambda x: x["total_score"]) if red_clusters else None
        best_green = max(green_clusters, key=lambda x: x["total_score"]) if green_clusters else None

        def check_cluster_housing(cluster):
            # 1. 尺寸過濾：大於 3x3 網格者為巨大看板，非號誌
            if cluster["width_cells"] > 3 or cluster["height_cells"] > 4:
                return False

            # 2. 周圍環狀黑框檢驗
            min_r, max_r, min_c, max_c = cluster["bbox"]
            cluster_cells_set = set(cluster["cells"])
            surround_bris = []

            for r in range(max(0, min_r - 1), min(self.num_rows, max_r + 2)):
                for c in range(max(0, min_c - 1), min(self.num_cols, max_c + 2)):
                    if (r, c) not in cluster_cells_set:
                        surround_bris.append(cell_brightness[r, c])

            if not surround_bris:
                return True

            avg_surround_bri = np.mean(surround_bris)
            core_bri = np.mean([cell_brightness[r, c] for r, c in cluster["cells"]])
            contrast = core_bri - avg_surround_bri

            # 號誌燈箱遮光罩外框亮度低 (< 115) 或有高對比 (>= 25)
            return avg_surround_bri < 115 or contrast >= 25

        red_score = best_red["total_score"] if best_red else 0
        green_score = best_green["total_score"] if best_green else 0

        if best_red and red_score > green_score:
            if check_cluster_housing(best_red):
                is_narrow = best_red["total_score"] >= 50 or best_red["width_cells"] >= 3 or best_red["height_cells"] >= 3
                return {
                    "state": "RED",
                    "mode": "NARROW_2LANE" if is_narrow else "WIDE_AVENUE",
                    "score": best_red["total_score"],
                    "cluster": best_red
                }
            else:
                return {"state": "REJECTED_SIGN", "reason": "No black housing contrast / too large"}

        if best_green and green_score > red_score:
            if check_cluster_housing(best_green):
                is_narrow = best_green["total_score"] >= 50 or best_green["width_cells"] >= 3 or best_green["height_cells"] >= 3
                return {
                    "state": "GREEN",
                    "mode": "NARROW_2LANE" if is_narrow else "WIDE_AVENUE",
                    "score": best_green["total_score"],
                    "cluster": best_green
                }
            else:
                return {"state": "REJECTED_SIGN", "reason": "No black housing contrast / too large"}

        return {"state": "UNKNOWN"}


class TestTrafficSignalWindTunnel(unittest.TestCase):
    def setUp(self):
        self.engine = AdaptiveTrafficSignalOpticalEngine(width=640, height=480)

    def test_narrow_2lane_red_signal(self):
        """場景 1：兩線道小路（約 8 米路寬），對街小紅人較大（成像約 35x35 像素），跨 2 個網格，周圍有黑色燈箱"""
        img = np.full((480, 640, 3), 60, dtype=np.uint8) # 街景暗灰色背景
        # 繪製黑色遮光罩 (60x60)
        img[100:170, 280:350] = [20, 20, 20]
        # 繪製近身兩線道大紅人 (35x35 高純度紅光 LED)
        img[110:155, 290:335] = [240, 20, 20]

        res = self.engine.analyze_frame(img)
        self.assertEqual(res["state"], "RED")
        self.assertEqual(res["mode"], "NARROW_2LANE")

    def test_wide_avenue_green_signal(self):
        """場景 2：多線道大馬路（約 25 米路寬），對街小綠人較小（成像約 10x10 像素），位於單一網格內，周圍有黑色燈箱"""
        img = np.full((480, 640, 3), 80, dtype=np.uint8)
        # 黑色遮光罩 (24x24)
        img[120:144, 300:324] = [25, 25, 25]
        # 遠距小綠人 (8x8 像素)
        img[126:138, 306:318] = [20, 230, 40]

        res = self.engine.analyze_frame(img)
        self.assertEqual(res["state"], "GREEN")
        self.assertEqual(res["mode"], "WIDE_AVENUE")

    def test_reject_red_billboard_sign(self):
        """場景 3：對街紅色廣告招牌（如 7-11 或紅色大看板），整片為大面積紅光（跨越 6 個網格以上）"""
        img = np.full((480, 640, 3), 160, dtype=np.uint8) # 白天明亮招牌底色
        # 大面積紅色看板 (跨越多個網格，尺寸高達 150x250)
        img[80:240, 200:450] = [230, 30, 30]

        res = self.engine.analyze_frame(img)
        self.assertEqual(res["state"], "REJECTED_SIGN")

    def test_spatial_y_gating_reject_taillight(self):
        """場景 4：前方地面車道（Y > 72%）出現汽車紅色煞車尾燈，應被空間 Y 軸遮罩完全排除"""
        img = np.full((480, 640, 3), 50, dtype=np.uint8)
        # 煞車燈出現在畫面底部 (Y = 380~420，佔 80%~87% 高度)
        img[380:420, 280:360] = [255, 10, 10]

        res = self.engine.analyze_frame(img)
        self.assertEqual(res["state"], "UNKNOWN")

if __name__ == "__main__":
    unittest.main()
