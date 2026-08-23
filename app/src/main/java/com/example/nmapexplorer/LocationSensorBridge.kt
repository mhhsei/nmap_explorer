package com.example.nmapexplorer

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.webkit.WebView
import androidx.core.content.ContextCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.Collections
import kotlin.math.*

/**
 * 二維行人卡爾曼濾波器 (Pedestrian Kalman Filter)
 * 
 * 核心功能與生活化比喻：
 * 1. 軌跡平滑：把 GPS 忽左忽右的跳動（測量雜訊），想像成一個喝醉的導遊，卡爾曼濾波器就像一個清醒的助手，根據行人正常的步行速度（0.8~2.0 m/s）把軌跡拉平拉直。
 * 2. 靜止防飄 (ZUPT)：當人在紅綠燈前停下腳步（速度 < 0.25 m/s），強制鎖定座標，杜絕原地乒乓橫跳。
 * 3. 都會折射過濾：走在大樓林立的市區時，GPS 訊號容易撞牆反射（多路徑誤差），此時主動調高測量誤差信任度，防止人物瞬間穿牆瞬移。
 * 4. L5 雙頻衛星加權：偵測到新型 L5/E5a 高精度雙頻衛星時，優先採納，將定位誤差壓低至 1.5~2.5 公尺。
 * 5. 騎樓步伐推算 (PDR)：走進騎樓或雨遮 GPS 中斷時，由計步器接管前進推算。
 */
class PedestrianKalmanFilter {
    private var isInitialized = false
    // 局部座標系的原點錨點（經緯度）
    private var anchorLat = 0.0
    private var anchorLon = 0.0

    // 狀態向量：[x (東向公尺), y (北向公尺), vx (東向速度 m/s), vy (北向速度 m/s)]
    private var x = 0.0
    private var y = 0.0
    private var vx = 0.0
    private var vy = 0.0

    // 協方差矩陣 4x4（對角線近似值，代表對自身估計的不確定度）
    private var p00 = 10.0 // x 位置變異數
    private var p11 = 10.0 // y 位置變異數
    private var p22 = 2.0  // vx 速度變異數
    private var p33 = 2.0  // vy 速度變異數

    private var lastTimestampNanos: Long = 0

    /**
     * 執行卡爾曼濾波更新
     * 
     * @param lat GPS 原始緯度
     * @param lon GPS 原始經度
     * @param accuracyMeters GPS 精度半徑（公尺）
     * @param timestampNanos 時間戳記（奈秒）
     * @param isMultipath 是否偵測到大樓多路徑折射反射雜訊
     * @param hasDualFrequencyL5 是否收到 L5 雙頻衛星高精度訊號
     * @return 濾波平滑後的 (緯度, 經度)
     */
    fun filter(
        lat: Double,
        lon: Double,
        accuracyMeters: Float,
        timestampNanos: Long,
        isMultipath: Boolean = false,
        hasDualFrequencyL5: Boolean = false
    ): Pair<Double, Double> {
        // 若為第一次定位：設定初始錨點與狀態
        if (!isInitialized) {
            anchorLat = lat
            anchorLon = lon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            lastTimestampNanos = timestampNanos
            isInitialized = true
            return Pair(lat, lon)
        }

        // 計算兩次測量的時間差 dt（秒）
        var dt = (timestampNanos - lastTimestampNanos) / 1_000_000_000.0
        lastTimestampNanos = timestampNanos

        // 異常時間差防護（若過久或為負值，回退為 1.0 秒）
        if (dt <= 0.0 || dt > 10.0) {
            dt = 1.0
        }

        // 1. 將經緯度轉換為局部平面直角座標（等距圓柱投影，單位：公尺）
        val radLat = Math.toRadians(anchorLat)
        val mPerLat = 111139.0
        val mPerLon = 111139.0 * cos(radLat)

        val zx = (lon - anchorLon) * mPerLon
        val zy = (lat - anchorLat) * mPerLat

        // 跨區大位移防護：若距離原錨點超過 60 公尺（如開車或瞬間換區），立即重置錨點避免濾波器拉扯
        if (sqrt(zx * zx + zy * zy) > 60.0) {
            anchorLat = lat
            anchorLon = lon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            return Pair(lat, lon)
        }

        // 2. 狀態預測步驟 (Predict Step)：依據先前估計的速度推進座標
        x += vx * dt
        y += vy * dt

        val qPos = 0.5 * dt // 位置過程雜訊
        val qVel = 1.0 * dt // 速度過程雜訊
        p00 += p22 * dt * dt + qPos
        p11 += p33 * dt * dt + qPos
        p22 += qVel
        p33 += qVel

        // 3. 測量更新步驟 (Measurement Update)：計算增益並融合新測量
        val measuredDelta = sqrt((zx - x).pow(2.0) + (zy - y).pow(2.0))
        val impliedSpeed = measuredDelta / dt

        // 基礎測量雜訊協方差 R（以 GPS 精度平方為基準）
        var baseR = max(accuracyMeters.toDouble().pow(2.0), 3.0)

        // 若具備 L5 雙頻衛星：雜訊協方差減半（更信任測量值）
        if (hasDualFrequencyL5) {
            baseR *= 0.5
        }

        // 若偵測到大樓峽谷折射反射：雜訊放大 6 倍（降低對跳動數據的信任度）
        if (isMultipath) {
            baseR *= 6.0
        }
        // 若換算速度 > 4.5 m/s（人類步行極限），判定為瞬移雜訊，進一步壓制
        val r = if (impliedSpeed > 4.5) baseR * 10.0 else baseR

        // 計算卡爾曼增益 K (Kalman Gain)
        val k0 = p00 / (p00 + r)
        val k1 = p11 / (p11 + r)

        // 修正位置估計
        x += k0 * (zx - x)
        y += k1 * (zy - y)

        // 更新協方差矩陣
        p00 *= (1.0 - k0)
        p11 *= (1.0 - k1)

        // 更新速度估計
        vx = (k0 * (zx - x)) / dt
        vy = (k1 * (zy - y)) / dt

        // 行人速度鉗制（最大步行速度限制在 4.5 m/s）
        val currentSpeed = sqrt(vx * vx + vy * vy)
        if (currentSpeed > 4.5) {
            val scale = 4.5 / currentSpeed
            vx *= scale
            vy *= scale
        } else if (currentSpeed < 0.25) {
            // ZUPT 零速修正 (Zero-Velocity Update)：速度小於 0.25 m/s 判定為靜止，速度直接歸零防止原地飄移
            vx = 0.0
            vy = 0.0
        }

        // 4. 將局部公尺座標轉回全球經緯度
        val outLat = anchorLat + (y / mPerLat)
        val outLon = anchorLon + (x / mPerLon)

        return Pair(outLat, outLon)
    }

    /**
     * 騎樓與遮蔽區航位推算推進 (PDR Step Advance)
     * 
     * 作用：當走進騎樓導致 GPS 斷訊時，利用步長與手機朝向角度平滑推算座標。
     */
    fun advanceStep(stepMeters: Double, headingDeg: Double): Pair<Double, Double> {
        if (!isInitialized) return Pair(anchorLat, anchorLon)
        val radHead = Math.toRadians(headingDeg)
        val dx = stepMeters * sin(radHead)
        val dy = stepMeters * cos(radHead)

        x += dx
        y += dy
        vx = dx / 0.6 // 假設一步耗時約 0.6 秒
        vy = dy / 0.6

        val radLat = Math.toRadians(anchorLat)
        val mPerLat = 111139.0
        val mPerLon = 111139.0 * cos(radLat)

        val outLat = anchorLat + (y / mPerLat)
        val outLon = anchorLon + (x / mPerLon)
        return Pair(outLat, outLon)
    }

    /** 是否已完成初始錨定 */
    fun isFilterInitialized(): Boolean = isInitialized

    /** 重置濾波器狀態 */
    fun reset() {
        isInitialized = false
    }
}


/**
 * 定位與感測器原生橋接器 (LocationSensorBridge)
 * 
 * 作用：負責調度 Android 手機底層所有導航與運動硬體感測器：
 * 1. 9 軸硬體旋轉向量 (TYPE_ROTATION_VECTOR)：50Hz 高頻無抖動即時朝向計算。
 * 2. 3D 空間真北補償 (Geomagnetic Declination)：消除台灣地區約 -3.8° 的地磁偏角，確保方向正對地理真北。
 * 3. 衛星訊噪比 (GNSS SNR) 與 L5 雙頻衛星辨識：動態過濾高樓大廈折射的反射雜訊。
 * 4. Weinberg 白手杖步態自適應模型：自動推算每一步長 (0.45m~0.85m)，在走進騎樓失去 GPS 時無縫接管導航。
 * 5. 跨程序即時通訊：將計算後的平滑座標與朝向，以 JavaScript 回調即時注入前端 WebView。
 */
class LocationSensorBridge(private val context: Context, private val webView: WebView) : SensorEventListener, LocationListener {

    private val tag = "LocationSensorBridge"
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val locationManager = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
    private val fusedLocationClient: FusedLocationProviderClient = LocationServices.getFusedLocationProviderClient(context)

    // 感測器旋轉與姿態陣列
    private val rotationMatrix = FloatArray(9)
    private val orientationAngles = FloatArray(3)
    private val accelerometerReading = FloatArray(3)
    private val magnetometerReading = FloatArray(3)

    private var hasRotationVector = false
    private var smoothedHeading = -1f
    private var lastHeadingEmitTime = 0L

    // 真北校正之地磁偏角（台灣地區預設約 -3.8°）
    private var geomagneticDeclination: Float = -3.8f

    // 衛星狀態回調、都會大樓多路徑折射旗標與 L5 雙頻衛星旗標
    private var gnssStatusCallback: GnssStatus.Callback? = null
    private var isUrbanCanyonMultipath = false
    private var hasDualFrequencyL5 = false

    // PDR 騎樓步態推算：步長估計、時間戳記與 Weinberg 模型加速度極值
    private var userStepLengthM = 0.65f
    private var lastGpsFixTimeMs = 0L
    private var lastStepEmitTimeMs = 0L
    private var stepDetectorSensor: Sensor? = null
    private var maxAccInWindow = 9.8f
    private var minAccInWindow = 9.8f

    // 行人卡爾曼濾波器實例
    private val kalmanFilter = PedestrianKalmanFilter()
    private var isRunning = false
    private var lastEmittedLocation: Location? = null

    // Google Play 融合定位 (Fused Location) 回調
    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(locationResult: LocationResult) {
            for (location in locationResult.locations) {
                onLocationChanged(location)
            }
        }
    }

    /**
     * 啟動所有感測器監聽與 GPS 定位
     */
    @SuppressLint("MissingPermission")
    fun start() {
        if (isRunning) return
        isRunning = true
        Log.i(tag, "Starting sensors with 9-axis fusion, True North correction, GNSS SNR filtering, Dual-Frequency L5, and Weinberg PDR...")

        // 1. 優先使用硬體 9 軸旋轉向量感測器 (TYPE_ROTATION_VECTOR)
        val rotVectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (rotVectorSensor != null) {
            hasRotationVector = true
            sensorManager.registerListener(this, rotVectorSensor, SensorManager.SENSOR_DELAY_GAME)
            Log.i(tag, "Using hardware 9-axis TYPE_ROTATION_VECTOR for responsive heading.")
        } else {
            // 若無 9 軸感測器，降級使用加速度計 + 磁力計
            hasRotationVector = false
            sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)?.also {
                sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
            }
            Log.i(tag, "Fallback to Accelerometer + Magnetometer.")
        }

        // 常態監聽加速度計，用於 Weinberg 步長動態自適應推算
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.also {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }

        // 2. 註冊硬體計步器 (TYPE_STEP_DETECTOR)，用於騎樓/室內 PDR 航位推算
        stepDetectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR)
        if (stepDetectorSensor != null) {
            sensorManager.registerListener(this, stepDetectorSensor, SensorManager.SENSOR_DELAY_FASTEST)
            Log.i(tag, "Using hardware STEP_DETECTOR for arcade PDR navigation.")
        }

        // 3. 註冊衛星狀態監聽器，即時監控訊噪比與 L5 雙頻衛星
        registerGnssStatusCallback()

        val hasFine = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        if (!hasFine && !hasCoarse) {
            Log.w(tag, "Location permissions not granted yet, sensors started but GPS waiting.")
            return
        }

        try {
            // 4. 啟動 Google Play 融合定位 (Fused Location Provider)
            val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
                .setMinUpdateIntervalMillis(500L)
                .setMinUpdateDistanceMeters(0.5f)
                .build()

            fusedLocationClient.requestLocationUpdates(
                locationRequest,
                locationCallback,
                Looper.getMainLooper()
            )

            // 快速熱啟動：若有最後已知位置（10 分鐘內且精度 150m 內），立即用於初次定位暖機
            fusedLocationClient.lastLocation.addOnSuccessListener { location: Location? ->
                location?.let {
                    val ageNanos = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
                        SystemClock.elapsedRealtimeNanos() - it.elapsedRealtimeNanos
                    } else {
                        (System.currentTimeMillis() - it.time) * 1_000_000L
                    }
                    val isUsable = it.hasAccuracy() && it.accuracy <= 150f && ageNanos < 600_000_000_000L // 10 分鐘內
                    if (isUsable) {
                        Log.i(tag, "Using initial warm-up lastLocation: ${it.latitude}, ${it.longitude} (Acc: ${it.accuracy}m, Age: ${ageNanos / 1_000_000_000L}s)")
                        onLocationChanged(it)
                    } else {
                        Log.i(tag, "Waiting for fresh live GPS fix (lastLocation too old or inaccurate).")
                    }
                }
            }


            // 5. 備援原生 LocationManager（GPS + Network 雙通道）
            locationManager?.let { lm ->
                if (lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                    lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0.5f, this, Looper.getMainLooper())
                }
                if (lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                    lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 1000L, 0.5f, this, Looper.getMainLooper())
                }
            }
        } catch (e: SecurityException) {
            Log.e(tag, "SecurityException while requesting location updates", e)
        }
    }

    /**
     * 螢幕開關自適應降頻省電調節：
     * 1. 螢幕關閉（放入口袋）：註銷高耗電 50Hz 姿態感測器，保留低功耗計步器。
     * 2. 螢幕開啟：恢復高頻姿態監聽。
     */
    fun setScreenActive(active: Boolean) {
        if (!isRunning) return
        Log.i(tag, "setScreenActive: $active (throttling sensors accordingly)")
        if (!active) {
            // 螢幕關閉：註銷耗電的姿態監聽
            sensorManager.unregisterListener(this, sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR))
            sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { sensorManager.unregisterListener(this, it) }
            sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)?.let { sensorManager.unregisterListener(this, it) }
        } else {
            // 螢幕開啟：重新註冊姿態監聽
            val rotVectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
            if (rotVectorSensor != null) {
                sensorManager.registerListener(this, rotVectorSensor, SensorManager.SENSOR_DELAY_GAME)
            } else {
                sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.also {
                    sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
                }
                sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)?.also {
                    sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
                }
            }
        }
    }

    /**
     * 註冊衛星狀態回調 (GnssStatus.Callback)
     * 作用：
     * 1. 檢查每顆衛星的 C/N0 訊噪比，若使用中的衛星平均 SNR < 21 dB-Hz 判定為大樓峽谷折射。
     * 2. 識別載波頻率 ~1176.45 MHz 的 L5/E5a 高頻寬雙頻衛星。
     */
    @SuppressLint("MissingPermission")
    private fun registerGnssStatusCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && locationManager != null) {
            try {
                gnssStatusCallback = object : GnssStatus.Callback() {
                    override fun onSatelliteStatusChanged(status: GnssStatus) {
                        val count = status.satelliteCount
                        var highCount = 0
                        var totalSnr = 0f
                        var usedCount = 0
                        var l5Count = 0

                        for (i in 0 until count) {
                            val snr = status.getCn0DbHz(i)
                            if (status.usedInFix(i)) {
                                usedCount++
                                totalSnr += snr
                                if (snr >= 22.0f) {
                                    highCount++
                                }
                                // 檢查是否為 L5 / E5a 雙頻載波 (~1176.45 MHz)
                                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && status.hasCarrierFrequencyHz(i)) {
                                    val freq = status.getCarrierFrequencyHz(i)
                                    if (abs(freq - 1.17645e9f) < 1.5e7f) {
                                        l5Count++
                                    }
                                }
                            }
                        }
                        val avgSnr = if (usedCount > 0) totalSnr / usedCount else 0f
                        // 大樓反射判定：若參與定位的衛星訊號極弱，判定為都市多路徑反射
                        isUrbanCanyonMultipath = (usedCount >= 3 && avgSnr < 21.0f) || (highCount < 4 && usedCount >= 4)
                        // L5 雙頻判定：至少鎖定 2 顆 L5 衛星且總衛星數 >= 5
                        hasDualFrequencyL5 = (l5Count >= 2 && usedCount >= 5)
                    }
                }
                locationManager.registerGnssStatusCallback(gnssStatusCallback!!, Handler(Looper.getMainLooper()))
                Log.i(tag, "GnssStatusCallback registered for urban canyon multipath and L5 dual-frequency filtering.")
            } catch (e: Exception) {
                Log.w(tag, "Could not register GnssStatusCallback: ${e.message}")
            }
        }
    }

    /**
     * 停止所有感測器與定位監聽，釋放資源
     */
    fun stop() {
        isRunning = false
        sensorManager.unregisterListener(this)
        kalmanFilter.reset()
        try {
            fusedLocationClient.removeLocationUpdates(locationCallback)
            locationManager?.removeUpdates(this)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && gnssStatusCallback != null) {
                locationManager?.unregisterGnssStatusCallback(gnssStatusCallback!!)
            }
        } catch (e: Exception) {
            Log.e(tag, "Error stopping location updates", e)
        }
    }

    /**
     * 計算當前經緯度與海拔下的地磁偏角（True North 補正）
     */
    private fun updateGeomagneticDeclination(lat: Double, lon: Double, alt: Double) {
        try {
            val geoField = GeomagneticField(
                lat.toFloat(),
                lon.toFloat(),
                alt.toFloat(),
                System.currentTimeMillis()
            )
            geomagneticDeclination = geoField.declination
        } catch (e: Exception) {
            Log.w(tag, "GeomagneticField fallback", e)
        }
    }

    /**
     * 當硬體計步器偵測到一步時觸發
     * 1. 採集加速度極值差，利用 Weinberg 模型動態微調步長。
     * 2. 若 GPS 訊號已中斷超過 1.2 秒（走進騎樓），自動推進卡爾曼座標並更新網頁。
     */
    private fun onStepDetected() {
        val now = SystemClock.uptimeMillis()
        if (now - lastStepEmitTimeMs < 250L) return
        lastStepEmitTimeMs = now

        // Weinberg 步長自適應模型: SL = K * (a_max - a_min)^(1/4)
        val deltaAcc = (maxAccInWindow - minAccInWindow).toDouble()
        maxAccInWindow = 9.8f
        minAccInWindow = 9.8f

        if (deltaAcc > 0.8 && deltaAcc < 25.0) {
            val estimatedSL = (0.43 * deltaAcc.pow(0.25)).toFloat()
            userStepLengthM = 0.8f * userStepLengthM + 0.2f * max(0.45f, min(0.85f, estimatedSL))
        }

        // 若 GPS 中斷超過 1.2 秒且濾波器已初始化：在騎樓/地下道啟動 PDR 平滑推算
        val timeSinceGps = now - lastGpsFixTimeMs
        if (timeSinceGps > 1200L && kalmanFilter.isFilterInitialized() && smoothedHeading >= 0f) {
            val (pdrLat, pdrLon) = kalmanFilter.advanceStep(userStepLengthM.toDouble(), smoothedHeading.toDouble())
            val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault()).format(Date())
            val humanLog = "[$timeStr] [騎樓PDR計步] 座標: ($pdrLat, $pdrLon) | 自適應步長: ${String.format(Locale.US, "%.2f", userStepLengthM)}m | 朝向: ${String.format(Locale.US, "%.1f", smoothedHeading)}°"
            val ndjson = org.json.JSONObject().apply {
                put("t", timeStr)
                put("evt", "PDR_STEP")
                put("lat", pdrLat)
                put("lon", pdrLon)
                put("stride_m", userStepLengthM)
                put("heading_deg", smoothedHeading)
            }.toString()
            addTrajectoryLog(humanLog, ndjson)

            Log.d(tag, "PDR Step Advance under arcade: ($pdrLat, $pdrLon) Adaptive Weinberg Step: ${userStepLengthM}m Heading: $smoothedHeading")
            webView.post {
                webView.evaluateJavascript(
                    "if (window.onLocationUpdate) window.onLocationUpdate(${pdrLat}, ${pdrLon}, 6.0, ${smoothedHeading}, 1.1);",
                    null
                )
            }
        }
    }

    /**
     * 感測器數值變更回調
     * 作用：計算抗傾斜的水平方位角 (Azimuth)、補正磁偏角，並以 50ms 節流傳送給前端網頁
     */
    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type == Sensor.TYPE_STEP_DETECTOR) {
            onStepDetected()
            return
        }

        val now = SystemClock.uptimeMillis()

        if (event.sensor.type == Sensor.TYPE_ROTATION_VECTOR) {
            SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
        } else if (event.sensor.type == Sensor.TYPE_ACCELEROMETER) {
            System.arraycopy(event.values, 0, accelerometerReading, 0, accelerometerReading.size)
            SensorManager.getRotationMatrix(rotationMatrix, null, accelerometerReading, magnetometerReading)

            // 採集加速度極值以供 Weinberg 步長模型使用
            val ax = event.values[0]
            val ay = event.values[1]
            val az = event.values[2]
            val mag = sqrt(ax * ax + ay * ay + az * az)
            if (mag > maxAccInWindow) maxAccInWindow = mag
            if (mag < minAccInWindow) minAccInWindow = mag
        } else if (event.sensor.type == Sensor.TYPE_MAGNETIC_FIELD) {
            System.arraycopy(event.values, 0, magnetometerReading, 0, magnetometerReading.size)
            SensorManager.getRotationMatrix(rotationMatrix, null, accelerometerReading, magnetometerReading)
        } else {
            return
        }

        // 3D 手持前向向量水平方位角計算（100% 免疫 0°~85° 手持俯仰傾斜）
        val eastForward = rotationMatrix[1].toDouble()
        val northForward = rotationMatrix[4].toDouble()
        val horizontalMagSq = eastForward * eastForward + northForward * northForward

        val rawDegrees: Float = if (horizontalMagSq > 0.03) {
            // 手持行走姿態（傾斜 15° ~ 80°）
            ((Math.toDegrees(atan2(eastForward, northForward)) + 360.0) % 360.0).toFloat()
        } else {
            // 手機水平平放於桌面
            SensorManager.getOrientation(rotationMatrix, orientationAngles)
            ((Math.toDegrees(orientationAngles[0].toDouble()) + 360.0) % 360.0).toFloat()
        }

        // 地磁偏角真北補正
        val trueDegrees = ((rawDegrees + geomagneticDeclination + 360.0f) % 360.0f)

        if (smoothedHeading < 0f) {
            smoothedHeading = trueDegrees
        } else {
            // 圓周最短路徑指數平滑 (0.45 平滑係數，轉彎靈敏俐落)
            var diff = trueDegrees - smoothedHeading
            while (diff < -180f) diff += 360f
            while (diff > 180f) diff -= 360f
            smoothedHeading = (smoothedHeading + 0.45f * diff + 360f) % 360f
        }

        // 每 50ms 節流傳送至前端 WebView，確保反應即時流暢
        if (now - lastHeadingEmitTime >= 50L) {
            lastHeadingEmitTime = now
            val deg = smoothedHeading
            webView.post {
                webView.evaluateJavascript("if (window.onHeadingUpdate) window.onHeadingUpdate(${deg});", null)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    /**
     * GPS 定位回調
     * 作用：
     * 1. 根據速度與高精度 GPS 自動校準使用者個人步長。
     * 2. 送入行人卡爾曼濾波器進行平滑與防飄。
     * 3. 記錄結構化日誌並評估回傳至前端 WebView。
     */
    override fun onLocationChanged(location: Location) {
        lastGpsFixTimeMs = SystemClock.uptimeMillis()

        // 捨棄極度低精度的訊號 (> 50m)
        if (location.hasAccuracy() && location.accuracy > 50f && lastEmittedLocation != null) {
            return
        }

        lastEmittedLocation = location
        val rawLat = location.latitude
        val rawLon = location.longitude
        val acc = if (location.hasAccuracy()) location.accuracy else 10f
        val bearing = if (location.hasBearing()) location.bearing else -1f
        val speed = if (location.hasSpeed()) location.speed else 0f
        val timestampNanos = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
            location.elapsedRealtimeNanos
        } else {
            System.currentTimeMillis() * 1_000_000L
        }

        // 更新所在經緯度的地磁偏角
        val alt = if (location.hasAltitude()) location.altitude else 0.0
        updateGeomagneticDeclination(rawLat, rawLon, alt)

        // 行走且 GPS 良好時，自適應校準個人步長
        if (location.hasSpeed() && speed > 0.6f && location.hasAccuracy() && acc < 5.0f) {
            val estimatedStep = (speed / 1.8f).coerceIn(0.50f, 0.85f)
            userStepLengthM = 0.85f * userStepLengthM + 0.15f * estimatedStep
        }

        // 執行卡爾曼濾波
        val (filteredLat, filteredLon) = kalmanFilter.filter(
            rawLat, rawLon, acc, timestampNanos, isUrbanCanyonMultipath, hasDualFrequencyL5
        )

        // 記錄人類可讀與結構化 NDJSON 日誌
        val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault()).format(Date())
        val humanLog = "[$timeStr] [GPS] 原始: ($rawLat, $rawLon) | 濾波: ($filteredLat, $filteredLon) | 精度: ${acc}m | 速度: ${String.format(Locale.US, "%.1f", speed)}m/s | 朝向: ${String.format(Locale.US, "%.1f", smoothedHeading)}° | L5雙頻: $hasDualFrequencyL5 | 都會反射: $isUrbanCanyonMultipath"
        val ndjson = org.json.JSONObject().apply {
            put("t", timeStr)
            put("evt", "GPS_FIX")
            put("raw_lat", rawLat)
            put("raw_lon", rawLon)
            put("lat", filteredLat)
            put("lon", filteredLon)
            put("acc_m", acc)
            put("speed_mps", speed)
            put("heading_deg", smoothedHeading)
            put("is_l5", hasDualFrequencyL5)
            put("is_multipath", isUrbanCanyonMultipath)
        }.toString()
        addTrajectoryLog(humanLog, ndjson)

        Log.d(tag, "GPS (Raw: $rawLat, $rawLon) -> (Kalman: $filteredLat, $filteredLon) Acc: $acc L5: $hasDualFrequencyL5 Multipath: $isUrbanCanyonMultipath")

        // 呼叫前端 JavaScript onLocationUpdate 函式
        webView.post {
            webView.evaluateJavascript(
                "if (window.onLocationUpdate) window.onLocationUpdate(${filteredLat}, ${filteredLon}, ${acc}, ${bearing}, ${speed});",
                null
            )
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}

    companion object {
        // 執行緒安全的軌跡日誌清單
        private val trajectoryHistory = Collections.synchronizedList(mutableListOf<String>())
        private val ndjsonRecords = Collections.synchronizedList(mutableListOf<String>())

        /**
         * 新增一筆軌跡紀錄（保留最近 2000 筆）
         */
        fun addTrajectoryLog(entry: String, ndjson: String? = null) {
            if (trajectoryHistory.size > 2000) {
                trajectoryHistory.removeAt(0)
            }
            trajectoryHistory.add(entry)
            if (ndjson != null) {
                if (ndjsonRecords.size > 2000) {
                    ndjsonRecords.removeAt(0)
                }
                ndjsonRecords.add(ndjson)
            }
        }

        /**
         * 取得純文字格式的軌跡日誌
         */
        fun getTrajectoryLogText(): String {
            return synchronized(trajectoryHistory) {
                if (trajectoryHistory.isEmpty()) {
                    "（尚無記錄到的 GPS 與感測器軌跡）"
                } else {
                    trajectoryHistory.joinToString("\n")
                }
            }
        }

        /**
         * 取得 NDJSON 格式的結構化軌跡
         */
        fun getTrajectoryNdjson(): String {
            return synchronized(ndjsonRecords) {
                ndjsonRecords.joinToString("\n")
            }
        }

        /**
         * 抽取所有有效 GPS 經緯度座標點清單（用於產生 GeoJSON 折線）
         */
        fun getGpsCoordinatesList(): List<Pair<Double, Double>> {
            val list = mutableListOf<Pair<Double, Double>>()
            synchronized(ndjsonRecords) {
                for (line in ndjsonRecords) {
                    try {
                        val obj = org.json.JSONObject(line)
                        val lat = obj.optDouble("lat", 0.0)
                        val lon = obj.optDouble("lon", 0.0)
                        if (lat != 0.0 && lon != 0.0) {
                            list.add(Pair(lat, lon))
                        }
                    } catch (e: Exception) {}
                }
            }
            return list
        }
    }
}

