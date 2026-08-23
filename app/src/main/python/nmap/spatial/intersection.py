"""
路口與行人過馬路安全性分析器 (Intersection & Crossing Safety Analyzer)

作用：
1. 路口型態辨識：分析路網拓撲圖節點的連接度 (degree)，自動辨別「直行道路」、「T字路口」、「十字路口」、「五岔路」或「圓環」。
2. 行人無障礙設施評估：
   - 斑馬線 (Crossings)：回報距離、鐘點方位、是否有行人號誌、是否有導盲磚。
   - 有聲號誌 (Acoustic Signals)：回報是否有布穀鳥聲、蟋蟀聲等無障礙有聲導引。
3. 分支走向導覽：精確指出例如「2點鐘方向往北新路一段」、「9點鐘方向往中正路」。
"""
from typing import List, Dict, Any, Optional
from nmap.spatial.geometry import (
    haversine_distance,
    calculate_bearing,
    relative_bearing,
    bearing_to_clock_position,
    bearing_to_relative_direction
)
from nmap.spatial.world_model import WorldModel


class IntersectionAnalyzer:
    """
    路口與行人穿越安全性分析器
    """

    def analyze(self, lat: float, lon: float, heading_deg: float, world_model: WorldModel, max_distance_m: float = 60.0, signal_announce_distance_m: float = 10.0) -> Dict[str, Any]:
        """
        【分析前方 60 公尺內的路口結構與過馬路安全性】
        """
        # 搜尋前方附近的斑馬線節點
        nearby_crossings = []
        for cr in world_model.crossings:
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

        # 搜尋前方附近的紅綠燈號誌
        nearby_signals = []
        for ts in world_model.traffic_signals:
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

        # 藉由檢查道路拓撲節點的度數 (degree) 來判定路口型態
        junction_type = "直行道路"
        closest_junction_dist = 999.0


        intersecting_roads = set()
        branches_info = []
        curr_road_info = world_model.get_road_info(lat, lon, heading_deg)
        curr_street = curr_road_info.get("street_name", "")

        for node_id, degree in world_model.road_graph.degree():
            node_data = world_model.road_graph.nodes[node_id]
            n_lat, n_lon = node_data["lat"], node_data["lon"]
            dist = haversine_distance(lat, lon, n_lat, n_lon)
            
            if dist <= max_distance_m:
                t_brng = calculate_bearing(lat, lon, n_lat, n_lon)
                rel_brng = relative_bearing(heading_deg, t_brng)
                if (abs(rel_brng) <= 90 or dist < 15.0) and dist < closest_junction_dist:
                    if degree >= 3:
                        closest_junction_dist = dist
                        junction_type = "十字路口" if degree >= 4 else "T字/岔路口"
                        
                        intersecting_roads.clear()
                        branches_info.clear()
                        edges = world_model.road_graph.out_edges(node_id, data=True)
                        for u, v, data in edges:
                            road_name = data.get("name", "未命名道路")
                            if road_name and road_name != curr_street and road_name != "未命名道路":
                                intersecting_roads.add(road_name)
                            
                            v_data = world_model.road_graph.nodes[v]
                            v_lat, v_lon = v_data["lat"], v_data["lon"]
                            out_brng = calculate_bearing(n_lat, n_lon, v_lat, v_lon)
                            out_rel = relative_bearing(heading_deg, out_brng)
                            branches_info.append({
                                "road_name": road_name,
                                "relative_direction": bearing_to_relative_direction(out_rel),
                                "clock_position": bearing_to_clock_position(out_rel)
                            })

        # If crossing exists nearby, confirm junction presence
        if junction_type == "直行道路" and nearby_crossings:
            junction_type = "行人穿越路口"
            closest_junction_dist = nearby_crossings[0]["distance_m"]

        # Build accessibility & safety summary text for NVDA
        safety_notes = []
        if nearby_crossings:
            c = nearby_crossings[0]
            sig_text = "有行人專用號誌" if c["crossing_signals"] in ["yes", "traffic_signals"] else "無號誌管制"
            tac_text = "有導盲磚" if c["tactile_paving"] == "yes" else "未標示導盲磚"
            safety_notes.append(f"前方 {c['distance_m']} 公尺 ({c['clock_position']}) 有斑馬線 ({sig_text}，{tac_text})")
        else:
            safety_notes.append("前方 50 公尺內暫無明顯斑馬線")

        signal_nearby = False
        if nearby_signals and nearby_signals[0]["distance_m"] <= signal_announce_distance_m:
            signal_nearby = True
            s = nearby_signals[0]
            sound_text = "設有語音導引號誌 (Acoustic Signal)" if s["sound"] == "yes" else "未標示語音號誌"
            safety_notes.append(f"設有交通號誌 ({sound_text})")

        if intersecting_roads:
            roads_str = "、".join(intersecting_roads)
            safety_notes.insert(0, f"即將進入與 {roads_str} 交會之{junction_type}")
        else:
            if junction_type != "直行道路":
                safety_notes.insert(0, f"前方 {closest_junction_dist:.1f} 公尺處有{junction_type}")

        # Build comprehensive spoken report for blind exploration
        report_lines = []
        if junction_type != "直行道路" and closest_junction_dist < 900:
            report_lines.append(f"前方 {round(closest_junction_dist)} 公尺為【{junction_type}】。")
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
                sig = "有行人專用號誌" if c["crossing_signals"] in ["yes", "traffic_signals"] else "無號誌管制"
                report_lines.append(f"過馬路設施：前方 {c['distance_m']} 公尺設有斑馬線（{sig}）。")
        else:
            curr_road = world_model.get_road_info(lat, lon, heading_deg)
            curr_name = curr_road.get("street_name", "道路")
            report_lines.append(f"前方 60 公尺內為直行道路，目前所在為【{curr_name}】。")
            if nearby_crossings:
                c = nearby_crossings[0]
                report_lines.append(f"前方 {c['distance_m']} 公尺處設有斑馬線。")

        detailed_report_str = "\n".join(report_lines)

        return {
            "junction_type": junction_type,
            "junction_distance_m": round(closest_junction_dist, 1) if closest_junction_dist < 900 else None,
            "intersecting_roads": list(intersecting_roads),
            "branches_info": branches_info,
            "crossings": nearby_crossings,
            "traffic_signals": nearby_signals,
            "signal_nearby": signal_nearby,
            "safety_summary": "；".join(safety_notes),
            "detailed_report": detailed_report_str
        }
