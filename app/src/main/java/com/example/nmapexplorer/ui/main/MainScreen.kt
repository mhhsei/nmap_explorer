package com.example.nmapexplorer.ui.main

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation3.runtime.NavKey
import com.example.nmapexplorer.data.DefaultDataRepository
import com.example.nmapexplorer.theme.NMapExplorerTheme

/**
 * 主畫面容器 (Stateful Composable)
 * 
 * 作用：負責連接 ViewModel，並根據目前的 UI 狀態（Loading、Success、Error）切換顯示不同的畫面內容。
 */
@Composable
fun MainScreen(
  onItemClick: (NavKey) -> Unit,
  modifier: Modifier = Modifier,
  viewModel: MainScreenViewModel = viewModel { MainScreenViewModel(DefaultDataRepository()) },
) {
  // 隨生命週期自動收集 ViewModel 的狀態，當狀態改變時會觸發畫面重繪
  val state by viewModel.uiState.collectAsStateWithLifecycle()
  when (state) {
    // 載入中：目前呈現空白或等待動畫
    MainScreenUiState.Loading -> {
      // Blank
    }
    // 載入成功：顯示資料內容
    is MainScreenUiState.Success -> {
      MainScreen(data = (state as MainScreenUiState.Success).data, modifier = modifier)
    }
    // 發生錯誤：顯示錯誤訊息文字
    is MainScreenUiState.Error -> {
      Text("Error loading data: ${(state as MainScreenUiState.Error).throwable.message}")
    }
  }
}

/**
 * 成功狀態下的無狀態 UI 元件 (Stateless Composable)
 * 
 * 作用：純粹接收資料清單，將每筆資料用垂直排列 (Column) 依序畫出問候語。
 */
@Composable
internal fun MainScreen(data: List<String>, modifier: Modifier = Modifier) {
  Column(modifier) { data.forEach { Greeting(it) } }
}

/**
 * 單筆問候文字元件
 * 
 * 作用：將傳入的名字組裝成 "Hello [name]!" 顯示在畫面上。
 */
@Composable
fun Greeting(name: String, modifier: Modifier = Modifier) {
  Text(text = "Hello $name!", modifier = modifier)
}

/**
 * Android Studio 預覽畫面（標準模式）
 */
@Preview(showBackground = true)
@Composable
fun MainScreenPreview() {
  NMapExplorerTheme { MainScreen(listOf("Android")) }
}

/**
 * Android Studio 預覽畫面（窄螢幕直立模式，寬度 340dp）
 */
@Preview(showBackground = true, widthDp = 340)
@Composable
fun MainScreenPortraitPreview() {
  NMapExplorerTheme { MainScreen(listOf("Android")) }
}

