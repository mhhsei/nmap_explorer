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
