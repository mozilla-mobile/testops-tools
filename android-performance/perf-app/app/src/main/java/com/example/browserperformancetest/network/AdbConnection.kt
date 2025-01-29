// AdbConnection.kt
package com.example.browserperformancetest.network

import android.content.Context
import android.net.LocalSocket
import android.net.LocalSocketAddress
import android.util.Log
import java.io.InputStream
import java.io.OutputStream
import java.util.regex.Pattern

class AdbConnection(private val context: Context) {
    companion object {
        private const val TAG = "AdbConnection"
        private val ADB_FORWARD = Pattern.compile("^([0-9]+)$")
    }

    private var socket: LocalSocket? = null
    private var outputStream: OutputStream? = null
    private var inputStream: InputStream? = null

    fun connect(): Boolean {
        try {
            socket = LocalSocket()
            socket?.connect(LocalSocketAddress("adbd", LocalSocketAddress.Namespace.RESERVED))
            outputStream = socket?.outputStream
            inputStream = socket?.inputStream
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to connect to ADB: ${e.message}")
            disconnect()
            return false
        }
    }

    fun disconnect() {
        try {
            outputStream?.close()
            inputStream?.close()
            socket?.close()
        } catch (e: Exception) {
            Log.e(TAG, "Error closing ADB connection: ${e.message}")
        }
        outputStream = null
        inputStream = null
        socket = null
    }

    fun sendCommand(command: String): String? {
        try {
            val fullCommand = "${command.length.toString().padStart(4, '0')}$command"
            outputStream?.write(fullCommand.toByteArray())
            outputStream?.flush()

            val response = readAdbResponse()
            if (response?.startsWith("OKAY") == true) {
                return readAdbResponse()
            } else {
                Log.e(TAG, "ADB command failed: $response")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error sending ADB command: ${e.message}")
        }
        return null
    }

    private fun readAdbResponse(): String? {
        try {
            // First read the status (4 bytes)
            val statusBuffer = ByteArray(4)
            if (inputStream?.read(statusBuffer) != 4) {
                return null
            }
            val status = String(statusBuffer)

            // If it's not OKAY, read the error message
            if (status != "OKAY") {
                // Read length (4 hex digits)
                val lenBuffer = ByteArray(4)
                if (inputStream?.read(lenBuffer) != 4) {
                    return null
                }
                val length = String(lenBuffer).toInt(16)

                // Read error message
                val errorBuffer = ByteArray(length)
                if (inputStream?.read(errorBuffer) != length) {
                    return null
                }
                return "FAIL" + String(errorBuffer)
            }

            // For OKAY responses, read the payload
            val buffer = ByteArray(4096)
            val read = inputStream?.read(buffer) ?: return null
            return "OKAY" + String(buffer, 0, read)
        } catch (e: Exception) {
            Log.e(TAG, "Error reading ADB response: ${e.message}")
            return null
        }
    }
}

