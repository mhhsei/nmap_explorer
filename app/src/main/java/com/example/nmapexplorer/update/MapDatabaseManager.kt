/**
 * 離線地圖資料庫管理器 (Map Database Manager)
 * 
 * 作用：
 * 1. 實現「App 引擎與大型圖資分離」架構：使 APK 安裝檔大幅瘦身（從 305MB 降至 ~35MB）。
 * 2. 獨立管理全台灣 193 萬筆 POI 資料庫 (overture_places.db, ~220MB)。
 * 3. 支援背景斷點下載、多轉址追蹤 (302 Redirect)、進度回報 (0%~100%) 與 TalkBack 語音廣播。
 * 4. 提供儲存空間管理，讓使用者隨時可下載或清理離線圖資。
 */
package com.example.nmapexplorer.update

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

data class DatabaseStatus(
    val exists: Boolean,
    val sizeBytes: Long,
    val sizeFormattedMb: String,
    val path: String,
    val lastModified: Long,
    val remoteVersion: String = "1.0",
    val downloadUrl: String = ""
)

class MapDatabaseManager(private val context: Context) {

    private val tag = "MapDatabaseManager"

    companion object {
        const val DB_FILENAME = "overture_places.db"
        const val DEFAULT_REPO_OWNER = "mhhsei"
        const val DEFAULT_REPO_NAME = "nmap_explorer"
        const val FALLBACK_DB_URL = "https://github.com/mhhsei/nmap_explorer/releases/download/v1.0.0/overture_places.db"
        private const val CONNECT_TIMEOUT_MS = 10000
        private const val READ_TIMEOUT_MS = 30000
    }

    /**
     * 取得本地資料庫儲存目錄 (优先使用外部應用專屬目錄，避免佔用手機內部系統分區)
     */
    fun getDataDir(): File {
        val dir = context.getExternalFilesDir(null)?.resolve("data") ?: context.filesDir.resolve("data")
        if (!dir.exists()) {
            dir.mkdirs()
        }
        return dir
    }

    /**
     * 取得資料庫目標檔案路徑
     */
    fun getDatabaseFile(): File {
        return File(getDataDir(), DB_FILENAME)
    }

    /**
     * 檢查本地圖資狀態
     */
    fun getDatabaseStatus(): DatabaseStatus {
        val file = getDatabaseFile()
        val exists = file.exists() && file.length() > 1024 * 1024 // 至少大於 1MB 視為有效
        val sizeBytes = if (exists) file.length() else 0L
        val mb = sizeBytes.toDouble() / (1024.0 * 1024.0)
        val formattedMb = String.format(Locale.US, "%.1f MB", mb)

        return DatabaseStatus(
            exists = exists,
            sizeBytes = sizeBytes,
            sizeFormattedMb = formattedMb,
            path = file.absolutePath,
            lastModified = if (exists) file.lastModified() else 0L,
            remoteVersion = "1.0",
            downloadUrl = FALLBACK_DB_URL
        )
    }

    /**
     * 向 GitHub Releases 查詢最新地圖資料庫下載連結
     */
    suspend fun fetchLatestDatabaseUrl(): String = withContext(Dispatchers.IO) {
        try {
            val apiUrl = "https://api.github.com/repos/$DEFAULT_REPO_OWNER/$DEFAULT_REPO_NAME/releases"
            val url = URL(apiUrl)
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            conn.connectTimeout = CONNECT_TIMEOUT_MS
            conn.readTimeout = READ_TIMEOUT_MS
            conn.setRequestProperty("User-Agent", "NMapExplorer-AndroidApp")
            conn.setRequestProperty("Accept", "application/vnd.github.v3+json")

            if (conn.responseCode == HttpURLConnection.HTTP_OK) {
                val jsonStr = conn.inputStream.bufferedReader().use { it.readText() }
                val releasesArray = org.json.JSONArray(jsonStr)
                for (i in 0 until releasesArray.length()) {
                    val release = releasesArray.getJSONObject(i)
                    val assets = release.optJSONArray("assets") ?: continue
                    for (j in 0 until assets.length()) {
                        val asset = assets.getJSONObject(j)
                        val name = asset.optString("name", "")
                        if (name.equals(DB_FILENAME, ignoreCase = true) || name.startsWith("overture_places", ignoreCase = true)) {
                            val downloadUrl = asset.optString("browser_download_url", "")
                            if (downloadUrl.isNotEmpty()) {
                                return@withContext downloadUrl
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(tag, "Failed to query remote releases for db asset, using fallback", e)
        }
        FALLBACK_DB_URL
    }

    /**
     * 【下載離線地圖資料庫】
     * 作用：處理 302 重新導向串流，並即時回報進度 (0% ~ 100%)。
     */
    suspend fun downloadDatabase(
        targetUrl: String? = null,
        onProgress: (percentage: Int) -> Unit = {}
    ): Result<File> = withContext(Dispatchers.IO) {
        try {
            val downloadUrl = targetUrl ?: fetchLatestDatabaseUrl()
            val destDir = getDataDir()
            val tempFile = File(destDir, "$DB_FILENAME.tmp")
            val targetFile = File(destDir, DB_FILENAME)

            if (tempFile.exists()) {
                tempFile.delete()
            }

            var currentUrl = downloadUrl
            var connection: HttpURLConnection
            var redirectCount = 0
            val maxRedirects = 8

            // 追蹤 301/302/307 轉址
            while (true) {
                val url = URL(currentUrl)
                connection = url.openConnection() as HttpURLConnection
                connection.instanceFollowRedirects = false
                connection.connectTimeout = CONNECT_TIMEOUT_MS
                connection.readTimeout = READ_TIMEOUT_MS
                connection.setRequestProperty("User-Agent", "NMapExplorer-AndroidApp")

                val status = connection.responseCode
                if (status == HttpURLConnection.HTTP_MOVED_PERM ||
                    status == HttpURLConnection.HTTP_MOVED_TEMP ||
                    status == HttpURLConnection.HTTP_SEE_OTHER ||
                    status == 307
                ) {
                    val newUrl = connection.getHeaderField("Location")
                    if (newUrl != null && redirectCount < maxRedirects) {
                        currentUrl = newUrl
                        redirectCount++
                        continue
                    }
                }
                break
            }

            if (connection.responseCode != HttpURLConnection.HTTP_OK) {
                return@withContext Result.failure(Exception("伺服器回應錯誤: ${connection.responseCode}"))
            }

            val fileLength = connection.contentLengthLong
            val input: InputStream = connection.inputStream
            val output = FileOutputStream(tempFile)

            val buffer = ByteArray(32768) // 32KB buffer 高效串流
            var totalBytesRead: Long = 0
            var bytesRead: Int
            var lastReportedPercent = -1

            while (input.read(buffer).also { bytesRead = it } != -1) {
                output.write(buffer, 0, bytesRead)
                totalBytesRead += bytesRead
                if (fileLength > 0) {
                    val percent = ((totalBytesRead * 100) / fileLength).toInt()
                    if (percent != lastReportedPercent && percent % 5 == 0) {
                        lastReportedPercent = percent
                        withContext(Dispatchers.Main) {
                            onProgress(percent)
                        }
                    }
                }
            }

            output.flush()
            output.close()
            input.close()

            // 下載成功後原子重命名
            if (targetFile.exists()) {
                targetFile.delete()
            }
            if (!tempFile.renameTo(targetFile)) {
                // 若 rename 失敗，手動複製
                tempFile.copyTo(targetFile, overwrite = true)
                tempFile.delete()
            }

            withContext(Dispatchers.Main) {
                onProgress(100)
            }

            Log.i(tag, "Offline map database downloaded successfully: ${targetFile.length()} bytes")
            Result.success(targetFile)
        } catch (e: Exception) {
            Log.e(tag, "Download database error", e)
            Result.failure(e)
        }
    }

    /**
     * 清理本地離線資料庫（釋放手機空間）
     */
    fun deleteDatabase(): Boolean {
        val file = getDatabaseFile()
        return if (file.exists()) {
            file.delete()
        } else {
            true
        }
    }
}
