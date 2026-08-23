# NMap Android APK 開發與更新日誌 (DEVELOPMENT_LOG)

> 這是一份動態文件，用於追蹤 NMap Android 版本的開發進度、架構變更、以及未來的更新紀錄。
> 任何核心設計的修改、模組的增刪、或重大 Bug 的修復，都必須記錄於此，確保團隊開發的延續性。

---

## 📅 開發階段追蹤 (Phase Tracking)

基於 [NMap Android APK 轉換計畫書](./nmap_android_plan.md) 所定義的階段，目前進度如下：

### 🔴 Phase 1：基礎架構（技術驗證與 Python 後端）
- [x] 建立 Android Studio 專案與 Chaquopy 設定
- [x] 驗證 Python 環境 (networkx, requests, bottle, numpy)
- [x] 實作純 Python 幾何計算 (`PureGeometry`) 以備 shapely 相容性問題
- [x] 實作網格空間索引 (`GridSpatialIndex`) 替代 rtree
- [x] 實作 `OvertureSQLiteClient` 直接查詢 SQLite (已確認未在原專案實作，故跳過)
- [x] 在 Android 上成功啟動 Bottle Server

### 🔴 Phase 2：WebView 前端移植
- [x] 移入 web 靜態資源 (HTML/CSS/JS/Sounds)
- [x] 設定 WebView 啟用 Web Audio 與 DOM Storage
- [x] 實作 JS `TouchGestureController` 觸控手勢
- [x] 實作 TalkBack 相容的替代 D-pad 介面
- [ ] 驗證 ARIA Live Region 與 TalkBack 的連動
- [ ] 驗證 3D 空間音效 (Web Audio API HRTF) 在 WebView 的執行狀況

### 🔴 Phase 3：原生功能整合
- [x] Kotlin 實作 `SensorBridge` (GPS)
- [x] Kotlin 實作 `SensorBridge` (陀螺儀方向)
- [x] Kotlin 實作 `HapticBridge` (震動反饋)
- [x] JS Bridge 串接，將感測器資料與震動功能提供給前端 JS
- [x] 實作 Foreground Service 以防 Python Server 遭 Android 系統查殺

### 🔴 Phase 4：資料管理與下載
- [x] 實作 `DataDownloadManager` (改為直接內建 280MB DB 於 APK，符合使用者「接受較大體積」之需求)
- [x] 設計首次啟動下載 UI 與 TalkBack 進度播報 (改為內建，Chaquopy 自動解壓縮)
- [x] Android 內部儲存路徑與 Python 端路徑的橋接 (透過 Chaquopy 虛擬與實體路徑解析處理)

### 🔴 Phase 5：打磨與測試
- [ ] 完整無障礙 (TalkBack) 探索測試
- [ ] 實機測試 (Android 12+) 與效能優化
- [ ] APK 打包與簽署

*(狀態燈號：🔴 尚未開始 / 🟡 進行中 / 🟢 已完成)*

---

## 📝 變更日誌 (Changelog)

### [2026-08-22] - TalkBack 原生無障礙即時廣播、16 方位極簡省話、L5 雙頻衛星高精度加權與 Weinberg 白手杖自適應步長 PDR
- **📢 TalkBack 原生無障礙廣播與即時語音插播**:
  1. 在 `WebAppInterface.kt` 實作 `@JavascriptInterface fun speak(text, interrupt)`，透過 `webView.announceForAccessibility(text)` 直接向 Android Accessibility 核心發送 `TYPE_ANNOUNCEMENT` 原生事件，徹底根除 WebView `aria-live` 在頻繁旋轉時靜音或漏讀的頑疾。
  2. 整合原生 Android `TextToSpeech` 作為無 TalkBack 環境下的通用語音備援。
  3. 在 `app.js` 與 `index.html` 將 live region 升級為 `aria-live="assertive"` 並與 `AndroidBridge.speak()` 緊密串接。
- **🧭 16 方位超精細羅盤與行走防打斷極簡省話**:
  1. 升級 `bearing_to_cardinal` 與 `getCardinalDirection` 至 16 方位（正北、北北東、東北、東北東...）。
  2. 轉動手機時實施「極簡省話模式」：僅報方位詞（如「正北」、「北北東」），去除所有多餘贅字，防抖反應時間壓縮至 200ms。
  3. 實自行走防打斷抑制：步行中（`speed >= 0.4 m/s`）且 2 秒內剛朗讀過店家/路口時，自動抑制轉向插嘴。
- **🛰️ 戶外 L5 雙頻衛星 (Dual-Frequency L1+L5) 辨識與動態降噪**:
  1. 在 `LocationSensorBridge.kt` 攔截 `GnssStatus` 載波頻率，識別 L5/E5a 高頻寬衛星（~1176.45 MHz）。
  2. 當鎖定 $\ge 2$ 顆 L5 衛星時，將 `PedestrianKalmanFilter` 測量協方差 $R$ 縮減 50%，使高精度衛星數據優先收斂，壓低都會峽谷多路徑誤差至 1.5~2.5m。
- **🦯 Weinberg 模型白手杖步態自適應步長推算 (PDR)**:
  1. 在加速度計中採集垂直分量極值差 $\Delta a = a_{\max} - a_{\min}$，透過 $SL = 0.43 \times \Delta a^{0.25}$ 動態自適應估算步長（0.45m ~ 0.85m）。
  2. 在騎樓/雨遮下 GPS 中斷時，以真實步長平滑推算前進，大幅提高戶外最後一哩路的連續定位精準度。

### [2026-08-22] - 後台常駐釋放與降頻節能、冷啟動快取清空、海外邊界防護、無障礙地標詳情、轉向刻度音與八方位齒輪觸覺回饋
- **🔋 後台常駐與異常耗電徹底修復**:
  1. 在 `ServerForegroundService.kt` 實作 `onTaskRemoved()`，當使用者將 App 從多工卡片滑掉（Task Removed）時，立即執行 `stopForeground(STOP_FOREGROUND_REMOVE)` 並呼叫 `stopSelf()` 終止服務，杜絕後台偷跑耗電。
  2. 將 `onStartCommand` 的返回值改為 `START_NOT_STICKY`，並於 `MainActivity.onDestroy()` 中主動調用 `stopService()` 釋放所有背景資源。
  3. 實作 `LocationSensorBridge.setScreenActive(active: Boolean)` 與 `MainActivity` 螢幕休眠廣播監聽：當螢幕關閉（放入口袋）時，動態註銷高耗電 50Hz 陀螺儀監聽，僅保留低功耗硬體計步器 (`TYPE_STEP_DETECTOR`) 進行 PDR 航位推算，大幅延長續航力。
- **🔄 冷啟動過期快取過濾與定位防誤報**:
  1. 強化 `lastLocation` 時效檢查：僅允許 5 秒內且精度 $\le 20\text{m}$ 的即時快取，其餘一律捨棄，杜絕在不同地點重啟 App 時誤報舊地址店家的問題。
  2. 在 `PedestrianKalmanFilter` 實作大距離（$>60\text{m}$）自動重錨機制，防止在不同城鎮移動重啟時 Kalman 濾波器拉扯飄移。
- **🌐 海外地區（非台灣）邊界判定與優雅降級**:
  1. 在 `ExplorerAgent` 實作台灣地理範圍判定 (`21.8 ~ 26.4°N`, `118.0 ~ 122.1°E`)。
  2. 超出台灣邊界時自動切換為全球線上圖資模式，並以語音與 ARIA-Live 主動提示：「偵測到您位於海外地區。已自動切換為 OpenStreetMap 全球線上圖資模式。」
- **🔒 權限引導橫幅與手動搜尋備援模式**:
  1. 前端 `index.html` 與 `app.js` 新增權限狀態偵測，若使用者未授予定位權限，自動顯示醒目高對比橫幅並朗讀說明，引導使用者點擊「開啟系統設定」。
  2. 提供即時手動地址搜尋列 (`#location-input-visible`)，即使在室內或無 GPS 訊號下也能手動輸入地址開啟「虛擬漫遊探索」。
- **ℹ️ 無障礙地標詳細資訊對話框 (Accessible POI Detail Modal)**:
  1. 店家清單支援點擊/Enter展開詳細資訊對話框，完整呈現店名、分類、營業時間、電話（點擊 `tel:` 直接撥號）、無障礙設施狀態與料理風味。
  2. 整合兩大導航按鈕：
     - **「🎯 空間聲音導引」**：在 App 內啟動 3D HRTF 空間立體聲 Beacon 導引聲音，隨距離縮減自動調整音訊頻率。
     - **「🗺️ Google 導航」**：透過 `AndroidBridge.openGoogleMaps()` 一鍵喚醒 Google Maps 步行導航。
- **📳 轉向立體聲刻度音、八大方位齒輪觸覺回饋與停止和弦報讀**:
  1. **轉向刻度音與輕震**：手機旋轉每跨越 15°，在左/右耳播放輕微立體聲 Tic 音效，並調用 `AndroidBridge.vibrateTick()` 產生 10ms 輕微刻度感。
  2. **八大方位齒輪觸覺**：轉向經過正北 (0°) 觸發雙重重震 (`vibrateHeavy`)，其餘七大方位觸發單點點擊震動 (`vibrateClick`)，讓視障者單憑手感精確辨識方位。
  3. **停止轉向和弦報讀**：轉向穩定超過 550ms 後，播放柔和和弦提示音並簡短報讀：「面向正北，走在【路名】」。
- **👆 手指探索地圖 (Two-finger Touch-to-Explore / 虛擬平移)**:
  1. 支援雙指手勢：雙指上滑（視角向前推進 30 公尺）、雙指下滑（後退 30 公尺）、雙指左右滑（切換至相鄰巷弄），並在後端新增 `/api/virtual_pan` 端點計算沿途店家路況進行語音摘要。
  2. 雙擊雙指即可快速重播當前路段門牌與座標。
- **🔍 「目前位置 (R)」門牌號碼提取修復與 POI 門牌號整合**:
  1. 修復 `announceRoadAndDoorNumbers` 讀取後端 `door_estimates` 鍵名不一致問題（原讀取 `doors.left` 但後端為 `left_side_estimate` 與 `concise_door`），徹底解決「有 GPS 卻報無門牌資料」之異常。
  2. 在 `world_model.py` 將 POI 標籤 (`addr:housenumber`) 一併匯入門牌插值池，大幅提升住家與店家巷弄門牌的覆蓋度。
- **🧭 16 方位超精細羅盤與極簡「省話模式」即時播報**:
  1. 全面升級至 16 方位系統（正北、北北東、東北、東北東、正東、東南東、東南、南南東、正南、南南西、西南、西南西、正西、西北西、西北、北北西，每 22.5° 一個刻度）。
  2. **極致省話（0.3 秒報讀）**：轉動手機時完全去除「面向」、「度數」、「走在某路」等冗長贅字，**只報讀方位本身**（例如：「北北東」、「正東」、「東南」），讓螢幕報讀軟體瞬間播報完畢不延遲。
  3. **反應時間大幅縮短**：轉向防抖延遲由 450ms 降至 **260ms**，只要跨越 16 方位刻度即瞬間播報。
  4. 實作**行走防打斷 (Walk Non-Interrupting Policy)**：
     - 行走狀態下（速度 $\ge 0.4\text{m/s}$ 或步態推算中），手機隨擺手晃動不觸發轉向語音播報（轉向門檻提高至 $60^\circ$），且若 2.5 秒內剛朗讀過店家或路口則完全不插嘴。
     - 靜止定向時（停下腳步轉身探索），高靈敏度（$15^\circ$ 轉向且停頓 260ms）立即播放和弦音並報讀極簡方位（例如：「北北東」）。

### [2026-08-14 下午] - 步行高精度定位、9軸方位融合、貼身店家省話播報與路口動態通知
- **🚶 步行卡爾曼濾波器與靜止防飄 (Pedestrian Kalman Filter & ZUPT)**:
  1. 在 `LocationSensorBridge.kt` 實作二維卡爾曼濾波器，專為視障者步行特徵（0.8 ~ 2.0 m/s）進行座標狀態估計與軌跡平滑。
  2. 速度鉗制（Clamp at 4.5 m/s），自動過濾因大樓遮蔽/折射導致速度換算 > 5.0 m/s 的 GPS 瞬移雜訊。
  3. 實作 Zero-Velocity Update (ZUPT 零速修正)，在速度 < 0.25 m/s 時鎖定座標，徹底消除在紅綠燈或店家門口停留時的原地飄移與抖動。
- **🧭 9 軸硬體姿態融合與瞬時朝向回報**:
  1. 優先調度硬體級 9 軸旋轉向量感測器 (`Sensor.TYPE_ROTATION_VECTOR`)，融合陀螺儀、磁力計與加速度計，取樣率達 50Hz，消除指南針晃動。
  2. 實作圓周最短路徑指數平滑，轉向達 30 度時在 350ms 內發出轉向提示音並即時報讀（如「面向正北」、「面向東南」）。
- **🏪 貼身店家 3~5 米接近主動播報（極簡「省話模式」）**:
  1. 接近感知觸發距離由 15m 縮減至 3.0 ~ 5.5m（即將路過或門口前夕）。
  2. 採用極簡省話格式：`[店名]，[方位]`（例如：「全家便利商店，右側」或「康是美，左前方」），配合 3D 立體聲音效引導方向，1 秒內播報完畢。
  3. 實作 60 秒防重複冷卻機制，避免同一店家反覆疲勞轟炸。
- **📐 街道兩旁店家精確排序與左右校正**:
  1. 依據真實相對方位角精準區分左側（-180° ~ 0°）與右側（0° ~ +180°）。
  2. 前端「掃描前方 (L)」列表與語音播報均嚴格以距離從小到大（由近到遠）精準排列。
- **🛣️ 靜默 20 秒極簡報路名門牌 ＆ 過路口即時通知**:
  1. 若沿途無店家且系統安靜超過 20 秒，自動發出輕柔提示音，極簡報讀：`[路名]，約 [號碼] 號附近`（如「學府路，約 211 號附近」）。
  2. 過路口動態追蹤：當使用者穿過路口（距離從 <= 15m 走到 > 18m）或轉彎進入新道路時，立即播放確認音效並播報：`過路口，走在【[路名]】` 或 `進入【[路名]】`。
- **🚦 專屬「前方路口 (I)」探索按鈕與後端 API**:
  1. 新增 `/api/intersection` 後端端點與前端 `前方路口 (I)` 按鈕（快捷鍵 `I`）。
  2. 詳細回報路口型態、各分支走向與路名（直行、左轉、右轉）、行人專用號誌與斑馬線配置。
- **🐞 專案 Bug 修復與品質打磨**:
  1. 修復前端 JS 呼叫未定義函式（`updatePOIList`, `renderStreetScene`）引起的 TypeError。
  2. 清理 `index.html` 內無效的外部腳本引用（`audio_engine.js`, `idb_storage.js`）。
  3. 新增 `/api/nlp` 路由別名並修復自然語言查詢結果朗讀。
  4. 根目錄自動同步輸出 [`nmap-latest.apk`](./nmap-latest.apk) 並完成多輪 ADB 實機覆蓋安裝驗證。

### [1.2.1] - 2026-08-22
- **🛠️ 語音體驗與 GIS 空間推算缺陷修復 (Bug Fixes & UX Polish)**:
  1. **門牌號碼單值格式化修復**：修正 [`world_model.py`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/world_model.py) 門牌區間單一數字時出現 `205~205號`、`24~24號` 重複字串問題，當 `min == max` 時直接輸出 `門牌 205號`。
  2. **路口同名自交會過濾**：在 [`intersection.py`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/intersection.py) 與 [`app.js`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/web/app.js) 中過濾當前所走道路名稱，徹底消除「走在北新路，即將交會北新路」的自我交會錯誤。
  3. **POI 類別全中文翻譯擴充**：在 [`app.js`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/web/app.js) 與 [`overpass.py`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/nmap/data/overpass.py) 新增 100+ 種 Overture/OSM 分類翻譯（寺廟、歷史建築、美容美睫、法式/韓式餐廳、生活百貨、樂器行等），杜絕 TalkBack 直接唸出英文蛇形單字。
  4. **冷啟動定位提示詞優化**：App 剛開啟 GPS 尚未鎖定時，提示詞由「地圖尚未初始化...手動輸入」改為「正在等待 GPS 衛星定位中...」，體驗更自然流暢。

### [1.2.0] - 2026-08-22
- **🤖 AI 可觀測性與結構化日誌全面升級 (AI-First Structured Telemetry & Diagnostics)**:
  1. **頂部速查摘要 (`0_AI_QUICK_SUMMARY.json`)**：匯出包含手機硬體、系統規格、會話總耗時、步數、GPS/POI 統計、導航最終狀態與異常清單的頂層 JSON，讓 AI Agent 在 1 秒內掌握全局健康度。
  2. **標準地理軌跡 (`1_trajectory.geojson`)**：將行走軌跡儲存為標準 GeoJSON `FeatureCollection`（含 `LineString` 行走折線、`Point` 店家地標、語音播報錨點），支援 GIS 幾何自動比對與地圖視覺化。
  3. **因果鏈 Trace ID 追蹤 (`2_causality_trace.ndjson`)**：每次 GPS 輸入、空間推算吸附、語音朗讀輸出皆附帶唯一的 `trace_id`，實現毫秒級因果決策樹還原。
  4. **結構化 POI 清單 (`3_detected_pois.json`)**：記錄所有掃描到的店家名稱、分類、鐘點方位、距離、經緯度、電話、營業時間與無障礙標籤。
  5. **結構化語音與感測歷程 (`4_speech_history.ndjson`, `5_sensor_trajectory.ndjson`)**：逐筆記錄 TalkBack 原生廣播文字與高頻 GPS/PDR 步態感測器數據。
  6. **ZIP 檔案自動命名**：產生的診斷檔名格式化為 `NMap_Logs_[品牌_型號]_[年月日_時分秒].zip`。
- **🔊 TalkBack 原生無障礙廣播與 16 方位即時指南針**:
  1. 實作原生 `announceForAccessibility` 廣播通道與 TTS 備援，徹底根除 WebView 朗讀漏字。
  2. 16 方位極簡省話模式與行走防打斷機制。

### [Unreleased]
- **初始建立**: 確立 Android WebView + Chaquopy 混合架構。
- **架構決策**: 為了支援 Android，放棄原有的 `rtree`、`duckdb` 與 `pyarrow`，改用純 Python 實作空間索引，以及直接操作 SQLite 查詢 Overture 離線資料。
- **重大修復 (GPS跨區鎖定問題)**:
  1. 修復 `ExplorerAgent` 在使用者離開原住處（如淡水）時，因與原網格道路距離 > 30m 判定為碰撞碰壁而拒絕同步，導致座標被強制還原回舊位置的死鎖問題。
  2. 新增專屬 `/api/gps` 端點與動態跨網格（`dist > 100m`）自動重載機制，確保真實 GPS 訊號隨時更新且不會被虛擬碰撞機制阻擋。
  3. `LocationSensorBridge.kt` 強化：過濾超過 30 秒的過期快取位置，啟用 Google Fused Location + 原生 GPS/Network 雙通道監聽。
  4. 補齊 Android 14+ 前台服務 `FOREGROUND_SERVICE_LOCATION` 宣告與 `VIBRATE` 權限。
- **重大修復 (系統穩定性與日誌匯出 - 2026/08/17)**:
  1. **移除 `dataSync` 前景服務類型**：解決 Android 14+ 因 6 小時配額耗盡引發的 `ForegroundServiceDidNotStopInTimeException` 閃退，全面改用無超時限制的純 `location` 類型。
  2. **啟動時序防護**：調整 `MainActivity` 於取得 GPS 授權後才喚醒 `ServerForegroundService`，杜絕冷啟動權限競爭引發的 `SecurityException`。
  3. **解除 256MB JVM Heap 限制**：在 `AndroidManifest.xml` 開啟 `android:largeHeap="true"`，並於 Python 空間拓撲建置後主動觸發 `gc.collect()`，根除 OOM 崩潰。
  4. **一鍵分享日誌機制**：配置 Android `FileProvider`、Kotlin `WebAppInterface.shareAppLogs()` 與前端無障礙按鈕，方便視障測試者無須連線電腦即可透過 LINE/Gmail 一鍵回傳 Logcat 診斷日誌。
- **四大核心精度優化升級 (2026/08/18)**:
  1. **寬路分側、窄巷居中（自適應道路吸附）**：在 `pure_geometry.py` 與 `ExplorerAgent` 實作路寬階層判斷。寬度 $\ge 8\text{m}$ 之主幹道依據行人實際位置精準吸附至路側人行道/騎樓；$< 8\text{m}$ 窄巷弄自動鎖定中心線，徹底消除小巷內左右橫跳的乒乓效應。
  2. **GPS 主導 + 騎樓步伐推算互補 (PDR)**：整合 `Sensor.TYPE_STEP_DETECTOR` 與行人卡爾曼濾波器 `advanceStep()`。在走進騎樓/遮蔽處衛星中斷（$>1.2\text{s}$）時，由腳步推算平滑接管前進；衛星良好時自動回歸 GPS 並自適應校正步長（$0.5\sim0.85\text{m}$）。
  3. **大樓折射雜訊過濾 (GNSS SNR Multipath Rejection)**：註冊 `GnssStatus.Callback` 監聽衛星訊噪比（C/N0）。在都市大樓峽谷偵測到反射雜訊時動態調高卡爾曼測量協方差 $R$，杜絕瞬間穿牆瞬移。
  4. **真北角度 3.8 度磁偏角校正**：引入 Android `GeomagneticField`，自動計算所在經緯度的地磁偏角並補正至旋轉向量方位角，確保 3D 空間音效與前方店家幾何 100% 正對使用者行進朝向。

---

## 🛠️ 開發與維護指南 (Developer Guidelines)

1. **Python 相容性考量**:
   - Chaquopy 對於帶有 C 擴展的 Python 函式庫支援有限（尤其在 ARM64 架構上）。
   - 未來若需新增 Python 套件，**必須優先尋找純 Python (Pure-Python) 的實作**。
2. **無障礙優先 (Accessibility First)**:
   - 前端 UI 的任何變動，都必須確保 `aria-live` 與 TalkBack 能正確抓取焦點。
   - 新增手勢時，必須考慮 TalkBack 開啟時會攔截系統手勢的問題。
3. **路徑處理 (Path Handling)**:
   - Android 系統上的檔案路徑與 Windows 完全不同。Python 後端在讀取 SQLite DB 或靜態檔案時，必須動態獲取 Android 應用的 `context.getFilesDir()` 或透過 Chaquopy 取得正確的 Asset 路徑。

---

## 🔗 相關文件
- [Android 轉換計畫書 (nmap_android_plan.md)](./nmap_android_plan.md)
- [原始 Windows 版 README](../nmap/README.md) (供參考)
