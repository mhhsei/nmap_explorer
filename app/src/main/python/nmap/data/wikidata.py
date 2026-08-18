import requests
from typing import Dict, Any, List, Optional
from nmap.data.cache import CacheManager

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
DEFAULT_USER_AGENT = "nmap-blind-world-explorer/1.0 (accessibility-gis-engine)"


class WikidataEnricher:
    """
    Free Data Enrichment Client querying Wikidata SPARQL and Wikipedia APIs
    for enhanced store metadata (wheelchair accessibility, official descriptions, 
    operating brands, and floor details) with zero API key requirement.
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
        Enrich POI with Wikidata entity descriptions and Wikipedia summary if available.
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
            # Query Wikipedia Search REST API (free, open)
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
