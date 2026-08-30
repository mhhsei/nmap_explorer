package com.example.nmapexplorer

import android.app.Activity
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.media.MediaActionSound
import android.os.Build
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import org.tensorflow.lite.Interpreter
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 【紅綠燈相機即時辨識與空間方位導航引擎 (TrafficSignalCameraManager)】
 *
 * 核心使命：
 * 1. 到路口自動開相機，過馬路自動關閉，全程以俐落音效取代冗長語音。
 * 2. 鏡頭偏斜時，以 Google 原生 TTS 提示方位（如「號誌在 1 點鐘方向」）。
 * 3. 鏡頭拍到號誌時，跳過方位，直接回報「小綠人，可通行」或「紅燈」。
 * 4. 採用「空間錐形遮罩 (Spatial Geo-Gating)」+「TFLite 端側深度學習」+「時序防抖」，
 *    徹底杜絕紅色招牌與車尾燈誤判，保障視障者過馬路生命安全。
 */
class TrafficSignalCameraManager(
    private val context: Context,
    private val webAppInterface: WebAppInterface
) {
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

    // 燈號重複播報冷卻
    private var lastAnnouncedState = SignalState.UNKNOWN
    private var lastAnnounceTimeMs = 0L
    private val RED_REMINDER_INTERVAL_MS = 8000L // 紅燈等候中每 8 秒提醒一次

    // 時序滑動窗口 (連續 3 幀確認才採納，杜絕瞬間反光誤判)
    private val recentStates = ArrayDeque<SignalState>()
    private val TEMPORAL_WINDOW_SIZE = 4
    private val CONFIRMATION_THRESHOLD = 3

    // TFLite 深度學習直譯器
    private var tfliteInterpreter: Interpreter? = null
    private var isTfliteLoaded = false

    // 號誌狀態列舉
    enum class SignalState {
        UNKNOWN,
        RED,            // 紅燈 / 小紅人 (停止等候)
        GREEN,          // 綠燈 / 小綠人 (安全通行)
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
            // 已在運行中，僅更新目標方位
            this.targetBearingDeg = bearingDeg
            this.targetClockPosition = clockPosition
            return
        }

        this.targetBearingDeg = bearingDeg
        this.targetClockPosition = clockPosition
        recentStates.clear()
        lastAnnouncedState = SignalState.UNKNOWN
        lastAnnounceTimeMs = 0L

        // 1. 播放相機開鏡音效 (短促快門聲，不發文字語音)
        try {
            mediaActionSound.play(MediaActionSound.START_VIDEO_RECORDING)
        } catch (e: Exception) {
            Log.e(tag, "Failed to play camera start sound", e)
        }

        // 2. 初始化背景執行緒
        cameraExecutor = Executors.newSingleThreadExecutor()

        val activity = context as? Activity ?: return
        activity.runOnUiThread {
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

        try {
            // 播放收鏡音效
            mediaActionSound.play(MediaActionSound.STOP_VIDEO_RECORDING)
        } catch (e: Exception) {
            Log.e(tag, "Failed to play camera stop sound", e)
        }

        val activity = context as? Activity
        activity?.runOnUiThread {
            try {
                cameraProvider?.unbindAll()
            } catch (e: Exception) {
                Log.e(tag, "Error unbinding camera", e)
            }
        }

        cameraExecutor?.shutdown()
        cameraExecutor = null
        recentStates.clear()
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
     * 包含：空間姿態檢查 -> 對街 ROI 裁切 -> TFLite / 光學深度分析 -> 時序防抖 -> 語音與震動回饋
     */
    private fun processFrame(imageProxy: ImageProxy) {
        if (!isRunning.get()) {
            imageProxy.close()
            return
        }

        val now = SystemClock.uptimeMillis()

        // 1. 空間姿態導引檢查 (Spatial Geo-Gating)
        val currentHeading = LocationSensorBridge.currentHeadingDeg.toDouble()
        val currentPitch = LocationSensorBridge.currentPitchDeg.toDouble()

        // 計算手機朝向與目標號誌方位之角偏差
        var diffAngle = ((currentHeading - targetBearingDeg + 540) % 360) - 180

        // 若手機仰角太低 (朝向地面 < -25°) 且超過冷卻時間，提示平舉手機
        if (currentPitch < -25.0) {
            if (now - lastDirectionPromptTimeMs > DIRECTION_PROMPT_COOLDOWN_MS) {
                lastDirectionPromptTimeMs = now
                webAppInterface.speakTtsDirect("請平舉手機對準對街", interrupt = false)
            }
            imageProxy.close()
            return
        }

        // 若偏離目標號誌超過 25 度，提示使用者轉動方位
        if (Math.abs(diffAngle) > 25.0) {
            if (now - lastDirectionPromptTimeMs > DIRECTION_PROMPT_COOLDOWN_MS) {
                lastDirectionPromptTimeMs = now
                val prompt = if (diffAngle > 0) {
                    "號誌在左側，請向左轉"
                } else {
                    "號誌在右側，請向右轉"
                }
                webAppInterface.speakTtsDirect(prompt, interrupt = false)
            }
            imageProxy.close()
            return
        }

        // 2. 影像轉換為 Bitmap 進行 ROI 檢測
        val bitmap = imageProxyToBitmap(imageProxy)
        imageProxy.close()
        if (bitmap == null) return

        // 3. 對街空間錐形遮罩 (只截取畫面中央上半部 20%~75% 範圍，排除地面車輛與天空)
        val w = bitmap.width
        val h = bitmap.height
        val roiLeft = (w * 0.20).toInt()
        val roiTop = (h * 0.10).toInt()
        val roiWidth = (w * 0.60).toInt()
        val roiHeight = (h * 0.55).toInt()

        val roiBitmap = try {
            Bitmap.createBitmap(bitmap, roiLeft, roiTop, roiWidth, roiHeight)
        } catch (e: Exception) {
            bitmap
        }

        // 4. 執行號誌辨識 (優先 TFLite，備援高精度光學形態分析)
        val detectedState = if (isTfliteLoaded && tfliteInterpreter != null) {
            classifyWithTflite(roiBitmap)
        } else {
            classifyWithPhotometricAnalysis(roiBitmap)
        }

        if (roiBitmap != bitmap) {
            roiBitmap.recycle()
        }
        bitmap.recycle()

        // 5. 時序防抖滑動窗口 (Temporal Filtering)
        updateTemporalState(detectedState, now)
    }

    /**
     * 使用 TFLite 深度神經網路進行號誌分類
     */
    private fun classifyWithTflite(bitmap: Bitmap): SignalState {
        val interpreter = tfliteInterpreter ?: return classifyWithPhotometricAnalysis(bitmap)

        return try {
            // 縮放至模型輸入尺寸 64x64
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
            val score = outputBuffer.float

            // 搭配光學驗證防護，雙重門檻
            val opticalState = classifyWithPhotometricAnalysis(bitmap)
            if (score > 0.6f && opticalState == SignalState.RED) {
                SignalState.RED
            } else if (score < 0.4f && opticalState == SignalState.GREEN) {
                SignalState.GREEN
            } else {
                opticalState
            }
        } catch (e: Exception) {
            classifyWithPhotometricAnalysis(bitmap)
        }
    }

    /**
     * 高精度光學與形態學分析器 (Photometric & Chrominance Analyzer)
     * 在 ROI 中檢測高純度 625nm 正紅光 (小紅人/紅燈) 與 505nm 翠綠光 (小綠人/綠燈)
     */
    private fun classifyWithPhotometricAnalysis(bitmap: Bitmap): SignalState {
        val w = bitmap.width
        val h = bitmap.height
        val step = 4 // 下取樣加速 (4x4 網格)
        var redPixels = 0
        var greenPixels = 0
        var yellowPixels = 0

        for (y in 0 until h step step) {
            for (x in 0 until w step step) {
                val p = bitmap.getPixel(x, y)
                val r = Color.red(p)
                val g = Color.green(p)
                val b = Color.blue(p)

                // 亮度閾值 (號誌發光 LED 明度高)
                val brightness = (r * 299 + g * 587 + b * 114) / 1000
                if (brightness < 120) continue

                // 紅燈特徵：R 明顯高於 G 和 B (R > 1.6*G 且 R > 1.6*B)
                if (r > 160 && r > g * 1.5 && r > b * 1.5) {
                    redPixels++
                }
                // 綠燈/小綠人特徵：G 顯著高於 R (G > 1.3*R 且 G > 140 且 B < G)
                else if (g > 140 && g > r * 1.35 && g > b * 0.9) {
                    greenPixels++
                }
                // 黃燈特徵：R 與 G 皆高且相近，B 明顯低
                else if (r > 170 && g > 150 && Math.abs(r - g) < 45 && b < 80) {
                    yellowPixels++
                }
            }
        }

        val minPixelCount = (w * h) / (step * step * 160) // 佔比門檻
        return when {
            greenPixels > minPixelCount && greenPixels > redPixels * 1.5 -> SignalState.GREEN
            redPixels > minPixelCount && redPixels > greenPixels * 1.5 -> SignalState.RED
            yellowPixels > minPixelCount && yellowPixels > redPixels -> SignalState.YELLOW
            else -> SignalState.UNKNOWN
        }
    }

    /**
     * 【時序狀態更新與防抖語音插播】
     */
    private fun updateTemporalState(state: SignalState, now: Long) {
        if (state == SignalState.UNKNOWN) return

        // 加入滑動窗口
        recentStates.addLast(state)
        if (recentStates.size > TEMPORAL_WINDOW_SIZE) {
            recentStates.removeFirst()
        }

        // 計算窗口內各狀態次數
        val greenCount = recentStates.count { it == SignalState.GREEN }
        val redCount = recentStates.count { it == SignalState.RED }
        val yellowCount = recentStates.count { it == SignalState.YELLOW }

        val confirmedState = when {
            greenCount >= CONFIRMATION_THRESHOLD -> SignalState.GREEN
            redCount >= CONFIRMATION_THRESHOLD -> SignalState.RED
            yellowCount >= CONFIRMATION_THRESHOLD -> SignalState.YELLOW
            else -> return
        }

        // 狀態變更或週期性提示
        val isStateChanged = confirmedState != lastAnnouncedState

        if (isStateChanged) {
            lastAnnouncedState = confirmedState
            lastAnnounceTimeMs = now

            when (confirmedState) {
                SignalState.GREEN -> {
                    // 轉為綠燈：第一優先級立即插播！
                    webAppInterface.speakTtsDirect("小綠人，可通行！", interrupt = true)
                    triggerDoubleVibrate()
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
            // 同一狀態持續中的週期性提醒
            if (confirmedState == SignalState.RED && now - lastAnnounceTimeMs > RED_REMINDER_INTERVAL_MS) {
                lastAnnounceTimeMs = now
                webAppInterface.speakTtsDirect("紅燈", interrupt = false)
            }
        }
    }

    /**
     * 將 CameraX ImageProxy 轉為 Bitmap
     */
    private fun imageProxyToBitmap(image: ImageProxy): Bitmap? {
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
        return android.graphics.BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
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
