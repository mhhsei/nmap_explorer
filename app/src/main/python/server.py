#!/usr/bin/env python3
"""
【NMap 視障者無障礙數位雙生地圖 - 後端伺服器核心 (Server Core)】

為什麼選擇 Bottle 框架？
1. 極致輕量與綠色部署 (Portable Deployment)：Bottle 只有單一檔案，完全不需要額外的依賴項，
   這對於打包給視障使用者的「隨身碟免安裝版 (Zero-Configuration Portable)」至關重要。
2. 效能與回應速度：我們的核心是 R-Tree 空間索引與 NetworkX 圖學計算，API 層必須盡可能薄，
   將請求處理時間壓在 22ms 內，確保前端 NVDA 報讀的「步態回饋」達到零延遲 (Zero-Latency)。
3. RESTful 架構：將所有狀態維護於 `agent` 與 `simulation` 內，提供清晰的 JSON API 供前端 
   ARIA-Live 機制進行非同步語音渲染。
"""

import os
import sys
import json
from bottle import Bottle, request, response, static_file, run

# Ensure nmap package is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nmap.agent.explorer import ExplorerAgent
from nmap.agent.nlp_query import NLPQueryEngine
from nmap.accessibility.reporter import NVDAReporter
from nmap.spatial.street_view import StreetViewAnalyzer
from nmap.spatial.geometry import bearing_to_cardinal
from nmap.data.google_places import GooglePlacesClient
from nmap.simulation.engine import SimulationEngine

app = Bottle()
agent = ExplorerAgent(enable_sound=False) # WebUI uses Web Audio API on frontend
nlp_engine = NLPQueryEngine()
reporter = NVDAReporter()
street_analyzer = StreetViewAnalyzer()
google_places = GooglePlacesClient()
simulation = SimulationEngine()

WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def json_response(data: dict, status: int = 200):
    response.content_type = "application/json; charset=utf-8"
    response.status = status
    return json.dumps(data, ensure_ascii=False)


@app.route("/")
def index():
    return static_file("index.html", root=WEB_ROOT)


@app.route("/<filename:path>")
def serve_static(filename):
    return static_file(filename, root=WEB_ROOT)


@app.route("/api/status", method="GET")
def get_status():
    if not agent.is_loaded:
        return json_response({
            "is_loaded": False,
            "message": "尚未初始化地圖起點。請在上方搜尋列輸入地址。"
        })

    road_info = agent.world_model.get_road_info(agent.lat, agent.lon, agent.heading_deg)
    pois = agent.world_model.get_nearby_pois(agent.lat, agent.lon, agent.heading_deg, radius_m=100.0)
    buildings = agent.world_model.get_nearby_buildings(agent.lat, agent.lon, agent.heading_deg, radius_m=50.0)
    intersection = agent.intersection_analyzer.analyze(agent.lat, agent.lon, agent.heading_deg, agent.world_model)
    door_estimates = agent.world_model.get_interpolated_door_numbers(agent.lat, agent.lon, agent.heading_deg)
    full_report = reporter.generate_full_report(agent)
    concise_report = reporter.generate_concise_report(agent)
    street_scene = street_analyzer.analyze_scene(agent.lat, agent.lon, agent.heading_deg, agent.world_model)

    return json_response({
        "success": True,
        "is_loaded": True,
        "location_label": agent.location_label,
        "lat": agent.lat,
        "lon": agent.lon,
        "heading_deg": agent.heading_deg,
        "step_count": agent.step_count,
        "road_info": road_info,
        "pois": pois,
        "buildings": buildings,
        "intersection": intersection,
        "door_estimates": door_estimates,
        "full_report": full_report,
        "concise_report": concise_report,
        "street_scene": street_scene
    })


@app.route("/api/teleport", method="POST")
def teleport():
    data = request.json or {}
    location = data.get("location", "").strip()
    if not location:
        return json_response({"success": False, "message": "請提供有效的地址或座標。"}, status=400)

    ok, msg = agent.teleport(location)
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)

    return get_status()


@app.route("/api/move", method="POST")
def move():
    """
    【處理玩家空間位移 (Spatial Translation)】
    為什麼這個端點這麼重要？
    視障者在探索時，移動是最頻繁的操作（預設每步 1~5 公尺）。
    1. 首先呼叫 `agent.move()` 透過空間引擎 (NetworkX) 計算最新的 (Lat, Lon)。
    2. 接著進行碰撞檢測 (Collision Detection)，若撞牆則提早攔截。
    3. 如果啟用了「遊戲模擬模式 (Simulation Engine)」，則會額外推算動態事件 (如車輛、行人)。
    4. 最終回傳一個巨大的 `status_data` JSON，讓前端 JS 根據這個狀態樹決定要報讀什麼。
       （將 UI 渲染與資料計算徹底解耦）。
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    data = request.json or {}
    direction = data.get("direction", "forward")
    distance = data.get("distance", 5.0)

    ok, msg = agent.move(direction, distance)
    
    # 碰撞攔截：透過判斷 agent 的移動訊息，決定是否觸發碰壁音效
    is_collision = "撞擊" in msg or "碰壁" in msg

    # Simulation mode integration
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = json.loads(get_status())
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    status_data["is_collision"] = is_collision

    return json_response(status_data)
    
@app.route("/api/jump_intersection", method="POST")
def jump_intersection():
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    ok, msg = agent.jump_to_next_intersection()
    
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = json.loads(get_status())
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    status_data["is_collision"] = "障礙物" in msg

    return json_response(status_data)

@app.route("/api/snap_turn", method="POST")
def snap_turn():
    data = request.json
    direction = data.get("direction", "left")
    ok, msg = agent.snap_to_branch(direction)
    
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = json.loads(get_status())
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg

    return json_response(status_data)

@app.route("/api/gps", method="POST")
def update_gps():
    data = request.json or {}
    lat = data.get("lat")
    lon = data.get("lon")
    heading = data.get("heading_deg")
    accuracy = data.get("accuracy", 10.0)

    if lat is None or lon is None:
        return json_response({"success": False, "message": "缺少 GPS 座標。"}, status=400)

    ok, msg = agent.update_gps_position(lat, lon, heading, accuracy)

    status_data = json.loads(get_status())
    status_data["action_message"] = msg
    status_data["is_collision"] = False
    return json_response(status_data)


@app.route("/api/sync", method="POST")
def sync():
    data = request.json or {}
    lat = data.get("lat")
    lon = data.get("lon")
    heading = data.get("heading_deg")
    dist = data.get("distance_moved", 0.0)
    is_gps = data.get("is_gps", False)

    if lat is None or lon is None or heading is None:
        return json_response({"success": False, "message": "缺少必要的同步參數。"}, status=400)

    if is_gps:
        ok, msg = agent.update_gps_position(lat, lon, heading)
        is_collision = False
    else:
        ok, msg = agent.sync_position(lat, lon, heading, dist)
        is_collision = not ok

    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = json.loads(get_status())
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    status_data["is_collision"] = is_collision

    return json_response(status_data)


@app.route("/api/turn", method="POST")
def turn():
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    data = request.json or {}
    target = data.get("target", "right")

    if target in ["north", "east", "south", "west"]:
        ok, msg = agent.face(target)
    else:
        ok, msg = agent.turn(target)

    # Simulation mode integration
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = json.loads(get_status())
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    return json_response(status_data)


@app.route("/api/query", method="POST")
@app.route("/api/nlp", method="POST")
def query():
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    data = request.json or {}
    query_text = data.get("query", "").strip()
    if not query_text:
        return json_response({"success": False, "message": "請輸入問題。"}, status=400)

    ans = nlp_engine.process_query(query_text, agent)
    return json_response({"success": True, "answer": ans})


@app.route("/api/history", method="GET")
def get_history():
    return json_response({
        "success": True,
        "history": agent.history
    })


@app.route("/api/intersection", method=["GET", "POST"])
def get_intersection():
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    analysis = agent.intersection_analyzer.analyze(agent.lat, agent.lon, agent.heading_deg, agent.world_model)
    report = analysis.get("detailed_report") or analysis.get("safety_summary") or "前方路口分析完成。"
    return json_response({
        "success": True,
        "intersection": analysis,
        "report": report
    })


@app.route("/api/poi/enrich", method="POST")
def enrich_poi():
    """Enrich a POI with Google Places data (rating, reviews, open_now)."""
    data = request.json or {}
    name = data.get("name", "").strip()
    lat = data.get("lat", 0)
    lon = data.get("lon", 0)

    if not name:
        return json_response({"available": False, "reason": "未提供店家名稱"})

    result = google_places.enrich_poi(name, lat, lon)
    return json_response(result)


@app.route("/api/history/export", method="GET")
def export_history():
    lines = ["# nmap 視障者地圖世界探索 - 測試履歷與軌跡紀錄\n"]
    lines.append(f"• 定位起點：{agent.location_label}")
    lines.append(f"• 累積總步數：{agent.step_count} 步\n")
    lines.append("## 📜 詳細動態軌跡列表\n")
    lines.append("| 步驟 | 動作 | GPS 座標 | 朝向 | 發現店家數 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")

    for h in agent.history:
        cardinal = bearing_to_cardinal(h.get("heading_deg", 0.0))
        lines.append(f"| {h.get('step', 0)} | {h.get('action', '')} | ({round(h.get('lat', 0), 5)}, {round(h.get('lon', 0), 5)}) | 面向{cardinal} ({int(h.get('heading_deg', 0))}°) | {h.get('poi_count', 0)} 處 |")

    content = "\n".join(lines)
    response.content_type = "text/markdown; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=nmap_test_history.md"
    return content


@app.route("/api/navigate", method="POST")
def navigate():
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    data = request.json or {}
    destination = data.get("destination", "").strip()
    if not destination:
        return json_response({"success": False, "message": "請輸入導航目的地。"}, status=400)

    success, msg = agent.navigate_to(destination)
    if success:
        agent.sound_manager.play_arrival()
    
    return json_response({
        "success": success,
        "message": msg,
        "route": agent.active_navigation
    })

@app.route('/api/simulation/start', method='POST')
def simulation_start():
    data = request.json or {}
    difficulty = data.get('difficulty', 'normal')
    if not agent.is_loaded:
        return json_response({'success': False, 'message': '請先定位起點再啟動模擬模式。'}, 400)
    simulation.start(difficulty)
    result = simulation.process_step(agent)
    return json_response({'success': True, 'message': f'模擬模式已啟動（{difficulty}）', **result})


@app.route('/api/simulation/stop', method='POST')
def simulation_stop():
    simulation.stop()
    return json_response({'success': True, 'message': '模擬模式已關閉，回到探索模式。'})


@app.route('/api/simulation/status', method='GET')
def simulation_status():
    return json_response(simulation.get_status())


@app.route('/api/simulation/action', method='POST')
def simulation_action():
    if not simulation.enabled:
        return json_response({'success': False, 'message': '模擬模式未啟動。'}, 400)
    data = request.json or {}
    action = data.get('action', '')
    result = simulation.process_action(action, agent)
    return json_response({'success': True, **result})


@app.route('/api/simulation/settings', method='POST')
def simulation_settings():
    data = request.json or {}
    simulation.update_settings(data)
    return json_response({'success': True, 'message': '模擬設定已更新。'})


if __name__ == "__main__":
    print("=== nmap WebUI 伺服器啟動中 ===")
    print("請用瀏覽器開啟: http://localhost:8000")
    run(app, host="localhost", port=8000, debug=True)
