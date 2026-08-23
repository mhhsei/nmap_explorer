package com.example.nmapexplorer

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

/**
 * 前台常駐服務 (Foreground Service)
 * 
 * 作用：保證 App 在背景或螢幕鎖定時，Python 伺服器與 GPS 定位不會被 Android 系統隨意砍掉（省電查殺）。
 * 就像在手機狀態列掛上一個「工作中」的小告示牌，讓 Android 系統知道這個 App 正在幫視障者即時導航，必須保持運作。
 */
class ServerForegroundService : Service() {

    private val tag = "ServerForegroundService"

    /**
     * 當服務被啟動時觸發
     * 1. 建立通知管道 (Notification Channel)
     * 2. 發布常駐通知並將此服務提升為「前台服務 (Foreground Service)」
     * 3. 嚴格遵循 Android 14+ 規範，指定類型為 FOREGROUND_SERVICE_TYPE_LOCATION
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 建立通知管道（Android 8.0 以上規定所有通知必須有 Channel）
        createNotificationChannel()

        // 建立顯示在手機通知列的常駐通知
        val notification: Notification = NotificationCompat.Builder(this, "NMAP_SERVICE_CHANNEL")
            .setContentTitle("NMap Explorer")
            .setContentText("GPS 與地圖探索引擎運行中...")
            .setSmallIcon(android.R.drawable.ic_dialog_map)
            .setOngoing(true)
            .build()

        try {
            // 檢查是否已取得精確定位或粗略定位權限
            val hasLocationPerm = ContextCompat.checkSelfPermission(
                this,
                android.Manifest.permission.ACCESS_FINE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED || ContextCompat.checkSelfPermission(
                this,
                android.Manifest.permission.ACCESS_COARSE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED

            // Android 10 (API 29) 以上支援指定前台服務類型
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                if (hasLocationPerm) {
                    // 已取得權限：以 location 類型啟動前台服務
                    startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
                } else {
                    // 尚未取得權限：在 Android 14 (API 34) 下若無權限調用 typed startForeground 會拋異常，故需降級防禦
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                        Log.w(tag, "Location permission not granted yet, deferring typed startForeground.")
                    } else {
                        startForeground(1, notification)
                    }
                }
            } else {
                startForeground(1, notification)
            }
        } catch (e: Exception) {
            Log.e(tag, "Failed to startForeground: ${e.message}", e)
        }
        
        // 若服務被系統意外終止，不要自動重啟（避免使用者已不需要時耗電）
        return START_NOT_STICKY
    }

    /**
     * 當使用者在多工畫面將 App 往上滑掉（關閉）時觸發
     * 作用：徹底釋放前台服務並移除通知，避免在背景偷偷耗電。
     */
    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        Log.i(tag, "App task removed (swiped away). Stopping foreground service to save battery.")
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                stopForeground(STOP_FOREGROUND_REMOVE)
            } else {
                @Suppress("DEPRECATION")
                stopForeground(true)
            }
        } catch (e: Exception) {
            Log.e(tag, "Error during stopForeground on task removal", e)
        }
        // 終止自己
        stopSelf()
    }

    /**
     * 當服務被銷毀時觸發
     * 作用：清理前台狀態與通知列圖示
     */
    override fun onDestroy() {
        super.onDestroy()
        Log.i(tag, "ServerForegroundService destroyed.")
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                stopForeground(STOP_FOREGROUND_REMOVE)
            } else {
                @Suppress("DEPRECATION")
                stopForeground(true)
            }
        } catch (e: Exception) {
            Log.e(tag, "Error in onDestroy stopForeground", e)
        }
    }

    /**
     * 本服務為啟動型服務 (Started Service)，不提供跨行程綁定 (Bind)
     */
    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    /**
     * 建立 Android 8.0+ 專用的通知管道
     */
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val serviceChannel = NotificationChannel(
                "NMAP_SERVICE_CHANNEL",
                "NMap Explorer Service",
                // 設定為低重要性 (IMPORTANCE_LOW)，避免每次發出嗶嗶聲打擾視障者聽語音
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(serviceChannel)
        }
    }
}

