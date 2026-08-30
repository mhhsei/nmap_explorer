package com.example.nmapexplorer

import android.os.SystemClock
import android.util.Log
import java.util.Locale
import kotlin.math.abs
import kotlin.math.pow

/**
 * 【垂直三度空間樓層列舉 (Vertical Level)】
 * 
 * 作用：界定視障者在現實立體空間中的垂直高度層次，徹底消滅「在人行天橋上卻報讀橋下店家」的死角。
 */
enum class VerticalLevel(val displayName: String, val spokenPrefix: String) {
    /** 1. 一般平面地面層 (Ground Level) */
    GROUND("地面層", "位於地面層"),

    /** 2. 人行天橋或商場二樓 (Overpass / 2F) */
    OVERPASS("人行天橋/二樓", "已登上人行天橋"),

    /** 3. 捷運站地下一樓或地下連通道 (Underground B1) */
    UNDERGROUND("地下連通道/B1", "已進入地下連通道"),

    /** 4. 捷運地下二樓月台大廳 (Underground B2) */
    UNDERGROUND_B2("捷運大廳/B2", "已進入地下二樓大廳")
}

/**
 * 【氣壓計一維垂直卡爾曼濾波器與三度空間樓層引擎 (BarometerVerticalFilter)】
 * 
 * 生活化比喻（小學生都看得懂）：
 * 就像在手機裡裝了一台微型「高度測量天平」。
 * 當您走上人行天橋的樓梯時，空氣會變得稍微稀薄一點點（氣壓微幅下降）；
 * 當您走下捷運地下連通道時，空氣又會變厚一點點（氣壓微幅上升）。
 * 這台引擎能精確抓住這幾公分的氣壓微變，即使閉著眼睛，也能準確知道您正站在天橋上還是走進了地下道！
 */
class BarometerVerticalFilter(
    private val onLevelChanged: (VerticalLevel, Float, String) -> Unit
) {
    private val tag = "BarometerVertical"

    // 基準地面海平面等效氣壓 (hPa)
    private var baselinePressureHpa: Float = 1013.25f
    private var isBaselineInitialized = false

    // 一維卡爾曼狀態向量：[高度 h (公尺), 垂直速度 vz (公尺/秒)]
    private var stateAltitudeM = 0.0f
    private var stateVelocityMps = 0.0f

    // 協方差矩陣 P: [[P00, P01], [P10, P11]]
    private var p00 = 1.0f
    private var p01 = 0.0f
    private var p10 = 0.0f
    private var p11 = 1.0f

    private var lastTimestampNs: Long = 0L
    private var lastRawPressureHpa: Float = 1013.25f

    fun getRawPressure(): Float = lastRawPressureHpa
    fun getBaselinePressure(): Float = baselinePressureHpa
    fun getAltitude(): Float = stateAltitudeM
    fun getVelocity(): Float = stateVelocityMps

    // 當前樓層狀態
    var currentLevel: VerticalLevel = VerticalLevel.GROUND
        private set

    // 遲滯與防抖鎖定計時器
    private var lastLevelTransitionTimeMs = 0L
    private var sustainedCandidateLevel: VerticalLevel? = null
    private var sustainedStartTimeMs = 0L

    companion object {
        /** 判定為人行天橋的進入高度門檻 (公尺)：爬上天橋通常高於地面 3.5 公尺以上 */
        const val OVERPASS_ENTER_ALTITUDE_M = 3.5f
        /** 離開人行天橋回歸地面的退出門檻 (公尺)：防止在階梯邊緣猶豫徘徊時頻繁跳針 */
        const val OVERPASS_EXIT_ALTITUDE_M = 2.2f

        /** 進入地下道/B1的下潛門檻 (公尺)：走下地下道通常低於地面 2.5 公尺 */
        const val UNDERGROUND_B1_ENTER_ALTITUDE_M = -2.6f
        /** 離開地下道回歸地面的退出門檻 (公尺) */
        const val UNDERGROUND_B1_EXIT_ALTITUDE_M = -1.6f

        /** 進入地下二樓 B2 的下潛門檻 (公尺)：捷運轉乘月台通常在地下 6 公尺以上 */
        const val UNDERGROUND_B2_ENTER_ALTITUDE_M = -6.2f
        /** 離開地下二樓回到 B1 的退出門檻 (公尺) */
        const val UNDERGROUND_B2_EXIT_ALTITUDE_M = -4.8f

        /** 靜止手持時氣壓感測器量測雜訊變異數 R (m^2)：約 0.12 m^2 (標準差 0.35m) */
        const val MEASUREMENT_NOISE_R = 0.12f

        /** 垂直加速度過程雜訊 q_acc (m^2/s^3)：步行上下樓梯時的垂直擾動 */
        const val PROCESS_NOISE_Q_ACC = 0.06f

        /** 人類垂直步行生理極限速度 (m/s)：上下樓梯正常為 0.2~0.4 m/s，奔跑極限不超過 0.75 m/s */
        const val MAX_PHYSICAL_VERTICAL_VELOCITY_MPS = 0.75f

        /** 樓層切換防抖冷卻鎖定 (毫秒)：切換後至少維持 8 秒，禁止瘋狂跳針切換 */
        const val LEVEL_TRANSITION_COOLDOWN_MS = 8000L

        /** 進入新樓層所需的持續穩定時間 (毫秒)：高度超標必須連續維持 2.0 秒，徹底消滅褲管活塞脈衝 */
        const val SUSTAINED_DURATION_MS = 2000L
    }

    /**
     * 輸入即時氣壓讀數 (hPa)，執行垂直卡爾曼濾波
     * 
     * @param pressureHpa 氣壓計數值 (hPa)
     * @param timestampNs 納秒時間戳記
     * @param isStationaryOnGround 使用者是否正處於地面靜止狀態（用於平滑微調基準氣壓）
     * @param isWalking 使用者是否正在行走步行（用於動態放大阻尼，過濾步態晃動）
     * @param isPocketLikely 手機是否被判定處於口袋或包包中（開啟強力阻尼，抵抗微壓活塞擠壓）
     */
    fun updatePressure(
        pressureHpa: Float, 
        timestampNs: Long, 
        isStationaryOnGround: Boolean = false,
        isWalking: Boolean = false,
        isPocketLikely: Boolean = false
    ): Pair<VerticalLevel, Float> {
        if (pressureHpa <= 300f || pressureHpa >= 1100f) {
            return Pair(currentLevel, stateAltitudeM)
        }

        lastRawPressureHpa = pressureHpa

        // 1. 初始化地面基準氣壓
        if (!isBaselineInitialized) {
            baselinePressureHpa = pressureHpa
            isBaselineInitialized = true
            lastTimestampNs = timestampNs
            Log.i(tag, "[INIT] Baseline ground pressure initialized to ${String.format(Locale.US, "%.2f", baselinePressureHpa)} hPa")
            return Pair(currentLevel, 0.0f)
        }

        // 當確認在地面且靜止時，極慢速追蹤大氣天氣變化（時間常數約 20 分鐘）
        if (isStationaryOnGround && currentLevel == VerticalLevel.GROUND) {
            baselinePressureHpa = 0.9995f * baselinePressureHpa + 0.0005f * pressureHpa
        }

        // 2. 利用國際標準大氣公式計算相對高程 (Hypsometric Formula)
        // h = 44330 * (1 - (P / P0)^(1/5.255))
        val rawRelativeAltitudeM = 44330.0f * (1.0f - (pressureHpa / baselinePressureHpa).pow(1.0f / 5.255f))

        // 3. 卡爾曼時間更新 (Predict Step)
        val dtSec = if (lastTimestampNs > 0L) {
            ((timestampNs - lastTimestampNs).coerceIn(10_000_000L, 500_000_000L)) / 1_000_000_000.0f
        } else {
            0.05f
        }
        lastTimestampNs = timestampNs

        // 狀態預測：h = h + vz * dt
        val predAltitude = stateAltitudeM + stateVelocityMps * dtSec
        val predVelocity = stateVelocityMps

        // 協方差預測：P = F * P * F^T + Q
        val dt2 = dtSec * dtSec
        val dt3 = dt2 * dtSec
        val q00 = 0.333f * dt3 * PROCESS_NOISE_Q_ACC
        val q01 = 0.5f * dt2 * PROCESS_NOISE_Q_ACC
        val q11 = dtSec * PROCESS_NOISE_Q_ACC

        val newP00 = p00 + dtSec * (p10 + p01) + dt2 * p11 + q00
        val newP01 = p01 + dtSec * p11 + q01
        val newP10 = p10 + dtSec * p11 + q01
        val newP11 = p11 + q11

        // 4. 卡爾曼測量更新 (Measurement Update Step)
        // 自適應動態量測雜訊 R：
        // • 手機在口袋活塞擠壓中：R 放大至 5.50 (強力阻尼低通濾波，吃掉 8hPa 震盪)
        // • 正常行走晃動：R 放大至 1.60 (中度阻尼)
        // • 靜止手持：R 維持 0.12 (高靈敏度)
        val dynamicR = when {
            isPocketLikely -> 5.50f
            isWalking -> 1.60f
            else -> MEASUREMENT_NOISE_R
        }

        // 新息 (Innovation): y = z - h_pred
        val innovation = rawRelativeAltitudeM - predAltitude
        val s = newP00 + dynamicR

        // 卡爾曼增益 K = P * H^T / S
        val k0 = newP00 / s
        val k1 = newP10 / s

        stateAltitudeM = predAltitude + k0 * innovation
        // 限制垂直升降速度至人體生理極限 (防範單一脈衝引發速度暴走)
        stateVelocityMps = (predVelocity + k1 * innovation).coerceIn(-MAX_PHYSICAL_VERTICAL_VELOCITY_MPS, MAX_PHYSICAL_VERTICAL_VELOCITY_MPS)

        // 更新協方差矩陣 P = (I - K * H) * P
        p00 = (1.0f - k0) * newP00
        p01 = (1.0f - k0) * newP01
        p10 = -k1 * newP00 + newP10
        p11 = -k1 * newP01 + newP11

        // 5. 雙向防抖遲滯與持續時間檢驗狀態機 (Sustained Hysteresis Level State Machine)
        evaluateLevelTransition(stateAltitudeM)

        return Pair(currentLevel, stateAltitudeM)
    }

    /**
     * 遲滯狀態機判斷：杜絕在樓梯邊緣上下徘徊時頻繁跳針切換
     * 結合「持續時間門檻 (2.0s)」與「轉態防抖鎖定 (8.0s)」，徹底消滅口袋活塞誤判
     */
    private fun evaluateLevelTransition(altM: Float) {
        val nowMs = SystemClock.uptimeMillis()
        val oldLevel = currentLevel
        var rawTargetLevel = oldLevel

        when (oldLevel) {
            VerticalLevel.GROUND -> {
                if (altM >= OVERPASS_ENTER_ALTITUDE_M) {
                    rawTargetLevel = VerticalLevel.OVERPASS
                } else if (altM <= UNDERGROUND_B1_ENTER_ALTITUDE_M) {
                    rawTargetLevel = VerticalLevel.UNDERGROUND
                }
            }
            VerticalLevel.OVERPASS -> {
                if (altM < OVERPASS_EXIT_ALTITUDE_M) {
                    rawTargetLevel = VerticalLevel.GROUND
                }
            }
            VerticalLevel.UNDERGROUND -> {
                if (altM > UNDERGROUND_B1_EXIT_ALTITUDE_M) {
                    rawTargetLevel = VerticalLevel.GROUND
                } else if (altM <= UNDERGROUND_B2_ENTER_ALTITUDE_M) {
                    rawTargetLevel = VerticalLevel.UNDERGROUND_B2
                }
            }
            VerticalLevel.UNDERGROUND_B2 -> {
                if (altM > UNDERGROUND_B2_EXIT_ALTITUDE_M) {
                    rawTargetLevel = VerticalLevel.UNDERGROUND
                }
            }
        }

        // 1. 若目標樓層回到目前所在樓層，立即重置持續計時器
        if (rawTargetLevel == oldLevel) {
            sustainedCandidateLevel = null
            sustainedStartTimeMs = 0L
            return
        }

        // 2. 轉態防抖鎖定：若距離上次樓層切換未滿 8 秒，直接抑制跳轉
        if (nowMs - lastLevelTransitionTimeMs < LEVEL_TRANSITION_COOLDOWN_MS) {
            return
        }

        // 3. 持續時間檢驗：高度超標必須連續維持超過 2.0 秒，絕不容許褲管活塞瞬態脈衝誤觸
        if (sustainedCandidateLevel != rawTargetLevel) {
            sustainedCandidateLevel = rawTargetLevel
            sustainedStartTimeMs = nowMs
            return
        }

        if (nowMs - sustainedStartTimeMs < SUSTAINED_DURATION_MS) {
            return
        }

        // 4. 正式批准樓層切換
        currentLevel = rawTargetLevel
        lastLevelTransitionTimeMs = nowMs
        sustainedCandidateLevel = null
        sustainedStartTimeMs = 0L

        val altSign = if (altM >= 0) "+" else ""
        val desc = "📍 偵測${rawTargetLevel.spokenPrefix}（高度 ${altSign}${String.format(Locale.US, "%.1f", altM)} 公尺），已切換為${rawTargetLevel.displayName}圖資。"
        Log.i(tag, "[LEVEL_TRANSITION] ${oldLevel.name} -> ${rawTargetLevel.name} (alt: ${altM}m, vz: ${String.format(Locale.US, "%.2f", stateVelocityMps)}m/s)")
        onLevelChanged(rawTargetLevel, altM, desc)
    }

    /**
     * 外部手動校準基準高度（例如透過已知捷運站出口或已知公眾 Beacon 定錨）
     */
    fun calibrateBaseline(knownAltitudeM: Float) {
        // 反推基準氣壓以吻合已知高度
        if (stateAltitudeM != 0f) {
            stateAltitudeM = knownAltitudeM
            evaluateLevelTransition(stateAltitudeM)
            Log.i(tag, "[CALIBRATE] Vertical altitude manually anchored to ${knownAltitudeM}m (Level: ${currentLevel.name})")
        }
    }
}
