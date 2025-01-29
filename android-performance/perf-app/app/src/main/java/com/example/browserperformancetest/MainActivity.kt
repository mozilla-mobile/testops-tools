// MainActivity.kt
package com.example.browserperformancetest

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.example.browserperformancetest.managers.ChromeDebugManager
import com.example.browserperformancetest.ui.MainScreen

class MainActivity : ComponentActivity() {
    private lateinit var chromeDebugManager: ChromeDebugManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        chromeDebugManager = ChromeDebugManager(this)

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MainScreen(chromeDebugManager)
                }
            }
        }
    }
}