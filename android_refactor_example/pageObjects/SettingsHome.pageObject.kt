
@PageObject
@NavigationTarget(
    route = [ClickElementStep("homeButton"), ClickElementStep("settingsIcon")]
)
class SettingsHomePageObject(driver: UiDevice) : BasePageObject(driver) {
    
    // Define required elements based on state
    fun getRequiredElements(state: Map<String, Any> = mapOf()): List<Element> {
        val isDefault = state["default"] as? Boolean ?: false
        val isPrivateBrowsing = state["privateBrowsing"] as? Boolean ?: false
        
        // from elements in ../selectors/SettingsHome.selectors.kt
        val baseElements = listOf(
            // filter on elements with state 'default'
        )
        
        // Add state-specific elements
        return if (isPrivateBrowsing) {
            baseElements + listOf(
                // filter on elements with state 'privateBrowsing'
            )
        } else {
            baseElements
        }
    }
    
    override fun waitForPageToLoad() {
        super.waitForPageToLoad()
        
        val requiredElements = getRequiredElements(pageState)
        if (!verifyRequiredElements(requiredElements)) {
            throw PageLoadException("Settings home page failed to load")
        }
    }
    
    // Placeholder page-specific actions that will use custom commands like mozClick
    fun clickSearchButton() {
        findElement(searchButton).click()
        // Return the next page object if desired
    }
    
    fun clickCustomizeButton() {
        findElement(customizeButton).click()
        // Return the next page object
    }
    
    // Verifications
    fun verifyGeneralHeading() {
        logger.info("Verifying general heading is visible")
        val element = findElement(generalHeading)
        assert(element.exists()) { "General heading not found" }
        logger.success("General heading is visible")
    }
}