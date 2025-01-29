// PerformanceMetricsListener.kt
package com.example.browserperformancetest.network

import org.json.JSONObject

interface PerformanceMetricsListener {
    fun onPerformanceMetricsReceived(data: JSONObject)
    fun onError(error: String)
}
