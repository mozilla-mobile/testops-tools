package com.example.browserperformancetest.utils

import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object Logger {
    private val _output = MutableStateFlow(listOf<String>())
    val output: StateFlow<List<String>> = _output.asStateFlow()

    fun log(message: String, type: LogType = LogType.INFO) {
        val timestamp = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date())
        val formattedMessage = "[$timestamp] ${type.prefix} $message"

        // Log to both logcat and terminal view
        when (type) {
            LogType.INFO -> Log.i("AppLogger", message)
            LogType.ERROR -> Log.e("AppLogger", message)
            LogType.DEBUG -> Log.d("AppLogger", message)
            LogType.TEST -> Log.i("TestLogger", message)
        }

        _output.update { currentList ->
            currentList + formattedMessage
        }
    }

    fun clear() {
        _output.value = emptyList()
    }

    enum class LogType(val prefix: String) {
        INFO("ℹ️"),
        ERROR("❌"),
        DEBUG("🔧"),
        TEST("🧪")
    }
}