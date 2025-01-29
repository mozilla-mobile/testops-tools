// background.js
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
    // Forward the message to Android via native messaging
    // This requires additional setup; for simplicity, we'll send it via `browser.runtime.sendMessage`
    // and handle it in the Android side.
    browser.runtime.sendNativeMessage("com.example.browserperformancetest", message, (response) => {
        // Handle response if needed
    });
});
