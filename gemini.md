# NMap Explorer 開發規範與維護指引 (gemini.md)

> 本文件為 NMap Explorer 專案的核心開發守則與維護規範。
> 任何參與本專案的開發者與 AI Agent 在進行程式碼撰寫、模組重構、依賴調整或除錯時，**必須嚴格遵守本文件之所有規定**。

---

## 1. 專案核心定位與無障礙第一原則 (Accessibility First)

1. **使用者族群**：視障者（使用 NVDA 螢幕報讀軟體於 PC 端，或 TalkBack / VoiceOver 於行動裝置）。
2. **語音輸出精簡化（省話模式）與聽覺優先級鏈 (Priority Chain)**：
   - 視障者需同時聆聽現實環境聲音（車聲、腳步聲、盲杖回聲）。
   - 前端發話權嚴格實施四級降序調度，**低優先級絕對禁止搶播蓋台**：
     1. `Priority 1 (生命安全防撞)`：人行道危險障礙物（變電箱、消防栓、施工 $\le 8.0$ 米）。
     2. `Priority 2 (視障有聲設施)`：視障有聲號誌（APS 鳥鳴/蟋蟀聲 $\le 22.0$ 米）。
     3. `Priority 3 (路口生命線狀態機)`：路口預告、直行對向接續、連續巷口接力。
     4. `Priority 4 (前進走廊店家與門牌)`：同側聚類打包、門牌自然錨定。
   - 單次語音回饋嚴禁冗長贅字，報讀必須控制在 0.6 ~ 1.2 秒內播報完畢。
3. **前進路徑走廊店家優先導引 (Forward Corridor POI Guidance)**：
   - 沿著行進真北朝向動態篩選前方走廊（前方 2.0 ~ 18.0 公尺、兩側橫向 $\le 14$ 公尺）內的店家，自動排除身後與遠處雜訊。
   - **緊鄰同側店家聚類打包 (POI Cluster Grouping)**：同側 2~3 家相鄰店家（角度差 $\le 28^\circ$ 且距離差 $\le 6.0$ 米）自動合併為 `[鐘點] [距離]：[店名A] ([門牌])、[店名B]`，減少 70% 重複方位詞。
   - **門牌自然錨定 (Door Number Anchoring)**：店家名稱後自動附帶門牌號碼（例如：`全家 (205號)，2點鐘 8米`），協助建立門牌心智地圖。
   - 具備 40 秒防重複冷卻機制與抵達確認（$< 3.8$ 米提示 `🎉 抵達【店名】`）。
4. **路口精準到達三態狀態機與連續接力 (Junction Arrival & Chained Pacing)**：
   - 嚴格劃分狀態：
     - `APPROACHING`（接近中，8~25 公尺）：以**鐘點走向**提示前方交會路段（例如：`左 10點鐘 大忠街，右 2點鐘 大忠街`），嚴禁使用視覺偏見名詞（如「十字路口/T字路」）。
     - `PASSING`（正通過，< 6 公尺）：短促提示過馬路，若對向接續道路變更則報讀 `📍 正通過路口，直行接【中正路】。`。
     - `LEAVING`（通過後，6~18 公尺）：提示 `📍 沿著【目前路名】繼續前進。`，具備 45 秒獨立冷卻防抖，杜絕原地跳針。
   - **連續/相鄰路口接力機制 (Chained Junction Pacing)**：
     - 若前方相距 $\le 12$ 公尺內有連續相鄰巷弄，接近時預告全貌（同側：`右 2點鐘 182巷，前續 184巷`；錯位：`左 9點鐘 182巷，右 2點鐘 184巷`）。
     - 跨過第 1 條巷子瞬間即時接力報讀：`📍 通過【182巷】，右前方 5米【184巷】。`，提供盲杖行進時最即時的空間里程碑。
5. **聽覺圖標優先 (Earcons First) 與 3D 空間音效**：
   - 考量視障使用者上街多數**不戴耳機（依賴手機擴音器以保持耳朵對外界環境警戒）**，系統優先採用「極短促專屬樂器音效 (Earcons, ~100ms)」建立聲音反射神經（超商為清脆叮噹聲、餐廳為木質敲擊聲、路口為向上滑音），輔以 Web Audio API (HRTF) 空間定位。
6. **ARIA-Live 即時連動**：
   - 前端所有狀態變更必須正確綁定 `aria-live="polite"` 或 `aria-live="assertive"`（危險警告），確保螢幕報讀軟體能即時抓取焦點。
7. **無障礙法規規範**：
   - 開發必須嚴格遵守 WCAG 2.2 AAA 無障礙規範。

---

## 2. 系統技術架構與目錄規範

專案採用 Android 離線優先架構（原生 Kotlin + Chaquopy 嵌入式 Python 後端）：

```
C:/ai pro/nmap_apk/
├── app/                                # Android 原生與 Python 後端專案
│   ├── src/main/java/com/example/nmapexplorer/
│   │   ├── MainActivity.kt             # 應用生命週期、Chaquopy 初始化與 WebView 載入
│   │   ├── LocationSensorBridge.kt     # 卡爾曼濾波、9 軸姿態融合、PDR 航位推算、GNSS 雜訊過濾
│   │   ├── WebAppInterface.kt          # 震動反饋與一鍵打包 Logcat 診斷日誌 (.zip)
│   │   └── ServerForegroundService.kt  # Android 14+ 前台服務保活
│   └── src/main/python/                # Chaquopy 嵌入式 Python 後端
│       ├── server.py                   # Bottle 輕量 HTTP API 伺服器 (127.0.0.1:8000)
│       ├── server_runner.py            # 背景執行緒啟動器
│       ├── data/                       # 離線資料庫 (overture_places.db, gov_places.db)
│       ├── nmap/                       # 核心演算法庫 (spatial, agent, accessibility)
│       └── web/                        # 前端靜態資源 (HTML5/CSS/JS, Web Audio)
├── .github/workflows/
│   └── build-and-release.yml           # GitHub Actions Android APK 自動編譯發布工作流程
├── DEVELOPMENT_LOG.md                  # 開發履歷與 Changelog 追蹤檔
├── nmap_android_plan.md                # 轉換計畫書與頂層架構設計
├── ARCHITECTURE.md                     # 專案知識地圖與詳細檔案導航 (AI Agent 大腦地圖)
└── gemini.md                           # 本開發守則
```

---

## 3. Python 後端開發與相容性鐵律 (Chaquopy ARM64)

> [!CAUTION]
> Chaquopy 執行於手機 ARM64 架構上，對底層含有 C/C++ 擴展的第三方套件支援極為嚴格。

1. **純 Python (Pure-Python) 原則**：
   - 嚴禁引入依賴 `GEOS`, `libspatialindex`, `arrow` 等 C 函式庫的套件（如 `rtree`, `duckdb`, `pyarrow`, `shapely`）。
   - 幾何運算一律使用 [`pure_geometry.py`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/pure_geometry.py) 實作（Haversine、射線法 Point-in-Polygon、向量交點計算）。
   - 空間索引一律使用 [`grid_index.py`](file:///C:/ai%20pro/nmap_apk/app/src/main/python/nmap/spatial/grid_index.py) 純 Python 網格索引。
2. **白名單套件清單**：
   - 允許之套件僅限 `app/build.gradle.kts` 中宣告的：`networkx`, `requests`, `bottle`, `numpy`。
3. **離線 SQLite 資料庫存取**：
   - 地標查詢一律透過 Python 內建 `sqlite3` 直接操作 `overture_places.db` 與 `nmap_cache.db`。
   - 查詢必須建立 B-Tree 或 R-Tree 空間索引，且單次查詢響應時間必須壓在 25ms 內。
4. **記憶體防護**：
   - 空間拓撲圖建置或大範圍圖資重載後，必須主動呼叫 `import gc; gc.collect()` 釋放未引用物件，防止手機端 OOM (Out Of Memory)。

---

## 4. 定位與感測器演算法法則 (Navigation & Sensor Rules)

1. **二維步行卡爾曼濾波防協方差塌陷鐵律 (Anti-Divergence Kalman Filter)**：
   - **全時注入過程雜訊 ($Q$)**：手持手機行走時，硬體計步器可能漏觸發。**嚴禁僅依賴步伐事件注入過程雜訊**。非靜止狀態下每次時間更新必須全時注入過程雜訊（$q_{pos} \ge 1.8\text{ m}^2/\text{s}$），防止協方差 $P \to 0$ 導致濾波器拒絕真實 GPS 測量。
   - **新息門控連續異常自動拉回 (Anti-Lockout Outlier Recovery)**：連續 2 筆 GPS 落在卡方門控外且自身距離一致（$< 15\text{m}$），立即判定為使用者真實物理位移並自動重新對齊，消滅整條街（80m）的滯後凍結。
   - **軟硬體雙重步伐偵測 (Dual-Source Step Detection)**：在 50Hz 加速度計上實作動態波峰檢測（峰值 $> 11.2\text{ m/s}^2$，間隔 $> 330\text{ms}$），作為硬體計步器的全時備援。
   - **速度鉗制**：瞬時速度換算步行 $> 4.0\text{ m/s}$（乘車 $> 25\text{ m/s}$）時予以壓制。
   - **ZUPT 零速修正 (Zero-Velocity Update)**：當判定為靜止鎖定（`STATIONARY_LOCKED`）時強制凍結座標，杜絕室內原地跳動。
2. **大樓折射雜訊過濾 (GNSS Multipath Rejection)**：
   - 透過 `GnssStatus.Callback` 監控衛星 C/N0 訊噪比。當平均 SNR $< 21\text{ dB-Hz}$ 判定為都市峽谷反射，動態放大卡爾曼測量協方差 $R$（提高 4 倍），防止穿牆瞬移。
3. **真北角度 3.8° 磁偏角校正**：
   - 調度 9 軸硬體旋轉向量感測器 (`Sensor.TYPE_ROTATION_VECTOR`)，融合陀螺儀、磁力計與加速度計。
   - 使用 Android `GeomagneticField` 動態取得所在經緯度之地磁偏角（台灣約 -3.8°）補正為地理真北，確保 3D 音效與使用者行進方向 100% 吻合。
4. **PDR 騎樓航位推算 (Pedestrian Dead Reckoning)**：
   - 整合硬體計步器與軟體加速度波峰檢測。
   - 當 GPS 衛星訊號中斷 $> 1.2\text{ 秒}$（如走進騎樓或地下連通道），由卡爾曼 `advanceStep()` 依據當前真北朝向平滑推算前進，並自動依據過往 GPS 速度校準個人步長（$0.50\sim0.85\text{ m}$）。
5. **自適應道路吸附**：
   - 路寬 $\ge 8\text{ 公尺}$ 之主幹道依據行人實際位置精準吸附至路側人行道/騎樓。
   - 路寬 $< 8\text{ 公尺}$ 窄巷弄自動鎖定中心線，杜絕巷內左右橫跳的乒乓效應。
6. **3D 數位地表高程定錨與裸地濾波 (SRTM Bare-Earth DTM Filter)**：
   - 專案內嵌全台 16 塊 NASA SRTM3 90 米網格高程庫（`taiwan_srtm3.zip`），供氣壓計即時校準絕對海拔。
   - **消除都市高樓雷達毛刺 (DSM -> DTM)**：在低海拔與平原盆地區（$< 350\text{m}$），必須執行 $3 \times 3$ 鄰域地表基線分析。若局部像素因摩天大樓、高架橋或車站巨構出現突起（$\Delta h > 6.0\text{m}$），演算法自動濾除屋頂回波，強制回退為道路裸地基線加權均值（例如台北 101 信義商圈地面定錨為 16.0m、高雄 85 港邊地面定錨為 7.0m），徹底杜絕氣壓計將山坡路誤判為天橋或室內樓層。

---

## 5. Android 系統穩定性與權限規範

1. **前台服務保活 (Foreground Service)**：
   - 嚴格遵守 Android 14+ 規範，前台服務類型一律使用 `foregroundServiceType="location"`。
   - 嚴禁使用帶有 6 小時執行配額上限的 `dataSync`，防止觸發 `ForegroundServiceDidNotStopInTimeException` 閃退。
2. **啟動時序保護**：
   - `MainActivity` 必須在使用者授予 GPS 權限（`ACCESS_FINE_LOCATION`）回調後，才可啟動 `ServerForegroundService` 與感測器監聽，杜絕冷啟動權限競爭引發的 `SecurityException`。
3. **大記憶體宣告**：
   - `AndroidManifest.xml` 必須常時開啟 `android:largeHeap="true"`，以容納拓撲圖資與圖形計算。
4. **診斷日誌機制**：
   - 保留 `WebAppInterface.shareAppLogs()`，視障測試者可隨時一鍵將 Logcat 與設備資訊打包為 `.zip` 分享回報。

---

## 6. 維護流程與文件同步協議

1. **更新日誌必填**：
   - 任何涉及核心演算法、後端 API 端點、前端手勢或原生橋接之變更，**完成後必須第一時間更新 [`DEVELOPMENT_LOG.md`](file:///C:/ai%20pro/nmap_apk/DEVELOPMENT_LOG.md)**。
2. **驗證閉環**：
   - 修改 Python 後端或 JS 前端後，需確保本地語法檢查無誤，並確認 Android 原生層與 Python 後端之間的 API 契約（API Contracts）無破壞性變更。

---

## 7. 程式碼品質、白話註解與高可維護性規範 (Code Quality & Engineering Standards)

為確保專案在長期迭代中易於維護、除錯與交接，所有開發者與 AI 必須嚴格遵循以下軟體工程準則：

### 1. 「小學生都看得懂」的白話註解原則 (ELI5 Comments)
* **講人話、講意圖**：註解重點在於解釋「為什麼要這樣寫（Why）」與「這段邏輯在現實生活對應什麼情境（What）」，嚴禁生硬照抄語法關鍵字。
* **生動比喻輔助**：遇到複雜數學、空間演算法或硬體感測器融合邏輯（例如卡爾曼濾波、磁偏角補償、空間網格），必須用直觀的生活比喻加註（例如：「*想像在過濾馬路上的汽車噪音，只留下人的平穩腳步聲*」）。

### 2. 代碼與註解同步維護鐵律 (Code & Comment Synchronicity)
* **修改代碼必修註解**：只要修改任何邏輯、常數、條件判斷或資料結構，**相關的註解必須同步更新**。
* **杜絕說謊註解**：嚴禁「代碼已經改了，註解還停留在舊版做法」的陳舊註解（Lying Comments）。過時註解比沒有註解更危險。若註解已無意義，應果斷修正或刪除。

### 3. 自解釋命名與消滅魔法數字 (Self-Documenting & No Magic Numbers)
* **見名知意**：變數、函式與類別命名必須清晰表達用途（例如使用 `is_user_staying_still` 而非 `flag_s`；使用 `distance_to_shop_meters` 而非 `d`），禁止使用難以理解的單一字母或隨興縮寫。
* **常數提取與意義註解**：程式碼中嚴禁散落無說明的數值（Magic Numbers，例如 `5.5`, `60`, `3.8`）。所有門檻值必須提取為大寫常數變數（例如 `MAX_BROADCAST_DISTANCE_METERS = 5.5`），並加註該數值設定的實務考量。

### 4. 單一職責與函式精簡 (Single Responsibility Principle)
* **一個函式只做一件事**：每個函式應專注於單一功能，長度建議控制在 30～50 行以內。
* **過長邏輯主動拆解**：若一個函式同時包含「抓取資料」、「篩選過濾」、「格式化輸出」等多個步驟，必須拆解成命名稱職的子函式。

### 5. 防禦性程式設計與零崩潰原則 (Defensive Programming & Fail-Safe)
* **空值與邊界防護**：對所有外部輸入、感測器數據、網路請求回應與 JSON 欄位，必須預先做好 `null` / `None` / 空陣列 / 異常數值（如經緯度為 0 或 NaN）的檢查與預設值回退。
* **友善錯誤紀錄**：所有 `try-catch` / `try-except` 嚴禁靜默吞掉錯誤（Silent Failure），必須以清楚的中文上下文記錄錯誤原因，並確保 App 仍能維持基本可用狀態而不崩潰。

### 6. 跨語言 API 契約防護 (Cross-Language Contract Guard)
* 本專案橫跨 Python（後端）、Kotlin/Swift（原生平台）與 JavaScript（前端 WebView）。
* 任何 JSON 資料欄位名稱（如 `lat`, `lon`, `heading`, `places`）的增修，必須確保三端連鎖相容，嚴禁單方面任意更動欄位型態或鍵值名稱。

### 7. 一定要寫開發紀錄
DEVELOPMENT_LOG.md 若有修改一定要寫在檔案裡
且要好看得懂 容易了解

### 8. 遇到 Bug 時，不得立即修改程式碼。

第一階段：
1. 找出相關檔案
2. 找出相關函式
3. 分析呼叫關係
4. 分析資料流
5. 確認問題真正來源
6. 判斷修改影響範圍

第二階段：
提出修改方案。

第三階段：
只有確認問題來源後，才能修改。

第四階段：
修改後執行測試與驗證。

## 9. 無肉身排雷：空間感測與演算法測試規範 (Mock Testing & Wind Tunnel Protocol)

> [!WARNING]
> 嚴禁在修改核心定位、卡爾曼濾波、狀態機或方向判定後，直接打包 APK 要求使用者上街進行「肉身測試」。所有空間邏輯變更，必須先在本地端通過「風洞實驗室」的極端場景重播驗證。

### 9.1 測試架構與資料輸入 (pytest + CSV)
* **純 Python 驗證原則：** 所有空間演算法的測試，必須抽離 Android 原生層，強制使用 Python 的 `pytest` 框架進行單元測試，確保執行速度與跨平台除錯的便利性。
* **拒絕無塵室數據：** 測試輸入檔必須使用專屬的 **CSV 格式**（包含：時間戳記、經緯度、誤差半徑、真北角度、步伐觸發）。嚴禁傳入完美的直線等速座標，必須直接讀取真實錄製的雜訊軌跡，或由 AI 捏造帶有干擾的極端數值。

### 9.2 聽覺斷言機制 (Audio Event Queue Assertion)
* **攔截語音輸出：** 測試框架中必須實作一個「虛擬監聽佇列（Mock Audio Queue）」。演算法產生的每一次 `speak()` 呼叫，都必須連同當時的「模擬時間點」記錄到該佇列中。
* **嚴格斷言：** 測試腳本的判斷標準，不得僅依賴最終變數狀態，必須直接審查虛擬監聽佇列。例如斷言：「同一個 POI 兩次播報間隔必須大於 40 秒冷卻期」、「佇列中不允許出現連續兩次矛盾的方位報讀」。

### 9.3 演算法必考的「五大地獄空間場景」
任何空間邏輯的修改，必須確保能通過以下五個歷史 CSV 軌跡的重播測試：

1. **都市峽谷的乒乓球 (Multipath Ping-Pong)**
   * **情境：** 高樓旁，GPS 瞬間往馬路對面跳躍 30 公尺又跳回。
   * **斷言：** 卡爾曼濾波必須攔截異常，虛擬佇列中**嚴禁**觸發對面馬路的店家語音。
2. **走進騎樓的訊號黑洞 (The Arcade Black Hole)**
   * **情境：** GPS 衛星訊號瞬間歸零，僅剩加速度計步伐觸發。
   * **斷言：** 航位推算 (PDR) 必須在 1.2 秒內接管，佇列必須能依據真北與步伐繼續平滑推播前方店家。
3. **等紅綠燈的原地幽靈 (The Traffic Light Ghost)**
   * **情境：** 步伐停止，但 GPS 雜訊在 15 公尺半徑內亂飄。
   * **斷言：** ZUPT 零速修正必須強制鎖定座標，虛擬佇列必須維持**完全靜默**，嚴禁重複報讀路口。
4. **手電筒光束的 90 度直角轉彎 (The 90-Degree Corner Turn)**
   * **情境：** 直行中停下，真北角度瞬間改變 90 度進入巷子。
   * **斷言：** 測試時間軸推進 0.5 秒內，佇列必須立刻丟棄原本正前方的店家，並正確推播巷子內的新店家。
5. **迷航後的 180 度大迴轉 (The U-Turn of Confusion)**
   * **情境：** 進入路口 `APPROACHING` 狀態後，真北角度反轉 180 度，且距離開始遠離路口。
   * **斷言：** 狀態機必須強制流產並退回 `IDLE`，POIs 緩存必須瞬間洗牌。佇列中**絕對不准**出現「正通過該路口」的錯誤報讀，且無須等待 40 秒冷卻即可報讀反方向的新店家。