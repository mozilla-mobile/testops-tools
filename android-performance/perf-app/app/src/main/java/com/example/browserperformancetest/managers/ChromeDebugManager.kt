// ChromeDebugManager.kt
package com.example.browserperformancetest.managers

import android.content.Context
import android.content.Intent
import android.util.Log
import com.example.browserperformancetest.utils.Logger
import com.example.browserperformancetest.data.ChromeDebugStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import java.net.Socket

class ChromeDebugManager(private val context: Context) {
    companion object {
        private const val TAG = "ChromeDebugManager"
        private const val CHROME_PACKAGE = "com.android.chrome"
        private const val CHROME_ACTIVITY = "com.google.android.apps.chrome.Main"
    }

    private val _debugStatus = MutableStateFlow(ChromeDebugStatus.DISCONNECTED)
    val debugStatus: StateFlow<ChromeDebugStatus> = _debugStatus.asStateFlow()

    private val _logs = MutableStateFlow<List<String>>(emptyList())
    val logs: StateFlow<List<String>> = _logs.asStateFlow()

    suspend fun setupChromeDebugging(): Result<Int> = withContext(Dispatchers.IO) {
        try {
            addLog("Attempting to launch Chrome with debugging enabled...")

            // Try to launch Chrome directly with debug flags
            val intent = Intent().apply {
                setClassName(CHROME_PACKAGE, CHROME_ACTIVITY)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                // Add Chrome debugging flags
                putExtra("enable-debugging", true)
                putExtra("remote-debugging-port", "9222")
                putExtra("dcheck-is-on", true) // Enables more debugging features
            }

            context.startActivity(intent)
            addLog("Launched Chrome, waiting for debug port...")

            // Wait for the debugging port to be available
            var attempts = 0
            val maxAttempts = 10
            while (attempts < maxAttempts) {
                try {
                    val socket = Socket("localhost", 9222)
                    socket.close()
                    addLog("Debug port 9222 is available")
                    _debugStatus.value = ChromeDebugStatus.CONNECTED
                    return@withContext Result.success(9222)
                } catch (e: Exception) {
                    attempts++
                    delay(500) // Wait half a second between attempts
                }
            }

            throw Exception("Timeout waiting for debug port")
        } catch (e: Exception) {
            addLog("Error: ${e.message}")
            _debugStatus.value = ChromeDebugStatus.DISCONNECTED
            Result.failure(e)
        }
    }

    fun addLog(message: String) {
        Logger.log(message)
        Log.d(TAG, message)
    }

    fun disconnectDebugger() {
        // Force stop Chrome to ensure debugging is disabled
        try {
            val intent = Intent().apply {
                setClassName(CHROME_PACKAGE, CHROME_ACTIVITY)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                action = Intent.ACTION_MAIN
                addCategory(Intent.CATEGORY_HOME)
            }
            context.startActivity(intent)
            addLog("Chrome closed")
        } catch (e: Exception) {
            addLog("Error closing Chrome: ${e.message}")
        }
        _debugStatus.value = ChromeDebugStatus.DISCONNECTED
    }
}