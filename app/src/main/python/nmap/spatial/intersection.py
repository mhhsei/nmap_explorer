"""
路口與行人過馬路安全性分析器 (Intersection & Crossing Safety Analyzer)

作用：
1. 路口型態辨識：分析路網拓撲圖節點的連接度 (degree)，自動辨別「直行道路」、「T字路口」、「十字路口」、「五岔路」或「圓環」。
2. 行人無障礙設施評估：
   - 斑馬線 (Crossings)：回報距離、鐘點方位、是否有行人號誌、是否有導盲磚。
   - 有聲號誌 (Acoustic Signals)：回報是否有布穀鳥聲、蟋蟀聲等無障礙有聲導引。
3. 分支走向導覽：精確指出例如「2點鐘方向往北新路一段」、「9點鐘方向往中正路」。
"""
import math
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
        # 依據緯度餘弦校正經度搜尋半徑，消除台灣地區 9.4% 的東西向檢索盲區
        cos_lat = max(math.cos(math.radians(lat)), 0.1)
        radius_deg_lon = max_distance_m / (111139.0 * cos_lat)
        radius_deg_lat = max_distance_m / 111139.0
        bounds = (lon - radius_deg_lon, lat - radius_deg_lat, lon + radius_deg_lon, lat + radius_deg_lat)

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

        # 3. 藉由空間網格檢索拓撲路口節點 (degree >= 3，延伸搜尋下一個路口，最遠 500 公尺)
        junction_type = "直行道路"
        closest_junction_dist = 999.0
        closest_junction_t_brng = 0.0
        closest_junction_rel_brng = 0.0
        intersecting_roads = set()
        branches_info = []
        if curr_road_info is None:
            curr_road_info = world_model.get_road_info(lat, lon, heading_deg)
        curr_street = curr_road_info.get("street_name", "")

        # 延伸至前方 500 公尺搜尋下一個實體路口，消除距離限制
        max_junction_distance_m = max(max_distance_m, 500.0)
        j_radius_deg_lon = max_junction_distance_m / (111139.0 * cos_lat)
        j_radius_deg_lat = max_junction_distance_m / 111139.0
        j_bounds = (lon - j_radius_deg_lon, lat - j_radius_deg_lat, lon + j_radius_deg_lon, lat + j_radius_deg_lat)
        closest_junction_meta = {}

        for item in world_model.junction_rtree.intersection(j_bounds, objects=True):
            node_id, degree, n_lat, n_lon = item.object[:4]
            junction_meta = item.object[4] if len(item.object) > 4 else {}
            dist = haversine_distance(lat, lon, n_lat, n_lon)
            
            if dist <= max_junction_distance_m:
                t_brng = calculate_bearing(lat, lon, n_lat, n_lon)
                rel_brng = relative_bearing(heading_deg, t_brng)
                # 關注前方視野 (朝向 ±75° 以內) 或近距離但非身後 (< 12m 且 abs(rel_brng) <= 90°) 的路口節點
                is_front_junction = abs(rel_brng) <= 75 or (dist < 12.0 and abs(rel_brng) <= 90)
                if is_front_junction and dist < closest_junction_dist:
                    physical_neighbors = (set(world_model.road_graph.predecessors(node_id)) | set(world_model.road_graph.successors(node_id))) - {node_id}
                    real_degree = len(physical_neighbors)
                    if real_degree >= 3:
                        closest_junction_dist = dist
                        closest_junction_t_brng = t_brng
                        closest_junction_rel_brng = rel_brng
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
            closest_junction_rel_brng = nearby_crossings[0].get("relative_bearing_deg", 0.0)
            closest_junction_t_brng = (heading_deg + closest_junction_rel_brng) % 360.0

        # 提取融合號誌與無障礙安全情報
        is_signalized = closest_junction_meta.get("is_signalized", False)
        has_aps = closest_junction_meta.get("has_aps", False)
        sound_desc = closest_junction_meta.get("sound_desc", "")
        has_refuge_island = closest_junction_meta.get("has_refuge_island", False)
        has_button = closest_junction_meta.get("has_button", False)
        button_guide = closest_junction_meta.get("button_guide", "")
        signal_name = closest_junction_meta.get("signal_name", "")

        # 號誌與相機導引目標方位：優先使用最近的號誌實體，若無則使用路口幾何中心
        target_signal_brng = closest_junction_t_brng
        target_signal_clock = bearing_to_clock_position(closest_junction_rel_brng)
        if nearby_signals:
            # 優先以最近之前方號誌作為導引標的
            target_signal_clock = nearby_signals[0].get("clock_position", target_signal_clock)
            sig_rel_brng = nearby_signals[0].get("relative_bearing_deg", 0.0)
            target_signal_brng = (heading_deg + sig_rel_brng) % 360.0

        # 組合親切易懂的路口專屬名稱 (例如「北新路與大忠街口」或「大忠街口」)
        junction_display_name = junction_type
        sorted_intersecting_roads = sorted(intersecting_roads)
        if signal_name:
            junction_display_name = signal_name
        elif sorted_intersecting_roads:
            cross_first = sorted_intersecting_roads[0]
            junction_display_name = f"{cross_first}口" if not cross_first.endswith("口") else cross_first
        elif junction_type != "直行道路":
            junction_display_name = "路口"

        # 構建視障極簡「鐘點走向」動態分支導引 (Dynamic Clock-Position Branches)
        # 排除當前行進道路與正後方來時路，只提取前方與側向的目標分支
        valid_branches = [
            b for b in branches_info 
            if b.get("road_name") 
            and b.get("road_name") != curr_street 
            and not b.get("road_name").startswith("無名") 
            and abs(b.get("relative_angle", 0)) < 140 
            and "來時路" not in b.get("relative_direction", "")
        ]

        concise_branches_parts = []
        for b in valid_branches:
            r_name = b["road_name"]
            clock = b.get("clock_position", "")
            r_dir = b.get("relative_direction", "")
            # 簡明左右前綴：若有多個分支，標註左右以強化空間感 (例如: "左 10點鐘 大忠街")
            prefix = ""
            if "左" in r_dir and len(valid_branches) > 1:
                prefix = "左 "
            elif "右" in r_dir and len(valid_branches) > 1:
                prefix = "右 "
            
            if clock:
                concise_branches_parts.append(f"{prefix}{clock} {r_name}")
            else:
                concise_branches_parts.append(f"{r_dir} {r_name}")

        concise_branches_str = "，".join(concise_branches_parts)
        if not concise_branches_str:
            concise_branches_str = junction_display_name if junction_display_name not in ["十字路口", "T字/岔路口", "直行道路"] else "前方交會"

        aps_tag = "（有聲號誌）" if has_aps else ("（紅綠燈）" if is_signalized else "")
        concise_approaching_prompt = f"接近路口{aps_tag}，{concise_branches_str}"
        concise_passing_prompt = "正通過路口，請直線前進"

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

        if sorted_intersecting_roads:
            roads_str = "、".join(sorted_intersecting_roads)
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
                report_lines.append(f"下一個路口約在前方 {round(closest_junction_dist)} 公尺處【{junction_display_name}】。")

            if is_signalized:
                if has_aps:
                    report_lines.append(f"號誌設施：設有行車紅綠燈與【{sound_desc or '視障有聲號誌'}】。")
                else:
                    report_lines.append("號誌設施：設有行車紅綠燈管制，無有聲號誌。")
                if has_button:
                    report_lines.append(f"按鈕指引：{button_guide or '路旁柱子設有行人觸控按鈕'}。")
            else:
                report_lines.append("號誌設施：此處為無號誌路口，過馬路請注意左右來車。")

            if has_refuge_island:
                report_lines.append("安全設施：馬路中央設有行人庇護島，可分段通過。")

            # 即將交會道路提示
            if sorted_intersecting_roads:
                report_lines.append(f"即將交會：{'、'.join(sorted_intersecting_roads)}。")

            # 分支走向提示 (讓視障者知道各道路通往幾點鐘方向)
            if branches_info:
                branches_desc = []
                for b in branches_info:
                    branches_desc.append(f"• {b['relative_direction']} ({b['clock_position']}) 往：{b['road_name']}")
                report_lines.append("各分支走向：\n" + "\n".join(branches_desc))

            if nearby_crossings:
                c = nearby_crossings[0]
                sig_desc = "設有行人專用號誌" if (is_signalized or c["crossing_signals"] in ["yes", "traffic_signals"]) else "無行人號誌"
                tac_desc = "鋪設導盲磚" if c["tactile_paving"] == "yes" else "無導盲磚"
                report_lines.append(f"斑馬線：前方 {c['distance_m']} 公尺 ({c['clock_position']}) 有行人穿越道 ({sig_desc}，{tac_desc})。")
        else:
            report_lines.append("前方為直行道路，暫無明顯十字或T字交會路口。")
            if nearby_crossings:
                c = nearby_crossings[0]
                report_lines.append(f"前方 {c['distance_m']} 公尺處設有斑馬線。")

        detailed_report_str = "\n".join(report_lines)

        return {
            "junction_type": junction_type,
            "junction_name": junction_display_name,
            "junction_distance_m": round(closest_junction_dist, 1) if closest_junction_dist < 900 else None,
            "bearing_deg": round(target_signal_brng, 1),
            "clock_position": target_signal_clock,
            "is_signalized": is_signalized,
            "has_aps": has_aps,
            "sound_desc": sound_desc,
            "has_refuge_island": has_refuge_island,
            "has_button": has_button,
            "button_guide": button_guide,
            "intersecting_roads": list(intersecting_roads),
            "branches_info": branches_info,
            "concise_branches": concise_branches_str,
            "concise_approaching_prompt": concise_approaching_prompt,
            "concise_passing_prompt": concise_passing_prompt,
            "crossings": nearby_crossings,
            "traffic_signals": nearby_signals,
            "signal_nearby": is_signalized,
            "safety_summary": "；".join(safety_notes),
            "detailed_report": detailed_report_str
        }
