package com.example.nmapexplorer

import kotlin.math.abs
import kotlin.math.min

/**
 * 【單顆衛星載波相位平滑 Hatch 濾波器 (Single-Satellite Hatch Filter)】
 * 
 * 生活化比喻：
 * 偽距（Code Pseudorange）就像碼錶量時間，每秒都因為大氣層抖動幾公尺，但長期不會偏；
 * 載波相位（Carrier Phase）就像極精密的齒輪，轉動滑順到毫米，但一旦撞到牆跳齒（週跳 Cycle Slip）就會失準。
 * Hatch 濾波器就是用「滑順的齒輪」把「抖動的碼錶」拉直成一條筆直線，消除 70% 的反射雜訊！
 */
class HatchFilter(
    val svid: Int,
    val constellationType: Int,
    private val maxEpochs: Int = 50
) {
    private var smoothedPseudorange: Double = 0.0
    private var lastAccumulatedDeltaRangeM: Double = 0.0
    private var epochCount: Int = 0
    private var isInitialized: Boolean = false

    /**
     * 灌入單顆衛星最新一曆元的觀測值
     * 
     * @param rawPseudorangeM 原始偽距（公尺）
     * @param accumulatedDeltaRangeM 累計載波相位變化量（公尺）
     * @param adrState 載波相位狀態旗標 (GnssMeasurement.ADR_STATE_*)
     * @return 平滑後的偽距（公尺）
     */
    fun update(
        rawPseudorangeM: Double,
        accumulatedDeltaRangeM: Double,
        adrState: Int
    ): Double {
        // 嚴格檢驗標準：檢查載波相位有效性與週跳 (Cycle Slip)
        // ADR_STATE_VALID = 1
        // ADR_STATE_RESET = 2
        // ADR_STATE_CYCLE_SLIP = 4
        val isValid = (adrState and 1) != 0
        val isReset = (adrState and 2) != 0
        val hasCycleSlip = (adrState and 4) != 0

        if (!isValid || isReset || hasCycleSlip || !isInitialized) {
            // 週跳或失鎖時，立即重置平滑視窗，防止將錯誤相位累積進來
            smoothedPseudorange = rawPseudorangeM
            lastAccumulatedDeltaRangeM = accumulatedDeltaRangeM
            epochCount = 1
            isInitialized = true
            return smoothedPseudorange
        }

        // 載波相位差分變化量（公尺）
        val deltaAdr = accumulatedDeltaRangeM - lastAccumulatedDeltaRangeM
        lastAccumulatedDeltaRangeM = accumulatedDeltaRangeM

        // 突發性異常跳變防護（1 秒內載波若跳躍 > 100m 視為隱性週跳）
        if (abs(deltaAdr) > 100.0) {
            smoothedPseudorange = rawPseudorangeM
            epochCount = 1
            return smoothedPseudorange
        }

        epochCount = min(epochCount + 1, maxEpochs)
        val weight = 1.0 / epochCount

        // 經典 Hatch 平滑公式：
        // rho_hat_k = (1/M) * rho_k + ((M-1)/M) * (rho_hat_{k-1} + delta_adr)
        smoothedPseudorange = weight * rawPseudorangeM + (1.0 - weight) * (smoothedPseudorange + deltaAdr)
        return smoothedPseudorange
    }

    /** 取得當前平滑收斂進度 (1..maxEpochs) */
    fun getConvergenceCount(): Int = epochCount

    /** 判定是否已充分收斂（連續平滑 >= 15 曆元） */
    fun isConverged(): Boolean = epochCount >= 15

    fun reset() {
        isInitialized = false
        epochCount = 0
        smoothedPseudorange = 0.0
        lastAccumulatedDeltaRangeM = 0.0
    }
}
