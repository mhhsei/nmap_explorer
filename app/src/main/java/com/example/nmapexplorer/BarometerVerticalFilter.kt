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
    UNDERGROUND_B2("捷運大廳/B2", "已進入地下二樓大廳"),
    
    // 新增室內商場絕對樓層
    INDOOR_B5("室內 B5", "已進入 B5"),
    INDOOR_B4("室內 B4", "已進入 B4"),
    INDOOR_B3("室內 B3", "已進入 B3"),
    INDOOR_B2("室內 B2", "已進入 B2"),
    INDOOR_B1("室內 B1", "已進入 B1"),
    INDOOR_2F("室內 2樓", "已進入 2樓"),
    INDOOR_3F("室內 3樓", "已進入 3樓"),
    INDOOR_4F("室內 4樓", "已進入 4樓"),
    INDOOR_5F("室內 5樓", "已進入 5樓"),
    INDOOR_6F("室內 6樓", "已進入 6樓"),
    INDOOR_7F("室內 7樓", "已進入 7樓"),
    INDOOR_8F("室內 8樓", "已進入 8樓"),
    INDOOR_9F("室內 9樓", "已進入 9樓"),
    INDOOR_10F("室內 10樓", "已進入 10樓")
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
    fun isInitialized(): Boolean = isBaselineInitialized

    // 當前樓層狀態
    var currentLevel: VerticalLevel = VerticalLevel.GROUND
        private set

    // 遲滯與防抖鎖定計時器
    private var lastLevelTransitionTimeMs = 0L
    private var sustainedCandidateLevel: VerticalLevel? = null
    private var sustainedStartTimeMs = 0L

    companion object {
        /** 判定為人行天橋的進入高度門檻 (公尺)：台灣實體天橋主樑淨空通常高於路面 4.5~5.5 公尺，設 4.2 公尺消滅平地風壓突波 */
        const val OVERPASS_ENTER_ALTITUDE_M = 4.2f
        /** 離開人行天橋回歸地面的退出門檻 (公尺)：防止在階梯邊緣猶豫徘徊時頻繁跳針 */
        const val OVERPASS_EXIT_ALTITUDE_M = 2.5f

        /** 進入地下道/B1的下潛門檻 (公尺)：走下地下道通常低於地面 3.0 公尺以上 */
        const val UNDERGROUND_B1_ENTER_ALTITUDE_M = -3.0f
        /** 離開地下道回歸地面的退出門檻 (公尺) */
        const val UNDERGROUND_B1_EXIT_ALTITUDE_M = -1.8f

        /** 靜止手持時氣壓感測器量測雜訊變異數 R (m^2)：約 0.12 m^2 (標準差 0.35m) */
        const val MEASUREMENT_NOISE_R = 0.12f

        /** 垂直加速度過程雜訊 q_acc (m^2/s^3)：步行上下樓梯時的垂直擾動 */
        const val PROCESS_NOISE_Q_ACC = 0.06f

        /** 人類垂直步行生理極限速度 (m/s)：上下樓梯正常為 0.2~0.4 m/s，奔跑極限不超過 0.75 m/s */
        const val MAX_PHYSICAL_VERTICAL_VELOCITY_MPS = 0.75f

        /** 樓層切換防抖冷卻鎖定 (毫秒)：切換後至少維持 10 秒，禁止瘋狂跳針切換 */
        const val LEVEL_TRANSITION_COOLDOWN_MS = 10000L

        /** 進入新樓層所需的持續穩定時間 (毫秒)：高度超標必須連續維持超過 4.5 秒，徹底消滅戶外側風與空調氣壓突波 */
        const val SUSTAINED_DURATION_MS = 4500L
    }

    /**
     * 強制重置回地面層 (GPS 霸體覆寫)
     * 當由外部 (如 JS 路網吸附) 判定使用者確實沿著戶外實體道路前進時，無條件瞬間拉回地面，消滅卡死！
     */
    fun forceResetToGround() {
        if (currentLevel != VerticalLevel.GROUND) {
            Log.w(tag, "[FORCE_RESET] Outdoor road snapped, forcibly resetting level from ${currentLevel.name} to GROUND.")
            currentLevel = VerticalLevel.GROUND
            lastLevelTransitionTimeMs = SystemClock.uptimeMillis()
            onLevelChanged(VerticalLevel.GROUND, 0.0f, "📍 已回到戶外平面道路，強制重置為地面層圖資。")
        }
        // 瞬間追蹤當前氣壓，抹平坡度
        baselinePressureHpa = lastRawPressureHpa
        stateAltitudeM = 0.0f
        stateVelocityMps = 0.0f
    }
    
    private var lastKnownDemGroundElevation: Float? = null

    fun setDemGroundElevation(elevationM: Float) {
        lastKnownDemGroundElevation = elevationM
    }

    /**
     * 輸入即時氣壓讀數 (hPa)，執行垂直卡爾曼濾波
     * 
     * @param pressureHpa 氣壓計數值 (hPa)
     * @param timestampNs 納秒時間戳記
     * @param isStationaryOnGround 使用者是否正處於地面靜止狀態
     * @param isWalking 使用者是否正在行走步行
     * @param isPocketLikely 手機是否被判定處於口袋或包包中
     * @param isGpsWeak GPS 訊號是否微弱 (代表進入室內商場)
     */
    fun updatePressure(
        pressureHpa: Float, 
        timestampNs: Long, 
        isStationaryOnGround: Boolean = false,
        isWalking: Boolean = false,
        isPocketLikely: Boolean = false,
        isGpsWeak: Boolean = false
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

        val dtSec = if (lastTimestampNs > 0L) {
            ((timestampNs - lastTimestampNs).coerceIn(10_000_000L, 500_000_000L)) / 1_000_000_000.0f
        } else {
            0.05f
        }
        lastTimestampNs = timestampNs

        // 基準大氣壓力動態平滑更新：
        // 只有在「戶外 (GPS 強)」時才緩慢追蹤氣壓漂移。
        // 若判定進入室內商場 (isGpsWeak)，則「凍結」 baselinePressureHpa，作為該建築的 1F 絕對基準。
        if (!isGpsWeak && currentLevel == VerticalLevel.GROUND) {
            val alpha = if (isStationaryOnGround) 0.0008f else if (isWalking && !isPocketLikely) 0.0002f else 0.0f
            if (alpha > 0f) {
                // Time-based EMA approximation to prevent sample-rate dependency
                val timeScaledAlpha = 1.0f - kotlin.math.exp(-alpha * dtSec * 50f) 
                baselinePressureHpa = (1.0f - timeScaledAlpha) * baselinePressureHpa + timeScaledAlpha * pressureHpa
            }
        }

        // 2. 利用國際標準大氣公式計算相對高程 (Hypsometric Formula)
        val rawRelativeAltitudeM = 44330.0f * (1.0f - (pressureHpa / baselinePressureHpa).pow(1.0f / 5.255f))

        // 3. 卡爾曼時間更新 (Predict Step)
        val predAltitude = stateAltitudeM + stateVelocityMps * dtSec
        val predVelocity = stateVelocityMps

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
        val dynamicR = when {
            isPocketLikely -> 5.50f
            isWalking -> 1.60f
            else -> MEASUREMENT_NOISE_R
        }

        val innovation = rawRelativeAltitudeM - predAltitude
        val s = newP00 + dynamicR
        val k0 = newP00 / s
        val k1 = newP10 / s

        stateAltitudeM = predAltitude + k0 * innovation
        stateVelocityMps = (predVelocity + k1 * innovation).coerceIn(-MAX_PHYSICAL_VERTICAL_VELOCITY_MPS, MAX_PHYSICAL_VERTICAL_VELOCITY_MPS)

        p00 = (1.0f - k0) * newP00
        p01 = (1.0f - k0) * newP01
        p10 = -k1 * newP00 + newP10
        p11 = -k1 * newP01 + newP11

        // 5. 雙向防抖遲滯與持續時間檢驗狀態機
        evaluateLevelTransition(stateAltitudeM, isGpsWeak)

        return Pair(currentLevel, stateAltitudeM)
    }

    private fun evaluateLevelTransition(altM: Float, isGpsWeak: Boolean) {
        val nowMs = SystemClock.uptimeMillis()
        val oldLevel = currentLevel
        var rawTargetLevel = oldLevel

        if (isGpsWeak) {
            // 室內商場絕對樓層模式 (每層樓約 3.2 ~ 3.5 公尺)
            rawTargetLevel = when {
                altM >= 28.8f -> VerticalLevel.INDOOR_10F
                altM >= 25.6f -> VerticalLevel.INDOOR_9F
                altM >= 22.4f -> VerticalLevel.INDOOR_8F
                altM >= 19.2f -> VerticalLevel.INDOOR_7F
                altM >= 16.0f -> VerticalLevel.INDOOR_6F
                altM >= 12.8f -> VerticalLevel.INDOOR_5F
                altM >= 9.6f -> VerticalLevel.INDOOR_4F
                altM >= 6.4f -> VerticalLevel.INDOOR_3F
                altM >= 2.0f -> VerticalLevel.INDOOR_2F
                altM <= -16.0f -> VerticalLevel.INDOOR_B5
                altM <= -12.8f -> VerticalLevel.INDOOR_B4
                altM <= -9.6f -> VerticalLevel.INDOOR_B3
                altM <= -6.4f -> VerticalLevel.INDOOR_B2
                altM <= -2.0f -> VerticalLevel.INDOOR_B1
                else -> VerticalLevel.GROUND
            }
        } else {
            // 戶外天橋/地下道模式
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
                VerticalLevel.UNDERGROUND, VerticalLevel.UNDERGROUND_B2 -> {
                    if (altM > UNDERGROUND_B1_EXIT_ALTITUDE_M) {
                        rawTargetLevel = VerticalLevel.GROUND
                    }
                }
                else -> {
                    // 若在戶外 (GPS 強) 但先前狀態誤切入室內樓層，無條件回歸地面層並重新校準基準氣壓
                    if (!isGpsWeak) {
                        rawTargetLevel = VerticalLevel.GROUND
                        baselinePressureHpa = lastRawPressureHpa
                        stateAltitudeM = 0.0f
                    }
                }
            }
        }

        if (rawTargetLevel == oldLevel) {
            sustainedCandidateLevel = null
            sustainedStartTimeMs = 0L
            return
        }

        // 轉態防抖鎖定
        if (nowMs - lastLevelTransitionTimeMs < LEVEL_TRANSITION_COOLDOWN_MS) {
            return
        }

        // 持續時間檢驗 (室內樓層切換較快 2 秒，戶外天橋需 4.5 秒)
        val requiredDuration = if (isGpsWeak) 2000L else SUSTAINED_DURATION_MS

        if (sustainedCandidateLevel != rawTargetLevel) {
            sustainedCandidateLevel = rawTargetLevel
            sustainedStartTimeMs = nowMs
            return
        }

        if (nowMs - sustainedStartTimeMs < requiredDuration) {
            return
        }

        // 正式批准樓層切換
        currentLevel = rawTargetLevel
        lastLevelTransitionTimeMs = nowMs
        sustainedCandidateLevel = null
        sustainedStartTimeMs = 0L

        val altSign = if (altM >= 0) "+" else ""
        val desc = "📍 偵測${rawTargetLevel.spokenPrefix}（高度 ${altSign}${String.format(Locale.US, "%.1f", altM)} 公尺），已切換為${rawTargetLevel.displayName}圖資。"
        Log.i(tag, "[LEVEL_TRANSITION] ${oldLevel.name} -> ${rawTargetLevel.name} (alt: ${altM}m, vz: ${String.format(Locale.US, "%.2f", stateVelocityMps)}m/s, indoor: $isGpsWeak)")
        onLevelChanged(rawTargetLevel, altM, desc)
    }

    fun calibrateBaseline(knownAltitudeM: Float) {
        if (stateAltitudeM != 0f) {
            stateAltitudeM = knownAltitudeM
            evaluateLevelTransition(stateAltitudeM, false)
            Log.i(tag, "[CALIBRATE] Vertical altitude manually anchored to ${knownAltitudeM}m (Level: ${currentLevel.name})")
        }
    }

    /**
     * 【依據 NASA SRTM 當地地表真實裸地海拔與 GPS 橢球高反推標準地面大氣壓】
     * 作用：徹底解決使用者在 5 樓開機時，將 5 樓氣壓誤認作地面基準 0 米之問題。
     * 防護：嚴格限定相對高度在 [-15m, 45m] 合理範圍內，杜絕都會峽谷 GPS 垂直幾十米巨大跳針毀滅氣壓基準。
     */
     fun calibrateBaselineFromDem(groundDemElevationM: Float, currentGpsAltitudeM: Float) {
        lastKnownDemGroundElevation = groundDemElevationM
        val relAltM = currentGpsAltitudeM - groundDemElevationM
        // 安全門檻：若反推的高度差在合理範圍 (-15m ~ 45m) 內才進行基準校準，杜絕 70m 假高程摧毀氣壓計
        if (relAltM in -15f..45f && lastRawPressureHpa in 300f..1100f) {
            val ratio = (1.0f - (relAltM / 44330.0f)).coerceIn(0.1f, 1.5f)
            val p0 = (lastRawPressureHpa / ratio.pow(5.255f)).coerceIn(800f, 1150f)
            baselinePressureHpa = p0
            // 僅在尚未初始化時賦予初始高度，避免在運動中強行覆寫卡爾曼平滑高度
            if (!isBaselineInitialized) {
                stateAltitudeM = relAltM
                isBaselineInitialized = true
                evaluateLevelTransition(stateAltitudeM, false)
            }
            Log.i(tag, "[CALIBRATE_DEM] Ground baseline calibrated from DEM ($groundDemElevationM m) & GPS Alt ($currentGpsAltitudeM m): P0=${String.format(Locale.US, "%.2f", p0)} hPa, relAlt=${String.format(Locale.US, "%.1f", relAltM)}m")
        } else {
            Log.w(tag, "[CALIBRATE_DEM_REJECTED] Ignored outlier GPS vertical elevation: GPS Alt=$currentGpsAltitudeM m, DEM=$groundDemElevationM m, relAlt=$relAltM m")
        }
    }

    /**
     * 【無氣壓計時之 GPS / SRTM 雙軌高度與層級直接覆寫】
     */
    fun setAltitudeAndLevelDirect(altM: Float, level: VerticalLevel, desc: String) {
        stateAltitudeM = altM
        currentLevel = level
        onLevelChanged(level, altM, desc)
    }
}
