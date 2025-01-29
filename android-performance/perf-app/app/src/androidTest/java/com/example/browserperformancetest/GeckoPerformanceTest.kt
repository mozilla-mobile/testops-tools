//// FirefoxPerformanceTest.kt
//package com.example.browserperformancetest
//
//import androidx.test.ext.junit.runners.AndroidJUnit4
//import androidx.compose.ui.test.junit4.createAndroidComposeRule
//import androidx.compose.ui.test.onNodeWithTag
//import androidx.compose.ui.test.performClick
//import kotlinx.coroutines.*
//import org.json.JSONObject
//import org.junit.After
//import org.junit.Before
//import org.junit.Rule
//import org.junit.Test
//import org.junit.runner.RunWith
//import android.util.Log
//import androidx.compose.ui.test.assertIsDisplayed
//import org.junit.Assert.*
//import java.util.concurrent.TimeUnit
//
//@RunWith(AndroidJUnit4::class)
//class FirefoxPerformanceTest {
//
//    @get:Rule
//    val composeTestRule = createAndroidComposeRule<GeckoViewActivity>()
//
//    private val TAG = "FirefoxPerformanceTest"
//    private val testScope = CoroutineScope(Dispatchers.Main + Job())
//
//    @Before
//    fun setup() {
//        // Let the GeckoRuntime initialize
//        Thread.sleep(2000)
//    }
//
//    @After
//    fun tearDown() {
//        testScope.cancel()
//    }
//
//    @Test
//    fun measurePageLoadPerformanceForAllWebsites() = runBlocking {
//        val metricsList = mutableListOf<JSONObject>()
//
//        repeat(5) { // Testing 5 websites
//            val deferredMetrics = CompletableDeferred<JSONObject?>()
//
//            composeTestRule.activity.apply {
//                setPerformanceListener(object : PerformanceMetricsListener {
//                    override fun onPerformanceMetricsReceived(data: JSONObject) {
//                        Log.d(TAG, "Performance Metrics Received: $data")
//                        deferredMetrics.complete(data)
//                    }
//
//                    override fun onError(error: String) {
//                        Log.e(TAG, "Error: $error")
//                        deferredMetrics.completeExceptionally(Exception(error))
//                    }
//                })
//            }
//
//            // Click the "Load Next Website" button
//            composeTestRule.onNodeWithTag("load_next_website_button")
//                .assertExists()
//                .assertIsDisplayed()
//                .performClick()
//
//            // Wait for metrics with timeout
//            val metrics = withTimeoutOrNull(TimeUnit.MINUTES.toMillis(1)) {
//                deferredMetrics.await()
//            }
//
//            // Reset listener
//            composeTestRule.activity.setPerformanceListener(null)
//
//            metrics?.let { metricsList.add(it) }
//
//            // Wait between loads to ensure clean state
//            delay(2000)
//        }
//
//        // Verify we collected metrics for all websites
//        assertTrue("Expected 5 website metrics, got ${metricsList.size}", metricsList.size == 5)
//
//        // Log the results
//        metricsList.forEachIndexed { index, metrics ->
//            Log.d(TAG, "Website ${index + 1} metrics: $metrics")
//        }
//    }
//}