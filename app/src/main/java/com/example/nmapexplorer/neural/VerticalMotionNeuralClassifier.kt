package com.example.nmapexplorer.neural

import java.util.ArrayDeque
import kotlin.math.abs
import kotlin.math.max

/**
 * 【項目 4：氣壓計微波形與垂直運動神經分類器 (VerticalMotionNeuralClassifier)】
 *
 * 核心使命（生活化比喻）：
 * 就像登山者的「耳壓與腿部肌肉神經」。
 * 單純的氣壓計非常脆弱，進出冷氣房的一陣強風就能讓氣壓跳動 0.5 hPa，
 * 導致系統把人在 2 樓走廊誤判成在 1 樓中庭吃雞腿！
 * 本神經引擎同時觀察「氣壓微差斜率 (dP/dt)」與「人體垂直加速度脈衝」：
 * 1. 爬樓梯：氣壓階梯式微跳 + 每一步有 2Hz 的垂直踩踏反彈。
 * 2. 搭電梯：氣壓高速平滑狂瀉 + 身體完全沒有邁步震動。
 * 3. 吹冷氣/風切：只有氣壓亂飄，零步態關聯，立即鎖定當前樓層拒絕誤判！
 */
class VerticalMotionNeuralClassifier(
    private val onMotionStateChanged: (VerticalMotionType, String, Float) -> Unit
) {

    enum class VerticalMotionType(val description: String) {
        /** 1. 水平走廊/平地 (樓層牢固鎖定) */
        HORIZONTAL_CORRIDOR("水平平地/走廊"),

        /** 2. 步行走樓梯上樓 */
        WALKING_STAIRS_UP("走樓梯上樓"),

        /** 3. 步行走樓梯下樓 */
        WALKING_STAIRS_DOWN("走樓梯下樓"),

        /** 4. 搭乘無障礙電梯移動中 */
        ELEVATOR_MOVING("搭乘電梯中")
    }

    // 氣壓滑動歷史隊列 (timestampMs -> pressureHpa)
    private val pressureHistory = ArrayDeque<Pair<Long, Float>>()
    // 垂直加速度滑動隊列
    private val verticalAccHistory = ArrayDeque<Float>()

    private var baselinePressureHpa = 1013.25f
    private var isBaselineCalibrated = false

    // 當前推算樓層
    var currentFloorIndex: Int = 1 // 1 = 1F, 2 = 2F, 0 = B1
        private set

    var currentMotionType: VerticalMotionType = VerticalMotionType.HORIZONTAL_CORRIDOR
        private set

    private var accumulatedRelativeAltitudeM = 0.0f
    private var lastStateChangeTimeMs = 0L

    /**
     * 校準基準氣壓 (通常於室外 GPS 良好時定錨)
     */
    fun calibrateBaseline(groundPressureHpa: Float) {
        baselinePressureHpa = groundPressureHpa
        isBaselineCalibrated = true
    }

    /**
     * 灌入氣壓與步態即時數據 (5~10Hz)
     * @param pressureHpa 當前氣壓 (hPa)
     * @param verticalAcc 垂直加速度 (m/s^2)
     * @param isStepRecently 是否近期有踩出步伐
     */
    fun feedSample(nowMs: Long, pressureHpa: Float, verticalAcc: Float, isStepRecently: Boolean) {
        if (!isBaselineCalibrated) {
            baselinePressureHpa = pressureHpa
            isBaselineCalibrated = true
        }

        pressureHistory.addLast(Pair(nowMs, pressureHpa))
        while (pressureHistory.isNotEmpty() && (nowMs - pressureHistory.first().first) > 3000L) {
            pressureHistory.removeFirst()
        }

        verticalAccHistory.addLast(verticalAcc)
        if (verticalAccHistory.size > 25) verticalAccHistory.removeFirst()

        if (pressureHistory.size < 5) return

        // 1. 計算氣壓變化率 dP/dt (hPa/s)
        val dtSec = (pressureHistory.last().first - pressureHistory.first().first) / 1000f
        if (dtSec < 0.8f) return
        val dP = pressureHistory.last().second - pressureHistory.first().second
        val dPdt = dP / dtSec

        // 換算等效垂直高度變化 (台灣海平面 1 hPa 約等於 8.43 公尺高度差)
        // 氣壓下降 (dP < 0) 代表往上爬升；氣壓上升 (dP > 0) 代表往下下降
        val altitudeDelta = -(dP * 8.43f)
        accumulatedRelativeAltitudeM = -(pressureHpa - baselinePressureHpa) * 8.43f

        // 2. 垂直震動能量 (Vertical Energy Spectrum)
        var accSum = 0f
        for (a in verticalAccHistory) accSum += a
        val accMean = accSum / verticalAccHistory.size
        var accVar = 0f
        for (a in verticalAccHistory) {
            val d = a - accMean
            accVar += d * d
        }
        val verticalEnergy = accVar / verticalAccHistory.size

        // 3. 多特徵神經推論分類
        val newMotion: VerticalMotionType
        val floorStepHeightM = 3.2f // 台灣標準建築一樓層約 3.0 ~ 3.5 米

        // A. 爬樓梯特徵：氣壓有持續變化 (|dPdt| in 0.035..0.18 hPa/s) 且 垂直震動能量活躍 (accVar > 0.35) 且 伴隨步伐
        if (dPdt < -0.035f && isStepRecently && verticalEnergy > 0.25f) {
            newMotion = VerticalMotionType.WALKING_STAIRS_UP
        } else if (dPdt > 0.035f && isStepRecently && verticalEnergy > 0.25f) {
            newMotion = VerticalMotionType.WALKING_STAIRS_DOWN
        }
        // B. 搭電梯特徵：氣壓劇烈變化 (|dPdt| > 0.22 hPa/s) 但身體幾乎無步伐震動 (verticalEnergy < 0.15)
        else if (abs(dPdt) > 0.22f && verticalEnergy < 0.18f) {
            newMotion = VerticalMotionType.ELEVATOR_MOVING
        }
        // C. 平地走廊特徵：氣壓變化小，或純粹是空調風切
        else {
            newMotion = VerticalMotionType.HORIZONTAL_CORRIDOR
        }

        // 4. 樓層推算與防抖
        val rawFloorOffset = (accumulatedRelativeAltitudeM / floorStepHeightM).toInt()
        val calculatedFloor = 1 + rawFloorOffset

        if (newMotion != currentMotionType && (nowMs - lastStateChangeTimeMs > 2000L)) {
            currentMotionType = newMotion
            currentFloorIndex = calculatedFloor
            lastStateChangeTimeMs = nowMs

            val floorString = when {
                currentFloorIndex <= 0 -> "B${abs(currentFloorIndex - 1)}"
                else -> "${currentFloorIndex}F"
            }
            onMotionStateChanged(newMotion, floorString, accumulatedRelativeAltitudeM)
        }
    }
}
