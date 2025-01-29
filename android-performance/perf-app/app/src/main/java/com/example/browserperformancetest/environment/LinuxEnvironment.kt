package com.example.browserperformancetest.environment

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import java.io.*

class LinuxEnvironment(private val context: Context) {
    private val tag = "LinuxEnvironment"
    private val baseDir: File = context.filesDir
    private var currentProcess: Process? = null

    init {
        setupEnvironment()
    }

    private fun getNativeLibraryPath(binary: String): String {
        val libraryName = "lib${binary}.so"
        return "${context.applicationInfo.nativeLibraryDir}/$libraryName"
    }

    private fun setupEnvironment() {
        try {
            // Create directory structure
            arrayOf(
                "usr/bin",
                "usr/lib",
                "usr/lib64",
                "tmp",
                "dev",
                "proc"
            ).forEach { path ->
                File(baseDir, path).mkdirs()
            }

            // Copy native libraries from app's native library dir
            val nativeLibDir = File(context.applicationInfo.nativeLibraryDir)
            Log.d(tag, "Native library dir: ${nativeLibDir.absolutePath}")

            // Copy all .so files to usr/lib
            nativeLibDir.listFiles()?.forEach { file ->
                if (file.name.endsWith(".so")) {
                    val destFile = File(baseDir, "usr/lib/${file.name}")
                    file.copyTo(destFile, overwrite = true)
                    destFile.setExecutable(true, true)
                    Log.d(tag, "Copied ${file.name} to usr/lib")
                }
            }

            // For executables that are packaged as .so files but are meant to be run
            nativeLibDir.listFiles()?.forEach { file ->
                if (file.name.startsWith("exe_")) {
                    val actualName = file.name.removePrefix("exe_").removeSuffix(".so")
                    val destFile = File(baseDir, "usr/bin/$actualName")
                    file.copyTo(destFile, overwrite = true)
                    destFile.setExecutable(true, true)
                    Log.d(tag, "Copied executable ${file.name} to usr/bin/$actualName")
                }
            }

            setPermissions()
        } catch (e: Exception) {
            Log.e(tag, "Failed to setup environment", e)
        }
    }

    private fun setPermissions() {
        // Set execute permissions for all binaries and libraries
        File(baseDir, "usr/bin").walk()
            .filter { it.isFile }
            .forEach { file ->
                file.setExecutable(true, true)
                Log.d(tag, "Set executable permission for ${file.absolutePath}")
            }
    }

    // Modify your executeCommand function
    suspend fun executeCommand(command: String): Flow<String> = flow {
        val parts = command.split("\\s+".toRegex())
        val binary = parts[0]

        // Use system binary path for basic commands
        val systemBinary = when (binary) {
            "ls" -> "/system/bin/ls"
            "ps" -> "/system/bin/ps"
            "pwd" -> "/system/bin/pwd"
            // ... add other system commands as needed
            else -> "${baseDir.absolutePath}/usr/bin/$binary"
        }

        val fullCommand = listOf(systemBinary) + parts.drop(1)

        try {
            val process = ProcessBuilder(fullCommand)
                .directory(baseDir)
                .redirectErrorStream(true)
                .apply {
                    environment().apply {
                        put("HOME", baseDir.absolutePath)
                        put("TMPDIR", "${baseDir.absolutePath}/tmp")
                        put("PREFIX", "${baseDir.absolutePath}/usr")
                        put("LD_LIBRARY_PATH", "${baseDir.absolutePath}/usr/lib")
                        put("PATH", "/system/bin:${baseDir.absolutePath}/usr/bin")
                    }
                }
                .start()

            BufferedReader(InputStreamReader(process.inputStream)).use { reader ->
                var line: String?
                while (reader.readLine().also { line = it } != null) {
                    emit(line ?: "")
                }
            }

            val exitCode = process.waitFor()
            if (exitCode != 0) {
                emit("Command completed with exit code: $exitCode")
            }
        } catch (e: Exception) {
            emit("Error: ${e.message}")
            Log.e(tag, "Error executing command", e)
        }
    }.flowOn(Dispatchers.IO)
}