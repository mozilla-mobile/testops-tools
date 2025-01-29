package com.example.browserperformancetest.managers

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import eu.chainfire.libsuperuser.Shell

class WirelessDebugManager(private val context: Context) {
    private val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private val channelId = "wireless_debug_channel"
    private val notificationId = 1001

    init {
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Wireless Debug",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Channel for wireless debugging notifications"
            }
            notificationManager.createNotificationChannel(channel)
        }
    }

    fun enableWirelessDebugging() {
        try {
            Settings.Global.putInt(context.contentResolver, "adb_wifi_enabled", 1)

            // Launch developer options
            val intent = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            context.startActivity(intent)

        } catch (e: Exception) {
            Log.e("WirelessDebug", "Failed to enable wireless debugging", e)
        }
    }

    fun checkDebuggingEnabled(): Boolean {
        return try {
            Settings.Global.getInt(
                context.contentResolver,
                Settings.Global.ADB_ENABLED,
                0
            ) == 1
        } catch (e: Exception) {
            false
        }
    }
}