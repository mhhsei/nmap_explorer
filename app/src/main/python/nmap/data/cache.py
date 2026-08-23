"""
本機 SQLite 快取管理器 (Cache Manager)

作用：將網路查詢過的地點（Nominatim）與地圖圖資（Overpass）儲存在手機/電腦本機的 SQLite 資料庫中。
優點：
1. 避免重複連網抓資料被伺服器封鎖 (Rate Limiting)。
2. 下次再去同一個地方時，不需要網路就能「0 毫秒瞬間載入」離線探索。
"""
import sqlite3
import json
import time
import os
from typing import Optional, Any, Dict

def get_default_cache_db():
    data_dir = os.environ.get("NMAP_DATA_DIR")
    if data_dir:
        return os.path.join(data_dir, "nmap_cache.db")
    return os.path.join(os.path.dirname(__file__), "..", "..", "nmap_cache.db")

DEFAULT_CACHE_DB = get_default_cache_db()


class CacheManager:
    """
    SQLite 本機持久化快取管理員
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = get_default_cache_db()
        self.db_path = os.path.abspath(db_path)
        self._init_db()


    def _get_connection(self) -> sqlite3.Connection:
        """建立資料庫連線並啟用 WAL 高效能寫入模式"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """初始化快取資料表結構（地理編碼表與 Overpass 圖資表）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    query_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS overpass_cache (
                    query_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            conn.commit()

    def get_geocode(self, query_key: str, max_age_seconds: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """從快取讀取地址解析結果"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json, timestamp FROM geocode_cache WHERE query_key = ?", (query_key,))
            row = cursor.fetchone()
            if row:
                data_json, ts = row
                if max_age_seconds is None or (time.time() - ts) <= max_age_seconds:
                    return json.loads(data_json)
        return None

    def set_geocode(self, query_key: str, data: Dict[str, Any]):
        """將地址解析結果存入快取"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO geocode_cache (query_key, data_json, timestamp) VALUES (?, ?, ?)",
                (query_key, json.dumps(data, ensure_ascii=False), time.time())
            )
            conn.commit()

    def get_overpass(self, query_key: str, max_age_seconds: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """從快取讀取 Overpass 地圖資料"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json, timestamp FROM overpass_cache WHERE query_key = ?", (query_key,))
            row = cursor.fetchone()
            if row:
                data_json, ts = row
                if max_age_seconds is None or (time.time() - ts) <= max_age_seconds:
                    return json.loads(data_json)
        return None

    def set_overpass(self, query_key: str, data: Dict[str, Any]):
        """將 Overpass 地圖資料存入快取"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO overpass_cache (query_key, data_json, timestamp) VALUES (?, ?, ?)",
                (query_key, json.dumps(data, ensure_ascii=False), time.time())
            )
            conn.commit()

    def clear(self):
        """清空所有本機快取資料"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM geocode_cache")
            cursor.execute("DELETE FROM overpass_cache")
            conn.commit()

