
// Include default test data and state at top of file before tests
val testState = mapOf(
    "default" to true,
    "privateBrowsing" to false,
    "loggedIn" to false,
)

class SettingsHomePageTest(testState) {
    
    // This will run a test to visit SettingsHomePage and verify the page loads
    //     for each state we want to test, which are set to 'true' in our 'testState'
    //     object above.
    //     
    // Each combination of unique states set to 'true' will generate a test
    //    run by default unless a specific state (or combinations of states) are
    //    set to 'true' by the user at runtime.
    //
    // This allows us to create very atomic and case-specific test suites later
    //     that are optimized for specific code changes, 'unstable' features,
    //     debugging, etc.
    testState.forEach(state = true, {
        @Test
        fun verifySettingsHomePageLoads(state)
        // The test runner would show test results something like this:
        //     verifySettingsHomePageLoads.default: PASSED
        //     verifySettingsHomePageLoads.privateBrowsing: PASSED
        //     verifySettingsHomePageLoads.Experiment_1: PASSED
        //
        // The logs for a single test might look something like this:
        //     [TEST_BEGIN] Testing verifySettingsHomePageLoads.default...
        //     [TEST_SETUP] Building Test for the following state: DEFAULT
        //     [TEST_SETUP] Building Page Object for SettingsHomePage
        //     [TEST_SETUP] Building Navigation Path for SettingsHomePage
        //     [TEST_SETUP] Building Complete: using the following TEST_SETUP
        //     [TEST_SETUP] Dump of test config { state: ..., navigationPath: ..., selectors: ... }
        //     [TEST_STEPS] Attempting to navigate to SettingsHomePage... <- blue text to encapsulate all navigations
        //     [TEST_STEPS] Launching App... <- yellow text
        //     [TEST_STEPS] App Launch Complete <- green text
        //     [TEST_STEPS] Fetching required elements for HomePage.state=DEFAULT... <- yellow text
        //     [TEST_STEPS] Required elements found. Using these elements to verify page load\n\t <- green text of elements dump
        //     [TEST_STEPS] Waiting for {firstRequiredElement.description} to load... <- yellow text
        //     [TEST_STEPS] Element {firstRequiredElement.description} found. <- green text
        //     [TEST_STEPS] Attempting to click on {buttonElement.description}... <- purple text for all element interactions
        //     [TEST_STEPS] Clicked {buttonElement.description} successfully. <- green text
        //     [TEST_STEPS] Navigation to SettingsHomePage.state=DEFAULT COMPLETE. <- blue text to close navigation action
        //     [TEST_ASSERTIONS] Waiting for {firstRequiredElement.description} to load... <- yellow text; these assertions are only for the 'primary' data/feature under test
        //     [TEST_ASSERTIONS] Element {firstRequiredElement.description} found. <- green text
        //     [TEST_END] Testing verifySettingsHomePageLoads.state=DEFAULT is complete: PASSED
    })

    // Note: only a single line of code can now represent any number of permutations
    //     for verifying this page's contents, state, layout, experiments, etc.
    //
    //     This reduces the maintenance overhead and test developement to only managing
    //     the selector data in ../selectors/SettingsHome.page.kt.
    fun verifySettingsHomePageLoads(state) {
        // Test Setup
            // Modify or override the 'state' object passed in, if desired or
            // include custom/state-specific test data, like a user for Sync testing.

        // create page object from state machine and factory dynamically
        // This setup can instead be included in the above 'testState.forEach' block
        val settingsHomePage = PageObjectFactory.navigateToPage(
            SettingsHomePageObject::class.java,
            state
        )

        // Test Steps
        onPage.SettingsHomePage.navigateToPage(state)

        // Test Assertions
            // This assertion is handled within navigateToPage and is created dynamically
            //     through our state machine, page object factory, and navigation helper.
            //
            // Page.navigateToPage(state) is equivalent to the following and is the only case
            //   where the assertions are not explicitly declared within our test themselves.
            //   All other tests explicitly follow the pattern of
            //       1. Test Setup
            //       2. Test Steps
            //       3. Test Assertions
            // 
            // onPage.HomePage.waitForPageToLoad(state) <- settingsMenuDropdown is a 'requiredForPage' element
            //     .mozClick("settingsMenuDropdown") <- mozClick contains our custom matchers, assertions, and logging
            //     .settingsMenuDropdownList.mozWaitForElementToExist(state)
            //     .settingsHome.mozClick(state)
            //
            // onPage.SettingsHomePage.waitForPageToLoad(state)
    }
}