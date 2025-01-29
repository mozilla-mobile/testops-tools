package com.example.test

import android.app.Instrumentation
import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test
import org.junit.runner.RunWith
//import org.chromium.chrome.browser.ChromeTabbedActivity
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.io.BufferedReader
import java.io.InputStreamReader

@RunWith(AndroidJUnit4::class)
class ChromePerformanceTest {

//    private val CHROME_PACKAGE = "com.android.chrome"
    private val LAUNCH_TIMEOUT = 5000L
    private val CHROME_PACKAGE = "com.android.chrome"
    private val PAGE_LOAD_TIMEOUT = 10000L

    @Test
    fun testChromePerformance() {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())

        // Enable Chrome debugging
//        enableChromeDebugging()

        // Start from home screen
        device.pressHome()

        // Find and click Chrome icon
        val chromeIcon = device.findObject(By.desc("Chrome"))
        chromeIcon?.let {
            it.click()

            // Wait until Chrome is in foreground
            val isChromeInForeground = device.wait(Until.hasObject(By.pkg(CHROME_PACKAGE)), LAUNCH_TIMEOUT)
            assert(isChromeInForeground) { "Chrome did not launch within timeout" }

            // Give Chrome a moment to fully load its UI
            Thread.sleep(2000)

            // Find URL bar and verify it exists
            val urlBar = device.findObject(By.res("$CHROME_PACKAGE:id/url_bar"))
            assert(urlBar != null) { "Could not find URL bar" }

            // Click URL bar and enter website
            urlBar.click()
            urlBar.text = "www.example.com"
            device.pressEnter()

            // Wait for page load with verification
//            val pageLoaded = device.wait(Until.findObject(By.desc("Page loaded")), PAGE_LOAD_TIMEOUT)
//            assert(pageLoaded != null) { "Page did not load within timeout" }

            // Give Chrome a moment to fully load its UI
            Thread.sleep(5000)

            // Collect performance metrics
            val metrics = collectPerformanceMetrics()
            println("Performance Metrics: $metrics")

            assert(metrics.isNotEmpty()) { "No performance metrics collected" }
        } ?: throw RuntimeException("Could not find Chrome icon on home screen")
    }

    private fun collectPerformanceMetrics(): Map<String, Any> {
        val metrics = mutableMapOf<String, Any>()

        try {
            // Get metrics using window.performance
            val performance = executeJavaScript("""
                JSON.stringify({
                    navigationTiming: performance.getEntriesByType('navigation')[0],
                    paintTiming: performance.getEntriesByType('paint'),
                    firstInputDelay: performance.getEntriesByType('first-input')[0],
                    loadEventEnd: performance.timing.loadEventEnd - performance.timing.navigationStart,
                    domComplete: performance.timing.domComplete - performance.timing.navigationStart,
                    firstPaint: performance.timing.firstPaint,
                    firstContentfulPaint: performance.timing.firstContentfulPaint
                })
            """.trimIndent())

            val jsonMetrics = JSONObject(performance)
            metrics["navigationTiming"] = jsonMetrics.getJSONObject("navigationTiming")
            metrics["paintTiming"] = jsonMetrics.getJSONArray("paintTiming")
            metrics["loadEventEnd"] = jsonMetrics.getLong("loadEventEnd")
            metrics["domComplete"] = jsonMetrics.getLong("domComplete")
            metrics["firstPaint"] = jsonMetrics.getLong("firstPaint")
            metrics["firstContentfulPaint"] = jsonMetrics.getLong("firstContentfulPaint")

        } catch (e: Exception) {
            println("Error collecting metrics: ${e.message}")
            e.printStackTrace()
        }

        return metrics
    }

    private fun executeJavaScript(script: String): String {
        val debuggerPort = 9515 // Default Chrome debugging port
        val url = URL("http://localhost:$debuggerPort/json")
        val connection = url.openConnection() as HttpURLConnection

        try {
            connection.requestMethod = "POST"
            connection.setRequestProperty("Content-Type", "application/json")
            connection.doOutput = true

            val payload = JSONObject().apply {
                put("id", 1)
                put("method", "Runtime.evaluate")
                put("params", JSONObject().apply {
                    put("expression", script)
                })
            }

            val requestBody = payload.toString()
            println("Request:")
            println(requestBody)

            val outputStream = connection.outputStream
            outputStream.write(requestBody.toByteArray())
            outputStream.flush()

            val responseCode = connection.responseCode
            if (responseCode == HttpURLConnection.HTTP_OK) {
                val inputStream = connection.inputStream
                val response = inputStream.bufferedReader().use { it.readText() }
                println("Response:")
                println(response)

                val jsonResponse = JSONObject(response)
                val result = jsonResponse.optJSONObject("result")
                return result?.optString("value", "") ?: ""
            } else {
                val errorStream = connection.errorStream
                val errorResponse = errorStream?.bufferedReader()?.use { it.readText() } ?: ""
                println("Error Response:")
                println(errorResponse)

                throw RuntimeException("Failed to execute JavaScript. Response code: $responseCode")
            }
        } finally {
            connection.disconnect()
        }
    }

//    private fun executeJavaScript(script: String): String {
//        // Use Chrome DevTools Protocol to execute JavaScript
//        // This is a simplified version - you'll need to implement the actual CDP communication
//        val debuggerPort = 9222 // Default Chrome debugging port
//        val conn = URL("http://localhost:$debuggerPort/json/new").openConnection() as HttpURLConnection
//
//        return try {
//            BufferedReader(InputStreamReader(conn.inputStream)).use { reader ->
//                reader.readText()
//            }
//        } finally {
//            conn.disconnect()
//        }
//    }
}