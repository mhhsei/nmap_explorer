package com.example.nmapexplorer.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.nmapexplorer.data.DataRepository
import com.example.nmapexplorer.ui.main.MainScreenUiState.Success
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn

/**
 * 主畫面的商業邏輯與狀態管家 (ViewModel)
 * 
 * 作用：負責向 DataRepository 請求資料，並把生硬的資料包裝成畫面 (UI) 容易理解的狀態（載入中、成功、失敗）。
 * 就算手機旋轉或畫面重繪，ViewModel 裡面的資料也不會遺失。
 */
class MainScreenViewModel(dataRepository: DataRepository) : ViewModel() {
  /**
   * 畫面的即時狀態流 (StateFlow)
   * 1. 取得資料後轉換為 Success 狀態。
   * 2. 若發生例外異常，透過 catch 捕捉並轉為 Error 狀態。
   * 3. 透過 stateIn 轉為狀態流，當畫面有在觀察時保持活耀（5秒超時緩衝），初始狀態為 Loading。
   */
  val uiState: StateFlow<MainScreenUiState> =
    dataRepository.data
      .map<List<String>, MainScreenUiState>(::Success)
      .catch { emit(MainScreenUiState.Error(it)) }
      .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), MainScreenUiState.Loading)
}

/**
 * 主畫面的三種狀態定義 (Sealed Interface)
 * 
 * 作用：保證畫面只會處於這三種狀態之一，不會有模糊地帶：
 * 1. Loading：正在載入資料
 * 2. Error：載入失敗並記錄錯誤原因
 * 3. Success：載入成功並附帶資料清單
 */
sealed interface MainScreenUiState {
  /** 載入中狀態 */
  object Loading : MainScreenUiState

  /** 錯誤狀態，包含異常資訊 */
  data class Error(val throwable: Throwable) : MainScreenUiState

  /** 成功狀態，包含取得的字串清單 */
  data class Success(val data: List<String>) : MainScreenUiState
}

