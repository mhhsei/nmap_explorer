# NMap Explorer 開發規範與維護指引 (gemini.md)

> 本文件為 NMap Explorer 專案的核心開發守則與維護規範。
> 任何參與本專案的開發者與 AI Agent 在進行程式碼撰寫、模組重構、依賴調整或除錯時，**必須嚴格遵守本文件之所有規定**。

---

## 1. 專案核心定位與無障礙第一原則 (Accessibility First)

1. **使用者族群**：視障者（使用 NVDA 螢幕報讀軟體於 PC 端，或 TalkBack / VoiceOver 於行動裝置）。
2. **語音輸出精簡化（省話模式）**：
   - 視障者需同時聆聽現實環境聲音（車聲、腳步聲、盲杖回聲）。
   - 語音回饋嚴禁冗長贅字，報讀格式遵循：`[店名]，[方位]`（例如：「全家便利商店，右側」），必須於 1 秒內播報完畢。
   - 接近店家播報距離設定為 **3.0 ~ 5.5 公尺**，並具備 60 秒防重複冷卻機制。
3. **3D 空間音效優先**：
   - 空間方向感優先依賴 Web Audio API (HRTF) 立體聲定位，讓使用者直覺透過耳機辨識左右與前後，減少純文字朗讀負擔。
4. **ARIA-Live 即時連動**：
   - 前端所有狀態變更必須正確綁定 `aria-live="polite"` 或 `aria-live="assertive"`（危險警告），確保螢幕報讀軟體能即時抓取焦點。

5. 開發要遵守 wcag 2.2 規範

---

## 2. 雙平台技術架構與目錄規範

專案採用雙平台（Android / iOS）離線優先混合架構：

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
├── ios/                                # iOS 原生專案
│   ├── project.yml                     # XcodeGen 專案配置檔
│   ├── README_IOS.md                   # iOS 雲端編譯與 Sideloadly 安裝指南
│   └── NMapExplorer/                   # Swift 5.9 原生層 + WKWebView + 離線 DB
├── .github/workflows/
│   └── build_ios.yml                   # GitHub Actions 免 Mac 雲端編譯工作流程
├── DEVELOPMENT_LOG.md                  # 開發履歷與 Changelog 追蹤檔
├── nmap_android_plan.md                # 轉換計畫書與頂層架構設計
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

1. **二維步行卡爾曼濾波 (Pedestrian Kalman Filter)**：
   - 針對步行速度（0.8 ~ 2.0 m/s）進行狀態估計與平滑。
   - **速度鉗制**：若瞬時速度換算 $> 4.5\text{ m/s}$，判定為 GPS 瞬移雜訊並予以壓制。
   - **ZUPT 零速修正 (Zero-Velocity Update)**：當速度 $< 0.25\text{ m/s}$ 時強制鎖定座標速度為 0，杜絕紅綠燈或門口停留時的原地飄移。
2. **大樓折射雜訊過濾 (GNSS Multipath Rejection)**：
   - 透過 `GnssStatus.Callback` 監控衛星 C/N0 訊噪比。當平均 SNR $< 21\text{ dB-Hz}$ 判定為都市峽谷反射，動態放大卡爾曼測量協方差 $R$（提高 6 倍），防止穿牆瞬移。
3. **真北角度 3.8° 磁偏角校正**：
   - 調度 9 軸硬體旋轉向量感測器 (`Sensor.TYPE_ROTATION_VECTOR`)，融合陀螺儀、磁力計與加速度計。
   - 使用 Android `GeomagneticField` 動態取得所在經緯度之地磁偏角（台灣約 -3.8°）補正為地理真北，確保 3D 音效與使用者行進方向 100% 吻合。
4. **PDR 騎樓航位推算 (Pedestrian Dead Reckoning)**：
   - 整合 `Sensor.TYPE_STEP_DETECTOR` 硬體計步器。
   - 當 GPS 衛星訊號中斷 $> 1.2\text{ 秒}$（如走進騎樓或地下連通道），由卡爾曼 `advanceStep()` 依據當前真北朝向平滑推算前進，並自動依據過往 GPS 速度校準個人步長（$0.50\sim0.85\text{ m}$）。
5. **自適應道路吸附**：
   - 路寬 $\ge 8\text{ 公尺}$ 之主幹道依據行人實際位置精準吸附至路側人行道/騎樓。
   - 路寬 $< 8\text{ 公尺}$ 窄巷弄自動鎖定中心線，杜絕巷內左右橫跳的乒乓效應。

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

## 6. iOS 版本開發與雲端編譯守則

1. **免 Mac 雲端建置**：
   - iOS 專案配置由 `ios/project.yml` 統一管理。
   - 每次推動至 `main`/`master` 分支，由 GitHub Actions (`.github/workflows/build_ios.yml`) 自動執行 XcodeGen 編譯打包並輸出 [`NMapExplorer.ipa`](file:///C:/ai%20pro/nmap_apk/NMapExplorer.ipa)。
2. **安裝與側載**：
   - Windows 使用者透過 Sideloadly 搭配免費 Apple ID 自簽安裝，步驟詳見 [`ios/README_IOS.md`](file:///C:/ai%20pro/nmap_apk/ios/README_IOS.md)。
3. **原生對齊**：
   - iOS 原生層 (`LocationSensorBridge.swift`, `DatabaseManager.swift`) 必須與 Android 端的卡爾曼濾波、PDR 推算、3D 空間音效保持一致的空間計算邏輯。

---

## 7. 維護流程與文件同步協議

1. **更新日誌必填**：
   - 任何涉及核心演算法、後端 API 端點、前端手勢或原生橋接之變更，**完成後必須第一時間更新 [`DEVELOPMENT_LOG.md`](file:///C:/ai%20pro/nmap_apk/DEVELOPMENT_LOG.md)**。
2. **驗證閉環**：
   - 修改 Python 後端或 JS 前端後，需確保本地語法檢查無誤，並確認 Android 與 iOS 雙平台的 API 契約（API Contracts）無破壞性變更。

---

## 8. 程式碼品質、白話註解與高可維護性規範 (Code Quality & Engineering Standards)

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
DEVELOPMENT_LOG.md 若有修改一定要寫在盪按理
且要好看得懂 容易了解
