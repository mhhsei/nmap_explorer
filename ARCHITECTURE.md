# NMap Explorer 專案知識地圖 (Project Knowledge Map)

這是一份針對 **NMap Explorer (Android APK)** 專案的全面導覽地圖。專案採用「Android 原生 + Chaquopy 嵌入式 Python 後端 + WebView 網頁前端」的三層離線優先架構，專為視障者設計無障礙導航與空間音效引導。

## 📍 專案根目錄
`H:\我的雲端硬碟\ai pro\nmap_apk\`

---

## 1. 核心規範與說明文件 (Documentation & Config)
任何開發前必須閱讀的重要文件，定義了架構原則與變更紀錄。

*   [`GEMINI.md`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/GEMINI.md)：**最關鍵的開發守則**。包含無障礙第一原則（精簡語音、防重複冷卻）、純 Python 限制（因 Chaquopy ARM64 限制）、白話註解與代碼同步要求。
*   [`DEVELOPMENT_LOG.md`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/DEVELOPMENT_LOG.md)：**開發與更新日誌**。記錄每次版本更新的痛點解決、架構變更與詳細 Changelog。
*   [`nmap_android_plan.md`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/nmap_android_plan.md)：專案初期從 CLI 轉換為 Android APK 的頂層規劃書。
*   [`app/build.gradle.kts`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/build.gradle.kts)：Android 專案建置檔，包含版本號 (`versionCode`, `versionName`) 與套件相依設定。

---

## 2. 網頁前端層 (WebView UI & Logic)
**路徑**: `app/src/main/python/web/`
負責使用者互動、Web Audio 聽覺圖標與 3D 空間音效、狀態機管理與發送 API 請求至本地 Python 伺服器。

*   [`app.js`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/web/app.js)：**前端核心調度大腦**。
    *   負責每秒輪詢向後端同步狀態 (`POST /api/gps`)。
    *   執行 **聽覺四級降序發話權優先級鏈** (`checkProximityAlerts`)：
        1. `Priority 1`: 人行道障礙物（變電箱/消防栓 $\le 8$m）
        2. `Priority 2`: 視障有聲號誌（APS $\le 22$m）
        3. `Priority 3`: **路口到達三態與連續巷口接力狀態機**（APPROACHING $\to$ PASSING $\to$ LEAVING）
        4. `Priority 4`: **前進走廊店家引導**（緊鄰同側聚類打包、門牌自然錨定）
    *   硬體控制解耦：直接呼叫 `window.AndroidBridge` 啟動/關閉紅綠燈相機，不受語音播報中斷。
*   [`spatial_engine.js`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/web/spatial_engine.js)：**3D 空間音效與 Earcons 引擎**。提供極短促專屬樂器聽覺圖標與 Web Audio API (HRTF) 方位立體聲。
*   `index.html` / `style.css`：前端 UI 介面，嚴格支援螢幕報讀軟體 (TalkBack/NVDA ARIA Live Regions)。

---

## 3. Python 嵌入式後端 (Chaquopy Backend)
**路徑**: `app/src/main/python/`
負責純邏輯運算、空間幾何與拓撲分析、3D 地形高程讀取、地標資料庫檢索。透過 `Bottle` 框架建立輕量級 HTTP API 供前端呼叫。

### 伺服器入口
*   [`server.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/server.py)：Bottle API 伺服器 (127.0.0.1:8000)。定義所有路由（如 `/api/gps`, `/api/intersection`），並將資料組裝為前端需要的 JSON 格式。
*   [`server_runner.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/server_runner.py)：背景啟動器，確保 Bottle 在獨立執行緒穩定運行。

### 空間演算法與地標模組 (`nmap/spatial/`)
*   [`world_model.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/world_model.py)：世界模型。負責門牌地址空間共識仲裁（實體門牌投票）、周遭 POI 店家檢索、以及跨資料庫同名地標智慧去重。
*   [`intersection.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/intersection.py)：**路口分析引擎**。
    *   計算路口幾何、實體交通號誌方位與鐘點走向（排除視覺幾何名詞）。
    *   **對向直行接續路名確認**（如直行接中正路）。
    *   **連續/相鄰路口鏈式接力偵測 (Chained Junction Pacing)**：前方 $\le 12$ 米連續巷口自動生成同側前續與通過接力提示。
*   [`srtm_reader.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/srtm_reader.py)：**NASA SRTM 3D 數位地表高程庫**。
    *   讀取 `data/taiwan_srtm3.zip` 全台 16 塊高程瓦片。
    *   具備 LRU 瓦片快取與四點雙線性插值（查詢耗時 $< 0.05$ms）。
    *   實作 **自適應地表裸地濾波 (Bare-Earth DTM Filter)**，過濾都市高樓雷達毛刺（如 101、85大樓屋頂反射），還原真實行人路面海拔。
*   [`pure_geometry.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/pure_geometry.py)：**純 Python 幾何計算庫**。取代 C-extension（如 shapely），包含 Haversine 距離、射線法等。
*   [`grid_index.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/grid_index.py)：純 Python 網格空間索引，取代 `rtree`，確保 Chaquopy ARM64 相容。
*   [`taiwan_signals.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/taiwan_signals.py)：台灣在地交通號誌與路網特性定義。
*   [`sidewalk_hazards.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/sidewalk_hazards.py)：人行道防撞雷達與安全偵測。

### 語音報讀與 Agent (`nmap/accessibility/` & `nmap/agent/`)
*   [`reporter.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/accessibility/reporter.py)：負責生成極簡的視障專用報讀文案（包含 POI 門牌自然錨定、聚類打包、高程與路口接力）。
*   [`explorer.py`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/python/nmap/agent/explorer.py)：代理人狀態與導航主幹。

---

## 4. Android 原生層 (Kotlin Native)
**路徑**: `app/src/main/java/com/example/nmapexplorer/`
負責與手機底層硬體（感測器、相機、GPS、震動）互動，並透過 WebView Bridge 將能力暴露給網頁前端。

### 應用程式生命週期與橋接
*   [`MainActivity.kt`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/java/com/example/nmapexplorer/MainActivity.kt)：程式進入點。負責要求權限、啟動 Python 引擎、載入 WebView。
*   [`WebAppInterface.kt`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/java/com/example/nmapexplorer/WebAppInterface.kt)：`window.AndroidBridge` 的實作。提供震動反饋、匯出日誌、啟閉相機等 JS 可呼叫的函數。
*   [`ServerForegroundService.kt`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/java/com/example/nmapexplorer/ServerForegroundService.kt)：Android 前台服務，掛載 `location` 類型以確保 Python 後端與定位不被系統殺死。

### 硬體感測與計算
*   [`LocationSensorBridge.kt`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/java/com/example/nmapexplorer/LocationSensorBridge.kt)：**定位與感測核心**。包含 GPS 軌跡平滑、步態偵測 (PDR)、9軸感測器融合計算真北方向、卡爾曼濾波防塌陷機制。
*   [`TrafficSignalCameraManager.kt`](file:///H:/我的雲端硬碟/ai%20pro/nmap_apk/app/src/main/java/com/example/nmapexplorer/TrafficSignalCameraManager.kt)：**紅綠燈相機管理**。整合 CameraX 與 TFLite 影像辨識，並比對手機仰角與偏差角度提示使用者左右轉向。
*   **進階感測濾波器**：
    *   `BarometerVerticalFilter.kt` (氣壓計)
    *   `HatchFilter.kt` / `GnssRawMeasurementProcessor.kt` (GNSS 原始資料處理)

---
*此地圖可做為未來 Debug 與模組重構的快速定位指南。*
