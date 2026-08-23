"""
Google Places API 地標評價與營業資訊擴充客戶端 (Google Places Client)

作用：當設定了 GOOGLE_PLACES_API_KEY 時，線上查詢店家的真實評價、最新評論、即時營業狀態與電話。
設計原則：
1. 優雅降級 (Graceful Degradation)：若未設定 API Key 或連線超時，系統不會崩潰，而是平順返回基本 OSM 圖資。
2. 記憶體快取 (In-Memory Cache)：避免在短時間內重複扣款查詢同一間店家。
"""
import os
import requests
from typing import Optional, Dict, Any

PRICE_LEVEL_MAP = {
    0: "免費",
    1: "平價 $",
    2: "中等 $$",
    3: "偏高 $$$",
    4: "高檔 $$$$"
}

BUSINESS_STATUS_MAP = {
    "OPERATIONAL": "正常營業",
    "CLOSED_TEMPORARILY": "暫時歇業",
    "CLOSED_PERMANENTLY": "永久歇業"
}


class GooglePlacesClient:
    """
    Google Places API 客戶端
    """

    BASE_URL = "https://maps.googleapis.com/maps/api/place"

    def __init__(self):
        self.api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "nmap-blind-world-explorer/1.0"
        })
        # 記憶體快取字典，避免重複發送付費 API
        self._cache: Dict[str, Dict] = {}

    @property
    def is_available(self) -> bool:
        """檢查是否具備可用的 Google API Key"""
        return bool(self.api_key)

    def search_place(self, name: str, lat: float, lon: float,
                     radius_m: int = 80) -> Optional[Dict[str, Any]]:
        """
        【以地標名稱與座標搜尋 Google 地點 ID (Place ID)】
        """

        if not self.is_available:
            return None

        cache_key = f"gs:{name}:{round(lat, 4)}:{round(lon, 4)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/nearbysearch/json",
                params={
                    "location": f"{lat},{lon}",
                    "radius": radius_m,
                    "keyword": name,
                    "key": self.api_key,
                    "language": "zh-TW"
                },
                timeout=3.0
            )
            data = resp.json()

            if data.get("status") == "OK" and data.get("results"):
                p = data["results"][0]
                result = {
                    "place_id": p.get("place_id"),
                    "name": p.get("name", ""),
                    "rating": p.get("rating"),
                    "user_ratings_total": p.get("user_ratings_total", 0),
                    "price_level": p.get("price_level"),
                    "business_status": p.get("business_status", ""),
                    "open_now": p.get("opening_hours", {}).get("open_now"),
                    "vicinity": p.get("vicinity", ""),
                }
                self._cache[cache_key] = result
                return result
        except Exception:
            pass

        return None

    def get_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed info: reviews, phone, hours, price level.
        """
        if not self.is_available or not place_id:
            return None

        cache_key = f"gd:{place_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/details/json",
                params={
                    "place_id": place_id,
                    "fields": "name,rating,user_ratings_total,opening_hours,"
                              "price_level,reviews,business_status,"
                              "formatted_phone_number,website,url",
                    "key": self.api_key,
                    "language": "zh-TW",
                    "reviews_sort": "newest"
                },
                timeout=3.0
            )
            data = resp.json()

            if data.get("status") == "OK" and data.get("result"):
                r = data["result"]

                # Parse reviews (top 3, truncated)
                reviews = []
                for rev in r.get("reviews", [])[:3]:
                    reviews.append({
                        "rating": rev.get("rating", 0),
                        "text": rev.get("text", "")[:200],
                        "time_desc": rev.get("relative_time_description", "")
                    })

                # Opening hours text
                oh = r.get("opening_hours", {})
                hours_text = ""
                if oh.get("weekday_text"):
                    hours_text = "；".join(oh["weekday_text"])

                result = {
                    "name": r.get("name", ""),
                    "rating": r.get("rating"),
                    "user_ratings_total": r.get("user_ratings_total", 0),
                    "price_level": r.get("price_level"),
                    "price_label": PRICE_LEVEL_MAP.get(r.get("price_level"), ""),
                    "business_status": BUSINESS_STATUS_MAP.get(
                        r.get("business_status", ""), ""
                    ),
                    "open_now": oh.get("open_now"),
                    "hours_text": hours_text,
                    "phone": r.get("formatted_phone_number", ""),
                    "website": r.get("website", ""),
                    "google_maps_url": r.get("url", ""),
                    "reviews": reviews
                }
                self._cache[cache_key] = result
                return result
        except Exception:
            pass

        return None

    def enrich_poi(self, name: str, lat: float, lon: float) -> Dict[str, Any]:
        """
        Full enrichment pipeline: search → get details.
        Returns dict with 'available' bool and enriched fields.
        """
        if not self.is_available:
            return {
                "available": False,
                "reason": "未設定 GOOGLE_PLACES_API_KEY 環境變數"
            }

        search = self.search_place(name, lat, lon)
        if not search:
            return {
                "available": False,
                "reason": f"在 Google 地圖上找不到「{name}」"
            }

        details = self.get_place_details(search.get("place_id", ""))
        if details:
            return {"available": True, **details}

        # Fallback: return search-level data only
        return {"available": True, **search}
