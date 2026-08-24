package com.example.nmapexplorer

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.*

/**
 * 【定位感測器與自適應卡爾曼濾波器單元測試】
 * 
 * 驗證目標：
 * 1. 靜止鎖定 (STATIONARY_LOCKED)：在室內 0 步數下，無論 GPS 經緯度如何劇烈彈跳，卡爾曼輸出座標 100% 凍結。
 * 2. 步態同步 (PEDESTRIAN_WALKING)：步伐推進 (advanceStep) 能正確以自適應步長更新座標，且卡方新息門控能剔除 >15m 之折射跳點。
 * 3. 乘車交通 (VEHICULAR_TRANSIT)：車速 > 2.8 m/s 時自動解除步數約束，連續高速平滑追蹤。
 */
class LocationSensorBridgeTest {

    private val originLat = 25.18070
    private val originLon = 121.45044

    @Test
    fun testStationaryLock_CompletelyFreezesCoordinates() {
        val filter = PedestrianKalmanFilter()
        
        // 初始第一筆定位錨定
        val firstFix = filter.filter(
            rawLat = originLat,
            rawLon = originLon,
            accuracyMeters = 5.0f,
            speedMps = 0.0f,
            timestampNanos = 1_000_000_000L,
            motionState = MotionState.STATIONARY_LOCKED
        )
        assertEquals(originLat, firstFix.first, 1e-6)
        assertEquals(originLon, firstFix.second, 1e-6)

        // 模擬室內多路徑 8 次劇烈跳動 (在 30~50 公尺範圍內亂跳)
        val jitterLats = doubleArrayOf(25.18035, 25.18095, 25.18020, 25.18110, 25.18040)
        val jitterLons = doubleArrayOf(121.45010, 121.45080, 121.45005, 121.45090, 121.45020)

        for (i in jitterLats.indices) {
            val res = filter.filter(
                rawLat = jitterLats[i],
                rawLon = jitterLons[i],
                accuracyMeters = 35.0f,
                speedMps = 0.0f,
                timestampNanos = 1_000_000_000L + (i + 1) * 1_000_000_000L,
                motionState = MotionState.STATIONARY_LOCKED,
                isMultipath = true
            )
            // 驗證輸出座標 100% 凍結在原點，完全不隨雜訊飄移
            assertEquals("Step $i lat must stay frozen", originLat, res.first, 1e-6)
            assertEquals("Step $i lon must stay frozen", originLon, res.second, 1e-6)
        }
    }

    @Test
    fun testPedestrianWalking_AdvancesWithStepsAndRejectsOutlierJumps() {
        val filter = PedestrianKalmanFilter()
        
        // 初始錨定
        filter.filter(
            rawLat = originLat,
            rawLon = originLon,
            accuracyMeters = 4.0f,
            speedMps = 1.2f,
            timestampNanos = 1_000_000_000L,
            motionState = MotionState.PEDESTRIAN_WALKING
        )

        // 模擬向正北 (0°) 走了 10 步，每步 0.65 公尺
        var lastCoord = Pair(originLat, originLon)
        for (step in 1..10) {
            lastCoord = filter.advanceStep(0.65, 0.0)
        }

        // 驗證向北推進了 6.5 公尺 (緯度約增加 6.5 / 111139.0 ≈ 0.0000585)
        val expectedLatDelta = 6.5 / 111139.0
        assertEquals(originLat + expectedLatDelta, lastCoord.first, 1e-4)

        // 模擬突然收到一個 45 公尺之外的折射跳點 (Outlier Jump)
        val jumpedLat = originLat + (45.0 / 111139.0)
        val gatedRes = filter.filter(
            rawLat = jumpedLat,
            rawLon = originLon,
            accuracyMeters = 30.0f,
            speedMps = 1.0f,
            timestampNanos = 11_000_000_000L,
            motionState = MotionState.PEDESTRIAN_WALKING,
            isMultipath = true
        )

        // 驗證馬氏距離新息門控成功剔除該跳點，座標維持在正常推算位置附​​近 (< 10m 誤差)
        val diffMeters = (gatedRes.first - lastCoord.first) * 111139.0
        assertTrue("Outlier jump must be gated out, delta was $diffMeters m", abs(diffMeters) < 2.0)
    }

    @Test
    fun testVehicularTransit_SmoothlyFollowsHighSpeedMovement() {
        val filter = PedestrianKalmanFilter()
        
        // 初始錨定
        filter.filter(
            rawLat = originLat,
            rawLon = originLon,
            accuracyMeters = 3.0f,
            speedMps = 15.0f, // 54 km/h
            timestampNanos = 1_000_000_000L,
            motionState = MotionState.VEHICULAR_TRANSIT
        )

        // 模擬車輛高速前進：每秒向東移動 15 公尺 (3 秒前進 45 公尺)
        val mPerLon = 111139.0 * cos(Math.toRadians(originLat))
        var currentLon = originLon
        for (sec in 1..3) {
            currentLon += (15.0 / mPerLon)
            val res = filter.filter(
                rawLat = originLat,
                rawLon = currentLon,
                accuracyMeters = 3.0f,
                speedMps = 15.0f,
                timestampNanos = 1_000_000_000L + sec * 1_000_000_000L,
                motionState = MotionState.VEHICULAR_TRANSIT
            )
            // 驗證車載模式下座標能夠流暢跟隨 GPS 移動
            val distMeters = (res.second - originLon) * mPerLon
            assertTrue("Vehicle mode must track movement, tracked $distMeters m", distMeters > 5.0 * sec)
        }
    }

    @Test
    fun testStationaryMotionDetector_TransitionsCorrectly() {
        var recordedState = MotionState.STATIONARY_LOCKED
        val detector = StationaryMotionDetector(windowSize = 10) { newState ->
            recordedState = newState
        }

        // 1. 預設為靜止
        assertEquals(MotionState.STATIONARY_LOCKED, detector.currentState)

        // 2. 踩出一步 -> 切換為步行
        detector.onStepDetected()
        assertEquals(MotionState.PEDESTRIAN_WALKING, detector.currentState)

        // 3. 偵測到高速車速 (12 m/s) -> 切換為乘車
        detector.feedAccelerometer(0f, 9.8f, 0f, currentGpsSpeedMps = 12.0f)
        assertEquals(MotionState.VEHICULAR_TRANSIT, detector.currentState)
    }
}
