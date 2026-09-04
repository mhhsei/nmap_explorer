# -*- coding: utf-8 -*-
"""
【隱馬爾可夫拓撲地圖匹配演算法 (HmmMapMatcher)】
遵照純 Python 原則實作（Pure Python，無外部 C 函式庫相依性）。

生活化比喻（小學生都看得懂）：
傳統的地圖吸附就像一個「健忘的小孩」：每看到一個 GPS 點，就只看旁邊哪條路最近就往哪裡靠。
當你在「北新路 169 巷」直走時，隔壁 15 公尺是「182 巷」。GPS 稍微手抖往右偏個 6 公尺，
小孩就以為你瞬間學會穿牆術，跳到 182 巷去了！下一秒又跳回來。

HMM 維特比（Viterbi）演算法就像一位「冷靜的私家偵探」：
偵探不只看你現在離哪條路近（發射機率），更會看你「上一步在何處、路網上通不通（轉移機率）」。
如果上一秒你在 169 巷，要到 182 巷必須走到路口轉彎（路網距離需要 80 公尺，但 GPS 才移動 3 公尺），
偵探就會判定「這絕對是 GPS 雜訊在騙人，你不可能隔空穿過大樓水泥牆！」強制將軌跡鎖定在 169 巷，
徹底消滅巷弄乒乓橫跳！
"""

import math
from typing import List, Dict, Any, Optional, Tuple
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing
)
from nmap.spatial.pure_geometry import (
    find_closest_point_on_line,
    snap_pedestrian_to_road
)


class HmmMapMatcher:
    """
    基於維特比 (Viterbi) 演算法的輕量純 Python 行人路網拓撲地圖匹配器。
    """

    def __init__(
        self,
        sigma_z: float = 4.5,      # GPS 測量誤差標準差 (公尺，行人都市環境約 4~6m)
        beta: float = 5.0,         # 路網轉移距離差異衰減尺度 (公尺)
        window_size: int = 4       # 維特比時序滑動窗口深度
    ):
        self.sigma_z = sigma_z
        self.beta = beta
        self.window_size = window_size

        # 時序狀態緩衝區：每筆記錄包含 (timestamp, raw_lat, raw_lon, candidates, viterbi_scores)
        self.trellis: List[Dict[str, Any]] = []
        self.current_matched_road_id: Optional[Any] = None
        self.current_matched_road_name: str = ""
        self.current_side: str = "center"

    def reset(self):
        """重置匹配狀態（如發生長距離瞬移或重新定位時）"""
        self.trellis.clear()
        self.current_matched_road_id = None
        self.current_matched_road_name = ""
        self.current_side = "center"

    def match(
        self,
        lat: float,
        lon: float,
        user_heading: Optional[float] = None,
        candidate_roads: Optional[List[Dict[str, Any]]] = None,
        road_graph: Optional[Any] = None
    ) -> Tuple[Optional[Dict[str, Any]], float, float, str]:
        """
        輸入當前 GPS 點與候選道路列表，輸出最佳路網匹配結果。

        @param lat: GPS 原始緯度
        @param lon: GPS 原始經度
        @param user_heading: 使用者當前行進真北朝向
        @param candidate_roads: 方圓 25 公尺內候選道路物件列表
        @param road_graph: NetworkX 道路拓撲圖（可選）
        @return: (best_road, snapped_lat, snapped_lon, side)
        """
        if not candidate_roads:
            return None, lat, lon, "center"

        # 1. 候選投影點計算與發射機率 (Emission Probability)
        step_candidates: List[Dict[str, Any]] = []
        for road in candidate_roads:
            geom = road.get("geometry", [])
            if len(geom) < 2:
                continue

            dist_m, proj_lat, proj_lon = find_closest_point_on_line(lat, lon, geom)
            if dist_m > 30.0:
                continue  # 忽略過遠之道路

            # 計算高斯發射對數機率：log P(z | r) = - (d^2) / (2 * sigma^2)
            emission_log_p = - (dist_m * dist_m) / (2.0 * self.sigma_z * self.sigma_z)

            # 行走朝向一致性加權：若道路方向與前進方向垂直，施加懲罰
            if user_heading is not None and user_heading >= 0 and len(geom) >= 2:
                seg_bearing = calculate_bearing(geom[0][0], geom[0][1], geom[-1][0], geom[-1][1])
                diff = abs((user_heading - seg_bearing + 180.0) % 360.0 - 180.0)
                axis_diff = min(diff, 180.0 - diff)
                if axis_diff > 55.0:
                    emission_log_p -= 2.8  # 垂直橫向小巷嚴重降分
                elif axis_diff < 30.0:
                    emission_log_p += 1.2  # 同向道路給予獎勵

            step_candidates.append({
                "road": road,
                "road_id": road.get("id") or road.get("name") or str(geom[0]),
                "road_name": road.get("name", ""),
                "dist_m": dist_m,
                "proj_lat": proj_lat,
                "proj_lon": proj_lon,
                "emission_log_p": emission_log_p
            })

        if not step_candidates:
            return None, lat, lon, "center"

        # 2. 維特比動態規劃更新 (Viterbi Trellis Update)
        viterbi_scores: Dict[str, Tuple[float, Optional[str]]] = {} # road_id -> (max_log_score, best_prev_id)

        if not self.trellis:
            # 第一個點：初始化機率
            for cand in step_candidates:
                viterbi_scores[cand["road_id"]] = (cand["emission_log_p"], None)
        else:
            prev_step = self.trellis[-1]
            prev_lat = prev_step["raw_lat"]
            prev_lon = prev_step["raw_lon"]
            euc_displacement = haversine_distance(prev_lat, prev_lon, lat, lon)
            prev_scores = prev_step["viterbi_scores"]

            for curr_cand in step_candidates:
                c_id = curr_cand["road_id"]
                c_road = curr_cand["road"]
                c_lat = curr_cand["proj_lat"]
                c_lon = curr_cand["proj_lon"]

                best_prev_score = -1e9
                best_prev_id = None

                for prev_cand in prev_step["candidates"]:
                    p_id = prev_cand["road_id"]
                    p_score = prev_scores.get(p_id, (-1e9, None))[0]
                    p_road = prev_cand["road"]
                    p_lat = prev_cand["proj_lat"]
                    p_lon = prev_cand["proj_lon"]

                    # 計算路網轉移距離 (Network Distance)
                    if p_id == c_id:
                        # 同一條道路：路網距離約等於兩投影點沿線距離
                        net_dist = haversine_distance(p_lat, p_lon, c_lat, c_lon)
                    else:
                        # 跨道路轉移：檢查兩道路是否有交會路口
                        is_connected = False
                        if p_road.get("name") and p_road.get("name") == c_road.get("name"):
                            is_connected = True
                            net_dist = haversine_distance(p_lat, p_lon, c_lat, c_lon)
                        elif road_graph is not None:
                            # 若有拓撲圖可查最短路徑
                            u = p_road.get("u")
                            v = c_road.get("v")
                            if u is not None and v is not None and road_graph.has_edge(u, v):
                                is_connected = True
                                net_dist = haversine_distance(p_lat, p_lon, c_lat, c_lon) * 1.2
                            else:
                                is_connected = False
                                net_dist = 999.0
                        else:
                            # 檢查幾何相交或端點銜接（支援 T 字路口、十字路口與巷弄銜接）
                            p_geom = p_road.get("geometry", [])
                            c_geom = c_road.get("geometry", [])
                            if p_geom and c_geom:
                                d_connect = min(
                                    find_closest_point_on_line(p_geom[0][0], p_geom[0][1], c_geom)[0],
                                    find_closest_point_on_line(p_geom[-1][0], p_geom[-1][1], c_geom)[0],
                                    find_closest_point_on_line(c_geom[0][0], c_geom[0][1], p_geom)[0],
                                    find_closest_point_on_line(c_geom[-1][0], c_geom[-1][1], p_geom)[0]
                                )
                                if d_connect < 8.5:
                                    is_connected = True
                                    net_dist = haversine_distance(p_lat, p_lon, c_lat, c_lon) * 1.15
                                else:
                                    is_connected = False
                                    net_dist = 999.0
                            else:
                                is_connected = False
                                net_dist = 999.0

                    # 轉移機率：比較 (路網長度 - 歐式位移)
                    # 若兩平行巷弄無連通卻橫跳，net_dist 極大，轉移機率直接斷崖暴跌！
                    dist_diff = abs(net_dist - euc_displacement)
                    trans_log_p = - dist_diff / self.beta

                    total_score = p_score + trans_log_p
                    if total_score > best_prev_score:
                        best_prev_score = total_score
                        best_prev_id = p_id

                viterbi_scores[c_id] = (best_prev_score + curr_cand["emission_log_p"], best_prev_id)

        # 3. 找出當前最佳狀態
        best_candidate = None
        max_final_score = -1e9
        for cand in step_candidates:
            score = viterbi_scores.get(cand["road_id"], (-1e9, None))[0]
            if score > max_final_score:
                max_final_score = score
                best_candidate = cand

        # 存入滑動歷史
        self.trellis.append({
            "raw_lat": lat,
            "raw_lon": lon,
            "candidates": step_candidates,
            "viterbi_scores": viterbi_scores
        })
        if len(self.trellis) > self.window_size:
            self.trellis.pop(0)

        if best_candidate is None:
            return None, lat, lon, "center"

        matched_road = best_candidate["road"]
        self.current_matched_road_id = best_candidate["road_id"]
        self.current_matched_road_name = best_candidate["road_name"]

        # 4. 呼叫自適應人行道/車道法向量偏移 (寬路分側、窄巷居中)
        geom = matched_road.get("geometry", [])
        _, snap_lat, snap_lon, side = snap_pedestrian_to_road(
            lat, lon, geom, matched_road,
            last_side=self.current_side,
            user_heading=user_heading
        )
        self.current_side = side

        return matched_road, snap_lat, snap_lon, side
