package com.example.nmapexplorer

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import android.webkit.JavascriptInterface
import androidx.core.content.FileProvider
import androidx.core.content.pm.PackageInfoCompat
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class WebAppInterface(private val context: Context) {

    private val tag = "WebAppInterface"

    @JavascriptInterface
    fun vibrate(durationMs: Long) {
        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        if (vibrator.hasVibrator()) {
            vibrator.vibrate(VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    @JavascriptInterface
    fun shareAppLogs() {
        try {
            val logDir = File(context.cacheDir, "logs")
            if (!logDir.exists()) {
                logDir.mkdirs()
            }

            // 1. Fetch Logcat
            val process = Runtime.getRuntime().exec("logcat -d -v time")
            val logText = process.inputStream.bufferedReader().readText()

            // 2. Build device & environment info
            val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date())
            val pkgInfo = try {
                context.packageManager.getPackageInfo(context.packageName, 0)
            } catch (e: Exception) {
                null
            }
            val versionCode = if (pkgInfo != null) PackageInfoCompat.getLongVersionCode(pkgInfo) else 0L
            val devInfo = buildString {
                appendLine("【NMap Explorer 診斷資訊】")
                appendLine("匯出時間: $timeStr")
                appendLine("App 版本: ${pkgInfo?.versionName} (VersionCode: $versionCode)")
                appendLine("手機型號: ${Build.MANUFACTURER} ${Build.MODEL} (${Build.DEVICE})")
                appendLine("Android 版本: ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})")
                appendLine("最大可用記憶體: ${Runtime.getRuntime().maxMemory() / (1024 * 1024)} MB")
            }

            // 3. Compress into zip
            val zipFile = File(logDir, "nmap_debug_logs.zip")
            if (zipFile.exists()) {
                zipFile.delete()
            }

            ZipOutputStream(FileOutputStream(zipFile)).use { zos ->
                // Entry 1: device_info.txt
                zos.putNextEntry(ZipEntry("device_info.txt"))
                zos.write(devInfo.toByteArray(Charsets.UTF_8))
                zos.closeEntry()

                // Entry 2: logcat.txt
                zos.putNextEntry(ZipEntry("logcat.txt"))
                zos.write(logText.toByteArray(Charsets.UTF_8))
                zos.closeEntry()
            }

            // 4. FileProvider & Intent
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                zipFile
            )

            val shareIntent = Intent(Intent.ACTION_SEND).apply {
                type = "application/zip"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_SUBJECT, "NMap Explorer 診斷日誌 (.zip)")
                putExtra(Intent.EXTRA_TEXT, "這是 NMap Explorer 的診斷日誌壓縮檔。")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }

            val chooser = Intent.createChooser(shareIntent, "分享 NMap 診斷壓縮檔 (.zip)").apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(chooser)
            Log.i(tag, "Logs zipped and shared successfully: ${zipFile.absolutePath}")
        } catch (e: Exception) {
            Log.e(tag, "Failed to zip and share logs", e)
        }
    }
}
