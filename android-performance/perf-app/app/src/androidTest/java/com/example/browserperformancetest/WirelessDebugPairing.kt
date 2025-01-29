package com.example.browserperformancetest

import FirefoxDevTools
import android.app.ActivityOptions
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.os.Build
import android.os.Environment
import android.provider.Settings
import android.view.KeyEvent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject
import androidx.test.uiautomator.UiSelector
import androidx.test.uiautomator.Until
import com.example.browserperformancetest.managers.TermuxManager.copyAssetToFile
import com.example.browserperformancetest.utils.Logger
import junit.framework.TestCase.assertTrue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.junit.Before
import org.junit.Ignore
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.IOException

@RunWith(AndroidJUnit4::class)
class WirelessDebugAutomationTest {
    // open settings > developer options in full screen
    // scroll to wireless debugging fragment
    // click wireless debugging switch
    // click 'accept' on system dialog
    // click wireless debugging title
    // get wireless debugging ip:port
    // click 'pair device with pairing code'
    // get pairing ip:port and pairing code
    // resize developer option to top 75% of screen as floating window
    // copy termux_setup_{timestamp}.sh from /main/assets to /sdcard
    // copy termux_bundle_{timestamp}.tar to /sdcard
    // open termux resized to bottom 25% of screen as floating window
    // send input text to termux to move termux files from /sdcard to $HOME
    // send input text to termux 'chmod +x termux_setup_{timestamp}.sh'
    // run termux_setup_{timestamp}.sh {timestamp} (timestamp is needed for termux_bundle_{timestamp}.tar in script)
    // SETUP SCRIPT:
    //    extract and unzip termux_bundle.tar
    //    run chmod 755 for entire termux_bundle directory (needed for /lib64/ld-linux-x86-64.so.2)
    //    move termux_bundle/termux.properties with new session shortcut 'control + t' to $HOME/.termux/termux.properties
    //    move termux_bundle/chromedriver binary to $HOME/chromedriver
    //    move termux_bundle/lib64 to $PREFIX/lib64 ($PREFIX=/data/data/com.termux/files/usr)
    //    ensure $PREFIX/lib64/ld-linux-x86-64.so.2 has 755 permissions
    //    install chromedriver dependency packages:
    //        android-tools (for adb)
    //        qemu-user-x86-64 (for linux64 emulatino on arm64)
    //        websocat (for websocket connection to browser debug ports)
    // reload termux with 'termux-reload-settings' to load new termux.properties
    private lateinit var device: UiDevice
    private lateinit var context: Context
    private val LAUNCH_TIMEOUT = 5000L

    @Before
    fun startMainActivityFromHomeScreen() {
        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val context = InstrumentationRegistry.getInstrumentation().targetContext

//        // Start from home screen
        device.pressHome()

        // Wait for launcher
        val launcherPackage = device.launcherPackageName
        device.wait(
            Until.hasObject(By.pkg(launcherPackage).depth(0)),
            LAUNCH_TIMEOUT
        )

        // First, open Developer Options normally in full screen
        // opening as floating window will block visibility of wireless debugging system dialog
        val devOptionsIntent = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(devOptionsIntent)

        // Wait for Developer Options to appear
        device.wait(
            Until.hasObject(By.text("Developer options")),
            LAUNCH_TIMEOUT
        )

        // Scroll to and enable Wireless debugging
        val wirelessDebugging = findWirelessDebuggingOption()
        assert(wirelessDebugging != null) { "Wireless debugging option not found" }

        // Click the toggle
        val toggle = device.findObject(
            UiSelector()
                .className("android.widget.Switch")
                .description("Wireless debugging")
        )
        assert(toggle.exists()) { "Wireless debugging switch not found" }
        toggle.click()

        // Wait for and handle the permission dialog
        device.wait(
            Until.hasObject(By.text("Allow wireless debugging")),
            LAUNCH_TIMEOUT
        )
        val allowButton = device.findObject(UiSelector().text("Allow"))
        assert(allowButton.exists()) { "Allow button not found" }
        allowButton.click()

        // Click the Wireless debugging title to enter the menu
        val wirelessDebuggingTitle = device.findObject(UiSelector().text("Wireless debugging"))
        assert(wirelessDebuggingTitle.exists()) { "Wireless debugging title not found" }
        wirelessDebuggingTitle.click()

        val connectionIpPort = getWirelessDebugConnectionInfo()

        // Wait for and click "Pair device with pairing code"
        println("Looking for 'Pair device with pairing code' option...")
        val pairOption = device.findObject(
            UiSelector().text("Pair device with pairing code")
        )
        assert(pairOption.exists()) { "Pair device option not found" }
        pairOption.click()

        // Get pairing info from the dialog
        getPairingInfo()?.let { (pairingCode, pairingIpPort) ->
            // Send output to app's terminal
            sendOutputToTerminal("Pairing Code: $pairingCode")
            sendOutputToTerminal("IP and Port: $pairingIpPort")
            // Now that we're in the wireless debugging menu, resize it and open Termux
            // Calculate window sizes
            val displayMetrics = context.resources.displayMetrics
            val screenHeight = displayMetrics.heightPixels
            val screenWidth = displayMetrics.widthPixels

            // Resize Developer Options to top 75%
            val devOptionsBounds = Rect(
                0,
                0,
                screenWidth,
                (screenHeight * 0.75).toInt()
            )

            val devOptionsResizeIntent = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }

            val devOptions = ActivityOptions.makeBasic().apply {
                launchBounds = devOptionsBounds
            }
            context.startActivity(devOptionsResizeIntent, devOptions.toBundle())

            Thread.sleep(5000)

            // Launch Termux in bottom 25%
            val termuxBounds = Rect(
                0,
                (screenHeight * 0.75).toInt(),
                screenWidth,
                screenHeight
            )

            val termuxIntent = Intent().apply {
                setClassName("com.termux", "com.termux.app.TermuxActivity")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                putExtra("com.termux.app.show_soft_keyboard", true)
            }

            val termuxOptions = ActivityOptions.makeBasic().apply {
                launchBounds = termuxBounds
            }

            context.startActivity(termuxIntent, termuxOptions.toBundle())
            Thread.sleep(5000)
            device.executeShellCommand("input text termux-setup-storage")
            Thread.sleep(7000)
            device.pressEnter()
            Thread.sleep(5000)
            val allowButton = device.wait(
                Until.findObject(By.res("com.android.permissioncontroller:id/permission_allow_button")),
                LAUNCH_TIMEOUT
            )
            allowButton?.click() // ?: throw IllegalStateException("Could not find Allow button")
            Thread.sleep(5000)
            val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            val timestamp = System.currentTimeMillis()

            // Setup both files with unique names
            val setupFile = File(downloadsDir, "01_termux_setup_${timestamp}.sh")
            val tarFile = File(downloadsDir, "termux_bundle_${timestamp}.tar")

            setupFile.createNewFile()
            tarFile.createNewFile()

            // Copy both files
            copyAssetToFile(context.assets, "01_termux_setup.sh", setupFile)
            copyAssetToFile(context.assets, "termux_bundle.tar", tarFile)

            device.executeShellCommand("input text mv%s/sdcard/Download/*termux_*%s\$HOME")
            Thread.sleep(5000)
            device.pressEnter()
            Thread.sleep(5000)
            device.executeShellCommand("input text bash%s\$HOME/01_termux_setup_${timestamp}.sh%s${timestamp}%s${pairingIpPort}%s${pairingCode}%s${connectionIpPort}")
            Thread.sleep(5000)
            device.pressEnter()

            // Read log file until completion marker
            val successFile = File("/sdcard/Download/termux_setup_SUCCESS_${timestamp}")
            val failedFile = File("/sdcard/Download/termux_setup_FAILED_${timestamp}")

            val maxAttempts = 48 // wait 600 seconds
            var attempts = 0
            while (attempts < maxAttempts) {
                when {
                    successFile.exists() -> break
                    failedFile.exists() -> throw RuntimeException("Setup failed")
                        else -> {
                            Thread.sleep(5000)
                            attempts++
                        }
                }
            }

            if (attempts >= maxAttempts) {
                throw RuntimeException("Setup timed out")
            }
        }
    }

    @Test
    fun testChromePerformance() = runBlocking {
        // Get debugger address
        val files = device.executeShellCommand("ls -l /sdcard/Download")
        val debuggerLine = files.split("\n")
            .find { it.contains("chrome_debugger_localhost") }
            ?: throw IllegalStateException("Debugger file not found in Download directory")

        val debuggerAddress = debuggerLine
            .substringAfter("chrome_debugger_")
            .substringBefore(" ")
            .replace("_", ":")

        println("Found debugger address: $debuggerAddress")

        val chromeDevTools = ChromeDevTools(debuggerAddress)
        assertTrue("Failed to connect to Chrome DevTools", chromeDevTools.connect())

        val testUrls = listOf(
            "https://fonts.googleapis.com",
            "https://facebook.com",
            "https://twitter.com",
            "https://google.com",
            "https://youtube.com",
            "https://s.w.org",
            "https://instagram.com",
            "https://googletagmanager.com",
            "https://linkedin.com",
            "https://ajax.googleapis.com",
            "https://plus.google.com",
            "https://gmpg.org",
            "https://pinterest.com",
            "https://fonts.gstatic.com",
            "https://wordpress.org",
            "https://en.wikipedia.org",
            "https://youtu.be",
            "https://maps.google.com",
            "https://itunes.apple.com",
            "https://github.com",
            "https://bit.ly",
            "https://play.google.com",
            "https://goo.gl",
            "https://docs.google.com",
            "https://cdnjs.cloudflare.com",
            "https://vimeo.com",
            "https://support.google.com",
            "https://google-analytics.com",
            "https://maps.googleapis.com",
            "https://flickr.com",
            "https://vk.com",
            "https://t.co",
            "https://reddit.com",
            "https://amazon.com",
            "https://medium.com",
            "https://sites.google.com",
            "https://drive.google.com",
            "https://creativecommons.org",
            "https://microsoft.com",
            "https://developers.google.com",
            "https://adobe.com",
            "https://soundcloud.com",
            "https://theguardian.com",
            "https://apis.google.com",
            "https://ec.europa.eu",
            "https://lh3.googleusercontent.com",
            "https://chrome.google.com",
            "https://cloudflare.com",
            "https://nytimes.com",
            "https://maxcdn.bootstrapcdn.com"
        )

        val siteMetrics = mutableMapOf<String, PageMetrics>()

        try {
            testUrls.forEach { url ->
                println("\n=== Testing URL: $url ===")
                val metrics = collectMetricsForUrl(chromeDevTools, url)
                metrics?.let { siteMetrics[url] = it }
            }

            // Print summary table
            println("\n==================================================================================")
            println("Chrome Browser - Performance Metrics Summary (all times in milliseconds)")
            println("==================================================================================")
            println("%-40s %10s %10s %10s %10s".format(
                "URL", "Load Time", "FCP", "TTI", "DCL"
            ))
            println("----------------------------------------------------------------------------------")

            siteMetrics.forEach { (url, metrics) ->
                println("%-40s %10.0f %10.0f %10.0f %10.0f".format(
                    url.take(40),
                    metrics.loadTime,
                    metrics.fcp,
                    metrics.tti,
                    metrics.dcl
                ))
            }

            // Calculate and print averages
            if (siteMetrics.isNotEmpty()) {
                val avgLoadTime = siteMetrics.values.map { it.loadTime }.average()
                val avgFCP = siteMetrics.values.map { it.fcp }.average()
                val avgTTI = siteMetrics.values.map { it.tti }.average()
                val avgDCL = siteMetrics.values.map { it.dcl }.average()

                println("\nAVERAGES:")
                println("%-40s %10.0f %10.0f %10.0f %10.0f".format(
                    "All Sites",
                    avgLoadTime,
                    avgFCP,
                    avgTTI,
                    avgDCL
                ))
            }
        } finally {
            chromeDevTools.disconnect()
        }
    }

    @Ignore("skipping until geckodriver bug/workaround is found")
    @Test
    fun testFirefoxPerformance() = runBlocking {
        // Get debugger address
        val files = device.executeShellCommand("ls -l /sdcard/Download")
        val geckoLine = files.split("\n")
            .find { it.contains("gecko_localhost") }
            ?: throw IllegalStateException("GeckoDriver file not found in Download directory")

        val serverUrl = geckoLine
            .substringAfter("gecko_")
            .substringBefore(" ")
            .replace("_", ":")

        println("Found Firefox debugger at: $serverUrl")

        val firefoxDevTools = FirefoxDevTools(serverUrl)
        assertTrue("Failed to connect to Firefox DevTools", firefoxDevTools.connect())

        val testUrls = listOf(
            "https://fonts.googleapis.com",
            "https://facebook.com",
            "https://twitter.com",
            "https://google.com",
            "https://youtube.com",
            "https://s.w.org",
            "https://instagram.com",
            "https://googletagmanager.com",
            "https://linkedin.com",
            "https://ajax.googleapis.com",
            "https://plus.google.com",
            "https://gmpg.org",
            "https://pinterest.com",
            "https://fonts.gstatic.com",
            "https://wordpress.org",
            "https://en.wikipedia.org",
            "https://youtu.be",
            "https://maps.google.com",
            "https://itunes.apple.com",
            "https://github.com",
            "https://bit.ly",
            "https://play.google.com",
            "https://goo.gl",
            "https://docs.google.com",
            "https://cdnjs.cloudflare.com",
            "https://vimeo.com",
            "https://support.google.com",
            "https://google-analytics.com",
            "https://maps.googleapis.com",
            "https://flickr.com",
            "https://vk.com",
            "https://t.co",
            "https://reddit.com",
            "https://amazon.com",
            "https://medium.com",
            "https://sites.google.com",
            "https://drive.google.com",
            "https://creativecommons.org",
            "https://microsoft.com",
            "https://developers.google.com",
            "https://adobe.com",
            "https://soundcloud.com",
            "https://theguardian.com",
            "https://apis.google.com",
            "https://ec.europa.eu",
            "https://lh3.googleusercontent.com",
            "https://chrome.google.com",
            "https://cloudflare.com",
            "https://nytimes.com",
            "https://maxcdn.bootstrapcdn.com"
        )

        val loadTimes = mutableMapOf<String, Double>()

        try {
            testUrls.forEach { url ->
                println("\n=== Testing URL: $url ===")
                val metrics = collectMetricsForUrl(firefoxDevTools, url)

                metrics?.let { response ->
                    val metricsString = response.getJSONObject("result")
                        .getJSONObject("result")
                        .getString("value")

                    try {
                        val navigation = JSONObject(metricsString).getJSONObject("navigation")
                        val duration = navigation.getDouble("duration")  // This is in milliseconds
                        loadTimes[url] = duration
                    } catch (e: Exception) {
                        println("Failed to parse navigation data for $url: ${e.message}")
                    }
                }
            }

            // Print summary at the end
            println("\n========================================")
            println("Firefox Browser - Page Load Duration Summary")
            println("========================================")
            loadTimes.forEach { (url, time) ->
                println("$url: ${time.toInt()}ms")
            }

            if (loadTimes.isNotEmpty()) {
                val average = loadTimes.values.average()
                println("\nAverage page load duration: ${average.toInt()}ms")
            }

        } finally {
            firefoxDevTools.disconnect()
        }
    }

    data class PageMetrics(
        val loadTime: Double,
        val fcp: Double,
        val tti: Double,
        val dcl: Double
    )

    private suspend fun collectMetricsForUrl(firefoxDevTools: FirefoxDevTools, url: String): JSONObject? {
        return try {
            println("Navigating to: $url")
            firefoxDevTools.navigateToUrl(url)

            println("Waiting for page load...")
            firefoxDevTools.waitForPageLoad()

            println("Collecting metrics...")
            delay(5000)  // Give extra time for resources to load

            val response = firefoxDevTools.getPerformanceMetrics()
            println("\nRaw Performance Metrics for $url:")
            println("----------------------------------------")
            println(response.toString(2))
            println("----------------------------------------\n")

            response

        } catch (e: Exception) {
            println("Error collecting metrics for $url: ${e.message}")
            e.printStackTrace()
            null
        }
    }

    private suspend fun collectMetricsForUrl(chromeDevTools: ChromeDevTools, url: String): PageMetrics? {
        return try {
            println("Navigating to: $url")
            chromeDevTools.navigateToUrl(url)
            chromeDevTools.waitForPageLoad()
            delay(1000)

            val response = chromeDevTools.getPerformanceMetrics()
            val timing = response.getJSONObject("timing")
            val paint = response.getJSONObject("paint")

            val metrics = PageMetrics(
                loadTime = timing.getLong("loadEventEnd") - timing.getLong("navigationStart").toDouble(),
                fcp = paint.getDouble("firstContentfulPaint"),
                tti = timing.getLong("domInteractive") - timing.getLong("navigationStart").toDouble(),
                dcl = timing.getLong("domContentLoadedEventEnd") - timing.getLong("navigationStart").toDouble()
            )

            // Validate metrics
            if (metrics.loadTime < 0 || metrics.fcp < 0 || metrics.tti < 0 || metrics.dcl < 0) {
                println("WARNING: Negative metrics detected for $url:")
                println("  Load Time: ${metrics.loadTime}")
                println("  FCP: ${metrics.fcp}")
                println("  TTI: ${metrics.tti}")
                println("  DCL: ${metrics.dcl}")
                null
            } else {
                metrics
            }
        } catch (e: Exception) {
            println("Error collecting metrics for $url: ${e.message}")
            null
        }
    }

    private fun getDebuggerAddressFromLog(): String {
        // Try to read from Termux directory first
        val termuxLogPath = "/sdcard/chromedriver_session.log"
        val logFile = File(termuxLogPath)

        try {
            if (logFile.exists() && logFile.canRead()) {
                val sessionLog = logFile.readText()
                return parseDebuggerAddress(sessionLog)
            } else {
                throw IOException("Cannot access log file at $termuxLogPath. Exists: ${logFile.exists()}, Readable: ${logFile.canRead()}")
            }
        } catch (e: Exception) {
            println("Error accessing Termux log file: ${e.message}")
            // Maybe try alternative methods like adb pull here
            throw e
        }
    }

    private fun parseDebuggerAddress(sessionLog: String): String {
        return try {
            val jsonResponse = JSONObject(sessionLog.trim().removeSuffix("~"))
            jsonResponse
                .getJSONObject("value")
                .getJSONObject("capabilities")
                .getJSONObject("goog:chromeOptions")
                .getString("debuggerAddress")
        } catch (e: Exception) {
            throw RuntimeException("Failed to parse debugger address from log: ${e.message}")
        }
    }

    private fun findWirelessDebuggingOption(): UiObject? {
        val maxScrolls = 10
        var scrolls = 0

        // Try to ensure Developer Options has focus
        val devOptionsScreen = device.findObject(UiSelector().text("Developer options"))
        if (devOptionsScreen.exists()) {
            devOptionsScreen.click()  // This should bring Developer Options to focus
            Thread.sleep(500)  // Give UI time to settle
        }

        // Look for the wireless debugging container
        val wirelessDebugging = device.findObject(
            UiSelector()
                .className("android.widget.LinearLayout")
                .childSelector(
                    UiSelector()
                        .resourceId("android:id/title")
                        .text("Wireless debugging")
                )
        )

        while (!wirelessDebugging.exists() && scrolls < maxScrolls) {
            // Scroll down
            device.swipe(
                device.displayWidth / 2,
                device.displayHeight * 2 / 3,  // Adjusted to avoid Termux window
                device.displayWidth / 2,
                device.displayHeight / 3,
                10
            )
            scrolls++
            Thread.sleep(500)
        }

        return if (wirelessDebugging.exists()) wirelessDebugging else null
    }

    private fun handleAllowDialog() {
        // Wait for potential "Allow wireless debugging" dialog
        val dialogExists = device.wait(
            Until.hasObject(By.text("Allow wireless debugging on this network?")),
            3000
        )

        if (dialogExists) {
            println("Found Allow dialog, accepting...")
            val allowButton = device.findObject(UiSelector().text("Allow"))
            allowButton.click()
        }
    }

    private fun getWirelessDebugConnectionInfo(): String {
        val connectionIpPort = device.wait(
            Until.findObject(By.res("android:id/summary").textContains(":")),
            LAUNCH_TIMEOUT
        )?.text ?: throw IllegalStateException("Could not find IP:Port text")

        println("Found wireless debug connection info: $connectionIpPort")
        return connectionIpPort
    }

    private data class PairingInfo(val pairingCode: String, val pairingIpPort: String)

    private fun getPairingInfo(): PairingInfo? {
        // Wait for pairing dialog
        device.wait(
            Until.hasObject(By.res("com.android.settings:id/pairing_code")),
            LAUNCH_TIMEOUT
        )

        val pairingCode = device.findObject(
            UiSelector().resourceId("com.android.settings:id/pairing_code")
        ).text

        val pairingIpPort = device.findObject(
            UiSelector().resourceId("com.android.settings:id/ip_addr")
        ).text

        return if (pairingCode.isNotEmpty() && pairingIpPort.isNotEmpty()) {
            PairingInfo(pairingCode, pairingIpPort)
        } else null
    }

    private fun termuxPairShell(ipPort: String, code: String) {
//        val context = InstrumentationRegistry.getInstrumentation().targetContext
//
//        // First check if Termux is installed
//        val packageManager = context.packageManager
//
//        // Get Termux's launch intent instead of creating our own
//        val launchIntent = packageManager.getLaunchIntentForPackage("com.termux")
//        launchIntent?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
//
//        // disable soft keyboard
//         device.executeShellCommand("settings put secure default_input_method none")
//
//        context.startActivity(launchIntent)

        // Try to find terminal view in multiple ways
//        val terminalView = device.wait(
//            Until.findObject(By.res("com.termux:id/terminal_view")),
//            LAUNCH_TIMEOUT
//        )
//        println("current terminalView: $terminalView")

//        val textInput = device.wait(
//            Until.findObject(By.res("com.termux:id/terminal_toolbar_text_input")),
//            LAUNCH_TIMEOUT
//        )

//        textInput.click()
//        Thread.sleep(1000)

//        device.executeShellCommand("input keyevent 108")
//        Thread.sleep(5000)
//        device.pressEnter()
//        Thread.sleep(5000)

        // Send text directly without needing the keyboard
        // Send text without quotes
        device.executeShellCommand("input text adb%spair%s$ipPort%s$code")
//        device.executeShellCommand("input text  ") // Space needs to be escaped
//        device.executeShellCommand("input text pair")
//        device.executeShellCommand("input text  ")
//        device.executeShellCommand("input text $ipPort")
//        device.executeShellCommand("input text  ")
//        device.executeShellCommand("input text $code")
        Thread.sleep(5000)
        device.executeShellCommand("input keyevent ${KeyEvent.KEYCODE_ENTER}")
//        textInput.text = "adb pair $ipPort $code"
//        Thread.sleep(5000)
//        device.pressEnter()
//        Thread.sleep(5000)
//        device.executeShellCommand("input keyevent ${KeyEvent.KEYCODE_ENTER}")
    }

    private fun openNewTermuxSession() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val intent = Intent().apply {
            setClassName("com.termux", "com.termux.app.TermuxActivity")
            action = "com.termux.ACTION_NEW_SESSION"
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun connectToDevice() {
        // Get IP and port
        val ipAndPort = getWirelessDebugConnectionInfo()
        requireNotNull(ipAndPort) { "Could not find IP address and port information" }

        // Focus Termux and input the connect command
        inputToTermux("adb connect $ipAndPort")
    }

    private fun inputToTermux(command: String) {
        // Disable soft keyboard first
        device.executeShellCommand("settings put secure show_ime_with_hard_keyboard 0")
//        device.executeShellCommand("input keyevent 111") // KEYCODE_ESCAPE to dismiss keyboard if showing

        // Disable soft keyboard completely
        // device.executeShellCommand("settings put secure default_input_method none")


        // Try to find terminal view in multiple ways
        val terminalView = device.wait(
            Until.findObject(By.res("com.termux:id/terminal_view")),
            LAUNCH_TIMEOUT
        )

        if (terminalView == null) {
            println("Could not find terminal view by resource ID, trying package search...")
            // Try finding Termux's window first
            val termuxRoot = device.wait(
                Until.findObject(By.pkg("com.termux")),
                LAUNCH_TIMEOUT
            )

            if (termuxRoot == null) {
                throw IllegalStateException("Could not find Termux window")
            }

            // Try finding terminal view within Termux's window
            val terminalViewInRoot = termuxRoot.findObject(By.res("terminal_view"))
                ?: throw IllegalStateException("Could not find terminal view within Termux window")
        }

        // Try different interaction methods
        try {
            // Try long click first
            terminalView.click(2000) // Long click for 2 seconds
            Thread.sleep(500)

            // If that didn't work, try getting coordinates and clicking directly
            val bounds = terminalView.visibleBounds
            device.click(bounds.centerX(), bounds.centerY())
            Thread.sleep(500)

            // Now try to find and swipe the extra keys
            val extraKeys = device.wait(
                Until.findObject(By.res("com.termux:id/terminal_toolbar_extra_keys")),
                LAUNCH_TIMEOUT
            )
            val displayHeight = device.displayHeight
            val displayWidth = device.displayWidth
            device.swipe(
                        (displayWidth * 0.75).toInt(),
                        (displayHeight * 0.9).toInt(),
                        (displayWidth * 0.25).toInt(),
                        (displayHeight * 0.9).toInt(),
                        20
                    )
            if (extraKeys == null) {
                // Try tapping where the extra keys should be
                val displayHeight = device.displayHeight
                val displayWidth = device.displayWidth
                // Assuming extra keys are at bottom of screen
                device.click(displayWidth / 2, (displayHeight * 0.9).toInt())
                Thread.sleep(500)

                // Try finding extra keys again after tap
                val extraKeysRetry = device.wait(
                    Until.findObject(By.res("com.termux:id/terminal_toolbar_extra_keys")),
                    LAUNCH_TIMEOUT
                )

                if (extraKeysRetry != null) {
                    // Swipe on the found extra keys
                    extraKeysRetry.swipe(Direction.LEFT, 0.75f)
                } else {
                    // If we still can't find it, try swiping at the bottom of screen
                    device.swipe(
                        (displayWidth * 0.75).toInt(),
                        (displayHeight * 0.9).toInt(),
                        (displayWidth * 0.25).toInt(),
                        (displayHeight * 0.9).toInt(),
                        20
                    )
                }
            } else {
                extraKeys.swipe(Direction.LEFT, 0.75f)
            }

            Thread.sleep(1000)

            // Try to find and use the text input
            val textInput = device.wait(
                Until.findObject(By.res("com.termux:id/terminal_toolbar_text_input")),
                LAUNCH_TIMEOUT
            )

            if (textInput != null) {
                textInput.click()
                textInput.text = command
                Thread.sleep(1000)
                device.pressEnter()
                Thread.sleep(1000)
                device.pressEnter()
            } else {
                throw IllegalStateException("Could not find text input after swipe")
            }

        } catch (e: Exception) {
            println("Error during Termux interaction: ${e.message}")
            e.printStackTrace()
            throw e
        }
    }

    private fun sendOutputToTerminal(message: String) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            Logger.log(message)
        }
    }
}