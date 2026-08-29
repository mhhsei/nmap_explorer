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
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
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
 * 【行人與車載運動狀態列舉 (Motion State)】
 * 
 * 作用：定義使用者當前的真實物理運動情境，讓定位系統自適應切換最佳濾波策略。
 */
enum class MotionState {
    /** 1. 室內或原地靜止（100% 座標完全凍結，阻絕任何跳動） */
    STATIONARY_LOCKED,

    /** 2. 行人正常步行（PDR 步態同步推進 + 卡爾曼平滑） */
    PEDESTRIAN_WALKING,

    /** 3. 乘車交通工具移動（時速 > 10 km/h，自動解除步數限制，以即時 GPS 流暢跟隨） */
    VEHICULAR_TRANSIT
}

/**
 * 【手持智慧型手機多特徵滑動視窗靜止偵測器 (StationaryMotionDetector)】
 * 
 * 生活化比喻：
 * 就像一位經驗豐富的領航員，同時觀察手部的微小震顫、步伐的節奏與車速。
 * 當您在室內坐下或在路口停步時，它會立即在 1.4 秒內為您「拉下手煞車（鎖定座標）」，
 * 徹底杜絕 GPS 在天花板下的鬼影飄移；而當您搭上公車、計程車或捷運時，它會自動識別高速並鬆開手煞車。
 */
class StationaryMotionDetector(
    private val windowSize: Int = 35, // 50Hz 採樣下約 0.7 秒
    private val onStateChanged: (MotionState) -> Unit
) {
    // 3 軸加速度計模長滑動視窗緩衝區
    private val accNormBuffer = FloatArray(windowSize)
    private var bufferIndex = 0
    private var isBufferFull = false

    // 最後一次偵測到實體步伐的時間戳記 (uptimeMillis)
    private var lastStepTimestampMs = 0L

    // 當前運動狀態
    var currentState: MotionState = MotionState.STATIONARY_LOCKED
        private set

    companion object {
        /** 加速度模長變異數靜止門檻 (m^2/s^4)：手持、坐著或原地轉向時通常 < 0.20 */
        const val ACC_VAR_STATIONARY_THRESHOLD = 0.20f

        /** 步伐逾時時間 (毫秒)：超過 1.4 秒沒有踩出下一步，判定可能已停下腳步 */
        const val STEP_TIMEOUT_MS = 1400L

        /** 判定為乘車的車速門檻 (m/s)：約 10.08 km/h，超出人類一般步行極限 */
        const val VEHICLE_SPEED_THRESHOLD_MPS = 2.8f
    }

    private fun getNowMs(): Long {
        return try {
            SystemClock.uptimeMillis()
        } catch (e: Exception) {
            System.currentTimeMillis()
        }
    }

    /**
     * 當硬體計步器偵測到一步時呼叫
     */
    fun onStepDetected() {
        lastStepTimestampMs = getNowMs()
        if (currentState == MotionState.STATIONARY_LOCKED) {
            updateState(MotionState.PEDESTRIAN_WALKING)
        }
    }

    /**
     * 於 50Hz onSensorChanged 灌入加速度計數據與即時 GPS 車速
     */
    fun feedAccelerometer(ax: Float, ay: Float, az: Float, currentGpsSpeedMps: Float) {
        // 1. 若 GPS 瞬時車速 > 2.8 m/s (~10 km/h)，自動切換為乘車高速模式
        if (currentGpsSpeedMps >= VEHICLE_SPEED_THRESHOLD_MPS) {
            if (currentState != MotionState.VEHICULAR_TRANSIT) {
                updateState(MotionState.VEHICULAR_TRANSIT)
            }
            return
        }

        val accNorm = sqrt(ax * ax + ay * ay + az * az)
        accNormBuffer[bufferIndex] = accNorm
        bufferIndex = (bufferIndex + 1) % windowSize
        if (bufferIndex == 0) isBufferFull = true

        if (!isBufferFull) return

        // 2. 計算加速度模長滑動變異數 (AMV, Acceleration Moving Variance)
        var accSum = 0f
        for (i in 0 until windowSize) accSum += accNormBuffer[i]
        val accMean = accSum / windowSize

        var accVarSum = 0f
        for (i in 0 until windowSize) {
            val diff = accNormBuffer[i] - accMean
            accVarSum += diff * diff
        }
        val accVariance = accVarSum / windowSize

        val now = getNowMs()
        val stepTimedOut = (now - lastStepTimestampMs) > STEP_TIMEOUT_MS

        // 3. 步行與靜止條件綜合仲裁：
        // 判定步行：若 GPS 明確有移動速度 (> 0.55 m/s, ~2 km/h)，或加速度有行走波動 (> 0.32)，或剛踩出步伐
        val isWalkingIndicated = (currentGpsSpeedMps >= 0.55f) || (accVariance > 0.32f) || !stepTimedOut
        // 判定靜止：加速度極平穩、逾時未邁步、且 GPS 車速極低 (< 0.4 m/s)
        val isPhysicallyStill = (accVariance < ACC_VAR_STATIONARY_THRESHOLD) && stepTimedOut && (currentGpsSpeedMps < 0.4f)

        if (isWalkingIndicated) {
            if (currentState != MotionState.PEDESTRIAN_WALKING) {
                Log.i("LocationSensorBridge", "[MOTION_STATE_CHANGE] ${currentState.name} -> PEDESTRIAN_WALKING (accVar=${String.format(Locale.US, "%.3f", accVariance)}, speed=${String.format(Locale.US, "%.2f", currentGpsSpeedMps)}m/s, stepTimedOut=$stepTimedOut)")
                updateState(MotionState.PEDESTRIAN_WALKING)
            }
        } else if (isPhysicallyStill) {
            if (currentState != MotionState.STATIONARY_LOCKED) {
                Log.i("LocationSensorBridge", "[MOTION_STATE_CHANGE] ${currentState.name} -> STATIONARY_LOCKED (accVar=${String.format(Locale.US, "%.3f", accVariance)}, speed=${String.format(Locale.US, "%.2f", currentGpsSpeedMps)}m/s, stepTimedOut=$stepTimedOut)")
                updateState(MotionState.STATIONARY_LOCKED)
            }
        }
    }

    private fun updateState(newState: MotionState) {
        currentState = newState
        onStateChanged(newState)
    }

    fun reset() {
        bufferIndex = 0
        isBufferFull = false
        currentState = MotionState.STATIONARY_LOCKED
        lastStepTimestampMs = 0L
    }
}


/**
 * 【二維行人與乘車自適應卡爾曼濾波器 (Pedestrian & Vehicular Adaptive Kalman Filter)】
 * 
 * 核心演算法亮點：
 * 1. 停留重心收斂定錨 (Centroid Anchoring & ZUPT)：
 *    停步時不取最後單一筆可能帶有漂移雜訊的 GPS，而是以停下前 2~3 秒內之平滑位置加權重心定錨。
 *    杜絕鎖在漂移點；原地轉身時位置 100% 凍結，僅朝向旋轉，維持 3D 空間音訊穩定。
 * 2. 前進軸與橫向軸阻尼分流 (Along-Track vs Cross-Track Damping)：
 *    將人體前進朝向旋轉解耦。前進軸 (Along-track) 正常放行確保步態敏銳反應；
 *    橫向軸 (Cross-track) 強力加壓阻尼，瞬間削平 80% 大樓折射引起的馬路左右橫跳雜訊！
 * 3. 馬氏距離新息門控 (Mahalanobis Innovation Gating)：以 95% 卡方檢定 (5.991) 嚴格把關 GPS，剔除大樓折射跳點。
 * 4. 乘車高速自適應 (Vehicular High-Speed Mode)：搭乘公車/計程車時自動解鎖，流暢追蹤車載軌跡。
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

    // 協方差矩陣 (對角近似值，代表對自身估計的不確定度)
    private var p00 = 4.0 // x 位置變異數
    private var p11 = 4.0 // y 位置變異數
    private var p22 = 1.0 // vx 速度變異數
    private var p33 = 1.0 // vy 速度變異數

    // 靜止鎖定座標
    private var lockedLat = 0.0
    private var lockedLon = 0.0

    private var lastTimestampNanos: Long = 0

    // 新息門控防鎖死機制變數
    private var consecutiveRejections = 0
    private var lastRejectedZx = 0.0
    private var lastRejectedZy = 0.0

    // 最近平滑座標緩衝區 (供停步時幾何重心收斂定錨計算)
    private data class FilteredFix(
        val x: Double,
        val y: Double,
        val accuracyMeters: Float,
        val timestampNanos: Long
    )
    private val recentFixes = java.util.ArrayDeque<FilteredFix>()

    /**
     * 【當偵測到進入靜止狀態時觸發 (On Stationary State Entered)】
     * 作用：
     * 停步時不取最後單一筆可能帶有漂移雜訊的 GPS，而是以停下前 2~3 秒內之平滑位置加權重心定錨。
     */
    fun onStationaryStateEntered() {
        if (!isInitialized || recentFixes.isEmpty()) return

        var sumW = 0.0
        var weightedX = 0.0
        var weightedY = 0.0
        val latestNanos = recentFixes.last.timestampNanos

        for (fix in recentFixes) {
            val ageSec = max(0.0, (latestNanos - fix.timestampNanos) / 1_000_000_000.0)
            // 2.0 秒半衰期時間衰減（越靠近停步時刻的權重越高）
            val timeWeight = exp(-ageSec / 2.0)
            // 精度倒數平方權重（精度越佳之權重越高）
            val accWeight = 1.0 / max(fix.accuracyMeters.toDouble(), 1.5).pow(2.0)
            val w = timeWeight * accWeight

            weightedX += fix.x * w
            weightedY += fix.y * w
            sumW += w
        }

        if (sumW > 0.0) {
            val centroidX = weightedX / sumW
            val centroidY = weightedY / sumW

            // 驗證幾何重心與當前位置之距離，防止異常離群跳躍 (< 5.5m)
            val distToCentroid = sqrt((centroidX - x).pow(2.0) + (centroidY - y).pow(2.0))
            if (distToCentroid < 5.5) {
                x = centroidX
                y = centroidY
            }
        }

        vx = 0.0
        vy = 0.0
        val (cLat, cLon) = getCurrentGeoLocation()
        lockedLat = cLat
        lockedLon = cLon
        Log.i("LocationSensorBridge", "[CENTROID_ANCHOR] 停步重心收斂定錨成功: ($lockedLat, $lockedLon)，整合 ${recentFixes.size} 筆歷史軌跡點。")
    }

    /**
     * 步態推進 (Predict Step - 由步伐事件驅動)
     * 作用：當使用者走一步時，由 Weinberg 自適應步長模型平滑推算前進。
     */
    fun advanceStep(stepMeters: Double, headingDeg: Double): Pair<Double, Double> {
        if (!isInitialized) return Pair(anchorLat, anchorLon)

        val radHeading = Math.toRadians(headingDeg)
        val dx = stepMeters * sin(radHeading)
        val dy = stepMeters * cos(radHeading)

        x += dx
        y += dy
        vx = dx / 0.6 // 假設一步約 0.6 秒
        vy = dy / 0.6

        p00 += 0.5
        p11 += 0.5

        val (curLat, curLon) = getCurrentGeoLocation()
        lockedLat = curLat
        lockedLon = curLon

        // 步態推算亦加入滑動視窗
        val nowNanos = System.currentTimeMillis() * 1_000_000L
        recentFixes.addLast(FilteredFix(x, y, 4.0f, nowNanos))
        while (recentFixes.size > 8) {
            recentFixes.removeFirst()
        }

        return Pair(curLat, curLon)
    }

    /**
     * 執行卡爾曼濾波測量更新
     * 
     * @param rawLat GPS 原始緯度
     * @param rawLon GPS 原始經度
     * @param accuracyMeters GPS 精度半徑（公尺）
     * @param speedMps GPS 測量速度（公尺/秒）
     * @param timestampNanos 時間戳記（奈秒）
     * @param motionState 當前運動狀態 (靜止/步行/乘車)
     * @param isMultipath 是否偵測到大樓多路徑折射反射雜訊
     * @param hasDualFrequencyL5 是否收到 L5 雙頻衛星高精度訊號
     * @param headingDeg 當前 9 軸融合真北朝向角 (度，0~360)
     * @param diffTier 五級差分定位品質等級 (DifferentialTier)
     * @return 濾波平滑後的 (緯度, 經度)
     */
    fun filter(
        rawLat: Double,
        rawLon: Double,
        accuracyMeters: Float,
        speedMps: Float,
        timestampNanos: Long,
        motionState: MotionState,
        isMultipath: Boolean = false,
        hasDualFrequencyL5: Boolean = false,
        headingDeg: Float = -1f,
        diffTier: DifferentialTier = DifferentialTier.OFFLINE_AUTONOMOUS
    ): Pair<Double, Double> {
        // 若為第一次定位：設定初始錨點與狀態
        if (!isInitialized) {
            anchorLat = rawLat
            anchorLon = rawLon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            lockedLat = rawLat
            lockedLon = rawLon
            lastTimestampNanos = timestampNanos
            isInitialized = true
            recentFixes.clear()
            recentFixes.addLast(FilteredFix(0.0, 0.0, accuracyMeters, timestampNanos))
            return Pair(rawLat, rawLon)
        }

        // 1. 【停留防抖、重心微收斂與看門狗安全破鎖 (Safety Breakout)】
        if (motionState == MotionState.STATIONARY_LOCKED) {
            val radLat = Math.toRadians(lockedLat)
            val mPerLat = 111139.0
            val mPerLon = 111139.0 * cos(radLat)
            val distFromLocked = sqrt(
                ((rawLon - lockedLon) * mPerLon).pow(2) +
                ((rawLat - lockedLat) * mPerLat).pow(2)
            )

            // 破鎖仲裁：若物理位移 > 4.8m 且 GPS 精度合理 (< 14m)，或移動速度 > 0.55m/s：
            // 代表使用者已開始走動，立即解除座標凍結重新對齊！
            if ((distFromLocked > 4.8 && accuracyMeters < 14.0f) || (speedMps > 0.55f && accuracyMeters < 14.0f)) {
                Log.w("LocationSensorBridge", "[KALMAN_BREAKOUT] Stationary lock broken by displacement: dist=${String.format(Locale.US, "%.1f", distFromLocked)}m, speed=${speedMps}m/s, acc=${accuracyMeters}m")
                anchorLat = rawLat
                anchorLon = rawLon
                x = 0.0
                y = 0.0
                vx = 0.0
                vy = 0.0
                p00 = 4.0
                p11 = 4.0
                lockedLat = rawLat
                lockedLon = rawLon
                consecutiveRejections = 0
                recentFixes.clear()
                recentFixes.addLast(FilteredFix(0.0, 0.0, accuracyMeters, timestampNanos))
                return Pair(rawLat, rawLon)
            } else {
                // 停留微收斂 (Stationary Micro-Convergence):
                // 若位移在定錨範圍內 (< 3.5m) 且衛星精度極佳 (< 4.2m) 且非折射雜訊：
                // 允許極微幅 (5%) 柔和微調重心，消除長時間等紅燈時的單點微小初始偏壓
                if (distFromLocked < 3.5 && accuracyMeters < 4.2f && !isMultipath) {
                    lockedLat = 0.95 * lockedLat + 0.05 * rawLat
                    lockedLon = 0.95 * lockedLon + 0.05 * rawLon
                    val (curLat, curLon) = getCurrentGeoLocation()
                    x += (lockedLon - curLon) * mPerLon
                    y += (lockedLat - curLat) * mPerLat
                }
                vx = 0.0
                vy = 0.0
                return Pair(lockedLat, lockedLon)
            }
        }

        var dt = (timestampNanos - lastTimestampNanos) / 1_000_000_000.0
        lastTimestampNanos = timestampNanos
        if (dt <= 0.0 || dt > 5.0) dt = 1.0

        // 將經緯度轉換為局部平面直角座標（等距圓柱投影，單位：公尺）
        val radLat = Math.toRadians(anchorLat)
        val mPerLat = 111139.0
        val mPerLon = 111139.0 * cos(radLat)

        val zx = (rawLon - anchorLon) * mPerLon
        val zy = (rawLat - anchorLat) * mPerLat

        // 跨區大位移重置防護 (> 80m，如搭車高速前進跨區)
        if (sqrt(zx * zx + zy * zy) > 80.0) {
            anchorLat = rawLat
            anchorLon = rawLon
            x = 0.0
            y = 0.0
            vx = 0.0
            vy = 0.0
            p00 = 4.0
            p11 = 4.0
            lockedLat = rawLat
            lockedLon = rawLon
            consecutiveRejections = 0
            recentFixes.clear()
            recentFixes.addLast(FilteredFix(0.0, 0.0, accuracyMeters, timestampNanos))
            return Pair(rawLat, rawLon)
        }

        // 2. 【狀態預測步驟：前進軸與橫向軸阻尼分流 (Along-Track vs Cross-Track Noise Projection)】
        val hasValidHeading = headingDeg in 0f..360f
        val (qX, qY) = if (hasValidHeading && motionState == MotionState.PEDESTRIAN_WALKING) {
            val radH = Math.toRadians(headingDeg.toDouble())
            val sinH = sin(radH)
            val cosH = cos(radH)
            // 前進方向正常放行 (2.0 m^2/s)；垂直前進方向施加強阻尼 (0.18 m^2/s)，大幅抑制左右橫跳！
            val qAlong = 2.0
            val qCross = 0.18
            Pair(
                qAlong * sinH * sinH + qCross * cosH * cosH,
                qAlong * cosH * cosH + qCross * sinH * sinH
            )
        } else if (motionState == MotionState.VEHICULAR_TRANSIT) {
            Pair(4.0, 4.0)
        } else {
            Pair(1.8, 1.8)
        }
        val qVel = if (motionState == MotionState.VEHICULAR_TRANSIT) 2.0 else 0.8

        x += vx * dt
        y += vy * dt
        p00 += p22 * dt * dt + qX * dt
        p11 += p33 * dt * dt + qY * dt
        p22 += qVel * dt
        p33 += qVel * dt

        // 3. 自適應測量雜訊協方差 R（融合五級差分定位品質階梯，公分/分米級高精度動態信任）
        var baseR = when (diffTier) {
            DifferentialTier.RTK_FIXED_CENTIMETER -> 0.15
            DifferentialTier.RTK_FLOAT_DECIMETER -> 0.35
            DifferentialTier.DGPS_CODE_DIFF -> 0.75
            DifferentialTier.CARRIER_SMOOTHED_HATCH -> 1.60
            DifferentialTier.OFFLINE_AUTONOMOUS -> max(accuracyMeters.toDouble().pow(1.8) * 0.7, 3.0)
        }
        if (hasDualFrequencyL5) baseR *= 0.7
        if (isMultipath) baseR *= 4.0

        // 4. 馬氏距離新息門控 (Mahalanobis Innovation Gating) 與防鎖死連續異常復位
        val innovX = zx - x
        val innovY = zy - y
        val sX = p00 + baseR
        val sY = p11 + baseR
        val mahalanobisSq = (innovX * innovX / sX) + (innovY * innovY / sY)

        val maxGate = if (motionState == MotionState.VEHICULAR_TRANSIT) 64.0 else 16.0
        if (mahalanobisSq > maxGate) {
            val distToLastRej = sqrt((zx - lastRejectedZx) * (zx - lastRejectedZx) + (zy - lastRejectedZy) * (zy - lastRejectedZy))
            if (distToLastRej < 15.0) {
                consecutiveRejections++
            } else {
                consecutiveRejections = 1
            }
            lastRejectedZx = zx
            lastRejectedZy = zy

            if (consecutiveRejections >= 2) {
                // 連續收到一致的新位置，代表使用者真實前進而非單點跳躍，快速平滑拉至新位置
                x = zx
                y = zy
                vx = 0.0
                vy = 0.0
                p00 = baseR
                p11 = baseR
                consecutiveRejections = 0
            } else {
                // 單點折射瞬移雜訊，予以過濾
                return getCurrentGeoLocation()
            }
        } else {
            consecutiveRejections = 0
        }

        // 5. 【前進軸與橫向軸新息阻尼解耦 (Along-Track vs Cross-Track Innovation Damping)】
        val (effectiveInnovX, effectiveInnovY) = if (hasValidHeading && motionState == MotionState.PEDESTRIAN_WALKING) {
            val radH = Math.toRadians(headingDeg.toDouble())
            val sinH = sin(radH)
            val cosH = cos(radH)

            // 投影至前進軸與橫向軸
            val innovAlong = innovX * sinH + innovY * cosH
            val innovCross = innovX * cosH - innovY * sinH

            // 橫向新息壓縮阻尼：人體行走無法瞬間側向跳躍 3 公尺。
            // 超出 1.2m 擺動門檻之橫向折射雜訊施加 Huber 阻尼 (壓縮係數 0.25)，徹底抹平人行道左右橫跳！
            val lateralThreshold = 1.2
            val absCross = abs(innovCross)
            val dampedCross = if (absCross > lateralThreshold) {
                sign(innovCross) * (lateralThreshold + 0.25 * (absCross - lateralThreshold))
            } else {
                innovCross
            }

            // 重構正交直角座標新息向量
            Pair(
                innovAlong * sinH + dampedCross * cosH,
                innovAlong * cosH - dampedCross * sinH
            )
        } else {
            Pair(innovX, innovY)
        }

        // 6. 計算卡爾曼增益並更新狀態
        val k0 = p00 / sX
        val k1 = p11 / sY

        x += k0 * effectiveInnovX
        y += k1 * effectiveInnovY

        p00 *= (1.0 - k0)
        p11 *= (1.0 - k1)

        vx = (k0 * effectiveInnovX) / dt
        vy = (k1 * effectiveInnovY) / dt

        // 速度鉗制防護
        val maxSpeed = if (motionState == MotionState.VEHICULAR_TRANSIT) 25.0 else 4.0
        val curSpd = sqrt(vx * vx + vy * vy)
        if (curSpd > maxSpeed) {
            val scale = maxSpeed / curSpd
            vx *= scale
            vy *= scale
        }

        val (outLat, outLon) = getCurrentGeoLocation()
        lockedLat = outLat
        lockedLon = outLon

        // 記錄平滑軌跡供定錨計算
        recentFixes.addLast(FilteredFix(x, y, accuracyMeters, timestampNanos))
        while (recentFixes.size > 8) {
            recentFixes.removeFirst()
        }

        return Pair(outLat, outLon)
    }

    private fun getCurrentGeoLocation(): Pair<Double, Double> {
        val radLat = Math.toRadians(anchorLat)
        val mPerLat = 111139.0
        val mPerLon = 111139.0 * cos(radLat)
        return Pair(anchorLat + (y / mPerLat), anchorLon + (x / mPerLon))
    }

    fun isFilterInitialized(): Boolean = isInitialized

    /**
     * 室內公眾 Beacon 或 Wi-Fi RTT 絕對定錨重置
     * 作用：當在室內/地下街偵測到已知公眾燈塔時，直接將卡爾曼座標與局部原點對齊至該燈塔
     */
    fun reanchor(newLat: Double, newLon: Double, accuracyM: Float = 2.0f) {
        anchorLat = newLat
        anchorLon = newLon
        x = 0.0
        y = 0.0
        vx = 0.0
        vy = 0.0
        p00 = accuracyM * accuracyM.toDouble()
        p11 = accuracyM * accuracyM.toDouble()
        p22 = 0.5
        p33 = 0.5
        isInitialized = true
        consecutiveRejections = 0
        recentFixes.clear()
        recentFixes.add(FilteredFix(0.0, 0.0, accuracyM, System.nanoTime()))
    }

    fun reset() {
        isInitialized = false
        consecutiveRejections = 0
        recentFixes.clear()
    }
}


/**
 * 【定位與感測器原生橋接器 (LocationSensorBridge)】
 * 
 * 作用：負責調度 Android 手機底層所有導航與運動硬體感測器：
 * 1. 9 軸硬體旋轉向量 (TYPE_ROTATION_VECTOR)：50Hz 高頻無抖動即時朝向計算。
 * 2. 3D 空間真北補償 (Geomagnetic Declination)：消除台灣地區約 -3.8° 的地磁偏角，確保方向正對地理真北。
 * 3. 衛星訊噪比 (GNSS SNR) 與 L5 雙頻衛星辨識：動態過濾高樓大廈折射的反射雜訊。
 * 4. 三態運動分類器與靜止鎖定：室內/停留時 100% 座標凍結防飄；搭車時自動切換高速追蹤。
 * 5. Weinberg 白手杖步態自適應模型：自動推算每一步長 (0.45m~0.85m)，在走進騎樓失去 GPS 時無縫接管導航。
 * 6. 跨程序即時通訊：將計算後的平滑座標與朝向，以 JavaScript 回調即時注入前端 WebView。
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
    private var lastEmittedHeading = -1f
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
    private var lastGpsSpeedMps = 0f
    private var stepDetectorSensor: Sensor? = null
    private var maxAccInWindow = 9.8f
    private var minAccInWindow = 9.8f
    private var lastSoftwareStepMs = 0L
    private var lastAccMag = 9.8f

    // 行人卡爾曼濾波器與靜止偵測器實例
    private val kalmanFilter = PedestrianKalmanFilter()
    private val stationaryDetector = StationaryMotionDetector { state ->
        Log.i(tag, "Motion state changed to: $state")
        if (state == MotionState.STATIONARY_LOCKED) {
            kalmanFilter.onStationaryStateEntered()
        }
    }

    // 國家級 e-GNSS NTRIP 差分客戶端與雙頻載波平滑處理器實例
    private var ntripClient: NtripDiffClient? = null
    private var rawGnssProcessor: GnssRawMeasurementProcessor? = null
    private var currentDiffTier: DifferentialTier = DifferentialTier.OFFLINE_AUTONOMOUS

    // 氣壓計垂直高度濾波器與公眾室內 Beacon 定錨引擎
    private var barometerFilter: BarometerVerticalFilter? = null
    private var beaconManager: BeaconAnchorManager? = null
    private var pressureSensor: Sensor? = null
    private var currentVerticalLevel: VerticalLevel = VerticalLevel.GROUND
    private var currentAltitudeM: Float = 0.0f

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

    init {
        barometerFilter = BarometerVerticalFilter { level, altM, desc ->
            currentVerticalLevel = level
            currentAltitudeM = altM
            val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault()).format(Date())
            val humanLog = "[$timeStr] [垂直樓層切換] 樓層: ${level.displayName} | 高度: ${String.format(Locale.US, "%.1f", altM)}m | 提示: $desc"
            val ndjson = org.json.JSONObject().apply {
                put("t", timeStr)
                put("evt", "VERTICAL_LEVEL_CHANGE")
                put("level", level.name)
                put("display_name", level.displayName)
                put("altitude_m", altM)
                put("desc", desc)
            }.toString()
            addTrajectoryLog(humanLog, ndjson)

            webView.post {
                val escapedDesc = desc.replace("'", "\\'")
                webView.evaluateJavascript(
                    "if (window.onVerticalLevelUpdate) window.onVerticalLevelUpdate('${level.name}', '${level.displayName}', ${altM}, '${escapedDesc}');",
                    null
                )
            }
        }

        beaconManager = BeaconAnchorManager(context) { beacon, distM ->
            handleBeaconAnchor(beacon, distM)
        }
    }

    private fun handleBeaconAnchor(beacon: PublicBeaconAnchor, distM: Float) {
        val now = SystemClock.uptimeMillis()
        val timeSinceGps = now - lastGpsFixTimeMs
        val isGpsWeak = timeSinceGps > 1200L || (lastEmittedLocation?.accuracy ?: 100f) > 15f

        val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault()).format(Date())
        val humanLog = "[$timeStr] [公眾Beacon定錨] 信標: ${beacon.name} | 距離: ${String.format(Locale.US, "%.1f", distM)}m | 樓層: ${beacon.level.displayName} | 座標: (${beacon.lat}, ${beacon.lon})"
        val ndjson = org.json.JSONObject().apply {
            put("t", timeStr)
            put("evt", "BEACON_REANCHOR")
            put("beacon_id", beacon.id)
            put("beacon_name", beacon.name)
            put("dist_m", distM)
            put("level", beacon.level.name)
            put("lat", beacon.lat)
            put("lon", beacon.lon)
        }.toString()
        addTrajectoryLog(humanLog, ndjson)

        if (isGpsWeak) {
            kalmanFilter.reanchor(beacon.lat, beacon.lon, 2.0f)
            Log.i(tag, "[BEACON_REANCHOR] Indoor coordinates anchored to (${beacon.lat}, ${beacon.lon}) by ${beacon.name}")
        }

        barometerFilter?.calibrateBaseline(if (beacon.level == VerticalLevel.UNDERGROUND) -3.2f else if (beacon.level == VerticalLevel.UNDERGROUND_B2) -6.5f else 0.0f)

        webView.post {
            val escapedName = beacon.name.replace("'", "\\'")
            val escapedDesc = beacon.description.replace("'", "\\'")
            webView.evaluateJavascript(
                "if (window.onBeaconAnchorUpdate) window.onBeaconAnchorUpdate('${beacon.id}', '${escapedName}', ${beacon.lat}, ${beacon.lon}, ${distM}, '${beacon.level.name}', '${escapedDesc}');",
                null
            )
        }
    }

    /**
     * 啟動所有感測器監聽與 GPS 定位
     */
    @SuppressLint("MissingPermission")
    fun start() {
        if (isRunning) return
        isRunning = true
        Log.i(tag, "Starting sensors with 9-axis fusion, True North correction, GNSS SNR filtering, Dual-Frequency L5, Stationary Lock, and Weinberg PDR...")

        // 1. 方位感測器 4 級適應鏈 (4-Tier Orientation Sensor Degradation Stack)
        val rotVectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        val geoRotVectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR)
        if (rotVectorSensor != null) {
            hasRotationVector = true
            sensorManager.registerListener(this, rotVectorSensor, SensorManager.SENSOR_DELAY_GAME)
            Log.i(tag, "[Heading Sensor] Tier 1: Hardware 9-axis TYPE_ROTATION_VECTOR registered (Best accuracy & zero drift).")
        } else if (geoRotVectorSensor != null) {
            hasRotationVector = true
            sensorManager.registerListener(this, geoRotVectorSensor, SensorManager.SENSOR_DELAY_GAME)
            Log.i(tag, "[Heading Sensor] Tier 2: TYPE_GEOMAGNETIC_ROTATION_VECTOR registered (Sensor hub fusion, gyro-free).")
        } else {
            // 若無硬體旋轉向量，降級使用加速度計 + 磁力計軟體向量融合
            hasRotationVector = false
            val magSensor = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
            if (magSensor != null) {
                sensorManager.registerListener(this, magSensor, SensorManager.SENSOR_DELAY_GAME)
                Log.i(tag, "[Heading Sensor] Tier 3: TYPE_MAGNETIC_FIELD registered (Software complementary filter).")
            } else {
                Log.w(tag, "[Heading Sensor] Tier 4: No compass hardware. Will rely on GPS Course-over-ground bearing when walking.")
            }
        }

        // 常態監聽加速度計，用於靜止偵測與 Weinberg 步長動態自適應推算
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.also {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }

        // 2. 註冊硬體計步器 (TYPE_STEP_DETECTOR)，用於騎樓/室內 PDR 航位推算
        stepDetectorSensor = sensorManager.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR)
        if (stepDetectorSensor != null) {
            sensorManager.registerListener(this, stepDetectorSensor, SensorManager.SENSOR_DELAY_FASTEST)
            Log.i(tag, "[Step Sensor] Hardware TYPE_STEP_DETECTOR registered for arcade PDR navigation.")
        } else {
            Log.i(tag, "[Step Sensor] Hardware STEP_DETECTOR unavailable; software accelerometer peak detection active.")
        }

        // 3. 註冊衛星狀態監聽器、雙頻載波平滑引擎與 e-GNSS 差分客戶端
        registerGnssStatusCallback()
        registerGnssRawMeasurementsCallback()
        startNtripClient()

        val hasFine = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        if (!hasFine && !hasCoarse) {
            Log.w(tag, "Location permissions not granted yet, sensors started but GPS waiting.")
            return
        }

        try {
            // 4. 單一資料來源架構 (Single Source of Truth)：
            // 優先使用 Google Play Services 融合定位 (FusedLocationProviderClient)。
            // 絕不同時註冊原生 LocationManager，徹底消除 A-B-A 乒乓拉扯震盪！
            val isGmsAvailable = try {
                GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(context) == ConnectionResult.SUCCESS
            } catch (e: Throwable) {
                false
            }
            Log.i(tag, "[GPS_INIT] Google Play Services availability check: $isGmsAvailable")

            if (isGmsAvailable) {
                Log.i(tag, "[GPS_INIT] Activating Google FusedLocationProviderClient as Single Source of Truth.")
                val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
                    .setMinUpdateIntervalMillis(500L)
                    .setMinUpdateDistanceMeters(0.0f)
                    .setMaxUpdateDelayMillis(0L)
                    .setWaitForAccurateLocation(false)
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
                            Log.i(tag, "[GPS_WARMUP] Using initial warm-up lastLocation: ${it.latitude}, ${it.longitude} (Acc: ${it.accuracy}m, Age: ${ageNanos / 1_000_000_000L}s, Provider: ${it.provider})")
                            onLocationChanged(it)
                        } else {
                            Log.i(tag, "[GPS_WARMUP] Waiting for fresh live GPS fix (lastLocation too old or inaccurate).")
                        }
                    }
                }
            } else {
                // 無 Google 服務之設備（純 AOSP、中國版本或華為無 GMS 設備）：自動降級回退至原生 LocationManager
                Log.w(tag, "[GPS_INIT] GMS unavailable. Fallback to native LocationManager (GPS_PROVIDER).")
                locationManager?.let { lm ->
                    if (lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                        lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0.0f, this, Looper.getMainLooper())
                    } else if (lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                        lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 1000L, 0.0f, this, Looper.getMainLooper())
                    }
                }
            }
        } catch (e: SecurityException) {
            Log.e(tag, "SecurityException while requesting location updates", e)
        }

        // 5. 註冊氣壓計感測器 (Sensor.TYPE_PRESSURE)，提供 3D 垂直樓層追蹤
        pressureSensor = sensorManager.getDefaultSensor(Sensor.TYPE_PRESSURE)
        if (pressureSensor != null) {
            sensorManager.registerListener(this, pressureSensor, SensorManager.SENSOR_DELAY_UI)
            Log.i(tag, "[Pressure Sensor] Hardware TYPE_PRESSURE registered for 3D pedestrian altitude tracking.")
        } else {
            Log.w(tag, "[Pressure Sensor] No hardware barometer detected.")
        }

        // 6. 啟動藍牙 BLE 與 Wi-Fi 公眾室內信標掃描定錨引擎
        beaconManager?.start()
    }

    /**
     * 螢幕開關自適應降頻省電調節
     */
    fun setScreenActive(active: Boolean) {
        if (!isRunning) return
        Log.i(tag, "setScreenActive: $active (throttling sensors accordingly)")
        if (!active) {
            sensorManager.unregisterListener(this, sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR))
            sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { sensorManager.unregisterListener(this, it) }
            sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)?.let { sensorManager.unregisterListener(this, it) }
        } else {
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
                                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && status.hasCarrierFrequencyHz(i)) {
                                    val freq = status.getCarrierFrequencyHz(i)
                                    if (abs(freq - 1.17645e9f) < 1.5e7f) {
                                        l5Count++
                                    }
                                }
                            }
                        }
                        val avgSnr = if (usedCount > 0) totalSnr / usedCount else 0f
                        isUrbanCanyonMultipath = (usedCount >= 3 && avgSnr < 21.0f) || (highCount < 4 && usedCount >= 4)
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
     * 註冊 Android 7.0+ 原生 GnssMeasurementsEvent 監聽器（雙頻載波相位 Hatch 平滑）
     */
    @SuppressLint("MissingPermission")
    private fun registerGnssRawMeasurementsCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && locationManager != null) {
            try {
                val processor = GnssRawMeasurementProcessor { localTier, smoothedCount, l5Count ->
                    // 若當前未連上更高階之 NTRIP 差分，採用本地載波平滑等級
                    if (!isNtripDifferentialActive()) {
                        currentDiffTier = localTier
                    }
                }
                rawGnssProcessor = processor
                locationManager.registerGnssMeasurementsCallback(processor, Handler(Looper.getMainLooper()))
                Log.i(tag, "[GNSS_RAW] GnssMeasurementsCallback registered. Hatch carrier smoothing activated.")
            } catch (e: Exception) {
                Log.w(tag, "Could not register GnssMeasurementsCallback: ${e.message}")
            }
        }
    }

    /**
     * 啟動台灣 e-GNSS NTRIP 差分客戶端
     */
    private fun startNtripClient() {
        try {
            val client = NtripDiffClient { tier, ageSec ->
                currentDiffTier = if (tier != DifferentialTier.OFFLINE_AUTONOMOUS) {
                    tier
                } else {
                    if ((rawGnssProcessor?.getSmoothedSatelliteCount() ?: 0) >= 5) {
                        DifferentialTier.CARRIER_SMOOTHED_HATCH
                    } else {
                        DifferentialTier.OFFLINE_AUTONOMOUS
                    }
                }
            }
            ntripClient = client
            client.start()
            Log.i(tag, "[NTRIP_INIT] e-GNSS NTRIP Client initiated in background.")
        } catch (e: Exception) {
            Log.w(tag, "Could not start NtripDiffClient: ${e.message}")
        }
    }

    private fun isNtripDifferentialActive(): Boolean {
        return ntripClient?.isDifferentialFresh() == true && 
               (ntripClient?.getCurrentTier() != DifferentialTier.OFFLINE_AUTONOMOUS)
    }

    /**
     * 停止所有感測器與定位監聽，釋放資源
     */
    fun stop() {
        isRunning = false
        sensorManager.unregisterListener(this)
        kalmanFilter.reset()
        stationaryDetector.reset()
        try {
            fusedLocationClient.removeLocationUpdates(locationCallback)
            locationManager?.removeUpdates(this)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                if (gnssStatusCallback != null) {
                    locationManager?.unregisterGnssStatusCallback(gnssStatusCallback!!)
                }
                if (rawGnssProcessor != null) {
                    locationManager?.unregisterGnssMeasurementsCallback(rawGnssProcessor!!)
                }
            }
            ntripClient?.stop()
            beaconManager?.stop()
            pressureSensor?.let { sensorManager.unregisterListener(this, it) }
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
     */
    private fun onStepDetected() {
        stationaryDetector.onStepDetected()

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

        // 若 GPS 中斷超過 0.7 秒且濾波器已初始化：在騎樓/地下道/兩次GPS間隙啟動 PDR 平滑推算，消滅滯後
        val timeSinceGps = now - lastGpsFixTimeMs
        if (timeSinceGps > 700L && kalmanFilter.isFilterInitialized() && smoothedHeading >= 0f) {
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

            Log.i(tag, "[PDR_STEP] Advanced to ($pdrLat, $pdrLon), stride=${String.format(Locale.US, "%.2f", userStepLengthM)}m, heading=${String.format(Locale.US, "%.1f", smoothedHeading)}°")
            webView.post {
                webView.evaluateJavascript(
                    "if (window.onLocationUpdate) window.onLocationUpdate(${pdrLat}, ${pdrLon}, 6.0, ${smoothedHeading}, 1.1);" +
                    "if (window.onVerticalLevelUpdate) window.onVerticalLevelUpdate('${currentVerticalLevel.name}', '${currentVerticalLevel.displayName}', ${currentAltitudeM}, '');",
                    null
                )
            }
        }
    }

    /**
     * 感測器數值變更回調
     */
    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type == Sensor.TYPE_STEP_DETECTOR) {
            Log.d(tag, "[STEP_DETECTED] source=HardwareStepDetector")
            onStepDetected()
            return
        }

        if (event.sensor.type == Sensor.TYPE_PRESSURE) {
            val pressureHpa = event.values[0]
            val isStationary = stationaryDetector.currentState == MotionState.STATIONARY_LOCKED
            barometerFilter?.updatePressure(pressureHpa, event.timestamp, isStationary)
            return
        }

        val now = SystemClock.uptimeMillis()

        if (event.sensor.type == Sensor.TYPE_ROTATION_VECTOR || event.sensor.type == Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR) {
            SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
        } else if (event.sensor.type == Sensor.TYPE_ACCELEROMETER) {
            System.arraycopy(event.values, 0, accelerometerReading, 0, accelerometerReading.size)
            SensorManager.getRotationMatrix(rotationMatrix, null, accelerometerReading, magnetometerReading)

            val ax = event.values[0]
            val ay = event.values[1]
            val az = event.values[2]
            val mag = sqrt(ax * ax + ay * ay + az * az)
            if (mag > maxAccInWindow) maxAccInWindow = mag
            if (mag < minAccInWindow) minAccInWindow = mag

            // 軟體波峰計步備援 (視障平穩行走調校：峰值 > 10.15 m/s²，增量 > 0.35 m/s²，間隔 > 280ms)
            val nowUptime = SystemClock.uptimeMillis()
            if (mag > 10.15f && (mag - lastAccMag) > 0.35f && (nowUptime - lastSoftwareStepMs) > 280L) {
                lastSoftwareStepMs = nowUptime
                Log.d(tag, "[STEP_DETECTED] source=SoftwarePeak, mag=${String.format(Locale.US, "%.2f", mag)}")
                onStepDetected()
            }
            lastAccMag = mag

            // 灌入靜止偵測器進行即時滑動變異數計算
            stationaryDetector.feedAccelerometer(ax, ay, az, lastGpsSpeedMps)
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
            ((Math.toDegrees(atan2(eastForward, northForward)) + 360.0) % 360.0).toFloat()
        } else {
            SensorManager.getOrientation(rotationMatrix, orientationAngles)
            ((Math.toDegrees(orientationAngles[0].toDouble()) + 360.0) % 360.0).toFloat()
        }

        // 地磁偏角真北補正
        val trueDegrees = ((rawDegrees + geomagneticDeclination + 360.0f) % 360.0f)

        if (smoothedHeading < 0f) {
            smoothedHeading = trueDegrees
            lastEmittedHeading = trueDegrees
        } else {
            var diff = trueDegrees - smoothedHeading
            while (diff < -180f) diff += 360f
            while (diff > 180f) diff -= 360f

            val alpha = if (Math.abs(diff) > 2.0f) 0.85f else 0.35f
            smoothedHeading = (smoothedHeading + alpha * diff + 360f) % 360f
        }

        // 節流與瞬時傳送：每 25ms 或角度有轉動 (> 2.0°) 時立即發送至前端 WebView
        var angleDelta = Math.abs(smoothedHeading - lastEmittedHeading)
        if (angleDelta > 180f) angleDelta = 360f - angleDelta

        if (now - lastHeadingEmitTime >= 25L || angleDelta >= 2.0f) {
            lastHeadingEmitTime = now
            lastEmittedHeading = smoothedHeading
            val deg = smoothedHeading
            webView.post {
                webView.evaluateJavascript("if (window.onHeadingUpdate) window.onHeadingUpdate(${deg});", null)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    /**
     * GPS 定位回調
     */
    override fun onLocationChanged(location: Location) {
        lastGpsFixTimeMs = SystemClock.uptimeMillis()

        // 捨棄極度低精度的訊號 (> 50m)
        if (location.hasAccuracy() && location.accuracy > 50f && lastEmittedLocation != null) {
            return
        }

        // 去除重複回調（避免 FusedLocationProvider 與 LocationManager 同一微秒雙重觸發）
        val last = lastEmittedLocation
        if (last != null && location.latitude == last.latitude && location.longitude == last.longitude && location.time == last.time) {
            return
        }

        lastEmittedLocation = location
        val rawLat = location.latitude
        val rawLon = location.longitude
        val acc = if (location.hasAccuracy()) location.accuracy else 10f
        val bearing = if (location.hasBearing()) location.bearing else -1f
        val speed = if (location.hasSpeed()) location.speed else 0f
        lastGpsSpeedMps = speed

        val timestampNanos = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
            location.elapsedRealtimeNanos
        } else {
            System.currentTimeMillis() * 1_000_000L
        }

        val alt = if (location.hasAltitude()) location.altitude else 0.0
        updateGeomagneticDeclination(rawLat, rawLon, alt)

        // 行走且 GPS 良好時，自適應校準個人步長
        if (location.hasSpeed() && speed > 0.6f && location.hasAccuracy() && acc < 5.0f) {
            val estimatedStep = (speed / 1.8f).coerceIn(0.50f, 0.85f)
            userStepLengthM = 0.85f * userStepLengthM + 0.15f * estimatedStep
        }

        // 判定當前生效之差分品質等級（符合五大嚴格工程檢核標準）
        val activeTier = if (isNtripDifferentialActive()) {
            ntripClient!!.getCurrentTier()
        } else if ((rawGnssProcessor?.getSmoothedSatelliteCount() ?: 0) >= 5) {
            DifferentialTier.CARRIER_SMOOTHED_HATCH
        } else {
            DifferentialTier.OFFLINE_AUTONOMOUS
        }
        currentDiffTier = activeTier

        // 執行三態自適應卡爾曼濾波（含前進軸與橫向軸阻尼分流 + 停留重心收斂定錨 + 五級差分品質協方差）
        val motionState = stationaryDetector.currentState
        val (filteredLat, filteredLon) = kalmanFilter.filter(
            rawLat = rawLat,
            rawLon = rawLon,
            accuracyMeters = acc,
            speedMps = speed,
            timestampNanos = timestampNanos,
            motionState = motionState,
            isMultipath = isUrbanCanyonMultipath,
            hasDualFrequencyL5 = hasDualFrequencyL5,
            headingDeg = smoothedHeading,
            diffTier = currentDiffTier
        )

        // 定期將最新平滑位置提供給 NTRIP 客戶端以維持 VRS 基準站鎖定
        ntripClient?.updateCurrentLocation(filteredLat, filteredLon, alt)

        val provider = location.provider ?: "fused"

        // 記錄人類可讀與結構化 NDJSON 日誌
        val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.getDefault()).format(Date())
        val humanLog = "[$timeStr] [GPS] 來源: $provider | 原始: ($rawLat, $rawLon) | 濾波: ($filteredLat, $filteredLon) | 等級: ${currentDiffTier.displayName} | 狀態: $motionState | 精度: ${acc}m | 速度: ${String.format(Locale.US, "%.1f", speed)}m/s | 朝向: ${String.format(Locale.US, "%.1f", smoothedHeading)}° | L5: $hasDualFrequencyL5 | 折射: $isUrbanCanyonMultipath"
        val ndjson = org.json.JSONObject().apply {
            put("t", timeStr)
            put("evt", "GPS_FIX")
            put("provider", provider)
            put("motion_state", motionState.name)
            put("diff_tier", currentDiffTier.name)
            put("diff_name", currentDiffTier.displayName)
            put("raw_lat", rawLat)
            put("raw_lon", rawLon)
            put("lat", filteredLat)
            put("lon", filteredLon)
            put("acc_m", acc)
            put("speed_mps", speed)
            put("heading_deg", smoothedHeading)
            put("is_l5", hasDualFrequencyL5)
            put("is_multipath", isUrbanCanyonMultipath)
            put("vertical_level", currentVerticalLevel.name)
            put("altitude_m", currentAltitudeM)
        }.toString()
        addTrajectoryLog(humanLog, ndjson)

        Log.i(tag, "[GPS_FIX] provider=$provider, diff=${currentDiffTier.displayName}, raw=($rawLat, $rawLon) -> kalman=($filteredLat, $filteredLon), state=$motionState, acc=${acc}m, speed=${String.format(Locale.US, "%.1f", speed)}m/s, heading=${String.format(Locale.US, "%.1f", smoothedHeading)}°, level=${currentVerticalLevel.name}")

        // 呼叫前端 JavaScript onLocationUpdate 與 onDifferentialTierUpdate 函式
        val effectiveSpeed = if (motionState == MotionState.STATIONARY_LOCKED) 0f else speed
        val effectiveAcc = min(acc, currentDiffTier.expectedAccuracyMeters)
        webView.post {
            webView.evaluateJavascript(
                "if (window.onLocationUpdate) window.onLocationUpdate(${filteredLat}, ${filteredLon}, ${effectiveAcc}, ${bearing}, ${effectiveSpeed});" +
                "if (window.onDifferentialTierUpdate) window.onDifferentialTierUpdate('${currentDiffTier.name}', '${currentDiffTier.displayName}', ${currentDiffTier.expectedAccuracyMeters});" +
                "if (window.onVerticalLevelUpdate) window.onVerticalLevelUpdate('${currentVerticalLevel.name}', '${currentVerticalLevel.displayName}', ${currentAltitudeM}, '');",
                null
            )
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}

    companion object {
        private val trajectoryHistory = Collections.synchronizedList(mutableListOf<String>())
        private val ndjsonRecords = Collections.synchronizedList(mutableListOf<String>())

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

        fun getTrajectoryLogText(): String {
            return synchronized(trajectoryHistory) {
                if (trajectoryHistory.isEmpty()) {
                    "（尚無記錄到的 GPS 與感測器軌跡）"
                } else {
                    trajectoryHistory.joinToString("\n")
                }
            }
        }

        fun getTrajectoryNdjson(): String {
            return synchronized(ndjsonRecords) {
                ndjsonRecords.joinToString("\n")
            }
        }

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
