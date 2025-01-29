// managers/SettingsManager.kt
package com.example.browserperformancetest.managers

import android.app.ActivityOptions
import android.content.Context
import android.content.Intent
import android.provider.Settings

object SettingsManager {
    fun openSettings(context: Context, onLog: (String) -> Unit) {
        try {
            val intent = Intent(Settings.ACTION_SETTINGS).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                            Intent.FLAG_ACTIVITY_LAUNCH_ADJACENT or
                            Intent.FLAG_ACTIVITY_MULTIPLE_TASK or
                            Intent.FLAG_ACTIVITY_NO_ANIMATION
                )
            }

            val options = ActivityOptions.makeBasic()
            context.startActivity(intent, options.toBundle())
            onLog("Opening Settings in split screen...")
        } catch (e: Exception) {
            onLog("Error opening Settings: ${e.message}")
        }
    }

    fun openDeveloperOptions(context: Context, onLog: (String) -> Unit) {
        try {
            val intent = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            onLog("Opening Developer Options...")
        } catch (e: Exception) {
            onLog("Error opening Developer Options: ${e.message}")
        }
    }
}