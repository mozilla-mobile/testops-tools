// MainScreen.kt
package com.example.browserperformancetest.ui

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.example.browserperformancetest.components.*
import com.example.browserperformancetest.environment.LinuxEnvironment
import com.example.browserperformancetest.managers.ChromeDebugManager
import com.example.browserperformancetest.managers.WirelessDebugManager
import com.example.browserperformancetest.utils.Logger
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

@Composable
fun MainScreen(chromeDebugManager: ChromeDebugManager) {
    // State
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val output by Logger.output.collectAsState()
    val debugManager = remember { WirelessDebugManager(context) }
    val isDebuggingEnabled by remember { mutableStateOf(debugManager.checkDebuggingEnabled()) }

    // Linux environment setup
    val linuxEnvironment = remember { LinuxEnvironment(context) }
    var terminalOutput by remember { mutableStateOf(listOf<String>()) }

    // Command execution handler
    val executeCommand: suspend (String) -> Unit = { command ->
        terminalOutput = terminalOutput + "> $command"
        linuxEnvironment.executeCommand(command).collect { line ->
            terminalOutput = terminalOutput + line
        }
    }

    // Layout
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        DebugTerminal(
            output = output,
            modifier = Modifier.weight(0.4f)
        )

        TerminalEmulator(
            onExecuteCommand = executeCommand,
            output = terminalOutput,
            modifier = Modifier.weight(0.4f)
        )

        ActionButtonsSection(
            scope = scope,
            context = context
        )

        DebugControlsSection(
            debugManager = debugManager,
            isDebuggingEnabled = isDebuggingEnabled
        )

        ChromeDebugSection(chromeDebugManager = chromeDebugManager)
    }
}