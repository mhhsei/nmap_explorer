package com.example.nmapexplorer

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioManager
import android.net.ConnectivityManager
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
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

    // 語音防剪音與防抖狀態追蹤
    private var lastSpokenText: String = ""
    private var lastSpokenTimeMs: Long = 0L
    private var lastTtsDirectText: String = ""
    private var lastTtsDirectTimeMs: Long = 0L

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
     * 3. 具備 600ms 防抖時間，杜絕邊界連續觸發引發的抽搐。
     * 
     * @param text 要朗讀的文字 (如「正北」、「北北東」)
     * @param interrupt 是否立即插播（預設 true）
     */
    @JavascriptInterface
    fun speakTtsDirect(text: String, interrupt: Boolean = true) {
        if (text.isBlank()) return
        val now = SystemClock.uptimeMillis()
        val elapsed = now - lastTtsDirectTimeMs
        // 防抖：相同方位在 1000ms 內、或任何方位在 350ms 內不重覆發音，杜絕機關槍殘音
        if (text == lastTtsDirectText && elapsed < 1000L) return
        if (elapsed < 350L) return

        lastTtsDirectText = text
        lastTtsDirectTimeMs = now
        Log.i(tag, "[TTS_DIRECT] text='$text', elapsed=${elapsed}ms")

        (context as? android.app.Activity)?.runOnUiThread {
            try {
                if (isTtsReady && tts != null) {
                    val queueMode = if (interrupt) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
                    tts?.speak(text, queueMode, null, "turn_${System.currentTimeMillis()}")
                } else {
                    webView?.announceForAccessibility(text)
                }
            } catch (e: Exception) {
                Log.e(tag, "Error in speakTtsDirect", e)
            }
        }
    }

    var trafficSignalCameraManager: TrafficSignalCameraManager? = null
    var locationSensorBridge: LocationSensorBridge? = null

    /**
     * 【主動請求原生層補發最新已知座標與感測器狀態】
     * 由前端 WebView 在 DOMContentLoaded 完成時主動調用
     * 作用：徹底消除網頁載入延遲導致的第一筆 GPS 遺失，確保世界模型 100% 立即啟動
     */
    @JavascriptInterface
    fun requestLatestLocation() {
        Log.i(tag, "[GPS_REPLAY] Frontend requested latest location replay.")
        locationSensorBridge?.replayLastLocation()
    }

    @JavascriptInterface
    fun forceResetBarometerToGround() {
        Log.i(tag, "[SENSOR_FUSION] Frontend triggered GPS Road-Snap override. Resetting barometer to GROUND.")
        LocationSensorBridge.forceResetBarometerToGround()
    }
    
    @JavascriptInterface
    fun setGroundElevation(elevationM: Float) {
        LocationSensorBridge.setGroundElevation(elevationM)
    }

    /**
     * 【啟動路口紅綠燈相機即時辨識】
     * 由前端 WebView 在接近號誌路口時自動調用
     * 作用：以快門音效開鏡、空間姿態引導對準對街號誌、並以 Google 原生 TTS 直報燈號
     */
    @JavascriptInterface
    fun startTrafficSignalCamera(bearingDeg: Double, clockPosition: String) {
        Log.i(tag, "[CAMERA_SIGNAL] startTrafficSignalCamera: bearing=$bearingDeg, clock=$clockPosition")
        (context as? android.app.Activity)?.runOnUiThread {
            trafficSignalCameraManager?.startCamera(bearingDeg, clockPosition)
        }
    }

    /**
     * 【關閉路口紅綠燈相機】
     * 由前端 WebView 在過馬路中或離開路口時自動調用
     * 作用：收鏡音效確認、釋放相機硬體資源節省電量
     */
    @JavascriptInterface
    fun stopTrafficSignalCamera() {
        Log.i(tag, "[CAMERA_SIGNAL] stopTrafficSignalCamera")
        (context as? android.app.Activity)?.runOnUiThread {
            trafficSignalCameraManager?.stopCamera()
        }
    }

    /**
     * 原生即時語音朗讀通道 (Native Speech Broadcast with Smart Sequencer)
     * 
     * 作用：徹底解決 WebView 網頁 aria-live 在手機頻繁旋轉時容易漏讀或消音的問題。
     * 1. 若 TalkBack 開啟中：直接向系統無障礙服務發送 announceForAccessibility 原生事件。
     * 2. 若 TalkBack 未開啟：透過原生 TTS 引擎直接發聲。
     * 3. 智慧排隊機制：一般店家與路況語音若在 800ms 內接連抵達，自動平滑排隊 (QUEUE_ADD)，
     *    只有危險警告或使用者主動點擊時才執行插播 (QUEUE_FLUSH)，根除 2ms 剪音吞字 Bug！
     * 
     * @param text 要朗讀的文字
     * @param interrupt 是否立即插播
     */
    @JavascriptInterface
    fun speak(text: String, interrupt: Boolean = true) {
        if (text.isBlank()) return
        val now = SystemClock.uptimeMillis()
        val elapsed = now - lastSpokenTimeMs

        // 避免完全相同字串在 1.5 秒內跳針重覆朗讀
        if (text == lastSpokenText && elapsed < 1500L) {
            Log.d(tag, "[SPEECH_DROPPED_DUPLICATE] '$text' (elapsed=${elapsed}ms)")
            return
        }

        // 智慧型插播判定：
        // 若為急迫警報或手動點擊（如包含 ⚠️、危險、目前位置），立即插播；
        // 若為一般例行店家/路口通知且上一句剛發聲 (< 800ms)，強制改為平滑排隊，杜絕被下一句腰斬！
        val isEmergency = text.startsWith("⚠️") || text.contains("危險") || text.startsWith("【目前位置】")
        val effectiveInterrupt = if (isEmergency) true else (interrupt && elapsed > 800L)

        lastSpokenText = text
        lastSpokenTimeMs = now
        Log.i(tag, "[SPEECH_DISPATCH] text='$text', requestedInterrupt=$interrupt, effectiveInterrupt=$effectiveInterrupt, elapsed=${elapsed}ms")

        (context as? android.app.Activity)?.runOnUiThread {
            try {
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

                // 同步調用 WebView announceForAccessibility
                webView?.announceForAccessibility(text)

                // 若未啟用觸控瀏覽輔助，透過原生 TTS 引擎發聲
                val isTouchExploration = am?.isEnabled == true && am.isTouchExplorationEnabled
                if (!isTouchExploration && isTtsReady) {
                    val queueMode = if (effectiveInterrupt) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
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
     * 一鍵打包 8 合 1 結構化診斷日誌並喚醒系統分享選單 (Share Sheet)
     * 
     * 包含內容：
     * 1. 0_文字版診斷總覽_SUMMARY.txt：NVDA 螢幕報讀與記事本可直接秒開的中文純文字報告
     * 2. 1_AI快速診斷_QUICK_SUMMARY.json：手機硬體、電源省電模式、感測器快照與異常速查
     * 3. 2_行走軌跡_trajectory.geojson.txt：標準 GeoJSON 行走軌跡與地標
     * 4. 3_周遭店家清單_detected_pois.json：掃描到的周遭店家
     * 5. 4_語音播報歷史紀錄_speech_history.txt：語音朗讀歷史
     * 6. 5_決策因果鏈_causality_trace.txt：決策因果鏈 Trace 紀錄
     * 7. 6_感測器與GPS軌跡_sensor_trajectory.txt：底層卡爾曼、氣壓計、信標與步態數據
     * 8. 7_Android系統Logcat日誌_system_logcat.log：Android 系統底層日誌
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

            val pkgInfo = try {
                context.packageManager.getPackageInfo(context.packageName, 0)
            } catch (e: Exception) {
                null
            }
            val versionCode = if (pkgInfo != null) PackageInfoCompat.getLongVersionCode(pkgInfo) else 0L

            // 1. 系統電源與運行環境指標（排查 GPS 凍結核心原因）
            val powerManager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
            val isPowerSaveMode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                powerManager?.isPowerSaveMode ?: false
            } else false

            val batteryIntent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val bLevel = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
            val bScale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
            val batteryPct = if (bLevel >= 0 && bScale > 0) (bLevel * 100 / bScale) else -1
            val bStatus = batteryIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
            val isCharging = bStatus == BatteryManager.BATTERY_STATUS_CHARGING || bStatus == BatteryManager.BATTERY_STATUS_FULL

            // 2. 網路連線類型
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            @Suppress("DEPRECATION")
            val activeNet = connectivityManager?.activeNetworkInfo
            @Suppress("DEPRECATION")
            val networkTypeStr = when {
                activeNet == null || !activeNet.isConnected -> "無網路 (離線探索模式)"
                activeNet.type == ConnectivityManager.TYPE_WIFI -> "Wi-Fi (${activeNet.extraInfo ?: "已連線"})"
                activeNet.type == ConnectivityManager.TYPE_MOBILE -> "行動網路 (${activeNet.subtypeName})"
                else -> activeNet.typeName
            }

            // 3. 音訊輸出途徑
            val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            @Suppress("DEPRECATION")
            val isBluetoothAudio = audioManager?.isBluetoothA2dpOn == true || audioManager?.isBluetoothScoOn == true
            @Suppress("DEPRECATION")
            val isWiredHeadset = audioManager?.isWiredHeadsetOn == true
            val audioRouteStr = when {
                isBluetoothAudio -> "藍牙無線耳機 (具備立體聲 3D HRTF 空間音效效果)"
                isWiredHeadset -> "有線立體聲耳機"
                else -> "手機內建揚聲器 (喇叭)"
            }

            // 4. 無障礙服務狀態
            val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager
            val isAccessibilityEnabled = am?.isEnabled ?: false
            val isTouchExploration = am?.isTouchExplorationEnabled ?: false

            // 5. 底層感測器與演算法快照
            val sensorDiag = LocationSensorBridge.getDiagnosticsSnapshot()

            val poisArray = json.optJSONArray("detectedPois")
            val speechArray = json.optJSONArray("speechHistory")
            val traceArray = json.optJSONArray("causalityTrace")
            val interactionsArray = json.optJSONArray("interactions")
            val anomaliesArray = json.optJSONArray("anomalies")
            val lastGpsObj = json.optJSONObject("lastGps")
            val cameraLogsList = TrafficSignalCameraManager.getCameraEventLogs()

            // =========================================================================
            // 檔案 1：0_文字版診斷總覽_SUMMARY.txt (NVDA 螢幕閱讀器與記事本直接秒開的純文字報告)
            // =========================================================================
            val plainTextSummary = buildString {
                appendLine("================================================================================")
                appendLine("【NMap Explorer 視障無障礙導航系統 - 設備與診斷總覽報告】")
                appendLine("================================================================================")
                appendLine("匯出時間：$displayTimeStr")
                appendLine("手機型號：${Build.MANUFACTURER} ${Build.MODEL} (Android ${Build.VERSION.RELEASE}, SDK ${Build.VERSION.SDK_INT})")
                appendLine("App 版本：${pkgInfo?.versionName ?: "1.0"} (版本代號: $versionCode)")
                appendLine("探索時長：${json.optInt("sessionDurationSec", 0)} 秒")
                appendLine("播報次數：${speechArray?.length() ?: 0} 則")
                appendLine("發現店家：${poisArray?.length() ?: 0} 處")
                appendLine("相機事件：${cameraLogsList.size} 筆")
                appendLine("操作互動：${interactionsArray?.length() ?: 0} 筆")
                appendLine()

                // =====================================================================
                // 【核心亮點：本次行走旅程大事記 (Journey Milestones Timeline)】
                // 依時間序列萃取關鍵事件，讓視障者用 NVDA 在 20 秒內完整掌握整趟旅程
                // =====================================================================
                appendLine("--------------------------------------------------------------------------------")
                appendLine("【本次行走旅程大事記 (Journey Milestones Timeline)】")
                appendLine("（按時間先後排列，讓視障者與工程師 10 秒掌握整趟探索所有核心動態）")
                appendLine("--------------------------------------------------------------------------------")
                val milestones = mutableListOf<Pair<String, String>>()

                // 1. 起點事件
                milestones.add(Pair(displayTimeStr, "[旅程起點] 定位鎖定於【${json.optString("currentRoad", "未知出發地")}】，開始探索"))

                // 2. 語音導引事件精選 (路口、過街、店家抵達、變燈)
                if (speechArray != null) {
                    for (i in 0 until speechArray.length()) {
                        val s = speechArray.optJSONObject(i) ?: continue
                        val t = s.optString("time", "")
                        val txt = s.optString("text", "")
                        if (txt.contains("接近路口") || txt.contains("正通過路口") || txt.contains("沿著") || txt.contains("抵達") || txt.contains("小綠人") || txt.contains("紅燈") || txt.contains("對街搜尋中")) {
                            milestones.add(Pair(t, "[語音導引] $txt"))
                        }
                    }
                }

                // 3. 相機關鍵狀態變更
                for (cLog in cameraLogsList) {
                    if (cLog.contains("CAMERA_START") || cLog.contains("CAMERA_CONFIRMED") || cLog.contains("CAMERA_STOP") || cLog.contains("CAMERA_SEARCH")) {
                        val clean = cLog.replace("[", "").replace("]", " |")
                        val parts = clean.split("|", limit = 2)
                        val t = if (parts.isNotEmpty()) parts[0].trim() else ""
                        val m = if (parts.size > 1) parts[1].trim() else clean
                        milestones.add(Pair(t, "[相機號誌] $m"))
                    }
                }

                // 4. 使用者觸控與手勢操作
                if (interactionsArray != null) {
                    for (i in 0 until interactionsArray.length()) {
                        val act = interactionsArray.optJSONObject(i) ?: continue
                        val t = act.optString("time", "")
                        val a = act.optString("action", "")
                        val d = act.optString("detail", "")
                        milestones.add(Pair(t, "[手勢操作] $a: $d"))
                    }
                }

                // 5. 異常事件
                if (anomaliesArray != null) {
                    for (i in 0 until anomaliesArray.length()) {
                        val an = anomaliesArray.optJSONObject(i) ?: continue
                        val t = an.optString("time", "")
                        val d = an.optString("message").ifEmpty { an.optString("desc", "") }
                        milestones.add(Pair(t, "[⚠️ 系統異常] $d"))
                    }
                }

                // 依時間排序並輸出精華大事
                val sortedMilestones = milestones.sortedBy { it.first }
                if (sortedMilestones.isNotEmpty()) {
                    sortedMilestones.takeLast(40).forEach { (t, desc) ->
                        val shortTime = if (t.length >= 8 && t.contains(":")) {
                            t.substringAfterLast("T").substringBefore(".").take(8)
                        } else t
                        appendLine("• $shortTime $desc")
                    }
                } else {
                    appendLine("• （探索剛啟動，尚無重大里程碑）")
                }
                appendLine()

                appendLine("--------------------------------------------------------------------------------")
                appendLine("一、 系統電源與運行環境（排查 GPS 凍結核心指標）")
                appendLine("--------------------------------------------------------------------------------")
                appendLine("• 系統省電模式 (Power Save Mode)：" + if (isPowerSaveMode) "【⚠️ 開啟中 (警告：省電模式會大幅抑制背景 GPS 頻率，可能造成導航卡頓)】" else "關閉 (正常)")
                appendLine("• 電池電量：$batteryPct% " + (if (isCharging) "(充電中)" else "(未充電)"))
                appendLine("• 網路連線狀態：$networkTypeStr")
                appendLine("• 螢幕閱讀器 (TalkBack)：" + if (isAccessibilityEnabled) "開啟中" else "未開啟")
                appendLine("• 觸控瀏覽輔助 (Touch Exploration)：" + if (isTouchExploration) "開啟中" else "未開啟")
                appendLine("• 音訊輸出途徑：$audioRouteStr")
                appendLine("• 定位權限授權：${if (hasLocationPermission()) "已授權 (精確定位)" else "未授權"}")
                appendLine()
                appendLine("--------------------------------------------------------------------------------")
                appendLine("二、 3D 立體垂直高程與氣壓計狀態 (Barometer & 3D Level)")
                appendLine("--------------------------------------------------------------------------------")
                appendLine("• 當前立體樓層：${sensorDiag.optString("vertical_level_display", "地面層")} (${sensorDiag.optString("vertical_level", "GROUND")})")
                appendLine("• 相對地面高度：${String.format(Locale.US, "%+.1f", sensorDiag.optDouble("altitude_m", 0.0))} 公尺")
                appendLine("• 即時原始氣壓：${String.format(Locale.US, "%.2f", sensorDiag.optDouble("raw_pressure_hpa", 1013.25))} hPa")
                appendLine("• 基準大氣壓力：${String.format(Locale.US, "%.2f", sensorDiag.optDouble("baseline_pressure_hpa", 1013.25))} hPa")
                appendLine("• 垂直升降速度：${String.format(Locale.US, "%.2f", sensorDiag.optDouble("vertical_velocity_mps", 0.0))} m/s")
                appendLine()
                appendLine("--------------------------------------------------------------------------------")
                appendLine("三、 定位品質與衛星狀態 (GNSS & Differential)")
                appendLine("--------------------------------------------------------------------------------")
                appendLine("• 差分定位等級：${sensorDiag.optString("diff_tier_display", "單機導航 (3-5m)")} [${sensorDiag.optString("diff_tier_name", "OFFLINE_AUTONOMOUS")}]")
                appendLine("• 可視衛星總數：${sensorDiag.optInt("satellites_total", 0)} 顆 (使用中：${sensorDiag.optInt("satellites_used", 0)} 顆)")
                appendLine("• 平均訊噪比 (C/N0)：${String.format(Locale.US, "%.1f", sensorDiag.optDouble("satellites_avg_snr", 0.0))} dB-Hz")
                appendLine("• 雙頻 L5 衛星：${if (sensorDiag.optBoolean("has_l5", false)) "已鎖定 (收獲 " + sensorDiag.optInt("satellites_l5_count", 0) + " 顆 L5)" else "無雙頻 L5"}")
                appendLine("• 都市峽谷多路徑折射 (Multipath)：${if (sensorDiag.optBoolean("is_multipath", false)) "【⚠️ 偵測到大樓訊號折射反射】" else "無折射 (訊號正常)"}")
                appendLine("• 最後 GPS 座標：(${lastGpsObj?.optDouble("lat", 0.0)}, ${lastGpsObj?.optDouble("lon", 0.0)})")
                appendLine()
                appendLine("--------------------------------------------------------------------------------")
                appendLine("四、 步伐、航位推算與手機姿態 (PDR & Motion State)")
                appendLine("--------------------------------------------------------------------------------")
                appendLine("• 運動狀態機：${sensorDiag.optString("motion_state", "STATIONARY_LOCKED")}")
                appendLine("• 硬體計步器累計：${sensorDiag.optLong("hardware_steps", 0L)} 步")
                appendLine("• 軟體波峰計步累計：${sensorDiag.optLong("software_steps", 0L)} 步")
                appendLine("• 自適應步長估計：${String.format(Locale.US, "%.2f", sensorDiag.optDouble("stride_length_m", 0.65))} 公尺")
                appendLine("• 手機手持姿態：")
                appendLine("  - 真北方位角 (Heading)：${String.format(Locale.US, "%.1f", sensorDiag.optDouble("heading_deg", 0.0))}°")
                appendLine("  - 俯仰角 (Pitch)：${String.format(Locale.US, "%.1f", sensorDiag.optDouble("pitch_deg", 0.0))}°")
                appendLine("  - 翻滾角 (Roll)：${String.format(Locale.US, "%.1f", sensorDiag.optDouble("roll_deg", 0.0))}°")
                appendLine()
                appendLine("--------------------------------------------------------------------------------")
                appendLine("五、 室內公眾信標與 Wi-Fi 定錨 (Indoor Beacons)")
                appendLine("--------------------------------------------------------------------------------")
                val matchedBeacon = sensorDiag.optJSONObject("last_matched_beacon")
                if (matchedBeacon != null) {
                    appendLine("• 目前定錨信標：${matchedBeacon.optString("name")} (距離約 ${String.format(Locale.US, "%.1f", matchedBeacon.optDouble("dist_m", 0.0))} 公尺)")
                    appendLine("  信標樓層：${matchedBeacon.optString("level")}")
                } else {
                    appendLine("• 目前定錨信標：尚未定錨公眾信標")
                }
                val recentBeacons = sensorDiag.optJSONArray("recent_beacons")
                appendLine("• 最近掃描到藍牙信標筆數：${recentBeacons?.length() ?: 0} 筆")
                appendLine()
                appendLine("--------------------------------------------------------------------------------")
                appendLine("六、 3D 空間導引狀態")
                appendLine("--------------------------------------------------------------------------------")
                val guidance = json.optJSONObject("activeGuidance")
                if (guidance != null) {
                    appendLine("• 導引目標名稱：${guidance.optString("targetName", "無")}")
                    appendLine("• 目標剩餘距離：${String.format(Locale.US, "%.1f", guidance.optDouble("lastDistanceM", 0.0))} 公尺")
                } else {
                    appendLine("• 3D 空間導引：未開啟")
                }
                appendLine()
                appendLine("--------------------------------------------------------------------------------")
                appendLine("七、 異常事件速查 (Anomalies)")
                appendLine("--------------------------------------------------------------------------------")
                if (anomaliesArray != null && anomaliesArray.length() > 0) {
                    for (i in 0 until anomaliesArray.length()) {
                        val an = anomaliesArray.optJSONObject(i)
                        if (an != null) {
                            val type = an.optString("type", "ANOMALY")
                            val desc = an.optString("message").ifEmpty { an.optString("desc", "未知異常") }
                            val time = an.optString("timestamp").ifEmpty { an.optString("time", "") }
                            appendLine("• [$type] $desc ($time)")
                        }
                    }
                } else {
                    appendLine("• 無異常事件記錄 (系統運行良好)")
                }
                appendLine("================================================================================")
            }

            // =========================================================================
            // 檔案 2：1_AI快速診斷_QUICK_SUMMARY.json (結構化診斷 JSON，供自動化工具解析)
            // =========================================================================
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
                put("power_and_environment", org.json.JSONObject().apply {
                    put("is_power_save_mode", isPowerSaveMode)
                    put("battery_percent", batteryPct)
                    put("is_charging", isCharging)
                    put("network_type", networkTypeStr)
                    put("audio_route", audioRouteStr)
                    put("talkback_active", isAccessibilityEnabled)
                    put("touch_exploration_active", isTouchExploration)
                })
                put("sensor_diagnostics", sensorDiag)
                put("session_metrics", json.optJSONObject("sessionMetrics") ?: org.json.JSONObject())
                put("navigation_state", org.json.JSONObject().apply {
                    put("current_road", json.optString("currentRoad", "未知道路"))
                    put("door_estimate", json.optString("lastDoor", ""))
                    put("intersection_status", json.optString("lastIntersection", ""))
                    put("last_heading_deg", json.optDouble("lastHeading", 0.0))
                    put("last_gps", lastGpsObj ?: org.json.JSONObject())
                    put("active_guidance", json.optJSONObject("activeGuidance"))
                })
                put("anomalies_detected", anomaliesArray ?: org.json.JSONArray())
                put("camera_events_count", cameraLogsList.size)
                put("user_interactions_count", interactionsArray?.length() ?: 0)
            }
            val summaryJsonStr = summaryObj.toString(2)

            // =========================================================================
            // 檔案 3：2_行走軌跡_trajectory.geojson.txt (標準 GeoJSON 軌跡檔，加 .txt 記事本與地圖工具通用)
            // =========================================================================
            val geojsonObj = org.json.JSONObject().apply {
                put("type", "FeatureCollection")
                val features = org.json.JSONArray()

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

            // =========================================================================
            // 檔案 4：3_周遭店家清單_detected_pois.json
            // =========================================================================
            val poisJsonStr = poisArray?.toString(2) ?: "[]"

            // =========================================================================
            // 檔案 5：4_語音播報歷史紀錄_speech_history.txt (易讀純文字格式)
            // =========================================================================
            val speechTxt = buildString {
                if (speechArray != null && speechArray.length() > 0) {
                    for (i in 0 until speechArray.length()) {
                        val s = speechArray.optJSONObject(i)
                        if (s != null) {
                            val timeStr = s.optString("time", "")
                            val textStr = s.optString("text", "")
                            appendLine("[$timeStr] $textStr")
                        }
                    }
                } else {
                    appendLine("（尚無語音播報紀錄）")
                }
            }

            // =========================================================================
            // 檔案 6：5_使用者操作互動紀錄_user_interactions.txt (易讀手勢與按鈕事件)
            // =========================================================================
            val interactionsTxt = buildString {
                if (interactionsArray != null && interactionsArray.length() > 0) {
                    for (i in 0 until interactionsArray.length()) {
                        val obj = interactionsArray.optJSONObject(i) ?: continue
                        val timeStr = obj.optString("time", "")
                        val actionStr = obj.optString("action", "")
                        val detailStr = obj.optString("detail", "")
                        appendLine("[$timeStr] [$actionStr] $detailStr")
                    }
                } else {
                    appendLine("（尚無使用者操作互動紀錄）")
                }
            }

            // =========================================================================
            // 檔案 7：6_決策因果鏈_causality_trace.txt (易讀決策事件清單)
            // =========================================================================
            val traceTxt = buildString {
                if (traceArray != null && traceArray.length() > 0) {
                    for (i in 0 until traceArray.length()) {
                        val obj = traceArray.optJSONObject(i)
                        if (obj != null) {
                            val timeStr = obj.optString("t").ifEmpty { obj.optString("time", "") }
                            val typeStr = obj.optString("type", "")
                            val descStr = obj.optString("text").ifEmpty { obj.optString("desc", obj.toString()) }
                            appendLine("[$timeStr] [$typeStr] $descStr")
                        }
                    }
                } else {
                    appendLine("（尚無決策因果鏈追蹤紀錄）")
                }
            }

            // =========================================================================
            // 檔案 8：7_紅綠燈相機辨識紀錄_camera_inference.txt (開關鏡與深度辨識日誌)
            // =========================================================================
            val cameraTxt = buildString {
                if (cameraLogsList.isNotEmpty()) {
                    cameraLogsList.forEach { appendLine(it) }
                } else {
                    appendLine("（探索期間紅綠燈相機未觸發運作）")
                }
            }

            // =========================================================================
            // 檔案 9：8_感測器與GPS軌跡_sensor_trajectory.txt (NDJSON 格式附 .txt 記事本直接開)
            // =========================================================================
            val sensorNdjson = LocationSensorBridge.getTrajectoryNdjson().ifBlank {
                "{\"info\": \"No sensor fixes recorded\"}"
            }

            // =========================================================================
            // 檔案 10：9_Android核心Logcat日誌_system_logcat.log (聚焦 App 關鍵標籤，去除 90% 系統雜訊)
            // =========================================================================
            val logText = try {
                val filterCmd = "logcat -d -v time -s LocationSensorBridge:V SignalCameraManager:V WebAppInterface:V Python:V Chaquopy:V Chromium:I AndroidRuntime:E *:S"
                val process = Runtime.getRuntime().exec(filterCmd)
                var txt = process.inputStream.bufferedReader().use { it.readText() }
                process.waitFor()
                process.destroy()
                if (txt.isBlank() || txt.lines().size < 8) {
                    val fallbackProcess = Runtime.getRuntime().exec("logcat -d -v time -t 2000")
                    txt = fallbackProcess.inputStream.bufferedReader().use { it.readText() }
                    fallbackProcess.waitFor()
                    fallbackProcess.destroy()
                }
                txt
            } catch (e: Exception) {
                "無法擷取 Logcat: ${e.message}"
            }

            // 將全部診斷檔案壓縮進動態命名的 ZIP 檔中（維持標準 .zip 副檔名原樣不動）
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

                addEntry("0_文字版診斷總覽_SUMMARY.txt", plainTextSummary)
                addEntry("1_AI快速診斷_QUICK_SUMMARY.json", summaryJsonStr)
                addEntry("2_行走軌跡_trajectory.geojson.txt", geojsonStr)
                addEntry("3_周遭店家清單_detected_pois.json", poisJsonStr)
                addEntry("4_語音播報歷史紀錄_speech_history.txt", speechTxt)
                addEntry("5_使用者操作互動紀錄_user_interactions.txt", interactionsTxt)
                addEntry("6_決策因果鏈_causality_trace.txt", traceTxt)
                addEntry("7_紅綠燈相機辨識紀錄_camera_inference.txt", cameraTxt)
                addEntry("8_感測器與GPS軌跡_sensor_trajectory.txt", sensorNdjson)
                addEntry("9_Android系統核心Logcat_system_logcat.log", logText)
            }

            // 同步複製一份至外部儲存空間 (/sdcard/Android/data/com.example.nmapexplorer/files/logs/)
            // 讓電腦端插上 USB 線時，可直接透過 adb pull 一鍵拉取，不需手動點擊分享
            try {
                val extLogDir = context.getExternalFilesDir("logs")
                if (extLogDir != null) {
                    if (!extLogDir.exists()) extLogDir.mkdirs()
                    val extZip = File(extLogDir, zipFileName)
                    zipFile.copyTo(extZip, overwrite = true)
                    Log.i(tag, "[LOG_BACKUP] Auto-backed up diagnostic zip to: ${extZip.absolutePath}")
                }
            } catch (e: Exception) {
                Log.w(tag, "Failed to copy diagnostic zip to external logs dir", e)
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
                putExtra(Intent.EXTRA_TITLE, zipFileName)
                putExtra(Intent.EXTRA_TEXT, "這是 NMap Explorer 的 AI 結構化診斷與軌跡日誌壓縮包（手機型號：${Build.MODEL}，匯出時間：$displayTimeStr）。")
                // 使用 ClipData 攜帶檔案名稱與 URI，確保各大通訊軟體 (LINE/Gmail/雲端硬碟) 接收時絕不丟失 .zip 副檔名
                clipData = ClipData.newUri(context.contentResolver, zipFileName, uri)
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
                            "if (window.onUpdateCheckResult) window.onUpdateCheckResult('latest', '${info.currentVersion}', ${!silent});",
                            null
                        )
                    }
                }.onFailure { err ->
                    Log.e(tag, "checkForUpdates failure", err)
                    if (!silent) {
                        speak("檢查更新失敗：${err.message ?: "請確認網路連線"}", interrupt = true)
                    }
                    webView?.evaluateJavascript(
                        "if (window.onUpdateCheckResult) window.onUpdateCheckResult('error', '${err.message ?: ""}', ${!silent});",
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
     * 【獨立下載或更新全台離線店家資料庫】
     */
    @JavascriptInterface
    fun downloadOfflineDatabase() {
        CoroutineScope(Dispatchers.Main).launch {
            try {
                speak("正在檢查離線圖資版本...", interrupt = true)
                val check = dbManager.checkDatabaseUpdate()

                if (check.isUpToDate) {
                    val msg = "目前離線資料庫（${check.sizeFormattedMb}）已是最新版本，無須重複下載。"
                    speak(msg, interrupt = true)
                    webView?.evaluateJavascript(
                        "if (window.onDatabaseAlreadyLatest) window.onDatabaseAlreadyLatest('${check.sizeFormattedMb}');",
                        null
                    )
                    return@launch
                }

                speak("發現新版離線圖資（${check.remoteVersion}），已開始在背景下載更新，請稍候...", interrupt = true)
                webView?.evaluateJavascript("if (window.onDatabaseDownloadStart) window.onDatabaseDownloadStart();", null)

                var lastSpoken = 0
                val result = dbManager.downloadDatabase(check.downloadUrl) { percent ->
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
                    dbManager.setLocalDbVersion(check.remoteVersion)
                    val status = dbManager.getDatabaseStatus()
                    speak("全台離線店家資料庫已更新至最新版（${status.sizeFormattedMb}），離線店家快速檢索已就緒！", interrupt = true)
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
                speak("檢查或下載離線圖資時發生異常", interrupt = true)
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



