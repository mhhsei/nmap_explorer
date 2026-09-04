package com.example.nmapexplorer.neural

import android.os.SystemClock
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/**
 * 【白手杖擺動對稱陷波抗抖濾波器 (CaneSwingHeadingFilter)】
 * 
 * 生活化比喻（小學生都看得懂）：
 * 當視障朋友拿著白手杖走在路上時，手杖會規律地「左敲一下、右敲一下」來探尋前方有沒有坑洞或障礙物。
 * 這時候，拿著手機的手（或同側身體）就會跟著產生像「撥浪鼓」一樣的左右小擺動（通常左右晃動約 8~15 度，每秒晃一次）。
 * 
 * 如果導航系統傻傻地跟著每次手部擺動去轉動方向，耳機裡的 3D 立體聲音效就會忽左忽右發瘋似地亂晃，
 * 讓人聽了頭暈目眩。
 * 
 * 本濾波器的作用就像一位「太極拳宗師」：
 * 它會觀察最近 1.2 秒內的擺動軌跡。只要發現你只是在規律地「左晃 10 度、右晃 10 度」，
 * 宗師就會運用正負抵銷的原理，直接把晃動借力打力化解為「零」，只穩穩輸出你真正向前的身體朝向！
 * 而一旦你真的在路口要右轉大彎（角度持續超過 25 度），宗師就會立刻放行，零延遲跟隨你的轉向！
 */
class CaneSwingHeadingFilter(
    /** 擺動觀察時間視窗（毫秒）：一般白手杖左右完整循環一次約 1000 ~ 1200ms */
    private val windowDurationMs: Long = 1200L,
    /** 判定為揮杖擺動的最大峰峰值夾角 (度)：超過 22 度視為真實意圖轉向 */
    private val maxSwingAmplitudeDeg: Float = 22.0f,
    /** 真實大轉彎突破門檻 (度)：超過此角度立即解除陷波抑制 */
    private val breakoutThresholdDeg: Float = 25.0f
) {
    private data class HeadingSample(
        val timestampMs: Long,
        val headingDeg: Float
    )

    // 滑動歷史緩衝隊列
    private val history = mutableListOf<HeadingSample>()

    // 上一次穩定輸出的航向角
    private var lastFilteredHeading = -1.0f

    // 揮杖擺動狀態指示
    var isCaneSwinging = false
        private set

    /**
     * 重置濾波器狀態
     */
    fun reset() {
        history.clear()
        lastFilteredHeading = -1.0f
        isCaneSwinging = false
    }

    /**
     * 輸入即時原始真北朝向角，輸出濾除揮杖擺動後的純淨軀幹朝向角
     * 
     * @param rawHeadingDeg 9 軸融合補償後之原始真北角度 (0.0 ~ 359.9)
     * @param isWalking 行人是否正在行走中（若靜止或乘車則不啟用揮杖陷波）
     * @param nowMs 當前時間戳記 (SystemClock.uptimeMillis())
     * @return 消除擺杖晃動後的穩定真北角度 (0.0 ~ 359.9)
     */
    fun filterHeading(rawHeadingDeg: Float, isWalking: Boolean, nowMs: Long = SystemClock.uptimeMillis()): Float {
        // 初始狀態直通
        if (lastFilteredHeading < 0f) {
            lastFilteredHeading = rawHeadingDeg
            history.add(HeadingSample(nowMs, rawHeadingDeg))
            return rawHeadingDeg
        }

        // 若非步行狀態（如停步辨位或搭車），直通標準平滑，不施加擺杖陷波
        if (!isWalking) {
            isCaneSwinging = false
            val diff = normalizeAngleDiff(rawHeadingDeg - lastFilteredHeading)
            val alpha = if (Math.abs(diff) > 2.0f) 0.65f else 0.25f
            lastFilteredHeading = (lastFilteredHeading + alpha * diff + 360f) % 360f
            return lastFilteredHeading
        }

        // 加入歷史緩衝並移除逾期樣本
        history.add(HeadingSample(nowMs, rawHeadingDeg))
        val cutoffTime = nowMs - windowDurationMs
        while (history.isNotEmpty() && history.first().timestampMs < cutoffTime) {
            history.removeAt(0)
        }

        // 樣本數不足時快速跟隨
        if (history.size < 8) {
            val diff = normalizeAngleDiff(rawHeadingDeg - lastFilteredHeading)
            lastFilteredHeading = (lastFilteredHeading + 0.35f * diff + 360f) % 360f
            return lastFilteredHeading
        }

        // 1. 計算時序視窗內的圓形均值 (Circular Mean)
        var sumSin = 0.0
        var sumCos = 0.0
        for (sample in history) {
            val rad = Math.toRadians(sample.headingDeg.toDouble())
            sumSin += sin(rad)
            sumCos += cos(rad)
        }
        val meanRad = atan2(sumSin / history.size, sumCos / history.size)
        val circularMeanDeg = ((Math.toDegrees(meanRad) + 360.0) % 360.0).toFloat()

        // 2. 檢驗視窗內的擺幅極值與零交叉符號反轉（揮杖特徵：左右對稱擺動）
        var maxDevPos = 0.0f
        var maxDevNeg = 0.0f
        var signChanges = 0
        var lastSign = 0

        for (sample in history) {
            val delta = normalizeAngleDiff(sample.headingDeg - circularMeanDeg)
            if (delta > maxDevPos) maxDevPos = delta
            if (delta < -maxDevNeg) maxDevNeg = -delta

            val currentSign = if (delta > 1.2f) 1 else if (delta < -1.2f) -1 else 0
            if (currentSign != 0 && lastSign != 0 && currentSign != lastSign) {
                signChanges++
            }
            if (currentSign != 0) {
                lastSign = currentSign
            }
        }

        val peakToPeakSwing = maxDevPos + maxDevNeg
        val diffFromBaseline = Math.abs(normalizeAngleDiff(rawHeadingDeg - lastFilteredHeading))

        // 3. 轉彎突破判定 (Breakout Detection)：
        // 若偏離上一個穩定基準超過 breakoutThresholdDeg，或無左右交替跡象且單向持續偏轉，判定為真實轉彎
        val isIntentionalTurn = diffFromBaseline > breakoutThresholdDeg || (signChanges == 0 && diffFromBaseline > 15.0f)

        if (isIntentionalTurn) {
            // 真實轉向：解除陷波抑制，採用高靈敏 alpha 敏捷跟隨轉向
            isCaneSwinging = false
            val diff = normalizeAngleDiff(rawHeadingDeg - lastFilteredHeading)
            val turnAlpha = 0.78f
            lastFilteredHeading = (lastFilteredHeading + turnAlpha * diff + 360f) % 360f
        } else if (peakToPeakSwing <= maxSwingAmplitudeDeg && signChanges >= 1) {
            // 典型白手杖規律擺動：鎖死在循環基線均值上，將手部晃動降噪 90%！
            isCaneSwinging = true
            val meanDiff = normalizeAngleDiff(circularMeanDeg - lastFilteredHeading)
            // 極緩慢微調基線（alpha=0.08），確保長直線行走時基線平穩如磐石
            lastFilteredHeading = (lastFilteredHeading + 0.08f * meanDiff + 360f) % 360f
        } else {
            // 一般自然行進微調
            isCaneSwinging = false
            val diff = normalizeAngleDiff(rawHeadingDeg - lastFilteredHeading)
            val alpha = 0.22f
            lastFilteredHeading = (lastFilteredHeading + alpha * diff + 360f) % 360f
        }

        return lastFilteredHeading
    }

    /**
     * 將角度差標準化至 (-180.0 ~ +180.0) 區間
     */
    private fun normalizeAngleDiff(diffDeg: Float): Float {
        var diff = diffDeg % 360.0f
        while (diff < -180.0f) diff += 360.0f
        while (diff > 180.0f) diff -= 360.0f
        return diff
    }
}
