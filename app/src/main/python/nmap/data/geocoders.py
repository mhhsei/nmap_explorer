"""
高精度地理編碼與地址解析器 (Geocoding & Reverse Geocoding)

作用：
1. 正向地理編碼 (geocode)：將使用者輸入的中文地址（如「淡水區北新路177號」）或地標名（如「台北101」）轉成精確經緯度。
   - 第一優先：ArcGIS World Geocoder（門牌定位極精準，命中率高）。
   - 第二備援：OSM Nominatim。
   - 門牌補強：若找不到特定門牌，使用 Overpass API 沿路搜尋最近的門牌節點。
2. 反向地理編碼 (reverse_geocode)：給予經緯度座標，反查出人類看得懂的完整地址與大樓社區名稱。
3. 萬能輸入解析 (parse_input)：無論使用者輸入「純座標 (25.03, 121.56)」、「Google 地圖短網址」或「地址文字」，都能一秒解析。
"""
import requests
import re
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple
from nmap.data.cache import CacheManager

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_USER_AGENT = "nmap-blind-world-explorer/1.0 (accessibility-gis-engine)"


class NominatimClient:
    """
    地理編碼服務客戶端（整合 ArcGIS、Nominatim、Overpass 門牌補全）
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.cache = cache_manager or CacheManager()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})

    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """
        【正向地理編碼：地址文字 -> GPS 經緯度】
        """
        query_clean = query.strip()
        cache_key = f"geo:{query_clean}"

        cached = self.cache.get_geocode(cache_key)
        if cached:
            return cached

        # 1. 優先使用 ArcGIS 高精度地理編碼 (支援台灣精確門牌定位，避免漂移)
        arcgis_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        arcgis_params = {
            "f": "json",
            "singleLine": query_clean,
            "outFields": "Match_addr,Addr_type",
            "maxLocations": 1
        }
        try:
            resp = self.session.get(arcgis_url, params=arcgis_params, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    best = candidates[0]
                    # 如果匹配到精確點位 (PointAddress) 或是街道/地標，直接採用
                    if best.get("score", 0) > 80:
                        res = {
                            "lat": float(best["location"]["y"]),
                            "lon": float(best["location"]["x"]),
                            "display_name": best.get("address", query_clean),
                            "address": {"formatted": best.get("address")}
                        }
                        self.cache.set_geocode(cache_key, res)
                        return res
        except Exception as e:
            pass

        # 2. 如果 ArcGIS 失敗，退回使用 Nominatim
        params = {
            "q": query_clean,
            "format": "json",
            "addressdetails": 1,
            "limit": 5,
            "countrycodes": "tw"
        }

        try:
            resp = self.session.get(NOMINATIM_SEARCH_URL, params=params, timeout=3)
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    first = results[0]
                    res = {
                        "lat": float(first["lat"]),
                        "lon": float(first["lon"]),
                        "display_name": first["display_name"],
                        "address": first.get("address", {})
                    }
                    self.cache.set_geocode(cache_key, res)
                    return res
        except Exception as e:
            pass

        # 3. 若地址包含門牌號（例如「北新路177號」），嘗試用 Overpass 搜尋沿線門牌
        street_match = re.search(r"([^\d\s]+(?:路|街|大道|段|巷|弄))\s*(\d+)號?", query_clean)
        if street_match:
            street_name = street_match.group(1)
            house_num = street_match.group(2)
            res = self._search_overpass_housenumber(street_name, house_num)
            if res:
                self.cache.set_geocode(cache_key, res)
                return res

        # 4. 回退機制：若找不到精確門牌號，移除門牌號後以路名再次搜尋
        fallback_query = re.sub(r"\d+號", "", query_clean).strip()
        if fallback_query and fallback_query != query_clean:
            return self.geocode(fallback_query)

        return None

    def _search_overpass_housenumber(self, street_name: str, housenumber: str) -> Optional[Dict[str, Any]]:
        """
        【使用 Overpass API 沿街搜尋門牌號碼】
        作用：在 OSM 道路上搜尋具有 addr:housenumber 標籤的節點，找出最靠近目標號碼的座標。
        """
        cache_key = f"housenum:{street_name}:{housenumber}"
        cached = self.cache.get_geocode(cache_key)
        if cached:
            return cached

        fallback_query = re.sub(r"\d+號", "", query_clean).strip()
        if fallback_query and fallback_query != query_clean:
            return self.geocode(fallback_query)

        return None

    def _search_overpass_housenumber(self, street_name: str, housenumber: str) -> Optional[Dict[str, Any]]:
        """
        Query Overpass for exact or nearby house number match along street with SQLite caching and fast 2s timeout.
        """
        cache_key = f"housenum:{street_name}:{housenumber}"
        cached = self.cache.get_geocode(cache_key)
        if cached:
            return cached

        try:
            num = int(housenumber)
            num_pattern = f"({num}|{num+1}|{num-1}|{num+2}|{num-2}|{num+3}|{num-3})"
        except ValueError:
            num_pattern = housenumber

        op_query = f"""
        [out:json][timeout:4];
        (
          node["addr:street"~"{street_name}"];
          way["addr:street"~"{street_name}"];
          node["name"~"{street_name}.*{num_pattern}"];
          way["name"~"{street_name}.*{num_pattern}"];
        );
        out center 5;
        """
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from nmap.data.overpass import OVERPASS_ENDPOINTS

            def _query_ep(ep):
                try:
                    resp = self.session.post(ep, data={"data": op_query}, timeout=1.8)
                    if resp.status_code == 200:
                        data = resp.json()
                        if "elements" in data and data["elements"]:
                            return data
                except Exception:
                    pass
                return None

            data = None
            with ThreadPoolExecutor(max_workers=len(OVERPASS_ENDPOINTS)) as executor:
                futures = [executor.submit(_query_ep, ep) for ep in OVERPASS_ENDPOINTS]
                for future in as_completed(futures):
                    res = future.result()
                    if res:
                        data = res
                        break

            if data and "elements" in data:
                elems = data.get("elements", [])
                if elems:
                    best_elem = elems[0]
                    best_diff = 999
                    for elem in elems:
                        tags = elem.get("tags", {})
                        hn = tags.get("addr:housenumber", "")
                        nm = tags.get("name", "")
                        found_nums = re.findall(r"\d+", hn + " " + nm)
                        if found_nums:
                            for fn in found_nums:
                                diff = abs(int(fn) - int(housenumber)) if housenumber.isdigit() else 0
                                if diff < best_diff:
                                    best_diff = diff
                                    best_elem = elem

                    lat = best_elem.get("lat") or best_elem.get("center", {}).get("lat")
                    lon = best_elem.get("lon") or best_elem.get("center", {}).get("lon")
                    tags = best_elem.get("tags", {})
                    name = tags.get("name") or f"{street_name}{housenumber}號"
                    if lat and lon:
                        res = {
                            "lat": float(lat),
                            "lon": float(lon),
                            "display_name": f"{name}, {street_name} ({housenumber}號週邊商圈)",
                            "address": {"road": street_name, "house_number": housenumber}
                        }
                        self.cache.set_geocode(cache_key, res)
                        return res
        except Exception as e:
            pass
        return None

    def reverse_geocode(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """
        【反向地理編碼：GPS 經緯度 -> 中文詳細地址】
        作用：在使用者透過 GPS 定位時，查詢目前位於哪一個縣市、行政區、路名、門牌或社區大樓名稱。
        """
        cache_key = f"rev:{round(lat, 5)},{round(lon, 5)}"
        cached = self.cache.get_geocode(cache_key)
        if cached:
            return cached

        # 1. 優先使用 ArcGIS 反向地理編碼 (提供極高精度的社區、門牌、地標)
        arcgis_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/reverseGeocode"
        arcgis_params = {
            "f": "json",
            "location": f"{lon},{lat}"
        }
        try:
            resp = self.session.get(arcgis_url, params=arcgis_params, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if "address" in data:
                    addr = data["address"]
                    # 組合出漂亮的中文地址：新北市淡水區北新路177號 (宏國青山社區)
                    city = addr.get("City", "")
                    region = addr.get("Region", "")
                    street = addr.get("Address", "")
                    poi = addr.get("PlaceName", "")
                    
                    parts = []
                    if region: parts.append(region)
                    if city: parts.append(city)
                    if street: parts.append(street)
                    
                    formatted = "".join(parts)
                    if poi and poi != street:
                        formatted += f" ({poi})"
                    
                    if formatted:
                        result = {
                            "lat": lat,
                            "lon": lon,
                            "display_name": formatted,
                            "address": {"formatted": formatted}
                        }
                        self.cache.set_geocode(cache_key, result)
                        return result
        except Exception as e:
            pass

        # 2. 如果 ArcGIS 失敗，退回使用 Nominatim
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "addressdetails": 1
        }
        try:
            resp = self.session.get(NOMINATIM_REVERSE_URL, params=params, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    result = {
                        "lat": float(data.get("lat", lat)),
                        "lon": float(data.get("lon", lon)),
                        "display_name": data.get("display_name", ""),
                        "address": data.get("address", {})
                    }
                    self.cache.set_geocode(cache_key, result)
                    return result
        except Exception as e:
            pass
        return None

    def get_doorplate_online(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """
        【方案 C 核心】：線上高精度門牌反查與持久化快取 (ArcGIS / NLSC)
        作用：當離線圖資無任何實體門牌時，線上查詢官方實體門牌點位，並自動存入 nmap_cache.db。
        """
        cache_key = f"doorplate:{round(lat, 5)}:{round(lon, 5)}"
        cached = self.cache.get_geocode(cache_key)
        if cached:
            return cached

        arcgis_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/reverseGeocode"
        params = {"f": "json", "location": f"{lon},{lat}"}
        try:
            resp = self.session.get(arcgis_url, params=params, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                addr_data = data.get("address", {})
                st = addr_data.get("Address", "")
                add_num = addr_data.get("AddNum", "")
                poi_name = addr_data.get("PlaceName", "")
                match_addr = addr_data.get("Match_addr", "")

                if add_num or ("號" in st):
                    clean_hn = add_num if add_num else ""
                    if not clean_hn:
                        m = re.search(r'(\d+)號', st)
                        if m:
                            clean_hn = m.group(1)

                    res = {
                        "street": st,
                        "housenumber": clean_hn,
                        "name": poi_name,
                        "full_address": match_addr,
                        "source": "arcgis"
                    }
                    self.cache.set_geocode(cache_key, res)
                    return res
        except Exception:
            pass

        return None

    def parse_input(self, input_str: str) -> Tuple[Optional[float], Optional[float], str]:
        """
        【萬能輸入解析器】
        作用：支援三種輸入格式：
        1. 純經緯度數字（例如："25.0601, 121.5332"）。
        2. Google Maps 網址（例如：包含 "@25.033,121.565" 的連結）。
        3. 中文地址或地標名稱（例如："台北市信義區市府路1號" 或 "台北車站"）。
        """
        input_str = input_str.strip()

        # Direct Lat,Lon regex e.g. "25.0601, 121.5332"

        coord_match = re.match(r"^([+-]?\d+\.?\d*)[,\s]+([+-]?\d+\.?\d*)$", input_str)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            rev = self.reverse_geocode(lat, lon)
            label = rev["display_name"] if rev else f"GPS ({lat}, {lon})"
            return lat, lon, label

        # Google Maps URL pattern containing `@lat,lon`
        url_match = re.search(r"@([+-]?\d+\.\d+),([+-]?\d+\.\d+)", input_str)
        if url_match:
            lat = float(url_match.group(1))
            lon = float(url_match.group(2))
            rev = self.reverse_geocode(lat, lon)
            label = rev["display_name"] if rev else f"Map Location ({lat}, {lon})"
            return lat, lon, label

        # Address search
        geo = self.geocode(input_str)
        if geo:
            return geo["lat"], geo["lon"], geo["display_name"]

        return None, None, input_str
