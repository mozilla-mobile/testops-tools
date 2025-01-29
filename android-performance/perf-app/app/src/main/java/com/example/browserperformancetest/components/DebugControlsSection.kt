package com.example.browserperformancetest.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.browserperformancetest.managers.WirelessDebugManager

@Composable
fun DebugControlsSection(
    debugManager: WirelessDebugManager,
    isDebuggingEnabled: Boolean
) {
    Column(
        modifier = Modifier.fillMaxWidth()
    ) {
        Button(
            onClick = { debugManager.enableWirelessDebugging() },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Enable Wireless Debugging")
        }

        Text(
            text = "Debugging Status: ${if (isDebuggingEnabled) "Enabled" else "Disabled"}",
            modifier = Modifier.padding(vertical = 4.dp)
        )
    }
}