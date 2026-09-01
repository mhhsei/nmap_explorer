package com.example.nmapexplorer

import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.example.nmapexplorer.theme.NMapExplorerTheme

/**
 * Android 主程式進入點 (Main Activity)
 * 
 * 核心職責：
 * 1. 啟動嵌入式 Python (Chaquopy) 環境與本機 HTTP 伺服器 (Bottle: 127.0.0.1:8000)。
 * 2. 向使用者請求 GPS 定位、動作識別與通知等必要權限。
 * 3. 載入前端 WebView 顯示導航地圖與語音操作介面。
 * 4. 監聽手機螢幕開關狀態，在放入口袋（螢幕關閉）時切換至低功耗模式省電。
 */
class MainActivity : ComponentActivity() {
    // 感測器橋接器：負責 GPS、陀螺儀與卡爾曼濾波的調度
    private var sensorBridge: LocationSensorBridge? = null
    private var currentWebView: WebView? = null

    /**
     * 動態權限請求回調處理器
     * 當使用者同意 GPS 權限後，立即啟動前台常駐服務與感測器監聽。
     */
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val fineGranted = permissions[android.Manifest.permission.ACCESS_FINE_LOCATION] ?: false
        val coarseGranted = permissions[android.Manifest.permission.ACCESS_COARSE_LOCATION] ?: false
        if (fineGranted || coarseGranted) {
            startServiceIfPermitted()
            sensorBridge?.start()
            currentWebView?.evaluateJavascript("if (window.onPermissionGranted) window.onPermissionGranted();", null)
        }
    }

    /**
     * 應用程式建立時觸發 (onCreate)
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 導航時保持螢幕常亮（避免手持探索時忽然關閉）
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // 1. 初始化 Chaquopy 嵌入式 Python 引擎
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        // 2. 在背景執行緒啟動 Bottle Web 伺服器 (127.0.0.1:8000) 並指定圖資儲存目錄
        val dataDir = getExternalFilesDir(null)?.resolve("data") ?: filesDir.resolve("data")
        dataDir.mkdirs()

        val py = Python.getInstance()
        val serverRunner = py.getModule("server_runner")
        serverRunner.callAttr("start_server_in_background", "127.0.0.1", 8000, dataDir.absolutePath)


        // 3. 檢查並請求所需權限（GPS、計步器、通知）
        checkAndRequestLocationPermissions()

        // 4. 啟用全螢幕邊界延伸 (Edge-to-Edge) 並載入 Compose 介面
        enableEdgeToEdge()
        setContent {
            NMapExplorerTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    // 載入本機 Web 介面
                    WebViewScreen("http://127.0.0.1:8000/") { bridge, webView ->
                        sensorBridge = bridge
                        currentWebView = webView
                        checkAndStartSensors()
                    }
                }
            }
        }
    }


    /**
     * 若已獲得權限，則啟動前台常駐服務 (ServerForegroundService)
     */
    private fun startServiceIfPermitted() {
        val fine = ContextCompat.checkSelfPermission(this, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(this, android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (fine || coarse) {
            val serviceIntent = Intent(this, ServerForegroundService::class.java)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    startForegroundService(serviceIntent)
                } else {
                    startService(serviceIntent)
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    /**
     * 檢查並向使用者彈出請求權限對話框
     */
    private fun checkAndRequestLocationPermissions() {
        val permissions = mutableListOf(
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.CAMERA
        )
        // Android 10+ 需要動作識別權限來讀取硬體計步器
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            permissions.add(android.Manifest.permission.ACTIVITY_RECOGNITION)
        }
        // Android 12+ 需要藍牙掃描權限來進行室內 Beacon 定錨
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions.add(android.Manifest.permission.BLUETOOTH_SCAN)
            permissions.add(android.Manifest.permission.BLUETOOTH_CONNECT)
        }
        // Android 13+ 需要通知發布權限
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(android.Manifest.permission.POST_NOTIFICATIONS)
        }

        // 篩選出尚未取得的權限清單
        val needed = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isNotEmpty()) {
            requestPermissionLauncher.launch(needed.toTypedArray())
        } else {
            startServiceIfPermitted()
        }
    }

    /**
     * 檢查權限並開啟感測器監聽
     */
    private fun checkAndStartSensors() {
        val fine = ContextCompat.checkSelfPermission(this, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(this, android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (fine || coarse) {
            startServiceIfPermitted()
            sensorBridge?.start()
        }
    }

    /**
     * 螢幕開關廣播監聽器：
     * 1. 螢幕關閉 (SCREEN_OFF)：使用者將手機放入口袋，通知感測器關閉高耗電陀螺儀，切換為低耗電計步推算。
     * 2. 螢幕開啟 (SCREEN_ON)：恢復全功能高頻感測器監聽。
     */
    private val screenReceiver = object : android.content.BroadcastReceiver() {
        override fun onReceive(context: android.content.Context?, intent: android.content.Intent?) {
            when (intent?.action) {
                Intent.ACTION_SCREEN_OFF -> sensorBridge?.setScreenActive(false)
                Intent.ACTION_SCREEN_ON -> sensorBridge?.setScreenActive(true)
            }
        }
    }

    override fun onStart() {
        super.onStart()
        // 註冊螢幕開關廣播
        val filter = android.content.IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
        }
        registerReceiver(screenReceiver, filter)
    }

    override fun onResume() {
        super.onResume()
        checkAndStartSensors()
        sensorBridge?.setScreenActive(true)
    }

    override fun onPause() {
        super.onPause()
        sensorBridge?.setScreenActive(false)
    }

    override fun onStop() {
        super.onStop()
        try {
            unregisterReceiver(screenReceiver)
        } catch (e: Exception) {
            // ignore if not registered
        }
    }

    /**
     * App 完全關閉銷毀時，釋放感測器並停止背景服務
     */
    override fun onDestroy() {
        super.onDestroy()
        sensorBridge?.stop()
        try {
            val serviceIntent = Intent(this, ServerForegroundService::class.java)
            stopService(serviceIntent)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}

/**
 * 嵌入式網頁畫面元件 (WebView Screen)
 * 
 * 作用：建立全螢幕 WebView 並載入本機 Bottle 伺服器的前端網頁。
 * 啟用 JavaScript、DOM Storage、Web Audio API，並注入 AndroidBridge 供網頁呼叫原生功能。
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebViewScreen(url: String, onBridgeCreated: (LocationSensorBridge, WebView) -> Unit) {
    AndroidView(
        factory = { context ->
            val webView = WebView(context).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                // 允許網頁自動播放 Web Audio 音效（無需使用者點擊手勢）
                settings.mediaPlaybackRequiresUserGesture = false
                // 本地開發除錯不快取，確保前端隨時載入最新檔案
                settings.cacheMode = WebSettings.LOAD_NO_CACHE
                
                // 【開機自動重試機制 (Auto-Retry on Server Warmup)】
                // 解決 Python Bottle 伺服器啟動耗時 (300~1000ms) 與 WebView 立即載入造成的 ERR_CONNECTION_REFUSED 白屏卡死
                val retryHandler = android.os.Handler(android.os.Looper.getMainLooper())
                var isPageSuccessfullyLoaded = false
                var hasPageError = false
                var retryAttempt = 0
                val maxRetryAttempts = 40

                webViewClient = object : WebViewClient() {
                    override fun onPageStarted(view: WebView?, startedUrl: String?, favicon: android.graphics.Bitmap?) {
                        super.onPageStarted(view, startedUrl, favicon)
                        hasPageError = false
                    }

                    override fun onReceivedError(
                        view: WebView?,
                        request: android.webkit.WebResourceRequest?,
                        error: android.webkit.WebResourceError?
                    ) {
                        if (request?.isForMainFrame == true) {
                            hasPageError = true
                            isPageSuccessfullyLoaded = false
                            android.util.Log.w("MainActivity", "[WebView Warmup] Main frame connection error (${error?.errorCode}: ${error?.description})")
                        }
                    }

                    override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                        super.onPageFinished(view, finishedUrl)
                        if (hasPageError) {
                            // 載入過程發生錯誤（伺服器尚未就緒），排程自動重試
                            if (retryAttempt < maxRetryAttempts) {
                                retryAttempt++
                                android.util.Log.w("MainActivity", "[WebView Warmup] Server warming up ($retryAttempt/$maxRetryAttempts), retrying load in 300ms...")
                                retryHandler.removeCallbacksAndMessages(null)
                                retryHandler.postDelayed({
                                    view?.loadUrl(url)
                                }, 300L)
                            }
                        } else if (!isPageSuccessfullyLoaded && finishedUrl != null && finishedUrl.startsWith("http://127.0.0.1:8000/")) {
                            // 完全無錯誤，首頁成功載入！
                            isPageSuccessfullyLoaded = true
                            retryHandler.removeCallbacksAndMessages(null)
                            android.util.Log.i("MainActivity", "[WebView Loaded] Successfully loaded $finishedUrl without errors")
                        }
                    }
                }

                webChromeClient = object : android.webkit.WebChromeClient() {
                    override fun onConsoleMessage(consoleMessage: android.webkit.ConsoleMessage?): Boolean {
                        android.util.Log.d("NMapConsole", "[JS ${consoleMessage?.messageLevel()}] ${consoleMessage?.message()} (${consoleMessage?.sourceId()}:${consoleMessage?.lineNumber()})")
                        return true
                    }
                }
                WebView.setWebContentsDebuggingEnabled(true)
                val appInterface = WebAppInterface(context, this)
                val signalCamera = TrafficSignalCameraManager(context, appInterface)
                appInterface.trafficSignalCameraManager = signalCamera
                addJavascriptInterface(appInterface, "AndroidBridge")

                val bridge = LocationSensorBridge(context, this)
                appInterface.locationSensorBridge = bridge
                onBridgeCreated(bridge, this)

                loadUrl(url)
            }
            webView
        },

        modifier = Modifier.fillMaxSize()
    )
}

