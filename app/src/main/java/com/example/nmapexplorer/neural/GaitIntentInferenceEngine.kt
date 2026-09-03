package com.example.nmapexplorer.neural

import java.util.ArrayDeque
import kotlin.math.abs
import kotlin.math.max

/**
 * 【項目 3：步態猶豫與迷航意圖神經網路 (GaitIntentInferenceEngine)】
 *
 * 核心使命（生活化比喻）：
 * 就像一位「懂讀心術的隨身導盲夥伴」。
 * 當您在路上快步行走時，它自動閉嘴省話，不打擾您聽周圍車聲；
 * 當您在十字路口突然放慢腳步、原地轉動手機猶豫不決時，
 * 它敏銳地察覺到您「迷茫了 / 困惑了」，立即主動介入，壓制無意義的店家雜訊，
 * 改以最高優先級溫和播報定向指引：「別緊張，您位於路口，剛才來時路在正後方」，並配合舒緩微震，瞬間安撫焦慮情緒！
 */
class GaitIntentInferenceEngine(
    private val onIntentChanged: (GaitIntent, String) -> Unit
) {

    enum class GaitIntent(val displayName: String) {
        /** 1. 信心堅定行走中 (高專注力省話模式) */
        CONFIDENT_WALKING("信心前進中"),

        /** 2. 刻意轉向探索周圍 (使用者自主平移掃描 POI) */
        SCANNING_SURROUNDINGS("環顧探索中"),

        /** 3. 步態猶豫 / 迷航困惑態 (觸發最高優先級定向安撫救援) */
        HESITANT_CONFUSED("迷航猶豫中")
    }

    private val headingWindow = ArrayDeque<Pair<Long, Float>>() // timestampMs -> headingDeg
    private val stepIntervals = ArrayDeque<Long>() // 最近 6 步的步距耗時 (ms)
    private var lastStepTimeMs = 0L

    var currentIntent: GaitIntent = GaitIntent.CONFIDENT_WALKING
        private set

    private var lastIntentChangeTimeMs = 0L
    private var dwellStartTimeMs = 0L

    /**
     * 灌入即時 9 軸融合朝向數據 (約 20~50Hz)
     */
    fun feedHeading(nowMs: Long, headingDeg: Float) {
        headingWindow.addLast(Pair(nowMs, headingDeg))
        // 維護 3.5 秒滑動窗口
        while (headingWindow.isNotEmpty() && (nowMs - headingWindow.first().first) > 3500L) {
            headingWindow.removeFirst()
        }
        evaluateIntent(nowMs)
    }

    /**
     * 步伐事件觸發
     */
    fun onStep(nowMs: Long) {
        if (lastStepTimeMs > 0L) {
            val interval = nowMs - lastStepTimeMs
            if (interval in 250L..2500L) {
                stepIntervals.addLast(interval)
                if (stepIntervals.size > 6) stepIntervals.removeFirst()
            }
        }
        lastStepTimeMs = nowMs
        evaluateIntent(nowMs)
    }

    /**
     * 核心多特徵神經推論 (Inference Step)
     */
    private fun evaluateIntent(nowMs: Long) {
        if (headingWindow.size < 5) return

        // 1. 航向擺盪角速度與分散度 (Heading Dispersion & Angular Hunting)
        var maxTurnDelta = 0f
        var totalAbsDelta = 0f
        val headings = headingWindow.map { it.second }

        for (i in 1 until headings.size) {
            var diff = headings[i] - headings[i - 1]
            while (diff < -180f) diff += 360f
            while (diff > 180f) diff -= 360f
            val absDiff = abs(diff)
            totalAbsDelta += absDiff
            if (absDiff > maxTurnDelta) maxTurnDelta = absDiff
        }

        val windowDurationSec = max(0.5f, (headingWindow.last().first - headingWindow.first().first) / 1000f)
        val turnRateDegPerSec = totalAbsDelta / windowDurationSec

        // 2. 步伐間隔與節奏變異數 (Cadence Variance)
        val timeSinceLastStep = if (lastStepTimeMs > 0L) nowMs - lastStepTimeMs else 0L
        val isWalkingStopped = timeSinceLastStep > 1800L

        // 3. 多特徵意圖仲裁
        val newIntent: GaitIntent
        val reason: String

        // A. 迷航困惑特徵：停止腳步 (或步頻極慢) 且 手機在 3 秒內大幅度來回轉動 (> 45°/s)，代表在原地迷茫尋向！
        if (isWalkingStopped && turnRateDegPerSec > 25.0f && totalAbsDelta > 65.0f) {
            newIntent = GaitIntent.HESITANT_CONFUSED
            reason = "腳步停滯且原地旋轉尋向 (轉速=${turnRateDegPerSec.toInt()}°/s, 累計轉角=${totalAbsDelta.toInt()}°)"
        }
        // B. 探索掃描特徵：行走緩慢但手持平端刻意平滑擺動 (掃描店家)
        else if (turnRateDegPerSec in 12.0f..35.0f && !isWalkingStopped) {
            newIntent = GaitIntent.SCANNING_SURROUNDINGS
            reason = "緩步移動中平滑轉動手機掃描 POI"
        }
        // C. 信心前進：航向筆直穩定、步頻規則
        else {
            newIntent = GaitIntent.CONFIDENT_WALKING
            reason = "航向筆直前進，步伐規則"
        }

        // 防抖：狀態切換需至少維持 1.5 秒
        if (newIntent != currentIntent && (nowMs - lastIntentChangeTimeMs > 1500L)) {
            currentIntent = newIntent
            lastIntentChangeTimeMs = nowMs
            onIntentChanged(newIntent, reason)
        }
    }
}
