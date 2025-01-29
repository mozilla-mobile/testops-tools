// WirelessDebugAccessibilityService.kt
package com.example.browserperformancetest.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

class WirelessDebugAccessibilityService : AccessibilityService() {
    private val _pairingInfo = MutableStateFlow<PairingInfo?>(null)
    val pairingInfo: StateFlow<PairingInfo?> = _pairingInfo

    data class PairingInfo(
        val code: String,
        val ipAndPort: String
    )

    companion object {
        private var instance: WirelessDebugAccessibilityService? = null

        fun getInstance(): WirelessDebugAccessibilityService? = instance
    }

    override fun onServiceConnected() {
        instance = this

        val info = AccessibilityServiceInfo().apply {
            eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                    AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
            packageNames = arrayOf("com.android.settings")
        }

        serviceInfo = info
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (event.packageName != "com.android.settings") return

        val rootNode = rootInActiveWindow ?: return

        // Look for the pairing dialog
        val pairingCode = findNodeByResourceId(rootNode, "com.android.settings:id/pairing_code")
        val ipAddr = findNodeByResourceId(rootNode, "com.android.settings:id/ip_addr")

        if (pairingCode != null && ipAddr != null) {
            _pairingInfo.value = PairingInfo(
                code = pairingCode.text.toString(),
                ipAndPort = ipAddr.text.toString()
            )
        }

        rootNode.recycle()
    }

    override fun onInterrupt() {
        instance = null
    }

    private fun findNodeByResourceId(root: AccessibilityNodeInfo, resourceId: String): AccessibilityNodeInfo? {
        val nodes = root.findAccessibilityNodeInfosByViewId(resourceId)
        return nodes.firstOrNull()
    }
}