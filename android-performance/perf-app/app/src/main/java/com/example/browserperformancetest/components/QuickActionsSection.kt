// components/QuickActionsSection.kt
package com.example.browserperformancetest.components

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.browserperformancetest.managers.TermuxManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import com.example.browserperformancetest.utils.Logger
import com.example.browserperformancetest.managers.SettingsManager

@Composable
fun QuickActionButtons(
    scope: CoroutineScope,
    context: Context
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // First row of buttons
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(
                onClick = {
                    scope.launch {
                        TermuxManager.launchTermux(context) {
                            Logger.log(it, Logger.LogType.INFO)
                        }
                    }
                },
                modifier = Modifier.weight(1f)
            ) {
                Text("Launch Termux Split", fontSize = 12.sp)
            }

            Button(
                onClick = {
                    scope.launch {
                        SettingsManager.openSettings(context) {
                            Logger.log(it, Logger.LogType.INFO)
                        }
                    }
                },
                modifier = Modifier.weight(1f)
            ) {
                Text("Open Settings Split", fontSize = 12.sp)
            }
        }

        // Second row for the new button
        Button(
            onClick = {
                scope.launch {
                    TermuxManager.openTermuxAndDevOptions(context) {
                        Logger.log(it, Logger.LogType.INFO)
                    }
                }
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Termux + Dev Options")
        }
    }
}