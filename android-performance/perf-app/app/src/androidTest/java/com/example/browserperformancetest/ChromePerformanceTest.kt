// ChromePerformanceTest.kt
package com.example.browserperformancetest

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import android.util.Log
import androidx.compose.ui.test.assertIsDisplayed
import com.example.browserperformancetest.network.PerformanceMetricsListener
import org.junit.Assert.*

@RunWith(AndroidJUnit4::class)
class ChromePerformanceTest {
    private val TAG = "ChromePerformanceTest"

    private val testScope = CoroutineScope(Dispatchers.Main + Job())

    @Before
    fun setup() {
        // Access the activity using the composeTestRule
//        composeTestRule.activity.apply {
//            webViewActivity = this
//        }
    }

    @After
    fun tearDown() {
        // Cancel the coroutine scope to clean up
        testScope.cancel()
    }

    @Test
    fun measurePageLoadPerformanceForAllWebsites() = runBlocking {
        // Define the list of websites to test
        val websites = listOf(
            "www.example.com",
            "www.adobe.com",
            "www.amazon.com",
            "www.walmart.com",
            "www.google.com"
            // Add more URLs as needed
        )

        // List to store metrics for each website
        val metricsList = mutableListOf<JSONObject>()

        // Iterate through each website
        for (index in websites.indices) {
            val website = websites[index]
            val deferredMetrics = CompletableDeferred<JSONObject?>()

//            composeTestRule.activity.apply {
//                // Set the listener to capture performance metrics
//                setPerformanceMetricsListener(object : PerformanceMetricsListener {
//                    override fun onPerformanceMetricsReceived(data: JSONObject) {
//                        Log.d(TAG, "Performance Metrics Received for $website: $data")
//                        deferredMetrics.complete(data)
//                    }
//
//                    override fun onError(error: String) {
//                        TODO("Not yet implemented")
//                    }
//                })
//            }

            // Click the "Load Next Website" button using Compose testing
//            composeTestRule.onNodeWithTag("load_next_website_button")
//                .assertExists("Load Next Website button does not exist")
//                .assertIsDisplayed()
//                .performClick()

            // Await the metrics with a timeout
            val metrics = withTimeoutOrNull(60000L) { // 60 seconds timeout
                deferredMetrics.await()
            }

            // Reset the listener to avoid memory leaks or unintended behavior
//            composeTestRule.activity.apply {
//                setPerformanceMetricsListener(null)
//            }

            if (metrics == null) {
                Log.d(TAG,"Performance metrics for $website were not received within the timeout period.")
            }

            if (metrics != null) {
                metricsList.add(metrics)
            }
        }
    }
}
