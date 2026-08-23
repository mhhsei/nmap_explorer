package com.example.nmapexplorer

import androidx.navigation3.runtime.NavKey
import kotlinx.serialization.Serializable

/**
 * 畫面導航的「鑰匙」（路由識別證）
 * 
 * 作用：就像不同房間的門牌號碼，告訴 Android 導航系統現在要切換到哪一個畫面。
 * 這裡定義了主畫面 (Main) 的門牌。
 */
@Serializable data object Main : NavKey

