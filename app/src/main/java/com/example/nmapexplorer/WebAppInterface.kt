package com.example.nmapexplorer

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.speech.tts.TextToSpeech
import android.util.Log
import android.view.accessibility.AccessibilityManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.core.content.FileProvider
import androidx.core.content.pm.PackageInfoCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File

import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 網頁與 Android 原生系統的溝通橋樑 (JavaScript Interface)
 * 
 * 作用：注入到 WebView 內作為 `window.AndroidBridge`，讓網頁裡面的 JavaScript
 * 可以直接調用手機的原生硬體功能（如：震動馬達、TalkBack 語音廣播、外部 App 喚醒、打包診斷日誌）。
 */
class WebAppInterface(private val context: Context, private val webView: WebView? = null) {

    private val tag = "WebAppInterface"
    // 原生文字轉語音引擎 (TTS)，作為 TalkBack 關閉時的語音發聲備援
    private var tts: TextToSpeech? = null
    private var isTtsReady = false

    init {
        try {
            // 初始化 Android 原生 TTS 語音引擎（優先設定台灣中文，並提升語速至 1.25x 達成極速響應）
            tts = TextToSpeech(context.applicationContext) { status ->
                if (status == TextToSpeech.SUCCESS) {
                    val result = tts?.setLanguage(Locale.TAIWAN)
                    if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                        tts?.setLanguage(Locale.CHINESE)
                    }
                    tts?.setSpeechRate(1.25f) // 俐落敏捷，縮短單字唸讀時間
                    tts?.setPitch(1.02f)
                    isTtsReady = true
                    Log.i(tag, "Google/Android Native TextToSpeech initialized successfully.")
                }
            }
        } catch (e: Exception) {
            Log.e(tag, "Failed to initialize TextToSpeech", e)
        }
    }

    /**
     * 【Google 內建原生 TTS 直接極速發聲通道 (Direct Native Google TTS)】
     * 作用：
     * 1. 專用於「手機轉動即時羅盤方位播報」。
     * 2. 100% 繞過 TalkBack 系統無障礙事件隊列 (QUEUE)，杜絕 TalkBack 的排隊延遲、卡頓與吞字。
     * 3. 使用 TextToSpeech.QUEUE_FLUSH 瞬間中斷並立即播報最新方位，達成「有轉動就馬上播報」。
     * 
     * @param text 要朗讀的文字 (如「正北」、「北北東」)
     * @param interrupt 是否立即插播（預設 true，立即中斷前一句）
     */
    @JavascriptInterface
    fun speakTtsDirect(text: String, interrupt: Boolean = true) {
        if (text.isBlank()) return
        Log.d(tag, "speakTtsDirect: $text (interrupt=$interrupt)")
        (context as? android.app.Activity)?.runOnUiThread {
            try {
                if (isTtsReady && tts != null) {
                    val queueMode = if (interrupt) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
                    tts?.speak(text, queueMode, null, "turn_${System.currentTimeMillis()}")
                } else {
                    // 若 TTS 尚未就緒，暫時以 announceForAccessibility 作為保底
                    webView?.announceForAccessibility(text)
                }
            } catch (e: Exception) {
                Log.e(tag, "Error in speakTtsDirect", e)
            }
        }
    }

    /**
     * 原生即時語音朗讀通道 (Native Speech Broadcast)
     * 
     * 作用：徹底解決 WebView 網頁 aria-live 在手機頻繁旋轉時容易漏讀或消音的問題。
     * 1. 若 TalkBack 開啟中：直接向系統無障礙服務發送 announceForAccessibility 原生事件。
     * 2. 若 TalkBack 未開啟：透過原生 TTS 引擎直接發聲。
     * 
     * @param text 要朗讀的文字
     * @param interrupt 是否立即插播（中斷先前未讀完的語音）
     */
    @JavascriptInterface
    fun speak(text: String, interrupt: Boolean = true) {
        if (text.isBlank()) return
        Log.d(tag, "speak: $text (interrupt=$interrupt)")
        (context as? android.app.Activity)?.runOnUiThread {
            try {
                // 1. 向 Android 無障礙服務 (TalkBack / 螢幕報讀器) 發送最高優先權廣播事件
                val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager
                if (am?.isEnabled == true) {
                    val event = android.view.accessibility.AccessibilityEvent.obtain(
                        android.view.accessibility.AccessibilityEvent.TYPE_ANNOUNCEMENT
                    )
                    event.text.add(text)
                    event.className = javaClass.name
                    event.packageName = context.packageName
                    am.sendAccessibilityEvent(event)
                }

                // 2. 同步調用 WebView announceForAccessibility
                webView?.announceForAccessibility(text)

                // 3. 若未啟用觸控瀏覽輔助，透過原生 TTS 引擎發聲
                val isTouchExploration = am?.isEnabled == true && am.isTouchExplorationEnabled
                if (!isTouchExploration && isTtsReady) {
                    val queueMode = if (interrupt) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
                    tts?.speak(text, queueMode, null, "nmap_${System.currentTimeMillis()}")
                }
            } catch (e: Exception) {
                Log.e(tag, "Error in speak", e)
            }
        }
    }


    /**
     * 自訂毫秒數的一般震動
     */
    @JavascriptInterface
    fun vibrate(durationMs: Long) {
        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        if (vibrator.hasVibrator()) {
            vibrator.vibrate(VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    /**
     * 輕微刻度微震 (Tick)
     * 作用：轉動手機每跨越 15 度時發出，像手錶秒針跳動的清脆觸感。
     */
    @JavascriptInterface
    fun vibrateTick() {
        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        if (vibrator.hasVibrator()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                vibrator.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK))
            } else {
                vibrator.vibrate(VibrationEffect.createOneShot(10, 50))
            }
        }
    }

    /**
     * 單點點擊感震動 (Click)
     * 作用：旋轉經過八大主要方位（東南、東北等）時觸發。
     */
    @JavascriptInterface
    fun vibrateClick() {
        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        if (vibrator.hasVibrator()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                vibrator.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK))
            } else {
                vibrator.vibrate(VibrationEffect.createOneShot(20, 120))
            }
        }
    }

    /**
     * 強烈重震 (Heavy Click)
     * 作用：旋轉經過正北方向 (0°) 時觸發，讓視障者單憑手感瞬間確認正北。
     */
    @JavascriptInterface
    fun vibrateHeavy() {
        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        if (vibrator.hasVibrator()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                vibrator.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK))
            } else {
                vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 30, 40, 30), -1))
            }
        }
    }

    /**
     * 開啟系統「應用程式設定」頁面
     * 作用：當使用者未授權 GPS 定位時，引導其前往系統設定頁面手動開通。
     */
    @JavascriptInterface
    fun openAppSettings() {
        try {
            val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                data = android.net.Uri.fromParts("package", context.packageName, null)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        } catch (e: Exception) {
            Log.e(tag, "Failed to open app settings", e)
        }
    }

    /**
     * 喚醒外部 Google Maps 開啟步行導航
     * 作用：視障者點擊地標詳情對話框中的「Google 導航」按鈕時，自動跳轉至外部地圖步行模式。
     */
    @JavascriptInterface
    fun openGoogleMaps(lat: Double, lon: Double, label: String) {
        try {
            val uri = android.net.Uri.parse("google.navigation:q=$lat,$lon&mode=w")
            val mapIntent = Intent(Intent.ACTION_VIEW, uri).apply {
                setPackage("com.google.android.apps.maps")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            if (mapIntent.resolveActivity(context.packageManager) != null) {
                context.startActivity(mapIntent)
            } else {
                // 若手機未安裝 Google Maps App，則透過瀏覽器開啟
                val browserUri = android.net.Uri.parse("https://www.google.com/maps/dir/?api=1&destination=$lat,$lon&travelmode=walking")
                val browserIntent = Intent(Intent.ACTION_VIEW, browserUri).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(browserIntent)
            }
        } catch (e: Exception) {
            Log.e(tag, "Failed to open Google Maps navigation", e)
        }
    }

    /**
     * 查詢目前是否具備 GPS 定位權限
     */
    @JavascriptInterface
    fun hasLocationPermission(): Boolean {
        val fine = androidx.core.content.ContextCompat.checkSelfPermission(
            context,
            android.Manifest.permission.ACCESS_FINE_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        val coarse = androidx.core.content.ContextCompat.checkSelfPermission(
            context,
            android.Manifest.permission.ACCESS_COARSE_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    /**
     * 無參數打包分享日誌（相容舊版呼叫）
     */
    @JavascriptInterface
    fun shareAppLogs() {
        shareAppLogsWithData("{}")
    }

    /**
     * 一鍵打包 7 合 1 AI 結構化診斷日誌並喚醒系統分享選單 (Share Sheet)
     * 
     * 包含內容：
     * 1. 0_AI_QUICK_SUMMARY.json：手機硬體、版本、導航狀態與異常速查
     * 2. 1_trajectory.geojson：標準 GeoJSON 行走軌跡與地標
     * 3. 2_causality_trace.ndjson：決策因果鏈 Trace ID
     * 4. 3_detected_pois.json：掃描到的周遭店家
     * 5. 4_speech_history.ndjson：語音朗讀歷史
     * 6. 5_sensor_trajectory.ndjson：底層卡爾曼/步態數據
     * 7. 6_system_logcat.txt：Android 系統底層日誌
     */
    @JavascriptInterface
    fun shareAppLogsWithData(frontendJsonData: String) {
        try {
            val logDir = File(context.cacheDir, "logs")
            if (!logDir.exists()) {
                logDir.mkdirs()
            }

            val timeStampForFile = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
            val displayTimeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date())
            val cleanModel = "${Build.MANUFACTURER}_${Build.MODEL}".replace(Regex("[^a-zA-Z0-9_-]"), "_")

            // 解析前端傳來的診斷 JSON
            val json = try {
                org.json.JSONObject(frontendJsonData)
            } catch (e: Exception) {
                org.json.JSONObject()
            }

            // 1. 0_AI_QUICK_SUMMARY.json (AI 一秒診斷速查摘要)
            val pkgInfo = try {
                context.packageManager.getPackageInfo(context.packageName, 0)
            } catch (e: Exception) {
                null
            }
            val versionCode = if (pkgInfo != null) PackageInfoCompat.getLongVersionCode(pkgInfo) else 0L

            val summaryObj = org.json.JSONObject().apply {
                put("generated_at", displayTimeStr)
                put("export_timestamp_iso", json.optString("exportTime", displayTimeStr))
                put("device_info", org.json.JSONObject().apply {
                    put("manufacturer", Build.MANUFACTURER)
                    put("model", Build.MODEL)
                    put("device", Build.DEVICE)
                    put("board", Build.BOARD)
                    put("hardware", Build.HARDWARE)
                    put("android_version", Build.VERSION.RELEASE)
                    put("sdk_int", Build.VERSION.SDK_INT)
                    put("app_version", pkgInfo?.versionName ?: "1.0")
                    put("version_code", versionCode)
                    put("max_memory_mb", Runtime.getRuntime().maxMemory() / (1024 * 1024))
                    put("location_permission_granted", hasLocationPermission())
                })
                put("session_metrics", json.optJSONObject("sessionMetrics") ?: org.json.JSONObject())
                put("navigation_state", org.json.JSONObject().apply {
                    put("current_road", json.optString("currentRoad", "未知道路"))
                    put("door_estimate", json.optString("lastDoor", ""))
                    put("intersection_status", json.optString("lastIntersection", ""))
                    put("last_heading_deg", json.optDouble("lastHeading", 0.0))
                    put("last_gps", json.optJSONObject("lastGps") ?: org.json.JSONObject())
                })
                put("anomalies_detected", json.optJSONArray("anomalies") ?: org.json.JSONArray())
            }
            val summaryJsonStr = summaryObj.toString(2)

            // 2. 1_trajectory.geojson (標準 GeoJSON 地理軌跡檔)
            val poisArray = json.optJSONArray("detectedPois")
            val geojsonObj = org.json.JSONObject().apply {
                put("type", "FeatureCollection")
                val features = org.json.JSONArray()

                // 行走折線幾何特徵 (LineString)
                val coordsList = LocationSensorBridge.getGpsCoordinatesList()
                if (coordsList.isNotEmpty()) {
                    val lineGeom = org.json.JSONObject().apply {
                        put("type", "LineString")
                        val coordArr = org.json.JSONArray()
                        coordsList.forEach { (lat, lon) ->
                            coordArr.put(org.json.JSONArray().put(lon).put(lat))
                        }
                        put("coordinates", coordArr)
                    }
                    val lineFeature = org.json.JSONObject().apply {
                        put("type", "Feature")
                        put("geometry", lineGeom)
                        put("properties", org.json.JSONObject().apply {
                            put("name", "行走軌跡 (Walking Trajectory)")
                            put("point_count", coordsList.size)
                        })
                    }
                    features.put(lineFeature)
                }

                // 店家地標點特徵 (Point Features)
                if (poisArray != null) {
                    for (i in 0 until poisArray.length()) {
                        val p = poisArray.optJSONObject(i) ?: continue
                        val lat = p.optDouble("lat", 0.0)
                        val lon = p.optDouble("lon", 0.0)
                        if (lat != 0.0 && lon != 0.0) {
                            val ptGeom = org.json.JSONObject().apply {
                                put("type", "Point")
                                put("coordinates", org.json.JSONArray().put(lon).put(lat))
                            }
                            val ptFeature = org.json.JSONObject().apply {
                                put("type", "Feature")
                                put("geometry", ptGeom)
                                put("properties", org.json.JSONObject().apply {
                                    put("name", p.optString("name", ""))
                                    put("category", p.optString("category", ""))
                                    put("distance_m", p.optDouble("distanceM", 0.0))
                                    put("clock", p.optString("clockPosition", ""))
                                    put("wheelchair", p.optString("wheelchair", ""))
                                    put("phone", p.optString("phone", ""))
                                    put("opening_hours", p.optString("opening_hours", ""))
                                })
                            }
                            features.put(ptFeature)
                        }
                    }
                }

                put("features", features)
            }
            val geojsonStr = geojsonObj.toString(2)

            // 3. 2_causality_trace.ndjson (因果鏈 Trace ID 結構化日誌)
            val traceArray = json.optJSONArray("causalityTrace")
            val traceNdjson = buildString {
                if (traceArray != null && traceArray.length() > 0) {
                    for (i in 0 until traceArray.length()) {
                        val obj = traceArray.optJSONObject(i)
                        if (obj != null) {
                            appendLine(obj.toString())
                        }
                    }
                } else {
                    appendLine("{\"info\": \"No causality traces recorded\"}")
                }
            }

            // 4. 3_detected_pois.json (結構化周遭店家清單)
            val poisJsonStr = poisArray?.toString(2) ?: "[]"

            // 5. 4_speech_history.ndjson (語音播報結構化歷史)
            val speechArray = json.optJSONArray("speechHistory")
            val speechNdjson = buildString {
                if (speechArray != null && speechArray.length() > 0) {
                    for (i in 0 until speechArray.length()) {
                        val obj = speechArray.optJSONObject(i)
                        if (obj != null) {
                            appendLine(obj.toString())
                        }
                    }
                } else {
                    appendLine("{\"info\": \"No speech events recorded\"}")
                }
            }

            // 6. 5_sensor_trajectory.ndjson (底層感測器歷程)
            val sensorNdjson = LocationSensorBridge.getTrajectoryNdjson().ifBlank {
                "{\"info\": \"No sensor fixes recorded\"}"
            }

            // 7. 6_system_logcat.txt (系統底層日誌)
            val process = Runtime.getRuntime().exec("logcat -d -v time")
            val logText = process.inputStream.bufferedReader().readText()

            // 將全部診斷檔案壓縮進動態命名的 ZIP 檔中
            val zipFileName = "NMap_Logs_${cleanModel}_${timeStampForFile}.zip"
            val zipFile = File(logDir, zipFileName)
            if (zipFile.exists()) {
                zipFile.delete()
            }

            ZipOutputStream(FileOutputStream(zipFile)).use { zos ->
                fun addEntry(name: String, content: String) {
                    zos.putNextEntry(ZipEntry(name))
                    zos.write(content.toByteArray(Charsets.UTF_8))
                    zos.closeEntry()
                }

                addEntry("0_AI_QUICK_SUMMARY.json", summaryJsonStr)
                addEntry("1_trajectory.geojson", geojsonStr)
                addEntry("2_causality_trace.ndjson", traceNdjson)
                addEntry("3_detected_pois.json", poisJsonStr)
                addEntry("4_speech_history.ndjson", speechNdjson)
                addEntry("5_sensor_trajectory.ndjson", sensorNdjson)
                addEntry("6_system_logcat.txt", logText)
            }

            // 透過 Android FileProvider 安全產生 URI 並呼叫系統分享介面
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                zipFile
            )

            val shareIntent = Intent(Intent.ACTION_SEND).apply {
                type = "application/zip"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_SUBJECT, "NMap Explorer 診斷日誌 - ${Build.MODEL} ($timeStampForFile)")
                putExtra(Intent.EXTRA_TEXT, "這是 NMap Explorer 的 AI 結構化診斷與軌跡日誌壓縮包（手機型號：${Build.MODEL}，匯出時間：$displayTimeStr）。")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }

            val chooser = Intent.createChooser(shareIntent, "分享 NMap AI 診斷日誌 ($zipFileName)").apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(chooser)
            Log.i(tag, "AI structured logs zipped and shared: ${zipFile.absolutePath}")
        } catch (e: Exception) {
            Log.e(tag, "Failed to zip and share AI structured logs", e)
        }
    }

    private val updateManager by lazy { com.example.nmapexplorer.update.AppUpdateManager(context) }

    /**
     * 【檢查 GitHub 最新發布版本】
     * 作用：讓網頁或主畫面呼叫，自動檢查 GitHub Releases。
     * @param silent 若為 true 則無新版時不語音打擾；若為 false (手動檢查) 則會語音回報「已是最新版本」。
     */
    @JavascriptInterface
    fun checkForUpdates(silent: Boolean = false) {
        Log.d(tag, "checkForUpdates called (silent=$silent)")
        CoroutineScope(Dispatchers.Main).launch {
            try {
                if (!silent) {
                    speak("正在檢查 GitHub 最新版本...", interrupt = true)
                }
                val result = updateManager.checkForUpdates()
                result.onSuccess { info ->
                    Log.d(tag, "checkForUpdates success: hasUpdate=${info.hasUpdate}, latest=${info.latestVersion}, current=${info.currentVersion}")
                    if (info.hasUpdate) {
                        speak("發現新版本 ${info.latestVersion}。${info.releaseTitle}。已開始為您下載更新檔。", interrupt = true)
                        val safeNotes = info.releaseNotes.replace("'", "\\'").replace("\n", "\\n")
                        val safeTitle = info.releaseTitle.replace("'", "\\'").replace("\n", "\\n")
                        webView?.evaluateJavascript(
                            "if (window.onUpdateAvailable) window.onUpdateAvailable('${info.latestVersion}', '$safeTitle', '${info.downloadUrl}', ${info.fileSize}, '$safeNotes');",
                            null
                        )
                        // 自動下載並引導安裝
                        downloadAndInstallUpdate(info.downloadUrl)
                    } else {
                        if (!silent) {
                            speak("目前已是最新版本 ${info.currentVersion}。", interrupt = true)
                        }
                        webView?.evaluateJavascript(
                            "if (window.onUpdateCheckResult) window.onUpdateCheckResult('latest', '${info.currentVersion}');",
                            null
                        )
                    }
                }.onFailure { err ->
                    Log.e(tag, "checkForUpdates failure", err)
                    if (!silent) {
                        speak("檢查更新失敗：${err.message ?: "請確認網路連線"}", interrupt = true)
                    }
                    webView?.evaluateJavascript(
                        "if (window.onUpdateCheckResult) window.onUpdateCheckResult('error', '${err.message ?: ""}');",
                        null
                    )
                }
            } catch (e: Exception) {
                Log.e(tag, "Check update failed", e)
            }
        }
    }


    /**
     * 【下載並安裝 GitHub 新版本 APK】
     */
    @JavascriptInterface
    fun downloadAndInstallUpdate(downloadUrl: String) {
        if (downloadUrl.isBlank()) return
        CoroutineScope(Dispatchers.Main).launch {
            try {
                var lastSpokenPercent = 0
                val result = updateManager.downloadUpdate(downloadUrl) { percent ->
                    webView?.evaluateJavascript(
                        "if (window.onDownloadProgress) window.onDownloadProgress($percent);",
                        null
                    )
                    // 每下載 25% 語音播報一次進度，避免太吵
                    if (percent >= lastSpokenPercent + 25 && percent < 100) {
                        lastSpokenPercent = percent
                        speak("下載進度 $percent 百分比", interrupt = false)
                    }
                }

                result.onSuccess { apkFile ->
                    speak("新版本下載完成，正在開啟安裝程式，請在畫面上點選「更新」或「安裝」。", interrupt = true)
                    webView?.evaluateJavascript("if (window.onDownloadComplete) window.onDownloadComplete();", null)
                    val installResult = updateManager.installUpdate(apkFile)
                    installResult.onFailure { installErr ->
                        speak(installErr.message ?: "開啟安裝程式失敗", interrupt = true)
                    }
                }.onFailure { err ->
                    speak("下載更新失敗：${err.message ?: "網路中斷"}", interrupt = true)
                    webView?.evaluateJavascript(
                        "if (window.onUpdateError) window.onUpdateError('${err.message ?: ""}');",
                        null
                    )
                }
            } catch (e: Exception) {
                Log.e(tag, "Download update failed", e)
            }
        }
    }


    /**
     * 取得目前安裝的 App 版本號
     */
    @JavascriptInterface
    fun getAppVersionName(): String {
        return updateManager.getCurrentVersionName()
    }

    private val dbManager by lazy { com.example.nmapexplorer.update.MapDatabaseManager(context) }

    /**
     * 【取得離線圖資狀態 JSON】
     */
    @JavascriptInterface
    fun getDatabaseStatusJson(): String {
        val status = dbManager.getDatabaseStatus()
        val json = org.json.JSONObject().apply {
            put("exists", status.exists)
            put("sizeFormattedMb", status.sizeFormattedMb)
            put("sizeBytes", status.sizeBytes)
            put("path", status.path)
            put("downloadUrl", status.downloadUrl)
        }
        return json.toString()
    }

    /**
     * 【獨立下載全台離線店家資料庫】
     */
    @JavascriptInterface
    fun downloadOfflineDatabase() {
        CoroutineScope(Dispatchers.Main).launch {
            try {
                speak("已開始在背景下載全台離線店家資料庫，請稍候...", interrupt = true)
                webView?.evaluateJavascript("if (window.onDatabaseDownloadStart) window.onDatabaseDownloadStart();", null)

                var lastSpoken = 0
                val result = dbManager.downloadDatabase { percent ->
                    webView?.evaluateJavascript(
                        "if (window.onDatabaseDownloadProgress) window.onDatabaseDownloadProgress($percent);",
                        null
                    )
                    if (percent >= lastSpoken + 20 && percent < 100) {
                        lastSpoken = percent
                        speak("離線圖資下載進度 $percent 百分比", interrupt = false)
                    }
                }

                result.onSuccess { file ->
                    val status = dbManager.getDatabaseStatus()
                    speak("全台離線店家資料庫下載完成（${status.sizeFormattedMb}），離線店家快速檢索已就緒！", interrupt = true)
                    webView?.evaluateJavascript(
                        "if (window.onDatabaseDownloadComplete) window.onDatabaseDownloadComplete('${status.sizeFormattedMb}');",
                        null
                    )
                }.onFailure { err ->
                    speak("離線圖資下載失敗：${err.message ?: "網路中斷"}", interrupt = true)
                    webView?.evaluateJavascript(
                        "if (window.onDatabaseDownloadError) window.onDatabaseDownloadError('${err.message ?: ""}');",
                        null
                    )
                }
            } catch (e: Exception) {
                Log.e(tag, "Download database failed", e)
            }
        }
    }

    /**
     * 【刪除離線圖資以釋放手機空間】
     */
    @JavascriptInterface
    fun deleteOfflineDatabase(): Boolean {
        val success = dbManager.deleteDatabase()
        if (success) {
            speak("已清理本地離線地圖資料庫，成功釋放儲存空間。", interrupt = true)
        }
        return success
    }
}



