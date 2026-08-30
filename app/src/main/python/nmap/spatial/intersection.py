"""
路口與行人過馬路安全性分析器 (Intersection & Crossing Safety Analyzer)

作用：
1. 路口型態辨識：分析路網拓撲圖節點的連接度 (degree)，自動辨別「直行道路」、「T字路口」、「十字路口」、「五岔路」或「圓環」。
2. 行人無障礙設施評估：
   - 斑馬線 (Crossings)：回報距離、鐘點方位、是否有行人號誌、是否有導盲磚。
   - 有聲號誌 (Acoustic Signals)：回報是否有布穀鳥聲、蟋蟀聲等無障礙有聲導引。
3. 分支走向導覽：精確指出例如「2點鐘方向往北新路一段」、「9點鐘方向往中正路」。
"""
import logging
from typing import List, Dict, Any, Optional
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_relative_direction
)
from nmap.spatial.world_model import WorldModel

logger = logging.getLogger("IntersectionAnalyzer")


class IntersectionAnalyzer:
    """
    路口與行人穿越安全性分析器
    """

    def analyze(self, lat: float, lon: float, heading_deg: float, world_model: WorldModel, max_distance_m: float = 60.0, signal_announce_distance_m: float = 10.0, curr_road_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        【分析前方 60 公尺內的路口結構與過馬路安全性】
        作用：
        利用 WorldModel 預先建立的空間網格索引 (crossing_rtree, traffic_signal_rtree, junction_rtree)，
        只檢索方圓 60 公尺內的實體設施與路口節點，將查詢複雜度由 O(N) 降至 O(1)。
        """
        radius_deg = max_distance_m / 111139.0
        bounds = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)

        # 1. 空間索引搜尋前方附近的斑馬線節點
        nearby_crossings = []
        for item in world_model.crossing_rtree.intersection(bounds, objects=True):
            cr = item.object
            c_lat, c_lon = cr["lat"], cr["lon"]
            dist = haversine_distance(lat, lon, c_lat, c_lon)
            if dist <= max_distance_m:
                t_brng = calculate_bearing(lat, lon, c_lat, c_lon)
                rel_brng = relative_bearing(heading_deg, t_brng)
                
                # 篩選前方視野內（朝向 ±100 度角以內）的設施
                if abs(rel_brng) <= 100:
                    clock = bearing_to_clock_position(rel_brng)
                    rel_dir = bearing_to_relative_direction(rel_brng)
                    nearby_crossings.append({
                        "id": cr["id"],
                        "distance_m": round(dist, 1),
                        "relative_bearing_deg": round(rel_brng, 1),
                        "clock_position": clock,
                        "relative_direction": rel_dir,
                        "crossing_type": cr.get("crossing_type", "zebra"),
                        "crossing_signals": cr.get("crossing_signals", "no"),
                        "tactile_paving": cr.get("tactile_paving", "unknown")
                    })

        nearby_crossings.sort(key=lambda x: x["distance_m"])

        # 2. 空間索引搜尋前方附近的紅綠燈號誌
        nearby_signals = []
        for item in world_model.traffic_signal_rtree.intersection(bounds, objects=True):
            ts = item.object
            s_lat, s_lon = ts["lat"], ts["lon"]
            dist = haversine_distance(lat, lon, s_lat, s_lon)
            if dist <= max_distance_m:
                t_brng = calculate_bearing(lat, lon, s_lat, s_lon)
                rel_brng = relative_bearing(heading_deg, t_brng)
                if abs(rel_brng) <= 100:
                    clock = bearing_to_clock_position(rel_brng)
                    rel_dir = bearing_to_relative_direction(rel_brng)
                    nearby_signals.append({
                        "id": ts["id"],
                        "distance_m": round(dist, 1),
                        "relative_bearing_deg": round(rel_brng, 1),
                        "clock_position": clock,
                        "relative_direction": rel_dir,
                        "sound": ts.get("sound", "unknown")
                    })

        nearby_signals.sort(key=lambda x: x["distance_m"])

        # 3. 藉由空間網格檢索拓撲路口節點 (degree >= 3)
        junction_type = "直行道路"
        closest_junction_dist = 999.0

        intersecting_roads = set()
        branches_info = []
        if curr_road_info is None:
            curr_road_info = world_model.get_road_info(lat, lon, heading_deg)
        curr_street = curr_road_info.get("street_name", "")

        # 3. 藉由空間網格檢索拓撲路口節點 (degree >= 3，延伸搜尋下一個路口，最遠 500 公尺)
        junction_type = "直行道路"
        closest_junction_dist = 999.0

        intersecting_roads = set()
        branches_info = []
        if curr_road_info is None:
            curr_road_info = world_model.get_road_info(lat, lon, heading_deg)
        curr_street = curr_road_info.get("street_name", "")

        # 延伸至前方 500 公尺搜尋下一個實體路口，消除距離限制
        max_junction_distance_m = max(max_distance_m, 500.0)
        j_radius_deg = max_junction_distance_m / 111139.0
        j_bounds = (lon - j_radius_deg, lat - j_radius_deg, lon + j_radius_deg, lat + j_radius_deg)
        closest_junction_meta = {}

        for item in world_model.junction_rtree.intersection(j_bounds, objects=True):
            node_id, degree, n_lat, n_lon = item.object[:4]
            junction_meta = item.object[4] if len(item.object) > 4 else {}
            dist = haversine_distance(lat, lon, n_lat, n_lon)
            
            if dist <= max_junction_distance_m:
                t_brng = calculate_bearing(lat, lon, n_lat, n_lon)
                rel_brng = relative_bearing(heading_deg, t_brng)
                # 關注前方視角 (朝向 ±85° 以內) 或極度接近 (< 15m) 的路口節點
                if (abs(rel_brng) <= 85 or dist < 15.0) and dist < closest_junction_dist:
                    physical_neighbors = (set(world_model.road_graph.predecessors(node_id)) | set(world_model.road_graph.successors(node_id))) - {node_id}
                    real_degree = len(physical_neighbors)
                    if real_degree >= 3:
                        closest_junction_dist = dist
                        closest_junction_meta = junction_meta
                        junction_type = "十字路口" if real_degree >= 4 else "T字/岔路口"
                        
                        intersecting_roads.clear()
                        branches_info.clear()
                        visited_neighbors = set()

                        for v in physical_neighbors:
                            if v in visited_neighbors:
                                continue
                            visited_neighbors.add(v)

                            # 獲取連接邊的屬性
                            edge_data = None
                            if world_model.road_graph.has_edge(node_id, v):
                                edge_data = list(world_model.road_graph[node_id][v].values())[0]
                            elif world_model.road_graph.has_edge(v, node_id):
                                edge_data = list(world_model.road_graph[v][node_id].values())[0]

                            raw_name = edge_data.get("name", "") if edge_data else ""
                            if not raw_name or raw_name == "未命名道路":
                                highway_type = edge_data.get("road", {}).get("highway", "") if edge_data else ""
                                if highway_type in ["footway", "pedestrian", "path", "steps"]:
                                    road_name = "人行通道"
                                else:
                                    road_name = "無名巷弄"
                            else:
                                road_name = raw_name

                            if road_name and road_name != curr_street and not road_name.startswith("無名"):
                                intersecting_roads.add(road_name)

                            v_data = world_model.road_graph.nodes[v]
                            v_lat, v_lon = v_data["lat"], v_data["lon"]
                            out_brng = calculate_bearing(n_lat, n_lon, v_lat, v_lon)
                            out_rel = relative_bearing(heading_deg, out_brng)
                            
                            clock_pos = bearing_to_clock_position(out_rel)
                            rel_dir = bearing_to_relative_direction(out_rel)
                            if abs(out_rel) >= 140:
                                rel_dir = "正後方 (來時路)"

                            branches_info.append({
                                "road_name": road_name,
                                "relative_direction": rel_dir,
                                "clock_position": clock_pos,
                                "relative_angle": out_rel
                            })

                        # 按相對角度排序：前向與側向分支優先，後方來時路放最後
                        branches_info.sort(key=lambda b: abs(b.get("relative_angle", 0)))
                        logger.info(f"[JUNCTION_DETECT] node={node_id}, degree={real_degree}, type={junction_type}, dist={dist:.1f}m, intersecting={list(intersecting_roads)}")

        # If crossing exists nearby, confirm junction presence
        if junction_type == "直行道路" and nearby_crossings:
            junction_type = "行人穿越路口"
            closest_junction_dist = nearby_crossings[0]["distance_m"]

        # 提取融合號誌與無障礙安全情報
        is_signalized = closest_junction_meta.get("is_signalized", False)
        has_aps = closest_junction_meta.get("has_aps", False)
        sound_desc = closest_junction_meta.get("sound_desc", "")
        has_refuge_island = closest_junction_meta.get("has_refuge_island", False)
        has_button = closest_junction_meta.get("has_button", False)
        button_guide = closest_junction_meta.get("button_guide", "")
        signal_name = closest_junction_meta.get("signal_name", "")

        # 組合親切易懂的路口專屬名稱 (例如「北新路與大忠街口」或「大忠街口」)
        junction_display_name = junction_type
        if signal_name:
            junction_display_name = signal_name
        elif intersecting_roads:
            cross_first = list(intersecting_roads)[0]
            junction_display_name = f"{cross_first}口" if not cross_first.endswith("口") else cross_first

        # Build accessibility & safety summary text for NVDA
        safety_notes = []
        if is_signalized:
            if has_aps:
                safety_notes.append(f"設有紅綠燈，具備【{sound_desc or '視障有聲號誌'}】")
            else:
                safety_notes.append("設有紅綠燈管制（無有聲號誌）")
        else:
            if junction_type != "直行道路":
                safety_notes.append("⚠️ 此處為無號誌路口，過馬路請注意左右來車")

        if has_refuge_island:
            safety_notes.append("馬路中央設有行人庇護島")

        if nearby_crossings:
            c = nearby_crossings[0]
            sig_text = "有行人號誌" if (is_signalized or c["crossing_signals"] in ["yes", "traffic_signals"]) else "無號誌"
            tac_text = "有導盲磚" if c["tactile_paving"] == "yes" else "未標示導盲磚"
            safety_notes.append(f"前方 {c['distance_m']} 公尺 ({c['clock_position']}) 設有斑馬線 ({sig_text}，{tac_text})")
        else:
            safety_notes.append("前方 50 公尺內暫無明顯斑馬線")

        if intersecting_roads:
            roads_str = "、".join(intersecting_roads)
            safety_notes.insert(0, f"即將進入與 {roads_str} 交會之{junction_type}")
        else:
            if junction_type != "直行道路":
                safety_notes.insert(0, f"前方 {closest_junction_dist:.1f} 公尺處有{junction_type}")

        # Build comprehensive spoken report for blind exploration (延伸至下個路口，不限距離)
        report_lines = []
        if junction_type != "直行道路" and closest_junction_dist < 900:
            if closest_junction_dist <= 30.0:
                report_lines.append(f"前方 {round(closest_junction_dist)} 公尺為【{junction_display_name}】。")
            else:
                report_lines.append(f"前方下一個路口（約 {round(closest_junction_dist)} 公尺）為【{junction_display_name}】。")

            if intersecting_roads:
                report_lines.append(f"即將交會：{'、'.join(intersecting_roads)}。")

            # 號誌與無障礙設施說明
            if is_signalized:
                aps_info = f"，設有【{sound_desc}】有聲鳥鳴導引" if has_aps else "，無有聲號誌"
                report_lines.append(f"號誌設施：設有行車紅綠燈管制{aps_info}。")
            else:
                report_lines.append("號誌設施：⚠️ 無交通號誌管制路口，過馬路請注意左右轉彎車聲。")

            if has_refuge_island:
                report_lines.append("無障礙設施：馬路中央設有實體行人庇護島（安全島）。")

            if has_button:
                report_lines.append(f"行人觸動按鈕：{button_guide}")

            if branches_info:
                seen_branches = set()
                branch_texts = []
                for b in branches_info:
                    rname = b["road_name"]
                    key = (b["clock_position"], rname)
                    if key not in seen_branches and rname:
                        seen_branches.add(key)
                        branch_texts.append(f"• {b['relative_direction']} ({b['clock_position']}) 往：{rname}")
                if branch_texts:
                    report_lines.append("各分支走向：\n" + "\n".join(branch_texts))
            if nearby_crossings:
                c = nearby_crossings[0]
                sig = "有行人專用號誌" if (is_signalized or c["crossing_signals"] in ["yes", "traffic_signals"]) else "無號誌管制"
                report_lines.append(f"過馬路設施：前方 {c['distance_m']} 公尺設有斑馬線（{sig}）。")
        else:
            curr_road = world_model.get_road_info(lat, lon, heading_deg)
            curr_name = curr_road.get("street_name", "道路")
            report_lines.append(f"前方 500 公尺內均為直行道路，目前所在為【{curr_name}】。")
            if nearby_crossings:
                c = nearby_crossings[0]
                report_lines.append(f"前方 {c['distance_m']} 公尺處設有斑馬線。")

        detailed_report_str = "\n".join(report_lines)

        return {
            "junction_type": junction_type,
            "junction_name": junction_display_name,
            "junction_distance_m": round(closest_junction_dist, 1) if closest_junction_dist < 900 else None,
            "is_signalized": is_signalized,
            "has_aps": has_aps,
            "sound_desc": sound_desc,
            "has_refuge_island": has_refuge_island,
            "has_button": has_button,
            "button_guide": button_guide,
            "intersecting_roads": list(intersecting_roads),
            "branches_info": branches_info,
            "crossings": nearby_crossings,
            "traffic_signals": nearby_signals,
            "signal_nearby": is_signalized,
            "safety_summary": "；".join(safety_notes),
            "detailed_report": detailed_report_str
        }
