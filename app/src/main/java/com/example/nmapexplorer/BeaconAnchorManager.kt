package com.example.nmapexplorer

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.net.wifi.ScanResult as WifiScanResult
import android.net.wifi.WifiManager
import android.net.wifi.rtt.RangingRequest
import android.net.wifi.rtt.RangingResult
import android.net.wifi.rtt.RangingResultCallback
import android.net.wifi.rtt.WifiRttManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.Locale
import kotlin.math.pow

/**
 * 【公眾定錨點資料結構 (Public Beacon Anchor POI)】
 */
data class PublicBeaconAnchor(
    val id: String,
    val name: String,
    val uuid: String,
    val major: Int,
    val minor: Int,
    val lat: Double,
    val lon: Double,
    val level: VerticalLevel,
    val description: String,
    val bssid: String? = null
)

/**
 * 【公眾 Wi-Fi RTT 與藍牙 iBeacon 室內深度定錨引擎 (BeaconAnchorManager)】
 * 
 * 生活化比喻（小學生都看得懂）：
 * 當您走進台北車站龐大的地下街或捷運大廳時，厚厚的天花板與大樓會把天上的 GPS 衛星訊號全部擋住。
 * 這時候，牆壁上的公眾藍牙 Beacon（信標）與 Wi-Fi 就扮演了「室內人造燈塔」的角色。
 * 一旦手機「看」到了這座燈塔，系統就會立刻將飄移的定位像磁鐵一樣牢牢吸附到燈塔的精確座標上，
 * 同時告訴您：「您現在已經在台北車站地下街 Z4 出口，不用擔心迷路！」
 */
class BeaconAnchorManager(
    private val context: Context,
    private val onAnchorMatched: (PublicBeaconAnchor, Float) -> Unit
) {
    private val tag = "BeaconAnchor"

    private val bluetoothManager: BluetoothManager? = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager?.adapter
    private var bleScanner: BluetoothLeScanner? = null

    private val wifiManager: WifiManager? = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
    private val wifiRttManager: WifiRttManager? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        context.getSystemService(Context.WIFI_RTT_RANGING_SERVICE) as? WifiRttManager
    } else null

    private var isScanning = false
    private val handler = Handler(Looper.getMainLooper())

    // 防重複播報冷卻表：Beacon ID -> 上次定錨時間戳記 (uptimeMillis)
    private val anchorCooldownMap = mutableMapOf<String, Long>()

    // 最近定錨信標與掃描歷史快照
    var lastMatchedBeacon: PublicBeaconAnchor? = null
        private set
    var lastMatchedDistanceM: Float = 0f
        private set
    private val recentScannedBeacons = java.util.Collections.synchronizedList(mutableListOf<org.json.JSONObject>())

    fun getRecentScannedBeaconsJson(): org.json.JSONArray {
        val arr = org.json.JSONArray()
        synchronized(recentScannedBeacons) {
            recentScannedBeacons.forEach { arr.put(it) }
        }
        return arr
    }

    companion object {
        /** 定錨觸發最大有效距離 (公尺)：只有走進距離 Beacon 6.5 公尺以內才判定為可靠定錨 */
        const val MAX_ANCHOR_DISTANCE_M = 6.5f

        /** 同一 Beacon 最小重複定錨冷卻時間 (毫秒)：15 秒內不重複洗版 */
        const val ANCHOR_COOLDOWN_MS = 15_000L

        /** Wi-Fi RTT 802.11mc 奈秒測距週期 (毫秒)：每 6 秒探測一次 */
        const val RTT_RANGING_INTERVAL_MS = 6_000L

        /** 台灣關鍵公眾交通樞紐與視障導引 Beacon 資料庫 */
        val TAIWAN_PUBLIC_BEACONS = listOf(
            // 1. 台北車站站前地下街 (Z 區)
            PublicBeaconAnchor(
                id = "TPE_Z4",
                name = "台北車站 站前地下街 Z4 出口 (新光三越/電梯)",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 4,
                lat = 25.04631,
                lon = 121.51465,
                level = VerticalLevel.UNDERGROUND,
                description = "直通新光三越前方，右側設有無障礙直通電梯。"
            ),
            PublicBeaconAnchor(
                id = "TPE_Z2",
                name = "台北車站 站前地下街 Z2 出口 (館前路口)",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 2,
                lat = 25.04635,
                lon = 121.51520,
                level = VerticalLevel.UNDERGROUND,
                description = "連通館前路人行步道與重慶南路書店街。"
            ),
            PublicBeaconAnchor(
                id = "TPE_K_ESLITE",
                name = "台北車站 K 區誠品生活地下街",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 10,
                lat = 25.04680,
                lon = 121.51600,
                level = VerticalLevel.UNDERGROUND,
                description = "誠品地下商場走廊，平整地面，兩側設有導盲導引。"
            ),
            // 2. 台北車站地面一樓大廳 (1F Ground)
            PublicBeaconAnchor(
                id = "TPE_1F_CENTER",
                name = "台北車站 1F 中央多功能展演中庭",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 100,
                lat = 25.04780,
                lon = 121.51700,
                level = VerticalLevel.GROUND,
                description = "台北車站一樓黑白棋盤格中庭大廳。"
            ),
            PublicBeaconAnchor(
                id = "TPE_1F_EAST1",
                name = "台北車站 1F 東一門出入口",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 101,
                lat = 25.04790,
                lon = 121.51780,
                level = VerticalLevel.GROUND,
                description = "鄰近排班計程車招呼站與公車轉運站。"
            ),
            PublicBeaconAnchor(
                id = "TPE_1F_WEST1",
                name = "台北車站 1F 西一門出入口",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 102,
                lat = 25.04780,
                lon = 121.51620,
                level = VerticalLevel.GROUND,
                description = "通往台北轉運站與市民大道人行步道。"
            ),
            // 3. 台北車站地下一樓與地下二樓穿堂 (B1 / B2)
            PublicBeaconAnchor(
                id = "TPE_B1_TRA_HSR",
                name = "台北車站 B1 台鐵與高鐵剪票穿堂層",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 201,
                lat = 25.04780,
                lon = 121.51700,
                level = VerticalLevel.UNDERGROUND,
                description = "台鐵高鐵進站剪票閘門，前進方向有語音導引服務鈴。"
            ),
            PublicBeaconAnchor(
                id = "TPE_B2_MRT_CONCOURSE",
                name = "捷運台北車站 B2 捷運大廳穿堂 (板南線/淡水信義線)",
                uuid = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                major = 1,
                minor = 301,
                lat = 25.04700,
                lon = 121.51650,
                level = VerticalLevel.UNDERGROUND_B2,
                description = "捷運轉乘大廳，右側設有專屬無障礙諮詢櫃台。"
            ),
            // 4. 板橋車站 (Banqiao Station)
            PublicBeaconAnchor(
                id = "BQC_B1_LINK",
                name = "板橋車站 B1 高鐵/台鐵/捷運三鐵共構連通道",
                uuid = "FDA50693-A4E2-4FB1-AFCF-C6EB07647825",
                major = 2,
                minor = 1,
                lat = 25.01350,
                lon = 121.46270,
                level = VerticalLevel.UNDERGROUND,
                description = "直通新北市政府與大遠百地下走廊。"
            ),
            // 5. 高雄美麗島站 (Formosa Boulevard)
            PublicBeaconAnchor(
                id = "FMD_B1_DOME",
                name = "捷運美麗島站 B1 光之穹頂大廳",
                uuid = "B9407F30-F5F8-466E-AFF9-25556B57FE6D",
                major = 7,
                minor = 1,
                lat = 22.63140,
                lon = 120.30190,
                level = VerticalLevel.UNDERGROUND,
                description = "美麗島站紅橘線轉乘核心大廳。"
            )
        )
    }

    private val wifiRttRunnable = object : Runnable {
        override fun run() {
            if (!isScanning) return
            performWifiRttRanging()
            handler.postDelayed(this, RTT_RANGING_INTERVAL_MS)
        }
    }

    /**
     * 啟動藍牙 BLE 與 Wi-Fi RTT 802.11mc 雙重室內定錨掃描
     */
    @SuppressLint("MissingPermission")
    fun start() {
        if (isScanning) return
        isScanning = true

        // 1. 啟動藍牙 BLE 掃描
        val hasBtScan = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            ContextCompat.checkSelfPermission(context, android.Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED
        } else {
            ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        }

        if (hasBtScan && bluetoothAdapter != null && bluetoothAdapter.isEnabled) {
            try {
                bleScanner = bluetoothAdapter.bluetoothLeScanner
                val settings = ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_BALANCED)
                    .setReportDelay(0)
                    .build()

                bleScanner?.startScan(null, settings, bleScanCallback)
                Log.i(tag, "Bluetooth LE Scanner successfully started for indoor public beacon re-anchoring.")
            } catch (e: Throwable) {
                Log.e(tag, "Failed to start BLE scanner: ${e.message}")
            }
        } else {
            Log.w(tag, "Bluetooth scan standby (permission missing or Bluetooth disabled).")
        }

        // 2. 啟動 Wi-Fi RTT (IEEE 802.11mc) 奈秒測距定錨排程
        startWifiRttScanning()
    }

    /**
     * 啟動 Wi-Fi RTT 奈秒測距定錨排程
     */
    private fun startWifiRttScanning() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && wifiRttManager != null) {
            if (context.packageManager.hasSystemFeature(PackageManager.FEATURE_WIFI_RTT)) {
                Log.i(tag, "Starting periodic Wi-Fi RTT 802.11mc ranging scheduler.")
                handler.removeCallbacks(wifiRttRunnable)
                handler.post(wifiRttRunnable)
            } else {
                Log.i(tag, "Hardware does not support FEATURE_WIFI_RTT. Wi-Fi RTT standby.")
            }
        }
    }

    /**
     * 執行 Wi-Fi RTT 802.11mc 微秒級飛行時間測距
     */
    @SuppressLint("MissingPermission")
    private fun performWifiRttRanging() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P || wifiRttManager == null) return
        if (!context.packageManager.hasSystemFeature(PackageManager.FEATURE_WIFI_RTT)) return
        if (!wifiRttManager.isAvailable) return

        val hasFine = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!hasFine) return

        try {
            val scanResults: List<WifiScanResult>? = wifiManager?.scanResults
            if (scanResults.isNullOrEmpty()) return

            // 挑選支援 802.11mc (RTT Responder) 的 AP 或匹配已知的公眾 BSSID
            val targetAps = scanResults.filter { ap ->
                ap.is80211mcResponder || TAIWAN_PUBLIC_BEACONS.any { it.bssid != null && it.bssid.equals(ap.BSSID, ignoreCase = true) }
            }.take(RangingRequest.getMaxPeers())

            if (targetAps.isEmpty()) return

            val request = RangingRequest.Builder().addAccessPoints(targetAps).build()
            wifiRttManager.startRanging(request, context.mainExecutor, object : RangingResultCallback() {
                override fun onRangingResults(results: List<RangingResult>) {
                    handleWifiRttResults(results)
                }

                override fun onRangingFailure(code: Int) {
                    Log.w(tag, "Wi-Fi RTT ranging callback failed: code=$code")
                }
            })
        } catch (e: Throwable) {
            Log.w(tag, "Failed to initiate Wi-Fi RTT ranging: ${e.message}")
        }
    }

    /**
     * 處理 Wi-Fi RTT 奈秒測距結果並比對公眾地下街燈塔
     */
    private fun handleWifiRttResults(results: List<RangingResult>) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return

        for (res in results) {
            if (res.status == RangingResult.STATUS_SUCCESS) {
                val mac = res.macAddress?.toString() ?: continue
                val distM = res.distanceMm / 1000.0f
                val stdDevM = res.distanceStdDevMm / 1000.0f

                val matched = TAIWAN_PUBLIC_BEACONS.find {
                    it.bssid != null && it.bssid.equals(mac, ignoreCase = true)
                }

                val scanObj = org.json.JSONObject().apply {
                    put("type", "WIFI_RTT")
                    put("bssid", mac)
                    put("dist_m", distM)
                    put("std_dev_m", stdDevM)
                    put("matched_name", matched?.name ?: "802.11mc AP")
                    put("t", System.currentTimeMillis())
                }
                synchronized(recentScannedBeacons) {
                    if (recentScannedBeacons.size > 30) recentScannedBeacons.removeAt(0)
                    recentScannedBeacons.add(scanObj)
                }

                if (matched != null && distM <= MAX_ANCHOR_DISTANCE_M) {
                    lastMatchedBeacon = matched
                    lastMatchedDistanceM = distM
                    val now = SystemClock.uptimeMillis()
                    val lastEmitted = anchorCooldownMap[matched.id] ?: 0L

                    if (now - lastEmitted >= ANCHOR_COOLDOWN_MS) {
                        anchorCooldownMap[matched.id] = now
                        Log.i(tag, "[WIFI_RTT_ANCHOR_MATCH] Hit: ${matched.name} (Dist: ${String.format(Locale.US, "%.1f", distM)}m, StdDev: ${stdDevM}m)")
                        handler.post {
                            onAnchorMatched(matched, distM)
                        }
                    }
                }
            }
        }
    }

    /**
     * 停止掃描
     */
    @SuppressLint("MissingPermission")
    fun stop() {
        if (!isScanning) return
        handler.removeCallbacks(wifiRttRunnable)
        try {
            bleScanner?.stopScan(bleScanCallback)
        } catch (e: Exception) {}
        isScanning = false
        Log.i(tag, "Bluetooth LE and Wi-Fi RTT Scanner stopped.")
    }

    /**
     * 藍牙 BLE 掃描回調處理器
     */
    private val bleScanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult?) {
            result?.let { parseAndMatchBeacon(it) }
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>?) {
            results?.forEach { parseAndMatchBeacon(it) }
        }

        override fun onScanFailed(errorCode: Int) {
            Log.w(tag, "BLE Scan failed with error code: $errorCode")
        }
    }

    /**
     * 解析 Apple iBeacon 廣播封包並與公眾資料庫比對
     */
    private fun parseAndMatchBeacon(result: ScanResult) {
        val scanRecord = result.scanRecord ?: return
        val bytes = scanRecord.bytes ?: return

        // 尋找 Apple iBeacon 標頭 (0x02, 0x15 代表 iBeacon advertisement)
        var startByte = 2
        var isFound = false
        while (startByte <= 5) {
            if (((bytes[startByte + 2].toInt() and 0xff) == 0x02) &&
                ((bytes[startByte + 3].toInt() and 0xff) == 0x15)) {
                isFound = true
                break
            }
            startByte++
        }

        if (!isFound || bytes.size < startByte + 24) return

        // 提取 UUID (16 bytes)
        val uuidBytes = ByteArray(16)
        System.arraycopy(bytes, startByte + 4, uuidBytes, 0, 16)
        val uuidStr = bytesToUuidString(uuidBytes)

        // 提取 Major (2 bytes) 與 Minor (2 bytes)
        val major = ((bytes[startByte + 20].toInt() and 0xff) shl 8) or (bytes[startByte + 21].toInt() and 0xff)
        val minor = ((bytes[startByte + 22].toInt() and 0xff) shl 8) or (bytes[startByte + 23].toInt() and 0xff)
        val txPower = bytes[startByte + 24].toInt() // 1 米處的標準參考 RSSI

        // 計算預估物理距離 (Log-distance Path Loss Model)
        val rssi = result.rssi
        val estimatedDistM = calculateDistance(txPower, rssi)

        // 比對公眾已知 Beacon
        val matchedBeacon = TAIWAN_PUBLIC_BEACONS.find {
            it.major == major && it.minor == minor && it.uuid.equals(uuidStr, ignoreCase = true)
        }

        val beaconObj = org.json.JSONObject().apply {
            put("uuid", uuidStr)
            put("major", major)
            put("minor", minor)
            put("rssi", rssi)
            put("dist_m", estimatedDistM)
            put("matched_name", matchedBeacon?.name ?: "未匹配公眾信標")
            put("t", System.currentTimeMillis())
        }
        synchronized(recentScannedBeacons) {
            if (recentScannedBeacons.size > 30) recentScannedBeacons.removeAt(0)
            recentScannedBeacons.add(beaconObj)
        }

        if (matchedBeacon != null && estimatedDistM <= MAX_ANCHOR_DISTANCE_M) {
            lastMatchedBeacon = matchedBeacon
            lastMatchedDistanceM = estimatedDistM
            val now = SystemClock.uptimeMillis()
            val lastEmitted = anchorCooldownMap[matchedBeacon.id] ?: 0L

            if (now - lastEmitted >= ANCHOR_COOLDOWN_MS) {
                anchorCooldownMap[matchedBeacon.id] = now
                Log.i(tag, "[BEACON_ANCHOR_MATCH] Hit: ${matchedBeacon.name} (Dist: ${String.format(Locale.US, "%.1f", estimatedDistM)}m, RSSI: ${rssi}dBm, Level: ${matchedBeacon.level.name})")
                handler.post {
                    onAnchorMatched(matchedBeacon, estimatedDistM)
                }
            }
        }
    }

    /**
     * 依據路徑衰減模型 (Log-Distance Path Loss) 估算距離公尺數
     */
    private fun calculateDistance(txPower: Int, rssi: Int): Float {
        if (rssi == 0) return -1.0f
        val ratio = (txPower - rssi) / (10.0f * 2.2f) // 環境衰減指數 n 取 2.2
        return 10.0f.pow(ratio)
    }

    /**
     * 將 16 位元組轉換為標準 UUID 字串格式
     */
    private fun bytesToUuidString(bytes: ByteArray): String {
        val sb = StringBuilder()
        for (i in bytes.indices) {
            sb.append(String.format("%02X", bytes[i]))
            if (i == 3 || i == 5 || i == 7 || i == 9) {
                sb.append("-")
            }
        }
        return sb.toString()
    }
}
