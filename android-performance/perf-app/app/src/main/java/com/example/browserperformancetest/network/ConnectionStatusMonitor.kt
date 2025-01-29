// ConnectionStatusMonitor.kt
package com.example.browserperformancetest.network

import android.util.Log
import com.example.browserperformancetest.data.ChromeDebugStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

class ConnectionStatusMonitor {
    companion object {
        private const val TAG = "ConnectionStatusMonitor"
    }

    private var webSocket: WebSocket? = null
    private val _debugStatus = MutableStateFlow(ChromeDebugStatus.DISCONNECTED)
    val debugStatus: StateFlow<ChromeDebugStatus> = _debugStatus.asStateFlow()

    private val _logs = MutableStateFlow<List<String>>(emptyList())
    val logs: StateFlow<List<String>> = _logs.asStateFlow()

    fun monitorConnection(port: Int) {
        _debugStatus.value = ChromeDebugStatus.CONNECTING
        addLog("Attempting to connect to Chrome DevTools on port $port...")

        val client = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)  // Disable timeout for WebSocket
            .build()

        val request = Request.Builder()
            .url("ws://localhost:$port/devtools/browser")
            .build()

        try {
            webSocket = client.newWebSocket(request, object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    Log.d(TAG, "WebSocket opened")
                    _debugStatus.value = ChromeDebugStatus.CONNECTED
                    addLog("Connected to Chrome DevTools")
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    Log.e(TAG, "WebSocket failure: ${t.message}")
                    _debugStatus.value = ChromeDebugStatus.DISCONNECTED
                    addLog("Connection failed: ${t.message}")
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    Log.d(TAG, "WebSocket closed: $reason")
                    _debugStatus.value = ChromeDebugStatus.DISCONNECTED
                    addLog("Connection closed: $reason")
                }
            })
        } catch (e: Exception) {
            Log.e(TAG, "Error creating WebSocket: ${e.message}")
            _debugStatus.value = ChromeDebugStatus.DISCONNECTED
            addLog("Error creating connection: ${e.message}")
        }
    }

    private fun addLog(message: String) {
        _logs.value = _logs.value + message
        Log.d(TAG, "Log: $message")
    }

    fun disconnect() {
        try {
            webSocket?.close(1000, "User initiated disconnect")
            webSocket = null
            _debugStatus.value = ChromeDebugStatus.DISCONNECTED
            addLog("Disconnected from Chrome DevTools")
        } catch (e: Exception) {
            Log.e(TAG, "Error during disconnect: ${e.message}")
            addLog("Error during disconnect: ${e.message}")
        }
    }
}