// managers/TermuxManager.kt
package com.example.browserperformancetest.managers

import android.app.ActivityOptions
import android.content.Context
import android.content.Intent
import android.graphics.Rect
import android.content.res.AssetManager
import android.os.Environment
import java.io.File
import java.io.FileOutputStream

object TermuxManager {
    fun launchTermux(context: Context, onLog: (String) -> Unit) {
        try {
            val termuxIntent = Intent().apply {
                setClassName("com.termux", "com.termux.app.TermuxActivity")
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                            Intent.FLAG_ACTIVITY_LAUNCH_ADJACENT or
                            Intent.FLAG_ACTIVITY_MULTIPLE_TASK or
                            Intent.FLAG_ACTIVITY_NO_USER_ACTION
                )
            }

            val options = ActivityOptions.makeBasic()
            context.startActivity(termuxIntent, options.toBundle())
            onLog("Launching Termux in split screen...")
        } catch (e: Exception) {
            onLog("Error launching Termux: ${e.message}\nMake sure Termux is installed from F-Droid or GitHub")
        }
    }

    fun openTermuxAndDevOptions(context: Context, onLog: (String) -> Unit) {
        try {
            onLog("Starting Termux setup...")

            val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            val timestamp = System.currentTimeMillis()

            // Setup both files with unique names
            val setupFile = File(downloadsDir, "termux_setup_script_${timestamp}.sh")
            val tarFile = File(downloadsDir, "termux_deps_${timestamp}.tar")

            setupFile.createNewFile()
            tarFile.createNewFile()

            // Copy both files
            copyAssetToFile(context.assets, "setup.sh", setupFile)
            copyAssetToFile(context.assets, "termux_deps.tar", tarFile)
            onLog("Copied setup script and tar file to Downloads...")

            // Launch Termux in bottom 25% of screen
            val termuxIntent = Intent().apply {
                setClassName("com.termux", "com.termux.app.TermuxActivity")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_NO_USER_ACTION)
            }

            // Calculate window sizes
            val displayMetrics = context.resources.displayMetrics
            val screenHeight = displayMetrics.heightPixels
            val screenWidth = displayMetrics.widthPixels

            val termuxBounds = Rect(
                0,  // left
                (screenHeight * 0.75).toInt(),  // top (75% down)
                screenWidth,  // right
                screenHeight  // bottom
            )

            val termuxOptions = ActivityOptions.makeBasic().apply {
                launchBounds = termuxBounds
            }

            context.startActivity(termuxIntent, termuxOptions.toBundle())
            Thread.sleep(500)

            // Launch Developer Options with top 75% bounds
            val devOptionsIntent = Intent(android.provider.Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }

            val devOptionsBounds = Rect(
                0,  // left
                0,  // top
                screenWidth,  // right
                (screenHeight * 0.75).toInt()  // bottom (75% height)
            )

            val devOptions = ActivityOptions.makeBasic().apply {
                launchBounds = devOptionsBounds
            }

            context.startActivity(devOptionsIntent, devOptions.toBundle())
            onLog("Launched Developer Options with floating Termux window...")
        } catch (e: Exception) {
            onLog("Error launching apps: ${e.message}")
        }
    }

    fun setupTermux(context: Context, onLog: (String) -> Unit) {
        try {
            onLog("Starting Termux setup...")

            val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            val timestamp = System.currentTimeMillis()

            // Setup both files with unique names
            val setupFile = File(downloadsDir, "termux_setup_script_${timestamp}.sh")
            val tarFile = File(downloadsDir, "termux_deps_${timestamp}.tar")

            setupFile.createNewFile()
            tarFile.createNewFile()

            // Copy both files
            copyAssetToFile(context.assets, "setup.sh", setupFile)
            copyAssetToFile(context.assets, "termux_deps.tar", tarFile)
            onLog("Copied setup script and tar file to Downloads...")

            val termuxIntent = Intent().apply {
                setClassName("com.termux", "com.termux.app.TermuxActivity")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_USER_ACTION)
            }

            val options = ActivityOptions.makeBasic()
            context.startActivity(termuxIntent, options.toBundle())

            Thread.sleep(1000)
            onLog("Setup commands sent to Termux.")

        } catch (e: Exception) {
            onLog("Error during setup: ${e.message}")
            e.printStackTrace()
        }
    }

    fun copyAssetToFile(assets: AssetManager, assetName: String, destFile: File) {
        assets.open(assetName).use { input ->
            FileOutputStream(destFile).use { output ->
                input.copyTo(output)
            }
        }
    }

    private fun copyAssetFolder(assets: AssetManager, srcPath: String, dstPath: String) {
        try {
            val files = assets.list(srcPath)
            if (files?.isEmpty() == true) return

            File(dstPath).mkdirs()

            files?.forEach { file ->
                val subSrcPath = if (srcPath == "") file else "$srcPath/$file"
                val subDstPath = "$dstPath/$file"

                if (assets.list(subSrcPath)?.isEmpty() == false) {
                    // If it's a folder, recurse
                    copyAssetFolder(assets, subSrcPath, subDstPath)
                } else {
                    // If it's a file, copy it
                    assets.open(subSrcPath).use { input ->
                        FileOutputStream(subDstPath).use { output ->
                            input.copyTo(output)
                        }
                    }
                }
            }
        } catch (e: Exception) {
            throw Exception("Error copying asset folder: ${e.message}")
        }
    }

    fun executeCommand(context: Context, command: String): String? {
        return try {
            val termuxIntent = Intent().apply {
                setClassName("com.termux", "com.termux.app.RunCommandService")
                action = "com.termux.RUN_COMMAND"
                putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash")
                putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arrayOf("-c", command))
                putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }

            context.startService(termuxIntent)
            "Command sent to Termux: $command"
        } catch (e: Exception) {
            "Failed to send command to Termux: ${e.message}"
        }
    }
}