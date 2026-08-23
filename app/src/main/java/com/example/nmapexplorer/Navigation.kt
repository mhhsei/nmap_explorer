package com.example.nmapexplorer

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import com.example.nmapexplorer.ui.main.MainScreen

/**
 * 整個 App 的畫面切換調度中心（主導航控制器）
 * 
 * 作用：負責管理使用者在各畫面之間「前進」與「返回」的歷史紀錄（像是一疊卡片）。
 * 當使用者按下返回鍵時，把最上面的一張卡片抽掉，回到上一頁。
 */
@Composable
fun MainNavigation() {
  // 建立並記住畫面的堆疊歷史，預設第一頁放進「主畫面 (Main)」
  val backStack = rememberNavBackStack(Main)

  // 畫面展示元件：根據目前的堆疊狀態顯示對應的畫面
  NavDisplay(
    backStack = backStack,
    // 當使用者按下系統返回鍵時，移除最上層畫面
    onBack = { backStack.removeLastOrNull() },
    // 提供每個門牌號碼對應的實際畫面元件
    entryProvider =
      entryProvider {
        // 當門牌是 Main 時，顯示主畫面 (MainScreen)
        entry<Main> {
          MainScreen(
            // 點擊項目時將新畫面的門牌推入堆疊
            onItemClick = { navKey -> backStack.add(navKey) }, 
            // 設定安全邊距（避開手機頂部瀏海與底部導航列）並加上 16dp 邊距
            modifier = Modifier.safeDrawingPadding().padding(16.dp)
          )
        }
      },
  )
}

