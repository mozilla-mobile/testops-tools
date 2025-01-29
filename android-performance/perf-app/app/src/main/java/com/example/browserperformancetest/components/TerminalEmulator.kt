// TerminalEmulator.kt
package com.example.browserperformancetest.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

@Composable
fun TerminalEmulator(
    onExecuteCommand: suspend (String) -> Unit,
    output: List<String>,
    modifier: Modifier = Modifier
) {
    val scope = rememberCoroutineScope()
    var command by remember { mutableStateOf("") }
    val listState = rememberLazyListState()

    Column(modifier = modifier) {
        // Output display
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .background(Color.Black)
                .padding(8.dp)
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize()
            ) {
                items(output) { line ->
                    Text(
                        text = line,
                        color = Color.Green,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(vertical = 2.dp)
                    )
                }
            }
        }

        // Command input
        OutlinedTextField(
            value = command,
            onValueChange = { command = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp),
            placeholder = { Text("Enter linux command...") },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(
                onSend = {
                    if (command.isNotBlank()) {
                        scope.launch {
                            onExecuteCommand(command)
                            command = ""
                            // Scroll to bottom
                            listState.animateScrollToItem(output.size)
                        }
                    }
                }
            ),
            colors = TextFieldDefaults.colors(
                unfocusedContainerColor = Color.Black,
                focusedContainerColor = Color.Black.copy(alpha = 0.8f),
                unfocusedTextColor = Color.Green,
                focusedTextColor = Color.Green
            ),
            textStyle = androidx.compose.ui.text.TextStyle(
                fontFamily = FontFamily.Monospace
            )
        )
    }
}