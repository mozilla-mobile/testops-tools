package com.example.browserperformancetest

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream

@RunWith(AndroidJUnit4::class)
class DumpSelectorsTest {

    @Test
    fun printUiHierarchyToConsole() {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())

        // Step 1: Launch the Settings app
        device.pressHome()
        device.executeShellCommand("am start -a android.settings.SETTINGS")
        device.waitForIdle()

        // Step 2: Dump the UI hierarchy to a ByteArrayOutputStream
        val outputStream = ByteArrayOutputStream()
        device.dumpWindowHierarchy(outputStream)

        // Step 3: Convert to String and print to Logcat
        val hierarchyDump = outputStream.toString(Charsets.UTF_8)
        println("======== UI HIERARCHY DUMP START ========")
        println(hierarchyDump)
        println("======== UI HIERARCHY DUMP END ========")
    }
}
