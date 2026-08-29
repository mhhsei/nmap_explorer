package com.example.nmapexplorer

/**
 * 【五級差分定位品質階梯 (Differential Positioning Tier)】
 * 
 * 生活化比喻：
 * 就像在黑夜中走路：
 * - OFFLINE_AUTONOMOUS：像拿著手電筒自己看路，看得清街道（誤差 3~5 米）。
 * - CARRIER_SMOOTHED_HATCH：像戴上偏光眼鏡消除反光，視野清晰多了（誤差 1~2 米）。
 * - DGPS_CODE_DIFF：像身邊有路人指路，能分清哪一側人行道（誤差約 0.8 米）。
 * - RTK_FLOAT_DECIMETER：像盲杖能精準敲到斑馬線邊緣（誤差 30~50 公分）。
 * - RTK_FIXED_CENTIMETER：像腳底踩上導盲磚的每一顆微小凸起（誤差小於 20 公分）。
 */
enum class DifferentialTier(val displayName: String, val expectedAccuracyMeters: Float) {
    /** Tier 0: 單機自主定位 (未連線差分或室內/騎樓 PDR) */
    OFFLINE_AUTONOMOUS("單機導航 (3-5m)", 4.0f),

    /** Tier 1: 本地雙頻載波平滑 (無需連網，Hatch 濾波收斂) */
    CARRIER_SMOOTHED_HATCH("載波平滑 (1.5m)", 1.5f),

    /** Tier 2: e-GNSS 代碼差分 (DGPS 偽距修正) */
    DGPS_CODE_DIFF("代碼差分 (0.8m)", 0.8f),

    /** Tier 3: e-GNSS 載波浮點解 (RTK Float 分米級) */
    RTK_FLOAT_DECIMETER("分米差分 (0.4m)", 0.4f),

    /** Tier 4: e-GNSS 載波固定解 (RTK Fixed 公分級) */
    RTK_FIXED_CENTIMETER("公分差分 (0.2m)", 0.2f)
}
