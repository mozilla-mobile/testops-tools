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

    fun myNewTest() {
        // Given: the onboarding is false, setting2 is false, setting3 is true
        val activityIntentTestRule = skipOnboarding.false

        // When: navigating to settings page and toggling credit card autofill
        on.BookmarksPage.navigateToPage()

        // Then: make sure all the page elements and top site elements are present

    }
}