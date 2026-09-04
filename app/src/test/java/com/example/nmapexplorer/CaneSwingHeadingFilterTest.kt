package com.example.nmapexplorer

import com.example.nmapexplorer.neural.CaneSwingHeadingFilter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.sin

class CaneSwingHeadingFilterTest {

    @Test
    fun testCaneSwingSuppressionDuringWalking() {
        val filter = CaneSwingHeadingFilter()
        var timeMs = 1000L
        val baseHeading = 90.0f // 基準朝東行走 (90度)

        // 模擬 3 秒內揮杖行走：週期 1 秒，左右振幅 ±10 度，採樣率 25Hz (每 40ms 一筆)
        var lastFiltered = baseHeading
        for (i in 0 until 75) {
            val tSec = i * 0.04
            // 規律正弦波晃動
            val wobble = 10.0f * sin(2.0 * Math.PI * 1.0 * tSec).toFloat()
            val rawHeading = baseHeading + wobble
            timeMs += 40L

            lastFiltered = filter.filterHeading(rawHeading, isWalking = true, nowMs = timeMs)
        }

        // 揮杖擺動時，輸出角度與基準 90 度的偏差應小於 2.0 度 (晃動抑制率 > 80%)
        val diffFromBase = abs(lastFiltered - baseHeading)
        assertTrue("揮杖抗抖應將 ±10 度擺動抑制至 2 度以內，實際偏差: $diffFromBase 度", diffFromBase < 2.0f)
        assertTrue("揮杖旗標應處於鎖定狀態", filter.isCaneSwinging)
    }

    @Test
    fun testIntentionalTurnBreakout() {
        val filter = CaneSwingHeadingFilter()
        var timeMs = 1000L

        // 先走直線 2 秒建立基線 (90度)
        for (i in 0 until 50) {
            timeMs += 40L
            filter.filterHeading(90.0f, isWalking = true, nowMs = timeMs)
        }

        // 使用者在路口轉向至 180 度 (轉向 90 度大彎)
        var turnedHeading = 90.0f
        for (i in 0 until 10) {
            timeMs += 40L
            turnedHeading = filter.filterHeading(180.0f, isWalking = true, nowMs = timeMs)
        }

        // 轉彎突破後應迅速跟隨至 180 度附近 (差距 < 5 度)
        val diffFromTurn = abs(turnedHeading - 180.0f)
        assertTrue("大角度轉彎時應立即突破陷波並跟隨，實際偏差: $diffFromTurn 度", diffFromTurn < 5.0f)
    }
}
