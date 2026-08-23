"""
無障礙步行路徑規劃引擎 (A* Navigation Engine)

作用：
1. 利用 NetworkX 圖形拓撲結構與 A* 啟發式搜尋演算法 (A-Star Algorithm)。
2. 計算從當前位置到目標地標的最短步行無障礙路徑。
3. 產生適合語音逐筆朗讀的「轉向指引清單」（例如：「首先朝右前方沿北新路前進」、「前進 45 公尺後右轉進入新生街」）。
"""
import networkx as nx
import math
from typing import List, Dict, Any, Optional
from nmap.spatial.geometry import haversine_distance, calculate_bearing, bearing_to_relative_direction, relative_bearing


class Navigator:
    """
    步行路徑導航員
    """
    def __init__(self, road_graph: nx.MultiDiGraph):
        self.graph = road_graph

    def _find_nearest_node(self, lat: float, lon: float) -> Optional[str]:
        """在路網拓撲圖中尋找距離經緯度座標最近的交叉點節點 (Node)"""
        best_node = None
        min_dist = float('inf')
        for node_id, data in self.graph.nodes(data=True):
            dist = haversine_distance(lat, lon, data['lat'], data['lon'])
            if dist < min_dist:
                min_dist = dist
                best_node = node_id
        return best_node

    def calculate_route(self, start_lat: float, start_lon: float, start_heading: float, end_lat: float, end_lon: float, destination_name: str) -> Dict[str, Any]:
        """
        【計算 A* 最佳無障礙路徑並產出 Turn-by-Turn 逐步導航指引】
        """
        if len(self.graph.nodes) == 0:
            return {"success": False, "message": "目前區域無道路網，無法導航。"}

        start_node = self._find_nearest_node(start_lat, start_lon)
        end_node = self._find_nearest_node(end_lat, end_lon)

        if not start_node or not end_node:
            return {"success": False, "message": "無法在地圖上找到合適的起點或終點道路。"}

        try:
            # 使用 A* 演算法，邊權重為公尺距離，啟發式函數為半正矢大圓距離
            path = nx.astar_path(
                self.graph, 
                start_node, 
                end_node, 
                heuristic=lambda u, v: haversine_distance(
                    self.graph.nodes[u]['lat'], self.graph.nodes[u]['lon'],
                    self.graph.nodes[v]['lat'], self.graph.nodes[v]['lon']
                ),
                weight="weight"
            )
        except nx.NetworkXNoPath:
            return {"success": False, "message": f"無法找到前往 {destination_name} 的連通路徑。"}

        instructions = self._generate_turn_instructions(path, start_heading)
        total_dist = sum(inst['distance_m'] for inst in instructions)

        return {
            "success": True,
            "message": f"開始導航至 {destination_name}。總長 {total_dist:.0f} 公尺，共 {len(instructions)} 個步驟。",
            "target": destination_name,
            "path_nodes": path,
            "instructions": instructions,
            "total_distance_m": total_dist
        }


    def _generate_turn_instructions(self, path: List[str], initial_heading: float) -> List[Dict[str, Any]]:
        instructions = []
        current_heading = initial_heading
        
        current_segment_name = None
        current_segment_dist = 0.0
        
        for i in range(len(path) - 1):
            u = path[i]
            v = path[i+1]
            
            edge_data = min(self.graph.get_edge_data(u, v).values(), key=lambda x: x['weight'])
            dist = edge_data['weight']
            road_name = edge_data.get('name', '無名道路')
            bearing = edge_data['bearing']
            
            if i == 0:
                current_segment_name = road_name
                rel_bearing = relative_bearing(current_heading, bearing)
                direction = bearing_to_relative_direction(rel_bearing)
                instructions.append({
                    "action": "start",
                    "text": f"首先，朝 {direction} 沿著 {road_name} 前進",
                    "distance_m": 0,
                    "target_bearing": bearing
                })
            elif road_name != current_segment_name:
                # Turn detected
                rel_bearing = relative_bearing(current_heading, bearing)
                direction = "右轉" if rel_bearing > 20 else "左轉" if rel_bearing < -20 else "直行"
                
                if direction != "直行":
                    instructions.append({
                        "action": "turn",
                        "text": f"前進 {current_segment_dist:.0f} 公尺後，{direction} 進入 {road_name}",
                        "distance_m": current_segment_dist,
                        "target_bearing": bearing
                    })
                    current_segment_dist = 0
                current_segment_name = road_name
            
            current_segment_dist += dist
            current_heading = bearing
            
        if current_segment_dist > 0:
            instructions.append({
                "action": "arrive",
                "text": f"繼續直行 {current_segment_dist:.0f} 公尺即可抵達目的地",
                "distance_m": current_segment_dist,
                "target_bearing": current_heading
            })
            
        return instructions
