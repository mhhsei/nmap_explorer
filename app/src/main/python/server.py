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
from nmap.spatial.poi_detail_fetcher import PoiDetailFetcher

app = Bottle()
agent = ExplorerAgent(enable_sound=False) # WebUI uses Web Audio API on frontend
nlp_engine = NLPQueryEngine()
reporter = NVDAReporter()
street_analyzer = StreetViewAnalyzer()
google_places = GooglePlacesClient()
simulation = SimulationEngine()
poi_detail_fetcher = PoiDetailFetcher()

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


def build_status_dict(include_full_report: bool = True, heading_deg: float = None, lat: float = None, lon: float = None) -> dict:
    """
    【單次管線構建地圖綜合狀態 (Single-Pass World Status Builder)】
    作用：
    1. 在單一運算週期中只計算一次 road_info、pois、buildings、intersection。
    2. 將計算好的 Context 同時共享給 reporter 與 street_analyzer，徹底消滅 3~5 次的重複 GIS 運算。
    3. 直接產出原生 Python 字典，消除 json.dumps -> json.loads 的無效序列化開銷。
    """
    if not agent.is_loaded:
        return {
            "success": False,
            "is_loaded": False,
            "message": "尚未初始化地圖起點。請在上方搜尋列輸入地址。"
        }

    cur_lat = lat if lat is not None else agent.lat
    cur_lon = lon if lon is not None else agent.lon
    cur_head = heading_deg if heading_deg is not None else agent.heading_deg

    agent.lat = cur_lat
    agent.lon = cur_lon
    agent.heading_deg = cur_head

    road_info = agent.world_model.get_road_info(cur_lat, cur_lon, cur_head)
    pois = agent.world_model.get_nearby_pois(cur_lat, cur_lon, cur_head, radius_m=150.0)
    buildings = agent.world_model.get_nearby_buildings(cur_lat, cur_lon, cur_head, radius_m=50.0)
    intersection = agent.intersection_analyzer.analyze(cur_lat, cur_lon, cur_head, agent.world_model, curr_road_info=road_info)
    door_estimates = agent.world_model.get_interpolated_door_numbers(cur_lat, cur_lon, cur_head)
    concise_report = reporter.generate_concise_report(agent, road_info=road_info, pois=pois, intersection=intersection)
    street_scene = street_analyzer.analyze_scene(cur_lat, cur_lon, cur_head, agent.world_model, road_info=road_info, pois=pois, buildings=buildings)

    if include_full_report:
        full_report = reporter.generate_full_report(
            agent,
            road_info=road_info,
            pois=pois,
            buildings=buildings,
            intersection_analysis=intersection,
            door_estimates=door_estimates,
            scene=street_scene
        )
    else:
        full_report = concise_report

    return {
        "success": True,
        "is_loaded": True,
        "is_overseas": getattr(agent, "is_overseas", False),
        "location_label": agent.location_label,
        "lat": cur_lat,
        "lon": cur_lon,
        "heading_deg": cur_head,
        "step_count": agent.step_count,
        "road_info": road_info,
        "pois": pois,
        "buildings": buildings,
        "intersection": intersection,
        "door_estimates": door_estimates,
        "full_report": full_report,
        "concise_report": concise_report,
        "street_scene": street_scene
    }


@app.route("/api/status", method=["GET", "POST"])
def get_status():
    """
    【取得當前地圖全景狀態 (Get Current World Status)】
    作用：前端隨時向後端查詢目前「站在哪條路、面向哪裡、身邊 120 米有什麼店、前方路口長怎樣、門牌幾號」。
    支援動態即時朝向與座標參數。
    """
    h = request.query.get("heading_deg") or (request.json.get("heading_deg") if request.json else None)
    lat = request.query.get("lat") or (request.json.get("lat") if request.json else None)
    lon = request.query.get("lon") or (request.json.get("lon") if request.json else None)

    h_val = float(h) if (h is not None and str(h).strip() != "") else None
    lat_val = float(lat) if (lat is not None and str(lat).strip() != "") else None
    lon_val = float(lon) if (lon is not None and str(lon).strip() != "") else None

    return json_response(build_status_dict(include_full_report=True, heading_deg=h_val, lat=lat_val, lon=lon_val))


@app.route("/api/poi_detail_legacy", method=["GET", "POST"])
def poi_detail_legacy():
    """
    【舊版地標查詢端點】
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)
    
    if request.method == "POST":
        data = request.json or {}
        poi_id = data.get("id")
    else:
        poi_id = request.query.get("id")

    if not poi_id:
        return json_response({"success": False, "message": "缺少地標 ID。"}, status=400)

    detail = agent.get_poi_detail(poi_id)
    if not detail:
        return json_response({"success": False, "message": "查無此地標詳細資訊。"}, status=404)

    return json_response({"success": True, "detail": detail})


@app.route("/api/virtual_pan", method="POST")
def virtual_pan():
    """
    【雙指虛擬漫遊推進 (Virtual Pan)】
    作用：視障者雙指在螢幕上滑時，不需要真的走動，就可以虛擬向前推進 30 公尺，預先探索前方街道的店家與路況。
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)
    data = request.json or {}
    forward_m = float(data.get("forward_m", 30.0))
    side_m = float(data.get("side_m", 0.0))
    ok, msg, result = agent.virtual_pan(forward_m, side_m)
    return json_response({
        "success": ok,
        "action_message": msg,
        "pan_data": result
    })


@app.route("/api/teleport", method="POST")
def teleport():
    """
    【瞬移到指定地址或座標 (Teleport)】
    作用：在搜尋列輸入地址（如「台北車站」），地圖立即切換到該地點並下載周遭圖資。
    """
    data = request.json or {}
    location = data.get("location", "").strip()
    if not location:
        return json_response({"success": False, "message": "請提供有效的地址或座標。"}, status=400)

    ok, msg = agent.teleport(location)
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)

    status_data = build_status_dict(include_full_report=True)
    return json_response(status_data)


@app.route("/api/move", method="POST")
def move():
    """
    【處理玩家空間位移 (Spatial Translation)】
    為什麼這個端點這麼重要？
    視障者在探索時，移動是最頻繁的操作（預設每步 1~5 公尺）。
    1. 首先呼叫 `agent.move()` 透過空間引擎計算最新經緯度。
    2. 接著進行碰撞檢測 (Collision Detection)，若撞牆則提早攔截。
    3. 如果啟用了「遊戲模擬模式 (Simulation Engine)」，則會額外推算動態事件 (如車輛、行人)。
    4. 最終回傳 status_data JSON，直接由 build_status_dict 產出，達成極速響應。
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

    status_data = build_status_dict(include_full_report=True)
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    status_data["is_collision"] = is_collision

    return json_response(status_data)
    

@app.route("/api/jump_intersection", method="POST")
def jump_intersection():
    """
    【直接跳到下一個路口 (Jump to Next Intersection)】
    作用：提供快速鍵（例如 J），讓視障者不用一步一步走，直接將視角瞬移到前方最近的十字路口或轉角。
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    ok, msg = agent.jump_to_next_intersection()
    
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = build_status_dict(include_full_report=True)
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    status_data["is_collision"] = "障礙物" in msg

    return json_response(status_data)


@app.route("/api/snap_turn", method="POST")
def snap_turn():
    """
    【自動對齊路口分支轉向 (Snap Turn)】
    作用：站在十字路口時，自動辨識左轉或右轉的道路角度，直接將朝向「吸附」至該道路方向。
    """
    data = request.json or {}
    direction = data.get("direction", "left")
    ok, msg = agent.snap_to_branch(direction)
    
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = build_status_dict(include_full_report=True)
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg

    return json_response(status_data)


@app.route("/api/gps", method="POST")
def update_gps():
    """
    【接收 Android 原生 GPS 與感測器高頻數據】
    作用：原生層（LocationSensorBridge）將平滑後的經緯度、朝向角度與精度發送給 Python 後端。
    後端立即更新探索者的真實位置，並在跨區位移超過 100 米時自動載入新圖資。
    """
    data = request.json or {}
    lat = data.get("lat")
    lon = data.get("lon")
    heading = data.get("heading_deg")
    accuracy = data.get("accuracy", 10.0)

    if lat is None or lon is None:
        return json_response({"success": False, "message": "缺少 GPS 座標。"}, status=400)

    ok, msg = agent.update_gps_position(lat, lon, heading, accuracy)

    status_data = build_status_dict(include_full_report=True)
    status_data["action_message"] = msg
    status_data["is_collision"] = False
    return json_response(status_data)


@app.route("/api/sync", method="POST")
def sync():
    """
    【通用位置與朝向同步】
    作用：前端將目前計算好的位置、朝向或移動距離同步至後端 Agent。
    """
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

    status_data = build_status_dict(include_full_report=True)
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    status_data["is_collision"] = is_collision

    return json_response(status_data)


@app.route("/api/turn", method="POST")
def turn():
    """
    【旋轉探索者朝向 (Turn/Face)】
    作用：支援左轉、右轉、迴轉，或是直接轉向特定絕對方位（東、南、西、北）或精確角度（heading_deg）。
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    data = request.json or {}
    
    # 支援直接傳入即時旋轉角度 (heading_deg)
    if "heading_deg" in data:
        try:
            h_deg = float(data["heading_deg"])
            agent.heading_deg = (h_deg + 360.0) % 360.0
            if "lat" in data and data["lat"] is not None:
                agent.lat = float(data["lat"])
            if "lon" in data and data["lon"] is not None:
                agent.lon = float(data["lon"])
            status_data = build_status_dict(include_full_report=False, heading_deg=agent.heading_deg, lat=agent.lat, lon=agent.lon)
            status_data["action_message"] = f"已轉向至 {round(agent.heading_deg, 1)}°"
            return json_response(status_data)
        except Exception as e:
            pass

    target = data.get("target", "right")

    if target in ["north", "east", "south", "west"]:
        ok, msg = agent.face(target)
    else:
        ok, msg = agent.turn(target)

    # 模擬引擎步進整合
    sim_data = None
    if simulation.enabled and ok:
        sim_data = simulation.process_step(agent)

    status_data = build_status_dict(include_full_report=True)
    if sim_data:
        status_data['simulation'] = sim_data
    status_data["action_message"] = msg
    return json_response(status_data)


@app.route("/api/query", method="POST")
@app.route("/api/nlp", method="POST")
def query():
    """
    【自然語言空間問答 (NLP Spatial Query)】
    作用：視障者可以用自然口語發問（例如：「附近有廁所嗎？」、「最近的便利商店在哪裡？」）。
    由 NLPQueryEngine 解析語意並查詢周遭實體地標回覆。
    """
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
    """
    【取得探索歷史紀錄】
    """
    return json_response({
        "success": True,
        "history": agent.history
    })


@app.route("/api/intersection", method=["GET", "POST"])
def get_intersection():
    """
    【前方路口安全分析 (Intersection Safety Analysis)】
    作用：詳細分析前方路口的分支走向、道路名稱、是否有行人斑馬線與號誌，產出報讀摘要。
    支援即時朝向與座標參數。
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    h = request.query.get("heading_deg") or (request.json.get("heading_deg") if request.json else None)
    lat = request.query.get("lat") or (request.json.get("lat") if request.json else None)
    lon = request.query.get("lon") or (request.json.get("lon") if request.json else None)

    h_val = float(h) if (h is not None and str(h).strip() != "") else agent.heading_deg
    lat_val = float(lat) if (lat is not None and str(lat).strip() != "") else agent.lat
    lon_val = float(lon) if (lon is not None and str(lon).strip() != "") else agent.lon

    agent.heading_deg = h_val
    agent.lat = lat_val
    agent.lon = lon_val

    analysis = agent.intersection_analyzer.analyze(lat_val, lon_val, h_val, agent.world_model)
    report = analysis.get("detailed_report") or analysis.get("safety_summary") or "前方路口分析完成。"
    return json_response({
        "success": True,
        "intersection": analysis,
        "report": report
    })


@app.route("/api/poi/enrich", method="POST")
def enrich_poi():
    """
    【Google Places 外部資訊加強】
    作用：線上即時補充店家的 Google 評價星級、評論數量與即時營業狀態。
    """
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
    """
    【匯出 Markdown 格式的探索軌跡報告】
    """
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
    """
    【目的地步行路徑規劃】
    作用：規劃從當前位置步行至目標地標的最佳無障礙路徑。
    """
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
    """
    【啟動定向行動定向教學模擬 (Simulation Mode)】
    作用：開啟虛擬路況模擬（障礙物、車輛聲音、天氣與白手杖探測），提供視障者室內擬真訓練。
    """
    data = request.json or {}
    difficulty = data.get('difficulty', 'normal')
    if not agent.is_loaded:
        return json_response({'success': False, 'message': '請先定位起點再啟動模擬模式。'}, 400)
    simulation.start(difficulty)
    result = simulation.process_step(agent)
    return json_response({'success': True, 'message': f'模擬模式已啟動（{difficulty}）', **result})


@app.route('/api/simulation/stop', method='POST')
def simulation_stop():
    """關閉定向模擬模式"""
    simulation.stop()
    return json_response({'success': True, 'message': '模擬模式已關閉，回到探索模式。'})


@app.route('/api/simulation/status', method='GET')
def simulation_status():
    """查詢模擬模式狀態"""
    return json_response(simulation.get_status())


@app.route('/api/simulation/action', method='POST')
def simulation_action():
    """處理模擬訓練中的互動動作（如揮動白手杖）"""
    if not simulation.enabled:
        return json_response({'success': False, 'message': '模擬模式未啟動。'}, 400)
    data = request.json or {}
    action = data.get('action', '')
    result = simulation.process_action(action, agent)
    return json_response({'success': True, **result})


@app.route('/api/simulation/settings', method='POST')
def simulation_settings():
    """更新模擬訓練難度與環境設定"""
    data = request.json or {}
    simulation.update_settings(data)
    return json_response({'success': True, 'message': '模擬設定已更新。'})


@app.route('/api/system/check_update', method=['GET', 'POST'])
def check_update():
    """
    【檢查 GitHub Releases 最新版本 (Check System Update)】
    作用：直接向 GitHub API 查詢是否有新版本 APK 發布，回傳版本號、更新日誌與下載網址。
    """
    import urllib.request
    import json
    current_version = "1.0.4"
    try:
        api_url = "https://api.github.com/repos/mhhsei/nmap_explorer/releases/latest"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "NMapExplorer-Server",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        with urllib.request.urlopen(req, timeout=5.0) as response:
            release_data = json.loads(response.read().decode('utf-8'))

        tag_name = release_data.get("tag_name", "").lstrip("vV").strip()
        title = release_data.get("name", "新版本發布")
        body = release_data.get("body", "無詳細說明")
        
        apk_url = ""
        file_size = 0
        for asset in release_data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".apk"):
                apk_url = asset.get("browser_download_url", "")
                file_size = asset.get("size", 0)
                if "release" in name.lower():
                    break

        # 版本比較
        has_update = False
        if tag_name and apk_url:
            curr_parts = [int(p) for p in current_version.split(".") if p.isdigit()]
            latest_parts = [int(p) for p in tag_name.split(".") if p.isdigit()]
            for c, l in zip(curr_parts, latest_parts):
                if l > c:
                    has_update = True
                    break
                elif l < c:
                    break
            if not has_update and len(latest_parts) > len(curr_parts):
                has_update = True

        return json_response({
            "success": True,
            "has_update": has_update,
            "current_version": current_version,
            "latest_version": tag_name or current_version,
            "release_title": title,
            "release_notes": body,
            "download_url": apk_url,
            "file_size": file_size
        })
    except urllib.error.HTTPError as he:
        if he.code == 404:
            return json_response({
                "success": True,
                "has_update": False,
                "current_version": current_version,
                "latest_version": current_version,
                "release_title": "已是最新版本",
                "release_notes": "目前 GitHub 尚未有發布記錄"
            })
        return json_response({
            "success": False,
            "has_update": False,
            "current_version": current_version,
            "message": f"GitHub API 回應錯誤 ({he.code})"
        })
    except Exception as e:
        return json_response({
            "success": False,
            "has_update": False,
            "current_version": current_version,
            "message": f"檢查更新失敗: {str(e)}"
        })


@app.route("/api/refresh_pois", method=["GET", "POST"])
def refresh_pois():
    """
    【即時重新載入並注入離線資料庫 POI】
    作用：當使用者下載好離線圖資包後，前端發送請求，後端立即在 0.01 秒內將數百至上千筆店家載入 R-Tree 空間模型。
    """
    if not agent.is_loaded:
        return json_response({"success": False, "message": "尚未初始化地圖。"}, status=400)

    total_pois = agent.reload_real_pois(radius_deg=0.008)
    return json_response({
        "success": True,
        "poi_count": total_pois,
        "message": f"已成功載入離線店家圖資！目前周遭地標總數：{total_pois} 間。"
    })


@app.route("/api/poi_detail", method=["GET", "POST"])
def get_poi_detail():
    """
    【免 API Key 即時獲取地標詳細營業時間、電話與無障礙設施】
    """
    import urllib.parse
    
    # 支援 JSON POST, Form, 以及從原始 QUERY_STRING 以 UTF-8 解析，杜絕任何編碼亂碼
    qs_data = urllib.parse.parse_qs(request.environ.get("QUERY_STRING", ""), encoding="utf-8")
    
    name = (request.json or {}).get("name") if request.json else None
    if not name:
        name = qs_data.get("name", [""])[0] if "name" in qs_data else request.params.get("name", "")
    
    address = (request.json or {}).get("address") if request.json else None
    if not address:
        address = qs_data.get("address", [""])[0] if "address" in qs_data else request.params.get("address", "")
        
    floor = (request.json or {}).get("floor") if request.json else None
    if not floor:
        floor = qs_data.get("floor", ["1F"])[0] if "floor" in qs_data else request.params.get("floor", "1F")
        
    lat_str = (request.json or {}).get("lat") if request.json else None
    if not lat_str:
        lat_str = qs_data.get("lat", [""])[0] if "lat" in qs_data else request.params.get("lat")
        
    lon_str = (request.json or {}).get("lon") if request.json else None
    if not lon_str:
        lon_str = qs_data.get("lon", [""])[0] if "lon" in qs_data else request.params.get("lon")

    lat = float(lat_str) if (lat_str and str(lat_str).strip() != "") else None
    lon = float(lon_str) if (lon_str and str(lon_str).strip() != "") else None

    print(f"[POI DETAIL FETCH] Decoded params: Name='{name}', Addr='{address}', Lat={lat}, Lon={lon}")
    details = poi_detail_fetcher.fetch_poi_details(name, lat, lon, address, floor)
    print(f"[POI DETAIL RESULT] '{name}' -> Phone='{details.get('phone')}', Hours='{details.get('opening_hours')}', Rating='{details.get('rating')}'")

    return json_response({
        "success": True,
        "details": details
    })




if __name__ == "__main__":
    print("=== nmap WebUI 伺服器啟動中 ===")
    print("請用瀏覽器開啟: http://localhost:8000")
    run(app, host="localhost", port=8000, debug=True)


