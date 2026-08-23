package com.example.nmapexplorer.data

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow

/**
 * 資料倉庫介面 (Data Repository Interface)
 * 
 * 作用：定義「資料從哪裡來」的標準規範。
 * 遵循依賴反轉原則，讓上層 ViewModel 只需要向倉庫要資料，不用管底層是從網路抓還是從本機讀取。
 */
interface DataRepository {
  /**
   * 異步資料流 (Flow)，會持續發射字串清單
   */
  val data: Flow<List<String>>
}

/**
 * 預設的資料倉庫實作 (Default Implementation)
 * 
 * 作用：提供最基礎的資料來源（此處預設回傳包含 "Android" 的清單）。
 */
class DefaultDataRepository : DataRepository {
  override val data: Flow<List<String>> = flow { emit(listOf("Android")) }
}

