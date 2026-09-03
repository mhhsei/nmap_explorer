import os
import sys
import json
import sqlite3
import urllib.request
import urllib.parse
import time

def fetch_taiwan_traffic_signals():
    print("[1/3] 正在向 Overpass 全球鏡像查詢全台灣交通號誌節點 (約 56,000 處)...", flush=True)
    # Using compact out format for fast download
    query = """
    [out:json][timeout:180];
    area["ISO3166-1"="TW"][admin_level=2]->.tw;
    (
      node["highway"="traffic_signals"](area.tw);
    );
    out body qt;
    """
    
    url = 'https://overpass-api.de/api/interpreter'
    data = urllib.parse.urlencode({'data': query}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'NMapExplorer/1.0 (Accessibility Navigation Project)'})
    
    start_t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = resp.read()
            print(f"  下載完成！耗時 {time.time() - start_t:.1f} 秒，原始 JSON 大小: {len(content) / 1024 / 1024:.2f} MB", flush=True)
            return json.loads(content.decode('utf-8'))
    except Exception as e:
        print(f"  下載失敗: {e}", flush=True)
        return None

def build_database(osm_json, db_path):
    print(f"[2/3] 正在編譯 SQLite 全台離線號誌資料庫: {db_path}...", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE taiwan_signals (
            id TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            is_signalized INTEGER DEFAULT 1,
            has_sound INTEGER DEFAULT 0,
            has_button INTEGER DEFAULT 0,
            crossing_type TEXT,
            name TEXT,
            tags TEXT
        );
    """)

    cur.execute("CREATE INDEX idx_taiwan_signals_lat ON taiwan_signals (lat);")
    cur.execute("CREATE INDEX idx_taiwan_signals_lon ON taiwan_signals (lon);")
    cur.execute("CREATE INDEX idx_taiwan_signals_lat_lon ON taiwan_signals (lat, lon);")

    elements = osm_json.get("elements", [])
    print(f"  解析到 {len(elements)} 筆號誌節點，正在批量寫入資料庫...", flush=True)

    rows = []
    for el in elements:
        node_id = str(el.get("id", ""))
        lat = float(el.get("lat", 0.0))
        lon = float(el.get("lon", 0.0))
        tags = el.get("tags", {})

        # 檢測是否有有聲號誌或盲人設施
        sound = tags.get("sound") or tags.get("traffic_signals:sound") or tags.get("acoustic")
        has_sound = 1 if sound in ("yes", "acoustic", "buzzer", "locate") else 0

        button = tags.get("button") or tags.get("traffic_signals:button") or tags.get("push_button")
        has_button = 1 if button in ("yes", "touch") else 0

        crossing = tags.get("crossing") or tags.get("crossing_ref") or ""
        name = tags.get("name") or tags.get("description") or ""
        tags_json = json.dumps(tags, ensure_ascii=False)

        rows.append((node_id, lat, lon, 1, has_sound, has_button, crossing, name, tags_json))

    # 匯入已知 32 筆官方有聲號誌作為高優先級校準
    from nmap.spatial.taiwan_signals import DEFAULT_TAIWAN_SIGNAL_DATABASE
    for sig in DEFAULT_TAIWAN_SIGNAL_DATABASE:
        s_id = sig["id"]
        s_lat = sig["lat"]
        s_lon = sig["lon"]
        s_name = sig.get("intersection_name", "")
        has_sound = 1 if sig.get("has_aps") else 0
        has_button = 1 if sig.get("has_button") else 0
        s_tags = json.dumps(sig, ensure_ascii=False)
        rows.append((s_id, s_lat, s_lon, 1, has_sound, has_button, "aps_intersection", s_name, s_tags))

    cur.executemany("""
        INSERT OR REPLACE INTO taiwan_signals (id, lat, lon, is_signalized, has_sound, has_button, crossing_type, name, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

    conn.commit()
    conn.close()

    db_size_mb = os.path.getsize(db_path) / 1024 / 1024
    print(f"[3/3] 號誌資料庫建立成功！總筆數: {len(rows)} 筆，檔案大小: {db_size_mb:.2f} MB", flush=True)

if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath("app/src/main/python"))
    db_out = os.path.abspath("app/src/main/python/data/taiwan_signals.db")
    data = fetch_taiwan_traffic_signals()
    if data:
        build_database(data, db_out)
        print("Done!")
    else:
        print("Failed to build taiwan_signals.db")
