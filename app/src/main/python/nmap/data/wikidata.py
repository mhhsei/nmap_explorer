"""
Wikidata 與維基百科開放資料擴充器 (Wikidata & Wikipedia Enricher)

作用：完全免費且不需任何 API Key。
當探索到知名景點、古蹟或大商場時，自動從維基百科搜尋簡短介紹與歷史背景，豐富導覽內容。
"""
import requests
from typing import Dict, Any, List, Optional
from nmap.data.cache import CacheManager

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
DEFAULT_USER_AGENT = "nmap-blind-world-explorer/1.0 (accessibility-gis-engine)"


class WikidataEnricher:
    """
    維基百科與 Wikidata 開放資料擴充客戶端
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.cache = cache_manager or CacheManager()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json"
        })

    def enrich_poi(self, name: str, lat: float, lon: float) -> Dict[str, Any]:
        """
        【透過維基百科搜尋景點簡介】
        作用：以景點名稱搜尋維基百科摘要（前 120 字元）與條目連結，並寫入本機快取。
        """
        cache_key = f"wikidata:{name}:{round(lat, 3)},{round(lon, 3)}"
        cached = self.cache.get_overpass(cache_key)
        if cached:
            return cached

        enrichment = {
            "description": "",
            "wiki_url": "",
            "brand_zh": ""
        }

        try:
            # 查詢中文維基百科 REST API
            search_url = f"https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch={name}&format=json"
            resp = self.session.get(search_url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("query", {}).get("search", [])
                if results:
                    first = results[0]
                    title = first.get("title", "")
                    snippet = first.get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
                    enrichment["description"] = snippet[:120]
                    enrichment["wiki_url"] = f"https://zh.wikipedia.org/wiki/{title}"
                    self.cache.set_overpass(cache_key, enrichment)
        except Exception:
            pass

        return enrichment

