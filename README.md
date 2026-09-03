# NMap Explorer (無障礙即時空間數位分身地圖探索系統)

專為視障者（使用 NVDA 螢幕報讀軟體於電腦端，或 TalkBack 於行動裝置）設計的高精準度、離線優先行動導航與街景探索系統。

---

## 📥 最新版本永久下載連結 (Permanent Download Links)

不論後續迭代到哪一個版本號，以下網址**永遠固定有效**，保證能下載與存取到 GitHub 上的最新正式發布版本：

* 🚀 **[點此直接下載最新版本 APK (直連載點)](https://github.com/mhhsei/nmap_explorer/releases/latest/download/nmap_explorer.apk)**
  * **永久直連網址**：https://github.com/mhhsei/nmap_explorer/releases/latest/download/nmap_explorer.apk
  * **說明**：點擊即可直接觸發下載最新編譯之正式發布版 
map_explorer.apk，網址字串永不隨版本號變動。
* 🌐 **[檢視最新版本發布頁面 (Release Notes)](https://github.com/mhhsei/nmap_explorer/releases/latest)**
  * **永久頁面網址**：https://github.com/mhhsei/nmap_explorer/releases/latest
  * **說明**：以網頁檢視最新版的功能更新履歷、發布時間與各架構獨立 APK 檔案。

---

## 📱 App 內建一鍵在線更新

NMap Explorer App 已內建 GitHub Releases 在線檢查與無縫安裝機制：
1. 開啟 NMap Explorer。
2. 點擊主畫面上的 **「檢查更新」** 按鈕（或系統啟動時背景靜默比對）。
3. 若檢測到新版本，App 會主動朗讀新版功能說明，點選確認後自動在手機背景下載新版 APK，並直接引導完成覆蓋安裝，無需手動刪除舊版。

---

## 🌟 核心特色與工程設計

1. **無障礙第一原則 (Accessibility First)**：
   * 嚴格遵循 WCAG 2.2 AAA 無障礙標準，UI 所有按鈕皆設有清楚語音標籤與 ARIA Live 即時狀態連動。
   * 聽覺發話權實施四級降序調度（生命安全防撞 > 有聲號誌 > 路口狀態機 > 走廊店家），低優先級絕對禁止搶播蓋台。
   * 空間音效（Web Audio HRTF 3D）與專屬短促樂器聽覺圖標（Earcons, ~100ms），不戴耳機也能憑反射神經辨識超商、餐廳與路口。
2. **周遭 360 度四向象限路口探測器 (Omnidirectional 4-Sector Junction Scanner)**：
   * 徹底打破寫死半徑，依據使用者身體真北朝向將周圍劃分為四大象限（正前方、右側、左側、後方/來時路），各方向自動定錨距離最近的 1 個真實交會路口。
   * 具備搜尋列「路口意圖自然辨識」，在搜尋列輸入「路口」即可 1 秒以語音報讀四周四向路網心智地圖。
3. **高精準二維步行卡爾曼濾波器 (Anti-Divergence Pedestrian Kalman Filter)**：
   * 雙頻 L5/E5a/B2a 衛星載波全時偵測，當鎖定雙頻時動態壓縮測量雜訊協方差（R x 0.4），達到路側次米級精確度。
   * ZUPT 零速修正機制，靜止停留時強制凍結座標，徹底消滅室內原地亂飄與跳針。
   * PDR 騎樓航位推算接管機制，走入騎樓或地下室時依據步伐與個人步長平滑推算前進。
4. **離線優先純 Python GIS 拓撲引擎 (Chaquopy ARM64)**：
   * 幾何與網格索引全純 Python 實作，內建全台灣 193 萬筆離線店家地標、門牌幾何投影與全台 56,824 座交通號誌資料庫。
   * 內嵌 NASA SRTM3 90 米 3D 數位地表高程庫與地表裸地濾波器（Bare-Earth DTM），消除都市高樓雷達毛刺。

---

## 🛠️ 開發與編譯指南

* **程式語言**：Kotlin (Android 原生) + Python 3.11 (Chaquopy) + JavaScript / HTML5
* **建置指令**：
  `ash
  ./gradlew assembleRelease
  `
* **更新日誌與技術規範**：
  * 詳細架構請參閱 ARCHITECTURE.md 與 gemini.md。
  * 每次版本改動記錄請參閱 DEVELOPMENT_LOG.md。
