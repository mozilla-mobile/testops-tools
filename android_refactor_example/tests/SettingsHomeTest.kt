// SettingsHomeTest.kt
class SettingsHomeTest : BaseTest() {
    @get:Rule
    val activityIntentTestRule =
        HomeActivityIntentTestRule.withDefaultSettingsOverrides(skipOnboarding = true)

    @Rule
    @JvmField
    val retryTestRule = RetryTestRule(3)

    @Test
    fun verifyHomepageSettingsTest() {
        // Test Steps
        on.SettingsHomePage.navigateToPage()

        // Test Assertions
        on.SettingsHomePage
            .mozVerifyElementsByGroup("requiredForPage")
            .mozVerifyElementsByGroup("settings")
    }
    
    @Test
    fun verifyHomePageLoads() {
        on.HomePage.navigateToPage()
            .mozVerifyElementsByGroup("requiredForPage")
            .mozVerifyElementsByGroup("topSites")
    }
}