/**
 * GitHub Releases 自動檢查更新與安裝管理器 (App Update Manager)
 * 
 * 作用：
 * 1. 當無法上架 Google Play 時，直接連線 GitHub Releases API (https://api.github.com/repos/mhhsei/nmap_explorer/releases/latest)。
 * 2. 比較本機版本號與 GitHub 最新 Release Tag (如 v1.0.1 > v1.0.0)。
 * 3. 具備多跳轉 (302 Redirect) 下載串流，將新版 APK 下載至本機快取目錄，並回傳下載進度百分比。
 * 4. 透過 Android FileProvider 與系統安裝器 (ACTION_VIEW) 無縫喚起安裝畫面，視障者只需點選確認即可自動更新。
 */
package com.example.nmapexplorer.update

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

data class UpdateInfo(
    val hasUpdate: Boolean,
    val currentVersion: String,
    val latestVersion: String,
    val releaseTitle: String,
    val releaseNotes: String,
    val downloadUrl: String,
    val apkFileName: String,
    val fileSize: Long
)

class AppUpdateManager(private val context: Context) {

    companion object {
        const val DEFAULT_REPO_OWNER = "mhhsei"
        const val DEFAULT_REPO_NAME = "nmap_explorer"
        private const val CONNECT_TIMEOUT_MS = 8000
        private const val READ_TIMEOUT_MS = 15000
    }

    /**
     * 取得當前 App 的版本名稱 (Version Name)
     */
    fun getCurrentVersionName(): String {
        return try {
            val pInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.packageManager.getPackageInfo(context.packageName, PackageManager.PackageInfoFlags.of(0))
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(context.packageName, 0)
            }
            pInfo.versionName ?: "1.0"
        } catch (e: Exception) {
            "1.0"
        }
    }

    /**
     * 【檢查 GitHub Releases 是否有新版本】
     * 作用：非同步向 GitHub REST API 索取最新 Release 資訊，若有新版 APK 則回傳包含下載網址的 UpdateInfo。
     */
    suspend fun checkForUpdates(
        repoOwner: String = DEFAULT_REPO_OWNER,
        repoName: String = DEFAULT_REPO_NAME
    ): Result<UpdateInfo> = withContext(Dispatchers.IO) {
        try {
            val currentVer = getCurrentVersionName()
            val apiUrl = "https://api.github.com/repos/$repoOwner/$repoName/releases/latest"
            val url = URL(apiUrl)
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            conn.connectTimeout = CONNECT_TIMEOUT_MS
            conn.readTimeout = READ_TIMEOUT_MS
            conn.setRequestProperty("User-Agent", "NMapExplorer-AndroidApp")
            conn.setRequestProperty("Accept", "application/vnd.github.v3+json")

            val responseCode = conn.responseCode
            if (responseCode == HttpURLConnection.HTTP_NOT_FOUND) {
                // GitHub 倉庫尚無發布記錄，代表當前即為最新版本
                return@withContext Result.success(
                    UpdateInfo(
                        hasUpdate = false,
                        currentVersion = currentVer,
                        latestVersion = currentVer,
                        releaseTitle = "已是最新版本",
                        releaseNotes = "目前 GitHub 尚無更新的發布版本",
                        downloadUrl = "",
                        apkFileName = "",
                        fileSize = 0
                    )
                )
            }
            if (responseCode != HttpURLConnection.HTTP_OK) {
                return@withContext Result.failure(Exception("GitHub API 回應錯誤：$responseCode"))
            }


            val jsonStr = conn.inputStream.bufferedReader().use { it.readText() }
            val releaseObj = JSONObject(jsonStr)

            val rawTagName = releaseObj.optString("tag_name", "")
            val cleanLatestVer = rawTagName.trimStart('v', 'V').trim()
            val title = releaseObj.optString("name", "新版本發布")
            val body = releaseObj.optString("body", "無更新說明")

            // 尋找 Release Assets 中的 .apk 檔案
            var apkDownloadUrl = ""
            var apkFileName = "nmap_update.apk"
            var fileSize: Long = 0

            val assetsArray = releaseObj.optJSONArray("assets")
            if (assetsArray != null && assetsArray.length() > 0) {
                for (i in 0 until assetsArray.length()) {
                    val asset = assetsArray.getJSONObject(i)
                    val name = asset.optString("name", "")
                    if (name.endsWith(".apk", ignoreCase = true)) {
                        apkDownloadUrl = asset.optString("browser_download_url", "")
                        apkFileName = name
                        fileSize = asset.optLong("size", 0)
                        // 若包含 release 關鍵字則優先選取
                        if (name.contains("release", ignoreCase = true)) {
                            break
                        }
                    }
                }
            }

            val hasUpdate = isNewerVersion(currentVer, cleanLatestVer) && apkDownloadUrl.isNotEmpty()

            val info = UpdateInfo(
                hasUpdate = hasUpdate,
                currentVersion = currentVer,
                latestVersion = cleanLatestVer,
                releaseTitle = title,
                releaseNotes = body,
                downloadUrl = apkDownloadUrl,
                apkFileName = apkFileName,
                fileSize = fileSize
            )
            Result.success(info)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 【版本號比較演算法】
     * 作用：比對語意化版本號（如 1.0.1 大於 1.0.0）。
     */
    private fun isNewerVersion(currentVer: String, latestVer: String): Boolean {
        if (currentVer.isBlank() || latestVer.isBlank()) return false
        val currParts = currentVer.split(".", "-").mapNotNull { it.toIntOrNull() }
        val latestParts = latestVer.split(".", "-").mapNotNull { it.toIntOrNull() }

        val maxLen = maxOf(currParts.size, latestParts.size)
        for (i in 0 until maxLen) {
            val c = if (i < currParts.size) currParts[i] else 0
            val l = if (i < latestParts.size) latestParts[i] else 0
            if (l > c) return true
            if (l < c) return false
        }
        return false
    }

    /**
     * 【下載新版 APK 至快取目錄】
     * 作用：處理 GitHub 302 重新導向串流，並即時回報進度 (0% ~ 100%)。
     */
    suspend fun downloadUpdate(
        downloadUrl: String,
        targetFileName: String = "nmap_update.apk",
        onProgress: (percentage: Int) -> Unit = {}
    ): Result<File> = withContext(Dispatchers.IO) {
        try {
            val updateDir = File(context.cacheDir, "updates").apply { mkdirs() }
            val destinationFile = File(updateDir, targetFileName)
            if (destinationFile.exists()) {
                destinationFile.delete()
            }

            var currentUrl = downloadUrl
            var connection: HttpURLConnection
            var redirectCount = 0
            val maxRedirects = 8

            // 追蹤 301/302/303/307 轉址（GitHub Releases 託管於 AWS S3）
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

            val fileLength = connection.contentLength
            val input: InputStream = connection.inputStream
            val output = FileOutputStream(destinationFile)

            val buffer = ByteArray(8192)
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

            withContext(Dispatchers.Main) {
                onProgress(100)
            }

            Result.success(destinationFile)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 【喚起 Android 系統安裝器進行自動更新】
     * 作用：
     * 1. 檢查 Android 8.0+ 的「安裝未知應用程式」權限，若未開啟則引導開啟。
     * 2. 透過 FileProvider 安全提供 content:// URI 授權，自動啟動安裝畫面。
     */
    fun installUpdate(apkFile: File): Result<Unit> {
        return try {
            if (!apkFile.exists() || apkFile.length() == 0L) {
                return Result.failure(Exception("APK 安裝檔不存在或檔案損毀"))
            }

            // Android 8.0 (API 26) 以上需要確認未知來源安裝權限
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                if (!context.packageManager.canRequestPackageInstalls()) {
                    val manageIntent = Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:${context.packageName}")
                    ).apply {
                        if (context !is Activity) {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                    }
                    context.startActivity(manageIntent)
                    return Result.failure(Exception("請先開啟「允許安裝未知應用程式」權限，開啟後請再次點選更新"))
                }
            }

            // 產生 FileProvider URI
            val authority = "${context.packageName}.fileprovider"
            val apkUri: Uri = FileProvider.getUriForFile(context, authority, apkFile)

            val installIntent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(apkUri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                if (context !is Activity) {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            }

            context.startActivity(installIntent)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
