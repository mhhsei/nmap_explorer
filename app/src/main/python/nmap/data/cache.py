import sqlite3
import json
import time
import os
from typing import Optional, Any, Dict

DEFAULT_CACHE_DB = os.path.join(os.path.dirname(__file__), "..", "..", "nmap_cache.db")


class CacheManager:
    """
    SQLite-backed local persistent cache for Nominatim and Overpass API requests.
    Prevents API rate limiting and enables instant offline exploration of cached areas.
    """

    def __init__(self, db_path: str = DEFAULT_CACHE_DB):
        self.db_path = os.path.abspath(db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO geocode_cache (query_key, data_json, timestamp) VALUES (?, ?, ?)",
                (query_key, json.dumps(data, ensure_ascii=False), time.time())
            )
            conn.commit()

    def get_overpass(self, query_key: str, max_age_seconds: Optional[float] = None) -> Optional[Dict[str, Any]]:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO overpass_cache (query_key, data_json, timestamp) VALUES (?, ?, ?)",
                (query_key, json.dumps(data, ensure_ascii=False), time.time())
            )
            conn.commit()

    def clear(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM geocode_cache")
            cursor.execute("DELETE FROM overpass_cache")
            conn.commit()
