package com.example.nmapexplorer

import android.app.Activity
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.media.MediaActionSound
import android.os.Build
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import android.view.WindowManager
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import org.tensorflow.lite.Interpreter
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 【紅綠燈相機即時辨識與空間方位導航引擎 (TrafficSignalCameraManager)】
 *
 * 核心使命與台灣交通號誌特化：
 * 1. 到路口自動開相機，過馬路自動關閉，全程以俐落音效取代冗長語音。
 * 2. 鏡頭偏斜時，以 Google 原生 TTS 提示方位（如「號誌在 1 點鐘方向」）。
 * 3. 鏡頭拍到號誌時，跳過方位，直接回報「小綠人，可通行」、「小綠人閃爍」或「紅燈」。
 * 4. 專為台灣號誌與道路尺度特化：
 *    - 【兩線道小路適應 (Narrow 2-lane street, 6~12m)】：近距離大號誌（30~80px）多尺度自適應聚類。
 *    - 【多線道大馬路適應 (Wide avenue, 18~30m)】：遠距離小號誌（10~25px）靈敏捕捉。
 *    - 【空間幾何 Y 軸遮罩】：嚴格屏蔽畫面底部 28%（柏油路反光、汽車保險桿、機車煞車燈）。
 *    - 【黑色燈箱遮光罩對比驗證 (Black Housing Contrast)】：檢驗紅光/綠光周邊深色外框，徹底杜絕 7-11/屈臣氏大面積紅色招牌誤判。
 *    - 【台灣法規 1Hz 綠燈閃爍預警】：綠燈末期每秒 1 次規律脈衝跳動時，即時提示「小綠人閃爍，請勿穿越」。
 * 5. 【狀態鐵證自動快照留證 (Automated Snapshot Archiving)】：
 *    變燈瞬間自動儲存當下現場 JPEG 快照，打包進診斷包供事後 100% 驗證地面真值。
 * 6. 【螢幕喚醒保活 (FLAG_KEEP_SCREEN_ON)】：
 *    開鏡期間強制防休眠，杜絕 Activity 鎖屏被 Android 砍相機。
 */
class TrafficSignalCameraManager(
    private val context: Context,
    private val webAppInterface: WebAppInterface
) {
    companion object {
        private val cameraEventLogs = ArrayDeque<String>()
        private const val MAX_CAMERA_LOGS = 250
        private const val MAX_SNAPSHOT_FILES = 6

        fun recordCameraEvent(msg: String) {
            val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault()).format(Date())
            synchronized(cameraEventLogs) {
                cameraEventLogs.addLast("[$timeStr] $msg")
                if (cameraEventLogs.size > MAX_CAMERA_LOGS) cameraEventLogs.removeFirst()
            }
            Log.i("SignalCameraManager", msg)
        }

        fun getCameraEventLogs(): List<String> {
            synchronized(cameraEventLogs) {
                return cameraEventLogs.toList()
            }
        }

        /**
         * 取得診斷日誌所需之相機快照圖片清單 (供 WebAppInterface 打包進 .zip)
         */
        fun getSnapshotFiles(context: Context): List<File> {
            val dir = File(context.cacheDir, "camera_snapshots")
            if (!dir.exists()) return emptyList()
            return dir.listFiles { _, name -> name.endsWith(".jpg") }
                ?.sortedByDescending { it.lastModified() }
                ?.take(MAX_SNAPSHOT_FILES)
                ?: emptyList()
        }
    }

    private val tag = "SignalCameraManager"

    // 相機執行緒與狀態控制
    private var cameraExecutor: ExecutorService? = null
    private var cameraProvider: ProcessCameraProvider? = null
    private val isRunning = AtomicBoolean(false)

    // 相機快門與收鏡音效
    private val mediaActionSound = MediaActionSound()

    // 震動回饋器
    private val vibrator: Vibrator? by lazy {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val manager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
            manager?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
    }

    // 當前目標號誌參數
    private var targetBearingDeg: Double = 0.0
    private var targetClockPosition: String = "12點鐘方向"

    // 空間角度提示冷卻 (避免喋喋不休)
    private var lastDirectionPromptTimeMs = 0L
    private val DIRECTION_PROMPT_COOLDOWN_MS = 3500L

    // 方案 C 搜尋階段計時器
    private var cameraStartTimeMs = 0L
    private var lastSearchPromptTimeMs = 0L
    private val SEARCH_PROMPT_COOLDOWN_MS = 5000L

    // 幀分析日誌節流 (每 1.5 秒記錄一次以防日誌暴增)
    private var lastFrameLogTimeMs = 0L

    // 燈號重複播報冷卻
    private var lastAnnouncedState = SignalState.UNKNOWN
    private var lastAnnounceTimeMs = 0L
    private val RED_REMINDER_INTERVAL_MS = 8000L // 紅燈等候中每 8 秒提醒一次

    // 時序滑動窗口 (連續 3 幀確認才採納，杜絕瞬間反光誤判)
    private val recentStates = ArrayDeque<SignalState>()
    private val TEMPORAL_WINDOW_SIZE = 4
    private val CONFIRMATION_THRESHOLD = 3

    // 綠燈 1Hz 閃爍偵測滑動佇列 (記錄最近 2.5 秒內綠光有無之時序)
    private val greenHistory = ArrayDeque<Pair<Long, Boolean>>() // timestampMs -> isGreenVisible

    // TFLite 深度學習直譯器
    private var tfliteInterpreter: Interpreter? = null
    private var isTfliteLoaded = false

    // 號誌狀態列舉
    enum class SignalState {
        UNKNOWN,
        RED,            // 紅燈 / 小紅人 (停止等候)
        GREEN,          // 綠燈 / 小綠人 (安全通行)
        FLASHING_GREEN, // 小綠人閃爍 (通行即將結束，請勿踏入)
        YELLOW          // 黃燈 (即將變燈)
    }

    init {
        loadTfliteModel()
    }

    /**
     * 載入 TFLite 號誌分類模型 (traffic_light_cnn.tflite)
     */
    private fun loadTfliteModel() {
        try {
            val assetManager = context.assets
            val modelNames = listOf("models/traffic_light_cnn.tflite", "traffic_light_cnn.tflite")
            for (name in modelNames) {
                try {
                    val fileDescriptor = assetManager.openFd(name)
                    val inputStream = FileInputStream(fileDescriptor.fileDescriptor)
                    val fileChannel = inputStream.channel
                    val startOffset = fileDescriptor.startOffset
                    val declaredLength = fileDescriptor.declaredLength
                    val buffer = fileChannel.map(FileChannel.MapMode.READ_ONLY, startOffset, declaredLength)
                    tfliteInterpreter = Interpreter(buffer)
                    isTfliteLoaded = true
                    Log.i(tag, "TFLite traffic light model loaded successfully from $name.")
                    break
                } catch (e: Exception) {
                    // Try next name
                }
            }
        } catch (e: Exception) {
            Log.w(tag, "TFLite model load fallback to optical analysis: ${e.message}")
        }
    }

    /**
     * 【啟動相機開始辨識紅綠燈】
     * @param bearingDeg 前方號誌之地理真方位角 (0~360)
     * @param clockPosition 前方號誌之鐘點方向 (例如「12點鐘方向」)
     */
    fun startCamera(bearingDeg: Double, clockPosition: String) {
        if (isRunning.getAndSet(true)) {
            this.targetBearingDeg = bearingDeg
            this.targetClockPosition = clockPosition
            return
        }

        this.targetBearingDeg = bearingDeg
        this.targetClockPosition = clockPosition
        recentStates.clear()
        greenHistory.clear()
        val now = SystemClock.uptimeMillis()
        cameraStartTimeMs = now
        lastSearchPromptTimeMs = now

        // 1. 播放相機開鏡音效並提示「對街搜尋中」
        try {
            mediaActionSound.play(MediaActionSound.START_VIDEO_RECORDING)
        } catch (e: Exception) {
            Log.e(tag, "Failed to play camera start sound", e)
        }
        webAppInterface.speakTtsDirect("對街搜尋中", interrupt = false)
        recordCameraEvent("[CAMERA_START] 啟動紅綠燈相機 | 目標號誌方位: ${String.format(Locale.US, "%.1f", bearingDeg)}° ($clockPosition)")

        // 2. 螢幕常亮喚醒保活 (FLAG_KEEP_SCREEN_ON)：消滅 070815 的 1 秒休眠砍相機死角！
        val activity = context as? Activity
        activity?.runOnUiThread {
            try {
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                Log.i(tag, "[SCREEN_LOCK] 已設置 FLAG_KEEP_SCREEN_ON，相機運作期間防止自動休眠。")
            } catch (e: Exception) {
                Log.w(tag, "設置 FLAG_KEEP_SCREEN_ON 失敗", e)
            }
        }

        // 3. 初始化背景執行緒與 CameraX
        cameraExecutor = Executors.newSingleThreadExecutor()

        activity?.runOnUiThread {
            val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
            cameraProviderFuture.addListener({
                try {
                    cameraProvider = cameraProviderFuture.get()
                    bindImageAnalysis(activity as LifecycleOwner)
                } catch (e: Exception) {
                    Log.e(tag, "CameraProvider initialization failed", e)
                    isRunning.set(false)
                }
            }, ContextCompat.getMainExecutor(context))
        }
    }

    /**
     * 【關閉相機並釋放硬體資源】
     */
    fun stopCamera() {
        if (!isRunning.getAndSet(false)) return
        recordCameraEvent("[CAMERA_STOP] 關閉紅綠燈相機並釋放硬體資源")

        try {
            mediaActionSound.play(MediaActionSound.STOP_VIDEO_RECORDING)
        } catch (e: Exception) {
            Log.e(tag, "Failed to play camera stop sound", e)
        }

        // 釋放螢幕常亮鎖，恢復系統省電休眠機制
        val activity = context as? Activity
        activity?.runOnUiThread {
            try {
                activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                Log.i(tag, "[SCREEN_LOCK] 已清除 FLAG_KEEP_SCREEN_ON，恢復正常待機休眠。")
            } catch (e: Exception) {
                Log.w(tag, "清除 FLAG_KEEP_SCREEN_ON 失敗", e)
            }
            try {
                cameraProvider?.unbindAll()
            } catch (e: Exception) {
                Log.e(tag, "Error unbinding camera", e)
            }
        }

        cameraExecutor?.shutdown()
        cameraExecutor = null
        recentStates.clear()
        greenHistory.clear()
        lastAnnouncedState = SignalState.UNKNOWN
        Log.i(tag, "Traffic signal camera stopped and resources released.")
    }

    /**
     * 綁定 CameraX 影像分析管線 (ImageAnalysis)
     */
    private fun bindImageAnalysis(lifecycleOwner: LifecycleOwner) {
        val provider = cameraProvider ?: return
        provider.unbindAll()

        val imageAnalysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()

        imageAnalysis.setAnalyzer(cameraExecutor ?: return) { imageProxy ->
            processFrame(imageProxy)
        }

        val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA

        try {
            provider.bindToLifecycle(lifecycleOwner, cameraSelector, imageAnalysis)
            Log.i(tag, "CameraX ImageAnalysis bound successfully.")
        } catch (e: Exception) {
            Log.e(tag, "Use case binding failed", e)
        }
    }

    /**
     * 【影像幀即時分析管線】
     * 包含：手持姿態檢查 -> 空間 Y 軸遮罩 -> 兩線道/多線道自適應多尺度分析 -> 黑色遮光罩對比驗證 -> 狀態確認與存證
     */
    private fun processFrame(imageProxy: ImageProxy) {
        if (!isRunning.get()) {
            imageProxy.close()
            return
        }

        val now = SystemClock.uptimeMillis()

        // 1. 空間仰角導引 (俯仰角太低朝向地面 < -32°，提示稍抬起手機)
        val currentPitch = LocationSensorBridge.currentPitchDeg.toDouble()
        if (currentPitch < -32.0) {
            if (now - lastDirectionPromptTimeMs > DIRECTION_PROMPT_COOLDOWN_MS) {
                lastDirectionPromptTimeMs = now
                webAppInterface.speakTtsDirect("手機朝下，請稍抬起", interrupt = false)
                recordCameraEvent("[CAMERA_GUIDE] 手機俯仰角過低 (Pitch: ${String.format(Locale.US, "%.1f", currentPitch)}°)，語音提示稍抬起")
            }
            imageProxy.close()
            return
        }

        // 2. 階段性搜尋進度提示：若開鏡超過 3.5 秒仍未捕捉到確定號誌
        if (lastAnnouncedState == SignalState.UNKNOWN && now - cameraStartTimeMs > 3500L && now - lastSearchPromptTimeMs > SEARCH_PROMPT_COOLDOWN_MS) {
            lastSearchPromptTimeMs = now
            webAppInterface.speakTtsDirect("未見號誌，請左右微調", interrupt = false)
            recordCameraEvent("[CAMERA_SEARCH] 搜尋號誌逾 3.5 秒仍未定錨，提示左右微調")
        }

        // 3. 轉換為 Bitmap
        val bitmap = imageProxyToBitmap(imageProxy)
        imageProxy.close()
        if (bitmap == null) return

        // 4. 空間 ROI 幾何截取：
        // 水平中央 10%~90%，垂直 3%~72%（頂部天際線至中下部，底部 28% 嚴格屏蔽消滅車尾燈與柏油路）
        val w = bitmap.width
        val h = bitmap.height
        val roiLeft = (w * 0.10).toInt()
        val roiTop = (h * 0.03).toInt()
        val roiWidth = (w * 0.80).toInt()
        val roiHeight = (h * 0.69).toInt() // 底部保留 28% 為地面遮蔽區

        val roiBitmap = try {
            Bitmap.createBitmap(bitmap, roiLeft, roiTop, roiWidth, roiHeight)
        } catch (e: Exception) {
            bitmap
        }

        // 5. 執行自適應光學與黑色燈箱對比度分析
        val opticalResult = classifyWithAdaptivePhotometricAnalysis(roiBitmap, now)
        var detectedState = opticalResult.state

        // 若有 TFLite 模型，作為雙重交叉驗證
        if (isTfliteLoaded && tfliteInterpreter != null && detectedState != SignalState.UNKNOWN) {
            val tfliteScore = runTfliteInference(roiBitmap)
            if (detectedState == SignalState.RED && tfliteScore < 0.35f) {
                // TFLite 強烈反對紅色，降級為 UNKNOWN
                detectedState = SignalState.UNKNOWN
            } else if (detectedState == SignalState.GREEN && tfliteScore > 0.65f) {
                detectedState = SignalState.UNKNOWN
            }
        }

        if (now - lastFrameLogTimeMs > 1500L) {
            lastFrameLogTimeMs = now
            val methodStr = if (isTfliteLoaded && tfliteInterpreter != null) "TFLite+光學雙檢" else "自適應幾何黑框光學"
            recordCameraEvent("[CAMERA_FRAME] 姿態 Pitch=${String.format(Locale.US, "%.1f", currentPitch)}° | 核心: $methodStr | 即時辨識: $detectedState (${opticalResult.details})")
        }

        if (roiBitmap != bitmap) {
            roiBitmap.recycle()
        }

        // 6. 時序防抖確認、語音播報、震動回饋與【自動截圖存證】
        updateTemporalState(detectedState, now, bitmap, opticalResult.details)
        bitmap.recycle()
    }

    /**
     * 號誌光學偵測內部結果資料結構
     */
    private data class OpticalResult(
        val state: SignalState,
        val details: String,
        val isFlashing: Boolean = false
    )

    /**
     * 【兩線道小路與多線道自適應多尺度光學防偽引擎】
     * 核心邏輯：
     * 1. 兩線道小路（6~12m）：號誌近身成像大（30~80px），聚類跨越多個網格，放寬上限。
     * 2. 多線道大馬路（18~30m）：號誌遠程成像小（10~25px），靈敏捕捉單點聚類。
     * 3. 黑色遮光罩外框對比度檢驗 (Black Housing Contrast)：
     *    號誌發光核心四周必有黑色燈箱遮光罩（亮度低）。整片紅色的廣告招牌四周也是亮色，直接被高對比度門檻剔除！
     * 4. 1Hz 綠燈閃爍脈衝檢測（台灣法規綠燈即將結束預警）。
     */
    private fun classifyWithAdaptivePhotometricAnalysis(bitmap: Bitmap, nowMs: Long): OpticalResult {
        val w = bitmap.width
        val h = bitmap.height

        // 網格劃分：將 ROI 分割為 16x12 的微型分析區塊 (Grid Cells)
        val numCols = 16
        val numRows = 12
        val cellW = w / numCols
        val cellH = h / numRows

        // 矩陣統計每個 Cell 的特徵
        val redScores = Array(numRows) { IntArray(numCols) }
        val greenScores = Array(numRows) { IntArray(numCols) }
        val cellBrightness = Array(numRows) { IntArray(numCols) }

        val step = 3 // 步長下取樣

        for (r in 0 until numRows) {
            for (c in 0 until numCols) {
                var cellRCount = 0
                var cellGCount = 0
                var totalBri = 0L
                var sampleCount = 0

                val startX = c * cellW
                val startY = r * cellH

                for (y in startY until (startY + cellH) step step) {
                    for (x in startX until (startX + cellW) step step) {
                        if (x >= w || y >= h) continue
                        val p = bitmap.getPixel(x, y)
                        val red = Color.red(p)
                        val green = Color.green(p)
                        val blue = Color.blue(p)

                        val bri = (red * 299 + green * 587 + blue * 114) / 1000
                        totalBri += bri
                        sampleCount++

                        // 台灣小紅人發光特徵 (高純度 625nm 紅光 LED，以 R 為主導，不設 Y 加權限制以防飽和紅光被誤殺)
                        if (red >= 150 && red > green * 1.45 && red > blue * 1.45) {
                            cellRCount++
                        }
                        // 台灣小綠人發光特徵 (505nm 翠綠光 LED)
                        else if (green >= 135 && green > red * 1.30 && blue < green * 1.15) {
                            cellGCount++
                        }
                    }
                }

                redScores[r][c] = cellRCount
                greenScores[r][c] = cellGCount
                cellBrightness[r][c] = if (sampleCount > 0) (totalBri / sampleCount).toInt() else 0
            }
        }

        // 連通塊聚類分析 (Connected Component Clustering for 2-Lane vs Wide Avenue)
        data class SignalCluster(
            val cells: List<Pair<Int, Int>>,
            val totalScore: Int,
            val widthCells: Int,
            val heightCells: Int
        )

        fun findClusters(matrix: Array<IntArray>, minScore: Int): List<SignalCluster> {
            val visited = Array(numRows) { BooleanArray(numCols) }
            val clusters = mutableListOf<SignalCluster>()
            for (r in 0 until numRows) {
                for (c in 0 until numCols) {
                    if (matrix[r][c] >= minScore && !visited[r][c]) {
                        val cells = mutableListOf<Pair<Int, Int>>()
                        val queue = ArrayDeque<Pair<Int, Int>>()
                        queue.add(Pair(r, c))
                        visited[r][c] = true
                        var totalScore = 0

                        while (queue.isNotEmpty()) {
                            val curr = queue.removeFirst()
                            cells.add(curr)
                            totalScore += matrix[curr.first][curr.second]

                            val neighbors = listOf(
                                Pair(curr.first - 1, curr.second),
                                Pair(curr.first + 1, curr.second),
                                Pair(curr.first, curr.second - 1),
                                Pair(curr.first, curr.second + 1)
                            )
                            for (n in neighbors) {
                                if (n.first in 0 until numRows && n.second in 0 until numCols) {
                                    if (matrix[n.first][n.second] >= minScore && !visited[n.first][n.second]) {
                                        visited[n.first][n.second] = true
                                        queue.add(n)
                                    }
                                }
                            }
                        }

                        val minR = cells.minOf { it.first }
                        val maxR = cells.maxOf { it.first }
                        val minC = cells.minOf { it.second }
                        val maxC = cells.maxOf { it.second }
                        clusters.add(SignalCluster(cells, totalScore, maxC - minC + 1, maxR - minR + 1))
                    }
                }
            }
            return clusters
        }

        val redClusters = findClusters(redScores, minScore = 4)
        val greenClusters = findClusters(greenScores, minScore = 4)

        val bestRed = redClusters.maxByOrNull { it.totalScore }
        val bestGreen = greenClusters.maxByOrNull { it.totalScore }

        fun checkClusterHousing(cluster: SignalCluster): Boolean {
            // 1. 尺寸過濾：跨越超過 3x3 網格（> 100px）者為大面積看板/招牌，非行人號誌
            if (cluster.widthCells > 3 || cluster.heightCells > 4) {
                return false
            }

            // 2. 外圍深色燈箱遮光罩檢驗 (Dark Housing Perimeter)
            val clusterSet = cluster.cells.toSet()
            val minR = cluster.cells.minOf { it.first }
            val maxR = cluster.cells.maxOf { it.first }
            val minC = cluster.cells.minOf { it.second }
            val maxC = cluster.cells.maxOf { it.second }

            var surroundBriSum = 0
            var surroundCount = 0

            val rStart = (minR - 1).coerceAtLeast(0)
            val rEnd = (maxR + 1).coerceAtMost(numRows - 1)
            val cStart = (minC - 1).coerceAtLeast(0)
            val cEnd = (maxC + 1).coerceAtMost(numCols - 1)

            for (r in rStart..rEnd) {
                for (c in cStart..cEnd) {
                    if (!clusterSet.contains(Pair(r, c))) {
                        surroundBriSum += cellBrightness[r][c]
                        surroundCount++
                    }
                }
            }

            if (surroundCount == 0) return true
            val avgSurroundBri = surroundBriSum / surroundCount
            val coreBri = cluster.cells.map { cellBrightness[it.first][it.second] }.average()
            val contrast = coreBri - avgSurroundBri

            // 號誌燈箱遮光罩外框亮度低 (< 115) 或有高對比 (>= 25)
            return avgSurroundBri < 115 || contrast >= 25.0
        }

        val redScore = bestRed?.totalScore ?: 0
        val greenScore = bestGreen?.totalScore ?: 0

        // 1. 檢驗紅燈判定
        if (bestRed != null && redScore > greenScore) {
            if (checkClusterHousing(bestRed)) {
                val isNarrow = bestRed.totalScore >= 50 || bestRed.widthCells >= 3 || bestRed.heightCells >= 3
                val roadDesc = if (isNarrow) "近距/兩線道大號誌" else "遠距/標準號誌"
                return OpticalResult(SignalState.RED, "$roadDesc(紅燈評分=$redScore)")
            } else {
                recordCameraEvent("[CAMERA_REJECT] 濾除無遮光黑框或過大之發光物 (疑似廣告看板/車牌)")
            }
        }

        // 2. 檢驗綠燈判定與 1Hz 閃爍偵測
        if (bestGreen != null && greenScore > redScore) {
            if (checkClusterHousing(bestGreen)) {
                val isGreenNow = true
                greenHistory.addLast(Pair(nowMs, isGreenNow))

                // 維護 2.5 秒滑動窗口
                while (greenHistory.isNotEmpty() && nowMs - greenHistory.first().first > 2500L) {
                    greenHistory.removeFirst()
                }

                // 檢驗最近 2 秒內是否發生 1Hz 亮暗交替 (綠燈閃爍)
                var transitions = 0
                var lastState = greenHistory.first().second
                for (i in 1 until greenHistory.size) {
                    val st = greenHistory.elementAt(i).second
                    if (st != lastState) {
                        transitions++
                        lastState = st
                    }
                }

                val isFlashing = transitions >= 3 // 在 2 秒內有多次亮暗跳變
                val isNarrow = bestGreen.totalScore >= 50 || bestGreen.widthCells >= 3 || bestGreen.heightCells >= 3
                val roadDesc = if (isNarrow) "近距/兩線道小綠人" else "遠距小綠人"

                return if (isFlashing) {
                    OpticalResult(SignalState.FLASHING_GREEN, "$roadDesc(1Hz閃爍中, 變更數=$transitions)", isFlashing = true)
                } else {
                    OpticalResult(SignalState.GREEN, "$roadDesc(通行綠燈, 評分=$greenScore)")
                }
            } else {
                recordCameraEvent("[CAMERA_REJECT] 濾除無遮光黑框之大面積綠光物")
            }
        }

        // 無號誌時記錄暗態
        greenHistory.addLast(Pair(nowMs, false))
        while (greenHistory.isNotEmpty() && nowMs - greenHistory.first().first > 2500L) {
            greenHistory.removeFirst()
        }

        return OpticalResult(SignalState.UNKNOWN, "未定錨")
    }

    /**
     * TFLite 輕量模型推理
     */
    private fun runTfliteInference(bitmap: Bitmap): Float {
        val interpreter = tfliteInterpreter ?: return 0.5f
        return try {
            val scaled = Bitmap.createScaledBitmap(bitmap, 64, 64, true)
            val inputBuffer = ByteBuffer.allocateDirect(64 * 64 * 3 * 4).apply {
                order(ByteOrder.nativeOrder())
                for (y in 0 until 64) {
                    for (x in 0 until 64) {
                        val p = scaled.getPixel(x, y)
                        putFloat(Color.red(p) / 255.0f)
                        putFloat(Color.green(p) / 255.0f)
                        putFloat(Color.blue(p) / 255.0f)
                    }
                }
            }
            scaled.recycle()

            val outputBuffer = ByteBuffer.allocateDirect(4).apply {
                order(ByteOrder.nativeOrder())
            }
            interpreter.run(inputBuffer, outputBuffer)
            outputBuffer.rewind()
            outputBuffer.float
        } catch (e: Exception) {
            0.5f
        }
    }

    /**
     * 【時序狀態更新、防抖語音插播與自動截圖存證】
     */
    private fun updateTemporalState(state: SignalState, now: Long, sourceBitmap: Bitmap, details: String) {
        if (state == SignalState.UNKNOWN) return

        recentStates.addLast(state)
        if (recentStates.size > TEMPORAL_WINDOW_SIZE) {
            recentStates.removeFirst()
        }

        val greenCount = recentStates.count { it == SignalState.GREEN }
        val flashingCount = recentStates.count { it == SignalState.FLASHING_GREEN }
        val redCount = recentStates.count { it == SignalState.RED }
        val yellowCount = recentStates.count { it == SignalState.YELLOW }

        val confirmedState = when {
            flashingCount >= 2 -> SignalState.FLASHING_GREEN
            greenCount >= CONFIRMATION_THRESHOLD -> SignalState.GREEN
            redCount >= CONFIRMATION_THRESHOLD -> SignalState.RED
            yellowCount >= CONFIRMATION_THRESHOLD -> SignalState.YELLOW
            else -> return
        }

        val isStateChanged = confirmedState != lastAnnouncedState

        if (isStateChanged) {
            lastAnnouncedState = confirmedState
            lastAnnounceTimeMs = now
            recordCameraEvent("[CAMERA_STATE_CHANGE] 燈號時序防抖確認為: $confirmedState (綠:$greenCount, 閃綠:$flashingCount, 紅:$redCount, 黃:$yellowCount) | $details -> 觸發存圖與播報")

            // 1. 【自動截圖存證】：留存當下地面真值照片至 snapshots/ 目錄！
            saveSnapshot(sourceBitmap, confirmedState, details)

            // 2. 語音播報與震動
            when (confirmedState) {
                SignalState.GREEN -> {
                    webAppInterface.speakTtsDirect("小綠人，可通行！", interrupt = true)
                    triggerDoubleVibrate()
                }
                SignalState.FLASHING_GREEN -> {
                    webAppInterface.speakTtsDirect("小綠人閃爍，請勿穿越！", interrupt = true)
                    triggerRapidVibrate()
                }
                SignalState.RED -> {
                    webAppInterface.speakTtsDirect("紅燈，請等候", interrupt = true)
                    triggerLongVibrate()
                }
                SignalState.YELLOW -> {
                    webAppInterface.speakTtsDirect("黃燈，即將變燈", interrupt = true)
                }
                else -> {}
            }
        } else {
            // 同一紅燈狀態持續中的週期性提醒
            if (confirmedState == SignalState.RED && now - lastAnnounceTimeMs > RED_REMINDER_INTERVAL_MS) {
                lastAnnounceTimeMs = now
                webAppInterface.speakTtsDirect("紅燈", interrupt = false)
            }
        }
    }

    /**
     * 【儲存號誌現場真值快照 (Save Diagnostic Snapshot)】
     * 作用：當相機辨識出紅綠燈的瞬間，自動將現場畫面加上狀態標記存為 JPEG，
     * 徹底消滅黑盒子猜測，讓視障者與工程師事後解壓縮 zip 就能 100% 查證照片！
     */
    private fun saveSnapshot(sourceBitmap: Bitmap, state: SignalState, details: String) {
        try {
            val dir = File(context.cacheDir, "camera_snapshots")
            if (!dir.exists()) dir.mkdirs()

            // 維護數量上限，清除舊檔只保留最新 MAX_SNAPSHOT_FILES 張
            val existing = dir.listFiles { _, name -> name.endsWith(".jpg") }
            if (existing != null && existing.size >= MAX_SNAPSHOT_FILES) {
                existing.sortedBy { it.lastModified() }
                    .take(existing.size - (MAX_SNAPSHOT_FILES - 1))
                    .forEach { it.delete() }
            }

            val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.getDefault()).format(Date())
            val file = File(dir, "SIGNAL_${state.name}_${timeStamp}.jpg")

            // 複製 Bitmap 並繪製診斷浮水印
            val mutableBitmap = sourceBitmap.copy(Bitmap.Config.ARGB_8888, true)
            val canvas = Canvas(mutableBitmap)

            val paint = Paint().apply {
                color = when (state) {
                    SignalState.GREEN, SignalState.FLASHING_GREEN -> Color.GREEN
                    SignalState.RED -> Color.RED
                    SignalState.YELLOW -> Color.YELLOW
                    else -> Color.WHITE
                }
                textSize = (mutableBitmap.height * 0.045f).coerceAtLeast(22f)
                isAntiAlias = true
                isFakeBoldText = true
                setShadowLayer(5f, 2f, 2f, Color.BLACK)
            }

            val bgPaint = Paint().apply {
                color = Color.argb(170, 0, 0, 0)
                style = Paint.Style.FILL
            }

            val bannerH = paint.textSize * 2.4f
            canvas.drawRect(0f, 0f, mutableBitmap.width.toFloat(), bannerH, bgPaint)
            val labelText = "NMap [${state.name}] $details"
            canvas.drawText(labelText, 20f, paint.textSize * 1.5f, paint)

            FileOutputStream(file).use { fos ->
                mutableBitmap.compress(Bitmap.CompressFormat.JPEG, 85, fos)
            }
            mutableBitmap.recycle()
            recordCameraEvent("[CAMERA_SNAPSHOT] 成功儲存現場號誌照片: ${file.name} (${file.length()} bytes)")
        } catch (e: Exception) {
            Log.w(tag, "儲存相機快照失敗: ${e.message}")
        }
    }

    /**
     * 將 CameraX ImageProxy 轉為 Bitmap
     */
    private fun imageProxyToBitmap(image: ImageProxy): Bitmap? {
        return try {
            val planes = image.planes
            val yBuffer = planes[0].buffer
            val uBuffer = planes[1].buffer
            val vBuffer = planes[2].buffer

            val ySize = yBuffer.remaining()
            val uSize = uBuffer.remaining()
            val vSize = vBuffer.remaining()

            val nv21 = ByteArray(ySize + uSize + vSize)
            yBuffer.get(nv21, 0, ySize)
            vBuffer.get(nv21, ySize, vSize)
            uBuffer.get(nv21, ySize + vSize, uSize)

            val yuvImage = android.graphics.YuvImage(nv21, android.graphics.ImageFormat.NV21, image.width, image.height, null)
            val out = java.io.ByteArrayOutputStream()
            yuvImage.compressToJpeg(android.graphics.Rect(0, 0, image.width, image.height), 85, out)
            val imageBytes = out.toByteArray()
            android.graphics.BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
        } catch (e: Exception) {
            Log.w(tag, "imageProxyToBitmap conversion error: ${e.message}")
            null
        }
    }

    /**
     * 清脆連續兩次短震動 (小綠人通行)
     */
    private fun triggerDoubleVibrate() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 100, 70, 120), -1))
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(longArrayOf(0, 100, 70, 120), -1)
        }
    }

    /**
     * 急促警示短震動 (小綠人閃爍)
     */
    private fun triggerRapidVibrate() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 60, 50, 60, 50, 60), -1))
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(longArrayOf(0, 60, 50, 60, 50, 60), -1)
        }
    }

    /**
     * 沉穩單次長震動 (紅燈等候)
     */
    private fun triggerLongVibrate() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(VibrationEffect.createOneShot(350, VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(350)
        }
    }
}
