package com.example.browserperformancetest

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class SettingsNavigationTest {
    private lateinit var device: UiDevice
    private val LAUNCH_TIMEOUT = 5000L
    private val PACKAGE = "com.android.settings"

    private fun dumpWindowHierarchy(filename: String = "window_dump.xml") {
        // Dump the window hierarchy to a file
        device.dumpWindowHierarchy(File(InstrumentationRegistry.getInstrumentation().targetContext.getExternalFilesDir(null), filename))
        println("Dumped window hierarchy to: ${filename}")
    }

    @Before
    fun startMainActivityFromHomeScreen() {
        // Initialize UiDevice instance
        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())

        // Start from home screen
        device.pressHome()

        // Wait for launcher
        val launcherPackage: String = device.launcherPackageName
        device.wait(
            Until.hasObject(By.pkg(launcherPackage).depth(0)),
            LAUNCH_TIMEOUT
        )

        // Launch our app
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)?.apply {
            addFlags(android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK)
        }
        context.startActivity(intent)

        // Wait for app to launch
        device.wait(
            Until.hasObject(By.pkg(context.packageName).depth(0)),
            LAUNCH_TIMEOUT
        )
    }

    @Test
    fun testNavigateToWirelessDebugging() {
        // Click the Settings button in our app
//        val settingsButton = device.findObject(UiSelector().text("Open Settings Split"))
//        settingsButton.click()
        // Launch Termux first
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val termuxIntent = context.packageManager.getLaunchIntentForPackage("com.termux")
        termuxIntent?.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(termuxIntent)

        // Wait for Termux to launch
        device.wait(
            Until.hasObject(By.pkg("com.termux").depth(0)),
            LAUNCH_TIMEOUT
        )

        // Press and hold recent apps button to enter split screen
        device.pressRecentApps()
        Thread.sleep(500) // Wait for recents to appear

        // Find and long press the Termux card to enter split screen
        val termuxCard = device.findObject(UiSelector().descriptionContains("Termux"))
        termuxCard.longClick()

        // Find and click "Split screen" option
        val splitScreenButton = device.findObject(UiSelector().text("Split screen"))
        splitScreenButton.click()

        // Now launch Settings in the other half
        val settingsIntent = context.packageManager.getLaunchIntentForPackage("com.android.settings")
        settingsIntent?.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(settingsIntent)

        // Wait for Settings to launch
        device.wait(
            Until.hasObject(By.pkg("com.android.settings")),
            LAUNCH_TIMEOUT
        )


        // Wait for Settings to open
        device.wait(Until.hasObject(By.pkg(PACKAGE).desc("Search")), LAUNCH_TIMEOUT)

        // Find and click the search button using its content description
        val searchButton = device.findObject(UiSelector().className("android.widget.Button").descriptionContains("Search"))
        assert(searchButton.exists()) { "Search button not found" }
        searchButton.click()

        // Wait for search field using its specific resource ID
        val searchField = device.findObject(
            UiSelector().resourceId("com.android.settings.intelligence:id/search_src_text")
        )
        assert(searchField.exists()) { "Search field not found" }
        searchField.text = "Wireless debugging"

        // Wait for search results to load and specifically for "Wireless debugging" to appear
        device.wait(
            Until.hasObject(By.text("Wireless debugging")),
            LAUNCH_TIMEOUT
        )

        // Click the parent clickable LinearLayout containing "Wireless debugging"
        println("Waiting for Wireless debugging search result...")
        val wirelessDebuggingSearchResult = device.findObject(
            UiSelector()
                .className("android.widget.LinearLayout")
                .clickable(true)
                .childSelector(
                    UiSelector()
                        .className("android.widget.TextView")
                        .text("Wireless debugging")
                )
        )

        assert(wirelessDebuggingSearchResult.exists()) { "Wireless debugging search result not found" }
        println("Found Wireless debugging search result, clicking...")
        wirelessDebuggingSearchResult.click()

        // Wait for Developer Options screen and Wireless debugging setting
        println("Waiting for Developer Options screen...")
        device.wait(
            Until.hasObject(By.text("Developer options")),
            LAUNCH_TIMEOUT
        )

        // The Wireless debugging setting might need scrolling to become visible
        val wirelessDebuggingSetting = device.findObject(
            UiSelector()
                .className("android.widget.LinearLayout")
                .childSelector(
                    UiSelector()
                        .className("android.widget.RelativeLayout")
                        .childSelector(
                            UiSelector()
                                .resourceId("android:id/title")
                                .text("Wireless debugging")
                        )
                )
        )

        // Scroll until we find it
        var maxScrolls = 10
        while (!wirelessDebuggingSetting.exists() && maxScrolls > 0) {
            device.swipe(720, 2000, 720, 500, 10) // Adjust coordinates based on your screen
            maxScrolls--
            Thread.sleep(500) // Give UI time to settle after scroll
        }

        assert(wirelessDebuggingSetting.exists()) { "Wireless debugging setting not found in Developer options" }
        println("Found Wireless debugging setting")

        // Verify the summary text is correct
        val summary = device.findObject(
            UiSelector()
                .resourceId("android:id/summary")
                .text("Debug mode when Wi‑Fi is connected")
        )
        assert(summary.exists()) { "Wireless debugging summary text not found" }

        // Find and click the wireless debugging toggle switch
        val toggleSwitch = device.findObject(
            UiSelector()
                .className("android.widget.Switch")
                .description("Wireless debugging")
        )
        assert(toggleSwitch.exists()) { "Wireless debugging toggle switch not found" }
        println("Found toggle switch, clicking...")
        toggleSwitch.click()

        // Wait for the system modal dialog with a 5 second timeout
        val dialogTitle = device.wait(
            Until.hasObject(
                By.text("Allow wireless debugging on this network?")
            ),
            5000 // 5 second timeout
        )

        // If dialog appears, click Allow
        if (dialogTitle) {
            println("Found system modal, clicking Allow...")
            val allowButton = device.findObject(
                UiSelector()
                    .className("android.widget.Button")
                    .text("Allow")
            )
            assert(allowButton.exists()) { "Allow button not found in system modal" }
            allowButton.click()
        } else {
            println("System modal did not appear within 5 seconds")
        }
    }
}