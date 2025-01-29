package com.example.browserperformancetest.components

import androidx.compose.animation.shrinkHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.browserperformancetest.data.ChromeDebugStatus
import com.example.browserperformancetest.managers.ChromeDebugManager
import com.example.browserperformancetest.network.AdbConnection
import kotlinx.coroutines.launch

@Composable
fun ChromeDebugSection (chromeDebugManager: ChromeDebugManager) {
    val scope = rememberCoroutineScope()
    val debugStatus by chromeDebugManager.debugStatus.collectAsState()
    val context = LocalContext.current

    Column(modifier = Modifier.fillMaxWidth().padding(8.dp)) {
        // Status indicator row stays the same
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            StatusIndicator(status = debugStatus)
            Text(
                text = when (debugStatus) {
                    ChromeDebugStatus.CONNECTED -> "Connected to Chrome"
                    ChromeDebugStatus.CONNECTING -> "Connecting..."
                    ChromeDebugStatus.DISCONNECTED -> "Disconnected"
                }
            )
        }

        Spacer(modifier = Modifier.height(8.dp))

        // Modified buttons layout to use FlowRow
        Row(
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Button(
                onClick = {
                    scope.launch {
                        chromeDebugManager.setupChromeDebugging()
                    }
                },
                enabled = debugStatus == ChromeDebugStatus.DISCONNECTED,
                modifier = Modifier.weight(1f)
            ) {
                Text(
                    "Open Debug Port",
                    modifier = Modifier.fillMaxWidth(),
                    fontSize = 13.sp
                )
            }

            Button(
                onClick = { chromeDebugManager.disconnectDebugger() },
                enabled = debugStatus != ChromeDebugStatus.DISCONNECTED,
                modifier = Modifier.weight(1f)
            ) {
                Text("Disconnect")
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        // Test ADB button in its own row
        Button(
            onClick = {
                scope.launch {
                    try {
                        val connection = AdbConnection(context)
                        if (connection.connect()) {
                            val result = connection.sendCommand("host:devices")
                            chromeDebugManager.addLog("ADB devices response: $result")
                        } else {
                            chromeDebugManager.addLog("Failed to connect to ADB")
                        }
                        connection.disconnect()
                    } catch (e: Exception) {
                        chromeDebugManager.addLog("Error checking devices: ${e.message}")
                    }
                }
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Test ADB Devices")
        }
    }
}

@Composable
fun StatusIndicator(status: ChromeDebugStatus) {
    val color = when (status) {
        ChromeDebugStatus.CONNECTED -> {
            Color.Green
        }
        ChromeDebugStatus.CONNECTING -> {
            Color.Yellow
        }
        ChromeDebugStatus.DISCONNECTED -> {
            Color.Red
        }
    }

    Box(
        modifier = Modifier
            .size(12.dp)
            .background(color = color, shape = CircleShape)
    )
}