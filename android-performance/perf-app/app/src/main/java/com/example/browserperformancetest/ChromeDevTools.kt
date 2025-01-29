package com.example.browserperformancetest

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap

class ChromeDevTools(private val debuggerAddress: String) {
    private val client = OkHttpClient()
    private var webSocket: WebSocket? = null
    private val pendingRequests = ConcurrentHashMap<Int, CompletableFuture<JSONObject>>()
    private var nextRequestId = 1

    companion object {
        private val PERFORMANCE_METRICS_SCRIPT = """
            (() => {
                function cleanEntry(entry) {
                    return {
                        name: entry.name,
                        entryType: entry.entryType,
                        startTime: entry.startTime,
                        duration: entry.duration,
                        initiatorType: entry.initiatorType,
                        nextHopProtocol: entry.nextHopProtocol,
                        workerStart: entry.workerStart,
                        redirectStart: entry.redirectStart,
                        redirectEnd: entry.redirectEnd,
                        fetchStart: entry.fetchStart,
                        domainLookupStart: entry.domainLookupStart,
                        domainLookupEnd: entry.domainLookupEnd,
                        connectStart: entry.connectStart,
                        connectEnd: entry.connectEnd,
                        secureConnectionStart: entry.secureConnectionStart,
                        requestStart: entry.requestStart,
                        responseStart: entry.responseStart,
                        responseEnd: entry.responseEnd,
                        transferSize: entry.transferSize,
                        encodedBodySize: entry.encodedBodySize,
                        decodedBodySize: entry.decodedBodySize,
                        serverTiming: entry.serverTiming
                    };
                }

                const timing = window.performance.timing || {};
                const navigation = window.performance.getEntriesByType('navigation')[0] || {};
                const resources = window.performance.getEntriesByType('resource') || [];
                const paintEntries = performance.getEntriesByType('paint');
                const longTasks = performance.getEntriesByType('longtask') || [];

                // Clean navigation and resource entries
                const cleanedNavigation = cleanEntry(navigation);
                const cleanedResources = resources.map(cleanEntry);

                // Process paint timings
                let firstPaint = null;
                let firstContentfulPaint = null;
                paintEntries.forEach(entry => {
                    if (entry.name === 'first-paint') {
                        firstPaint = entry.startTime;
                    } else if (entry.name === 'first-contentful-paint') {
                        firstContentfulPaint = entry.startTime;
                    }
                });

                const data = {
                    url: window.location.href,
                    timestamp: Date.now(),
                    navigation: cleanedNavigation,
                    timing: {
                        navigationStart: timing.navigationStart,
                        loadEventEnd: timing.loadEventEnd,
                        domComplete: timing.domComplete,
                        domInteractive: timing.domInteractive,
                        domContentLoadedEventEnd: timing.domContentLoadedEventEnd
                    },
                    resources: cleanedResources,
                    paint: {
                        firstPaint,
                        firstContentfulPaint
                    },
                    longTasks: longTasks.map(task => ({
                        startTime: task.startTime,
                        duration: task.duration
                    }))
                };

                return JSON.stringify(data);
            })()
        """.trimIndent()
    }

    fun connect(): Boolean {
        val wsUrl = "ws://$debuggerAddress/devtools/page/0"
        println("Attempting to connect to WebSocket URL: $wsUrl")

        val request = Request.Builder()
            .url(wsUrl)
            .build()

        val connectionFuture = CompletableFuture<Boolean>()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
                println("WebSocket connection opened successfully")
                connectionFuture.complete(true)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val response = JSONObject(text)
                val id = response.optInt("id")
                pendingRequests[id]?.complete(response)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
                println("WebSocket connection failed: ${t.message}")
                connectionFuture.completeExceptionally(t)
            }
        })

        return connectionFuture.get()
    }

    suspend fun navigateToUrl(url: String): JSONObject {
        val id = nextRequestId++
        val request = JSONObject().apply {
            put("id", id)
            put("method", "Page.navigate")
            put("params", JSONObject().put("url", url))
        }

        return sendCommand(request)
    }

    suspend fun waitForPageLoad(): Boolean {
        var readyState = ""
        while (readyState != "complete") {
            val response = evaluateJavaScript("document.readyState")
            readyState = response.optJSONObject("result")
                ?.optJSONObject("result")
                ?.optString("value", "") ?: ""
            if (readyState != "complete") {
                withContext(Dispatchers.IO) {
                    Thread.sleep(100)
                }
            }
        }
        return true
    }

    suspend fun getPerformanceMetrics(): JSONObject {
        val response = evaluateJavaScript(PERFORMANCE_METRICS_SCRIPT)

        // Get the stringified JSON from value and parse it
        val metricsString = response.optJSONObject("result")
            ?.optJSONObject("result")
            ?.optString("value")

        return if (metricsString != null) {
            try {
                JSONObject(metricsString)
            } catch (e: Exception) {
                println("Failed to parse metrics string: ${e.message}")
                println("Raw metrics string: $metricsString")
                JSONObject()
            }
        } else {
            println("Failed to get metrics string. Response structure:")
            println(response.toString(2))
            JSONObject()
        }
    }

    private suspend fun evaluateJavaScript(script: String): JSONObject {
        val id = nextRequestId++
        val request = JSONObject().apply {
            put("id", id)
            put("method", "Runtime.evaluate")
            put("params", JSONObject().put("expression", script))
        }

        println("Sending JavaScript request:")
        println(request.toString(2))

        return sendCommand(request)
    }

    private suspend fun sendCommand(request: JSONObject): JSONObject {
        val future = CompletableFuture<JSONObject>()
        pendingRequests[request.getInt("id")] = future
        webSocket?.send(request.toString())
        return withContext(Dispatchers.IO) {
            future.get()
        }
    }

    fun disconnect() {
        webSocket?.close(1000, "Closing connection")
        client.dispatcher.executorService.shutdown()
    }
}