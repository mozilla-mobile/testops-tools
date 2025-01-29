// components/CommandInputSection.kt
package com.example.browserperformancetest.components

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.browserperformancetest.managers.TermuxManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import androidx.compose.material3.OutlinedTextField
import com.example.browserperformancetest.utils.Logger

@Composable
fun CommandInputArea(
    scope: CoroutineScope,
    context: Context
) {
    var command by remember { mutableStateOf("") }

    Column {
        OutlinedTextField(
            value = command,
            onValueChange = { command = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("Enter command for Termux") },
            singleLine = true
        )

        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp)
        ) {
            Button(
                onClick = {
                    scope.launch {
                        TermuxManager.setupTermux(context) {
                            Logger.log(it, Logger.LogType.INFO)
                        }
                    }
                },
                modifier = Modifier.weight(1f)
            ) {
                Text("Setup Termux")
            }

            Button(
                onClick = {
                    scope.launch {
                        TermuxManager.executeCommand(context, command)?.let { result ->
                            Logger.log(result, Logger.LogType.INFO)
                        }
                        command = ""
                    }
                },
                modifier = Modifier.weight(1f)
            ) {
                Text("Execute")
            }
        }
    }
}