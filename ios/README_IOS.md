# NMap Explorer iOS (.ipa) 建置與安裝指南

本指南專為 **Windows 使用者** 設計，無需實體 Mac 電腦，透過 **GitHub Actions 免費雲端 Mac** 自動編譯產出 `.ipa`，並使用 Windows 上的免費工具安裝至 iPhone。

---

## 🚀 第一步：取得 `NMapExplorer.ipa` 安裝包

1. 將本專案程式碼上傳 (Git Push) 至您的 GitHub 儲存庫（公開或私有皆可）。
2. 在 GitHub 網頁上，點選上方的 **「Actions」** 分頁。
3. 點選左側的 **「Build iOS IPA」** 工作流程，並點擊右側的 **「Run workflow」**。
4. 約 2~3 分鐘後，GitHub 雲端 Mac 完成編譯，在頁面底部的 **Artifacts** 區塊點擊下載 **`NMapExplorer-iOS-IPA`**。
5. 解壓縮下載的檔案，即可取得 **`NMapExplorer.ipa`**！

---

## 📲 第二步：在 Windows 上將 `.ipa` 安裝至 iPhone（免越獄）

### 推薦工具：Sideloadly（最簡單、支援 Windows）

1. **下載並安裝 Sideloadly**：
   * 前往官網下載 Windows 版 Sideloadly（https://sideloadly.io/）。
   * 確保電腦已安裝 iTunes 與 iCloud（Windows 版）。
2. **連接 iPhone**：
   * 使用 USB 傳輸線將 iPhone 插上 Windows 電腦。
   * 手機跳出「信任這部電腦」時點選 **「信任」** 並輸入螢幕解鎖密碼。
3. **一鍵安裝**：
   * 打開 Sideloadly，軟體會自動偵測到您的 iPhone。
   * 將 `NMapExplorer.ipa` 拖曳進 Sideloadly 視窗中。
   * 在 **Apple ID** 欄位輸入您的 Apple ID（免費用戶即可，僅用於本機簽署安裝）。
   * 點擊 **「Start」** 開始簽署並安裝。
4. **手機上信任憑證**：
   * 安裝完成後，iPhone 桌面上會出現 **NMap Explorer** 圖示。
   * 首次點開若提示「不受信任的開發者」：
     * 前往 iPhone **「設定」➔「一般」➔「VPN 與裝置管理」**。
     * 點進您的 Apple ID，點選 **「信任」**。
   * 即可正常開啟使用！

---

## 🌟 iOS 版本特色
* **原生 True North 磁偏角校正**：直接由 iOS CoreLocation 提供真正的地理正北。
* **PDR 騎樓航位推算**：整合 iPhone CMPedometer 計步器，走進騎樓與遮蔽處依然平滑導航。
* **AirPods 3D 空間音效**：完整支援 Web Audio API 與立體聲耳機雙耳渲染。
* **VoiceOver 完美相容**：全介面支援 iOS 輔助使用與 ARIA-Live 即時報讀。
