package com.example.nmapexplorer.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/**
 * 深色模式配色方案
 */
private val DarkColorScheme = darkColorScheme(
  primary = Purple80, 
  secondary = PurpleGrey80, 
  tertiary = Pink80
)

/**
 * 淺色模式配色方案
 */
private val LightColorScheme =
  lightColorScheme(
    primary = Purple40,
    secondary = PurpleGrey40,
    tertiary = Pink40,

    /* 其他可覆蓋的預設顏色
    background = Color(0xFFFFFBFE),
    surface = Color(0xFFFFFBFE),
    onPrimary = Color.White,
    onSecondary = Color.White,
    onTertiary = Color.White,
    onBackground = Color(0xFF1C1B1F),
    onSurface = Color(0xFF1C1B1F),
    */
  )

/**
 * NMap Explorer 全域主題包裝器
 * 
 * 作用：決定整個 App 的視覺風格。
 * 1. 若手機系統是 Android 12 以上，且開啟 dynamicColor，會自動抽取手機桌布顏色作為主題色（Material You 動態取色）。
 * 2. 否則會自動依據手機是否開啟「深色模式」切換深色或淺色風格。
 */
@Composable
fun NMapExplorerTheme(
  darkTheme: Boolean = isSystemInDarkTheme(),
  // Android 12 (API 31) 以上支援動態主題色彩
  dynamicColor: Boolean = true,
  content: @Composable () -> Unit,
) {
  // 決定最終要套用的調色盤
  val colorScheme =
    when {
      // 支援動態取色且為 Android 12 以上：自動抽取系統桌布配色
      dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
        val context = LocalContext.current
        if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
      }
      // 深色模式套用暗色主題
      darkTheme -> DarkColorScheme
      // 預設套用亮色主題
      else -> LightColorScheme
    }

  // 套用 Material 3 主題設定至整個內容畫面
  MaterialTheme(
    colorScheme = colorScheme, 
    typography = Typography, 
    content = content
  )
}

