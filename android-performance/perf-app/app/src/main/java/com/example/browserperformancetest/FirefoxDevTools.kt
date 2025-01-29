import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap

class FirefoxDevTools(private val serverUrl: String) {
    private val client = OkHttpClient()
    private var webSocket: WebSocket? = null
    private val pendingRequests = ConcurrentHashMap<Int, CompletableFuture<JSONObject>>()
    private var nextRequestId = 1
    private var sessionId: String? = null

    suspend fun connect(): Boolean {
        // First create a session
        sessionId = createSession()

        // Then connect to WebSocket
        val wsUrl = "ws://localhost:4444/session/$sessionId/moz/browser/contexts/chrome"
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

    private fun createSession(): String {
        val request = Request.Builder()
            .url("http://localhost:4444/session")
            .post("""{"capabilities": {"browserName": "firefox"}}""".toRequestBody("application/json".toMediaType()))
            .build()

        val response = client.newCall(request).execute()
        val responseBody = JSONObject(response.body?.string() ?: "{}")
        return responseBody.getJSONObject("value").getString("sessionId")
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
        val script = """
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
                
                // Clean navigation and resource entries
                const cleanedNavigation = cleanEntry(navigation);
                const cleanedResources = resources.map(cleanEntry);

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
                    resources: cleanedResources
                };

                return JSON.stringify(data);
            })()
        """.trimIndent()

        return evaluateJavaScript(script)
    }

    private suspend fun evaluateJavaScript(script: String): JSONObject {
        val id = nextRequestId++
        val request = JSONObject().apply {
            put("id", id)
            put("method", "Runtime.evaluate")
            put("params", JSONObject().put("expression", script))
        }

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

        // Close the session
        sessionId?.let { sid ->
            try {
                val request = Request.Builder()
                    .url("http://localhost:4444/session/$sid")
                    .delete()
                    .build()
                client.newCall(request).execute()
            } catch (e: Exception) {
                println("Error closing Firefox session: ${e.message}")
            }
        }
    }
}