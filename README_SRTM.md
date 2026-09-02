# 🌍 NMap Explorer - SRTM 3D 地形離線資料庫 (台灣)

為了徹底解決「多山坡地被誤判為爬樓梯/天橋」的實體物理問題，我們引入了美國太空總署 (NASA) 的 SRTM 3-arc-second 離線地形高程資料庫。

## 如何匯入真正的台灣地形資料？
目前 `app/src/main/python/data/taiwan_srtm3.zip` 內放置的是一個**測試用假檔**（預設高度永遠為 50m），以利編譯通過。
為了獲得真實的全台灣 3D 地形，請您親自執行以下步驟：

1. 開啟瀏覽器前往: `http://viewfinderpanoramas.org/Coverage%20map%20viewfinderpanoramas_org3.htm`
2. 下載涵蓋台灣的兩個區塊檔案：`F50.zip`, `F51.zip`, `G50.zip`, `G51.zip`
3. 將這 4 個壓縮檔解壓縮，您會看到許多副檔名為 `.hgt` 的檔案（例如 `N25E121.hgt`）。
4. 請把所有台灣範圍的 `.hgt` 檔案（N21~N25, E119~E122）挑選出來。
5. 將這些 `.hgt` 檔案**直接打包壓縮成一個名為 `taiwan_srtm3.zip` 的壓縮檔**。
6. 將該 `taiwan_srtm3.zip` 覆蓋掉本專案 `app/src/main/python/data/` 裡面的同名假檔。

完成後重新打包 APK，您的 NMap Explorer 就會具備「讀取真實地形海拔」的超級能力了！
