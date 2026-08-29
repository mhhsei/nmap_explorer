# NMap Explorer 國家級 e-GNSS 差分定位與載波平滑技術規範與檢核標準 (GNSS_DIFFERENTIAL_STANDARDS.md)

> 本文件為 NMap Explorer 整合台灣 e-GNSS（內政部國土測繪中心 NLSC 基準站網）與裝置端雙頻載波平滑（Hatch Filter）之**嚴格檢核準則與工程標準**。
> 任何涉及差分定位、NTRIP 通訊協議、載波相位解算或卡爾曼濾波協方差耦合之變更，**必須嚴格符合本規範之五大檢核標準**。

---

## 1. 核心定位與分級架構 (Five-Tier Architecture)

本系統採**五級定位品質階梯 (Differential Positioning Tiers)**，確保無論使用者身處何種環境，系統皆能無感平滑切換，絕不中斷導航：

| 等級 | 代號 | 預期水平精度 | 必要條件 | 適用情境 |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 0** | `OFFLINE_AUTONOMOUS` | **3.0 ~ 5.0 公尺** | 單機 Android Fused Location + PDR 計步 | 100% 離線無網環境、深山或未啟用差分 |
| **Tier 1** | `CARRIER_SMOOTHED_HATCH` | **1.2 ~ 2.0 公尺** | 本地 `GnssMeasurementsEvent` 載波相位連續鎖定 $\ge 5$ 顆，Hatch 濾波收斂 | 離線有開闊天空，利用手機硬體雙頻抑制 70% 多路徑雜訊 |
| **Tier 2** | `DGPS_CODE_DIFF` | **0.6 ~ 1.0 公尺** | NTRIP 連線正常，RTCM 偽距代碼差分電文時效 $\le 6$ 秒 | 行動網路連線，一般市區道路人行道導引 |
| **Tier 3** | `RTK_FLOAT_DECIMETER` | **0.3 ~ 0.5 公尺** | e-GNSS 雙頻觀測值載波相位浮點解，差分時效 $\le 4$ 秒 | 開闊十字路口、班馬線精準對齊 |
| **Tier 4** | `RTK_FIXED_CENTIMETER` | **< 0.20 公尺** | e-GNSS 雙頻整週模糊度固定解，時效 $\le 2$ 秒，基線 $\le 20\text{km}$ | 國家級測量級精準度，路緣石與盲道公分級感知 |

---

## 2. 五大嚴格工程檢核標準 (Strict Engineering Standards)

### 標準一：電文健康與時效檢查標準 (Age of Differential & Health Gating)
1. **差分時效檢核 ($T_{\text{age}}$)**：
   * $T_{\text{age}} \le 6.0\text{ 秒}$：判定為**「極佳有效」**，全面放行差分修正。
   * $6.0 < T_{\text{age}} \le 12.0\text{ 秒}$：判定為**「電文老化警告 (Stale)」**，測量協方差 $R$ 自動提高 2 倍。
   * $T_{\text{age}} > 12.0\text{ 秒}$：**強制判定為「差分失效 (Expired)」**，於 100ms 內自動瞬時降級為 Tier 0 或 Tier 1，**嚴禁使用過期電文進行位置解算**。
2. **RTCM 3.x 幀校驗**：
   * 每個 RTCM 數據包前導字節必須為 `0xD3`。
   * 數據包必須通過國際標準 **CRC24Q 多項式校驗**（多項式 `0x1864CFB`）。校驗失敗者直接丟棄，計入異常封包計數。
3. **基準站距檢核 ($D_{\text{baseline}}$)**：
   * 手機當前位置與 NLSC 指派之基準站距離必須 $\le 30\text{ 公里}$。超出範圍時應請求 Caster 重新指派虛擬參考站 (VRS)。

### 標準二：載波相位平滑與週跳檢核標準 (Hatch Filter & Cycle Slip Standards)
1. **平滑視窗長度**：
   * 單一衛星之 Hatch 濾波平滑次數 $M$ 最大上限設定為 $M_{\max} = 50$ 曆元（約 50 秒）。
2. **週跳 (Cycle Slip) 與失鎖檢測**：
   * 監控 `accumulatedDeltaRangeState`：
     * 若出現 `ADR_STATE_RESET`、`ADR_STATE_CYCLE_SLIP` 或未包含 `ADR_STATE_VALID`，立即重置該衛星之平滑視窗 ($M \leftarrow 1$)，避免因建築物短暫遮擋引發錯誤平滑。
3. **直射有效衛星門檻**：
   * 有效平滑衛星數必須滿足：載波鎖定 $\ge 5$ 顆衛星且平均 C/N0 $\ge 24\text{ dB-Hz}$。

### 標準三：防穿牆與幾何合理性檢核標準 (Plausibility & Anti-Jump Gating)
1. **馬氏距離卡方門控 ($\chi^2 \le 9.21$)**：
   * 差分解算之新位置與卡爾曼當前狀態進行卡方檢定（99% 信心水準）。
   * 若單步跳躍 $> 3.5\text{ 公尺}$，判定為可能之大樓折射波誤解，予以門控抑制，絕不允許瞬間甩點。
2. **靜止鎖定 (ZUPT) 最高權力**：
   * 當手持感測器判定為 `STATIONARY_LOCKED`（靜止鎖定）時，**即使差分引擎輸出任何微小跳動，座標一律 100% 凍結在幾何重心定錨點**。差分引擎僅獲准在背景進行累積平滑收斂，不得破壞靜止防抖。

### 標準四：網路低功耗與流量安全標準 (Resilience & Battery Thrift)
1. **指數退避重連機制 (Exponential Backoff)**：
   * 連線中斷時，重試間隔依序為 $1\text{s} \to 2\text{s} \to 4\text{s} \to 8\text{s} \to 16\text{s} \to 32\text{s} \to 60\text{s}$（上限 60 秒）。
   * 嚴禁高頻密集重連，徹底杜絕在地下室或無訊號處將手機電池耗盡。
2. **頻寬預算保護**：
   * 下行 RTCM 電文串流頻寬配額限制 $\le 2.5\text{ KB/s}$。
   * 上行 `$GPGGA` 心跳電文限制每 $10.0\text{ 秒}$ 發送 1 筆，嚴禁高頻上傳。

### 標準五：視障無障礙報讀與透明度標準 (Accessibility Feedback)
1. **省話模式連動**：
   * 差分連線狀態變化時，不得喋喋不休朗讀技術術語（嚴禁朗讀「NTRIP 200 OK, RTCM 1074 received」）。
   * 僅於無障礙輔助區域提供極簡狀態標記：
     * `[差分已連線]`、`[公分級定位]`、`[已切換單機]`。
2. **ARIA-Live 即時更新**：
   * 差分狀態以 `aria-live="polite"` 注入前端 WebView，確保 NVDA 與 TalkBack 使用者可在狀態列隨時觸摸查詢，不干擾導航語音。

---

## 3. 台灣 e-GNSS 國家伺服器設定參數 (NLSC Parameters)

* **官方主機**：`e-gnss.nlsc.gov.tw`
* **連接埠**：`2101` (NTRIP v1.0 / v2.0)
* **常用掛載點 (Mountpoint)**：
  * `RTCM32_VRS`：虛擬參考站多星系 RTCM 3.2 差分流（GPS + GLONASS + GALILEO + BEIDOU）。
  * `RTCM30_VRS`：標準雙星 VRS 差分流。
* **申請網址**：https://egnss.nlsc.gov.tw/
