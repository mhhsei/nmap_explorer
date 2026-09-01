/**
 * NMap 客戶端純 JavaScript 空間拓撲與幾何運算引擎 (Client-Side Spatial Engine)
 * 
 * 作用：
 * 專為 iOS (WebKit)、PWA 與離線環境設計，提供 100% 離線本地端空間計算能力：
 * 1. NMapGeometry: 半正矢大圓距離、真方位角、時鐘方位、自適應道路吸附 (Adaptive Road Snapping)。
 * 2. TaiwanBrandSanitizer: 台灣 50+ 熱門品牌清洗字典 (O(1) 雜湊查找)。
 * 3. IntersectionAnalyzerJS: 前方 60 公尺路口結構與斑馬線分析。
 * 4. ClientWorldModel: 輕量級空間模型與 POI 方位計算。
 * 5. NMapCacheDB: 本地 SQLite (iOS 原生橋接) 與 IndexedDB 快取橋接。
 */

// 1. 幾何運算核心 (Pure Geometry & Spherical Geodesy)
const NMapGeometry = {
  haversineDistance(lat1, lon1, lat2, lon2) {
    const R = 6371000.0;
    const dLat = (lat2 - lat1) * Math.PI / 180.0;
    const dLon = (lon2 - lon1) * Math.PI / 180.0;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * Math.PI / 180.0) * Math.cos(lat2 * Math.PI / 180.0) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  },


  calculateBearing(lat1, lon1, lat2, lon2) {
    const lat1Rad = lat1 * Math.PI / 180.0;
    const lat2Rad = lat2 * Math.PI / 180.0;
    const dLon = (lon2 - lon1) * Math.PI / 180.0;
    const y = Math.sin(dLon) * Math.cos(lat2Rad);
    const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) -
              Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLon);
    const brng = Math.atan2(y, x);
    return (brng * 180.0 / Math.PI + 360.0) % 360.0;
  },

  relativeBearing(heading, targetBearing) {
    let diff = (targetBearing - heading + 360.0) % 360.0;
    if (diff > 180.0) diff -= 360.0;
    return diff;
  },

  bearingToClockPosition(relBearing) {
    let normalized = (relBearing + 360.0) % 360.0;
    let clock = Math.round(normalized / 30.0);
    if (clock === 0) clock = 12;
    return `${clock}點鐘方向`;
  },

  bearingToRelativeDirection(relBearing) {
    const absDiff = Math.abs(relBearing);
    if (absDiff <= 22.5) return "正前方";
    if (absDiff >= 157.5) return "正後方";
    if (relBearing > 22.5 && relBearing < 67.5) return "右前方";
    if (relBearing >= 67.5 && relBearing <= 112.5) return "右側";
    if (relBearing > 112.5 && relBearing < 157.5) return "右後方";
    if (relBearing < -22.5 && relBearing > -67.5) return "左前方";
    if (relBearing <= -67.5 && relBearing >= -112.5) return "左側";
    if (relBearing < -112.5 && relBearing > -157.5) return "左後方";
    return "周遭";
  },

  bearingToCardinal(bearing) {
    const dirs16 = [
      "正北", "北北東", "東北", "東北東",
      "正東", "東南東", "東南", "南南東",
      "正南", "南南西", "西南", "西南西",
      "正西", "西北西", "西北", "北北西"
    ];
    const normalized = ((bearing % 360.0) + 360.0) % 360.0;
    const idx = Math.round(normalized / 22.5) % 16;
    return dirs16[idx];
  },

  destinationPoint(lat, lon, distanceM, bearingDeg) {
    const R = 6371000.0;
    const latRad = lat * Math.PI / 180.0;
    const lonRad = lon * Math.PI / 180.0;
    const brngRad = bearingDeg * Math.PI / 180.0;

    const newLatRad = Math.asin(
      Math.sin(latRad) * Math.cos(distanceM / R) +
      Math.cos(latRad) * Math.sin(distanceM / R) * Math.cos(brngRad)
    );
    const newLonRad = lonRad + Math.atan2(
      Math.sin(brngRad) * Math.sin(distanceM / R) * Math.cos(latRad),
      Math.cos(distanceM / R) - Math.sin(latRad) * Math.sin(newLatRad)
    );

    return { lat: newLatRad * 180.0 / Math.PI, lon: newLonRad * 180.0 / Math.PI };
  },

  estimateRoadWidthM(road) {
    if (!road) return 6.0;
    const tags = road.tags || {};
    if (tags.width) {
      const w = parseFloat(String(tags.width).replace(/[^\d.]/g, ""));
      if (w > 0) return w;
    }
    if (tags.lanes) {
      const l = parseInt(String(tags.lanes).replace(/\D/g, ""), 10);
      if (l > 0) return l * 3.5;
    }
    const hw = tags.highway || road.type || "residential";
    if (["motorway", "trunk", "primary"].includes(hw)) return 16.0;
    if (hw === "secondary") return 12.0;
    if (hw === "tertiary") return 8.5;
    if (["residential", "unclassified"].includes(hw)) return 6.0;
    if (["service", "living_street", "pedestrian", "footway", "path", "track"].includes(hw)) return 4.0;
    return 6.0;
  },

  // 寬路分側、窄巷居中自適應吸附 (Adaptive Road Snapping)
  snapPedestrianToRoad(lat, lon, geom, road, lastSide = null) {
    if (!geom || geom.length < 2) return { min_dist: 0, lat, lon, side: "center" };

    let minDist = Infinity;
    let bestProjLat = lat;
    let bestProjLon = lon;
    let bestSegIdx = 0;

    const avgLatRad = (lat * Math.PI / 180.0);
    const cosLat = Math.cos(avgLatRad);
    const mPerDegLat = 111139.0;
    const mPerDegLon = 111139.0 * cosLat;

    for (let i = 0; i < geom.length - 1; i++) {
      const [lat1, lon1] = geom[i];
      const [lat2, lon2] = geom[i + 1];

      const px = (lon - lon1) * mPerDegLon;
      const py = (lat - lat1) * mPerDegLat;
      const vx = (lon2 - lon1) * mPerDegLon;
      const vy = (lat2 - lat1) * mPerDegLat;

      const l2 = vx * vx + vy * vy;
      let t = 0.0;
      let dist = 0.0;
      if (l2 === 0) {
        dist = Math.sqrt(px * px + py * py);
      } else {
        t = Math.max(0.0, Math.min(1.0, (px * vx + py * vy) / l2));
        const projX = t * vx;
        const projY = t * vy;
        dist = Math.sqrt((px - projX) ** 2 + (py - projY) ** 2);
      }

      if (dist < minDist) {
        minDist = dist;
        bestSegIdx = i;
        bestProjLat = lat1 + t * (lat2 - lat1);
        bestProjLon = lon1 + t * (lon2 - lon1);
      }
    }

    const roadWidth = this.estimateRoadWidthM(road);

    // 1. 窄巷弄 (< 8m)：直接吸附至中心線 (居中，消除乒乓效應)
    if (roadWidth < 8.0) {
      return { min_dist: minDist, lat: bestProjLat, lon: bestProjLon, side: "center" };
    }

    // 2. 寬馬路 (>= 8m)：依左右側吸附至路側人行道
    const [lat1, lon1] = geom[bestSegIdx];
    const [lat2, lon2] = geom[bestSegIdx + 1];

    const vx = (lon2 - lon1) * mPerDegLon;
    const vy = (lat2 - lat1) * mPerDegLat;
    const segLen = Math.sqrt(vx * vx + vy * vy);
    if (segLen === 0) {
      return { min_dist: minDist, lat: bestProjLat, lon: bestProjLon, side: "center" };
    }

    const px = (lon - lon1) * mPerDegLon;
    const py = (lat - lat1) * mPerDegLat;

    const cross = vx * py - vy * px;
    const rawSide = cross > 0 ? "left" : "right";
    const lateralDist = Math.abs(cross) / segLen;

    let currentSide = rawSide;
    if (lateralDist < 1.5 && (lastSide === "left" || lastSide === "right")) {
      currentSide = lastSide;
    }

    const sidewalkOffsetM = Math.min(Math.max(roadWidth / 2.0 - 1.0, 2.5), 18.0);
    const nx = currentSide === "right" ? (vy / segLen) : (-vy / segLen);
    const ny = currentSide === "right" ? (-vx / segLen) : (vx / segLen);

    const offsetLat = bestProjLat + (ny * sidewalkOffsetM) / mPerDegLat;
    const offsetLon = bestProjLon + (nx * sidewalkOffsetM) / mPerDegLon;

    return { min_dist: minDist, lat: offsetLat, lon: offsetLon, side: currentSide };
  }
};

// 2. 台灣 50+ 熱門連鎖品牌清洗大字典 (Taiwan Brand Sanitizer)
const TaiwanBrandSanitizer = {
  brands: {
    "7-Eleven": "7-Eleven 統一超商", "7-11": "7-Eleven 統一超商", "統一超商": "7-Eleven 統一超商",
    "FamilyMart": "全家便利商店", "全家": "全家便利商店",
    "Hi-Life": "萊爾富便利商店", "萊爾富": "萊爾富便利商店",
    "OK Mart": "OK便利商店", "OK超商": "OK便利商店",
    "PX Mart": "全聯福利中心", "全聯": "全聯福利中心",
    "Carrefour": "家樂福", "美廉社": "美廉社", "愛買": "愛買", "大潤發": "大潤發", "Costco": "好市多",
    "50嵐": "50嵐手搖飲", "清心福全": "清心福全飲料店", "Louisa": "路易莎咖啡", "路易莎": "路易莎咖啡",
    "Starbucks": "星巴克咖啡", "星巴克": "星巴克咖啡", "Milksha": "迷客夏手搖飲", "迷客夏": "迷客夏手搖飲",
    "可不可": "可不可熟成紅茶", "麻古": "麻古茶坊", "大苑子": "大苑子水果茶", "CoCo": "CoCo都可飲料",
    "龜記": "龜記茗品", "得正": "得正烏龍茶", "五桐號": "五桐號手搖飲", "春水堂": "春水堂人文茶館",
    "麥當勞": "麥當勞速食店", "McDonald's": "麥當勞速食店", "肯德基": "肯德基炸雞", "KFC": "肯德基炸雞",
    "摩斯": "摩斯漢堡 MOS", "MOS Burger": "摩斯漢堡 MOS", "八方雲集": "八方雲集鍋貼水餃",
    "三商巧福": "三商巧福牛肉麵", "爭鮮": "爭鮮迴轉壽司", "壽司郎": "壽司郎 Sushiro", "藏壽司": "藏壽司 Kura",
    "康是美": "康是美藥妝店", "屈臣氏": "屈臣氏藥妝店", "Watsons": "屈臣氏藥妝店", "寶雅": "寶雅生活館",
    "POYA": "寶雅生活館", "大創": "大創百貨 DAISO", "無印良品": "無印良品 MUJI", "NET": "NET服飾",
    "UNIQLO": "UNIQLO優衣庫", "GU": "GU服飾", "小北百貨": "小北百貨", "光南": "光南大批發",
    "九乘九": "九乘九文具專家", "金石堂": "金石堂書店", "誠品": "誠品生活書店",
    "台灣中油": "台灣中油加油站", "中油": "台灣中油加油站", "全國加油站": "全國加油站",
    "台塑加油站": "台塑加油站", "台亞加油站": "台亞加油站",
    "台灣銀行": "台灣銀行", "土地銀行": "土地銀行", "合作金庫": "合作金庫銀行", "第一銀行": "第一商業銀行",
    "華南銀行": "華南銀行", "彰化銀行": "彰化銀行", "台北富邦": "台北富邦銀行", "國泰世華": "國泰世華銀行",
    "兆豐銀行": "兆豐國際商銀", "玉山銀行": "玉山銀行", "台新銀行": "台新國際商銀", "中國信託": "中國信託銀行",
    "中華郵政": "中華郵政郵局", "郵局": "中華郵政郵局"
  },

  sanitizeName(rawName, tags = {}) {
    if (!rawName) return "未知名稱設施";
    for (const [key, cleanName] of Object.entries(this.brands)) {
      if (rawName.includes(key)) return cleanName;
    }
    return rawName.replace(/股份有限公司|分公司|門市|分店/g, "").trim();
  }
};

// 3. 空間路口拓撲分析器 (Intersection Topology Analyzer)
class IntersectionAnalyzerJS {
  analyze(lat, lon, headingDeg, roads, crossings = []) {
    let nearestDist = Infinity;
    let upcomingJunction = null;
    let branchRoads = [];

    // Find upcoming road intersections (extended to next junction up to 500m)
    for (const road of roads) {
      const geom = road.geometry || [];
      for (const pt of geom) {
        const d = NMapGeometry.haversineDistance(lat, lon, pt[0], pt[1]);
        if (d < 500.0) {
          const brng = NMapGeometry.calculateBearing(lat, lon, pt[0], pt[1]);
          const rel = NMapGeometry.relativeBearing(headingDeg, brng);
          if (Math.abs(rel) <= 45.0 && d < nearestDist) {
            nearestDist = d;
            upcomingJunction = {
              lat: pt[0],
              lon: pt[1],
              distance_m: d,
              road_name: road.name || "主要道路"
            };
          }
        }
      }
    }

    // Analyze nearby zebra crossings
    let nearestCrossingDist = Infinity;
    for (const c of crossings) {
      const cd = NMapGeometry.haversineDistance(lat, lon, c.lat, c.lon);
      if (cd < 40.0) {
        const cBrng = NMapGeometry.calculateBearing(lat, lon, c.lat, c.lon);
        const cRel = NMapGeometry.relativeBearing(headingDeg, cBrng);
        if (Math.abs(cRel) <= 45.0 && cd < nearestCrossingDist) {
          nearestCrossingDist = cd;
        }
      }
    }

    return {
      has_upcoming_junction: upcomingJunction !== null,
      junction_distance_m: upcomingJunction ? Math.round(upcomingJunction.distance_m) : null,
      junction_type: nearestCrossingDist < 25.0 ? "十字路口（含斑馬線）" : "路口分支",
      crossing_distance_m: nearestCrossingDist < 40.0 ? Math.round(nearestCrossingDist) : null,
      intersecting_roads: upcomingJunction ? [upcomingJunction.road_name] : []
    };
  }
}

// 4. 客戶端空間世界模型 (Client World Model)
class ClientWorldModel {
  constructor() {
    this.roads = [];
    this.pois = [];
    this.crossings = [];
    this.buildings = [];
    this.intersectionAnalyzer = new IntersectionAnalyzerJS();
    this.lastSide = null;
  }

  loadFromOverpassJSON(osmData, centerLat, centerLon) {
    this.roads = [];
    this.pois = [];
    this.crossings = [];
    this.buildings = [];

    const nodesMap = {};
    for (const el of (osmData.elements || [])) {
      if (el.type === "node") {
        nodesMap[el.id] = [el.lat, el.lon];
        if (el.tags) {
          if (el.tags.highway === "crossing") {
            this.crossings.push({ id: el.id, lat: el.lat, lon: el.lon, tags: el.tags });
          }
          if (el.tags.name || el.tags.amenity || el.tags.shop) {
            const cleanName = TaiwanBrandSanitizer.sanitizeName(el.tags.name, el.tags);
            this.pois.push({
              id: el.id,
              name: cleanName,
              category: el.tags.amenity || el.tags.shop || "店家",
              lat: el.lat,
              lon: el.lon,
              tags: el.tags
            });
          }
        }
      }
    }

    for (const el of (osmData.elements || [])) {
      if (el.type === "way") {
        const geom = (el.nodes || []).map(nid => nodesMap[nid]).filter(Boolean);
        if (geom.length >= 2) {
          if (el.tags && el.tags.highway) {
            this.roads.push({
              id: el.id,
              name: el.tags.name || "未命名道路",
              type: el.tags.highway,
              geometry: geom,
              tags: el.tags
            });
          }
        }
      }
    }
  }

  getNearbyPois(lat, lon, headingDeg, radiusM = 60.0) {
    const list = [];
    for (const poi of this.pois) {
      const dist = NMapGeometry.haversineDistance(lat, lon, poi.lat, poi.lon);
      if (dist <= radiusM) {
        const brng = NMapGeometry.calculateBearing(lat, lon, poi.lat, poi.lon);
        const rel = NMapGeometry.relativeBearing(headingDeg, brng);
        list.push({
          ...poi,
          distance_m: Math.round(dist),
          bearing_deg: Math.round(brng),
          relative_bearing: Math.round(rel),
          clock_position: NMapGeometry.bearingToClockPosition(rel),
          direction_label: NMapGeometry.bearingToRelativeDirection(rel)
        });
      }
    }
    return list.sort((a, b) => a.distance_m - b.distance_m);
  }

  findNearestRoad(lat, lon) {
    let minDist = Infinity;
    let bestRoad = null;
    for (const r of this.roads) {
      const snap = NMapGeometry.snapPedestrianToRoad(lat, lon, r.geometry, r, this.lastSide);
      if (snap.min_dist < minDist) {
        minDist = snap.min_dist;
        bestRoad = r;
      }
    }
    return { road: bestRoad, dist_m: minDist };
  }

  snapLocation(lat, lon) {
    const { road, dist_m } = this.findNearestRoad(lat, lon);
    if (road && dist_m <= 25.0) {
      const snap = NMapGeometry.snapPedestrianToRoad(lat, lon, road.geometry, road, this.lastSide);
      this.lastSide = snap.side;
      return { lat: snap.lat, lon: snap.lon, road_name: road.name, side: snap.side };
    }
    return { lat, lon, road_name: "主要道路", side: "center" };
  }
}

// 5. 本地 SQLite / IndexedDB 快取橋接器 (Database Cache Bridge)
const NMapCacheDB = {
  getOverpass(queryKey) {
    return new Promise((resolve) => {
      if (typeof window !== "undefined" && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.iOSBridge) {
        const callbackId = "cb_" + Math.random().toString(36).substring(2, 9);
        window._dbCallbacks = window._dbCallbacks || {};
        window._dbCallbacks[callbackId] = (dataJson) => {
          delete window._dbCallbacks[callbackId];
          try {
            resolve(dataJson ? JSON.parse(dataJson) : null);
          } catch (e) {
            resolve(null);
          }
        };
        window.webkit.messageHandlers.iOSBridge.postMessage({
          action: 'getOverpassCache',
          queryKey: queryKey,
          callbackId: callbackId
        });
      } else {
        try {
          const cached = localStorage.getItem("ovp_" + queryKey);
          resolve(cached ? JSON.parse(cached) : null);
        } catch (e) {
          resolve(null);
        }
      }
    });
  },

  setOverpass(queryKey, dataObj) {
    const jsonStr = JSON.stringify(dataObj);
    if (typeof window !== "undefined" && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.iOSBridge) {
      window.webkit.messageHandlers.iOSBridge.postMessage({
        action: 'setOverpassCache',
        queryKey: queryKey,
        dataJson: jsonStr
      });
    } else {
      try {
        localStorage.setItem("ovp_" + queryKey, jsonStr);
      } catch (e) {}
    }
  },

  // 查詢全台 193 萬筆 Overture 離線實體 POI 店家資料庫
  queryOverturePlaces(lat, lon, radiusM = 60.0) {
    return new Promise((resolve) => {
      if (typeof window !== "undefined" && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.iOSBridge) {
        const callbackId = "ovt_" + Math.random().toString(36).substring(2, 9);
        window._dbCallbacks = window._dbCallbacks || {};
        window._dbCallbacks[callbackId] = (dataJson) => {
          delete window._dbCallbacks[callbackId];
          try {
            resolve(dataJson ? JSON.parse(dataJson) : []);
          } catch (e) {
            resolve([]);
          }
        };
        window.webkit.messageHandlers.iOSBridge.postMessage({
          action: 'queryOverturePlaces',
          lat: lat,
          lon: lon,
          radius: radiusM,
          callbackId: callbackId
        });
      } else {
        resolve([]);
      }
    });
  }
};

// 掛載至全域 Window 物件
if (typeof window !== "undefined") {
  window.NMapGeometry = NMapGeometry;
  window.TaiwanBrandSanitizer = TaiwanBrandSanitizer;
  window.IntersectionAnalyzerJS = IntersectionAnalyzerJS;
  window.ClientWorldModel = ClientWorldModel;
  window.NMapCacheDB = NMapCacheDB;

  window.onDatabaseResult = function(callbackId, resultJson) {
    if (window._dbCallbacks && window._dbCallbacks[callbackId]) {
      window._dbCallbacks[callbackId](resultJson);
    }
  };
}
