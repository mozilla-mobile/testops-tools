// BasePage.kt
abstract class BasePage {
    // Every page needs to define these
    abstract val navigationPath: List<NavigationStep>
    
    // Navigate to this page
    fun navigateToPage(): BasePage {
        // First check if we're already on this page
        if (mozWaitForPageToLoad()) {
            // Already on the page, just return
            return this
        }
        
        // Execute navigation steps
        executeNavigationPath()
        
        // Wait for page to load and verify
        if (!mozWaitForPageToLoad()) {
            throw AssertionError("Failed to navigate to ${this.javaClass.simpleName}")
        }
        
        return this
    }
    
    // Execute navigation path steps
    private fun executeNavigationPath() {
        navigationPath.forEach { step ->
            when (step) {
                is NavigationStep.Click -> mozClick(step.selector)
                is NavigationStep.Swipe -> perform(step.swipeAction)
                // Add other step types as needed
            }
        }
    }
    
    // Wait for page to load by checking required elements
    fun mozWaitForPageToLoad(timeout: Long = 10000): Boolean {
        val requiredSelectors = mozGetSelectorsByGroup("requiredForPage")
        val startTime = System.currentTimeMillis()
        var allFound = false
        
        while (!allFound && System.currentTimeMillis() - startTime < timeout) {
            allFound = requiredSelectors.all { mozVerifyElement(it) }
            if (!allFound) Thread.sleep(500)
        }
        
        return allFound
    }
    
    // Get selectors by group
    abstract fun mozGetSelectorsByGroup(group: String = "requiredForPage"): List<Selector>
    
    // Verify elements by group
    fun mozVerifyElementsByGroup(group: String = "requiredForPage"): BasePage {
        val selectors = mozGetSelectorsByGroup(group)
        val allPresent = selectors.all { mozVerifyElement(it) }
        
        if (!allPresent) {
            throw AssertionError("Not all elements in group '$group' are present")
        }
        
        return this
    }
    
    // Click an element
    fun mozClick(selector: Selector): BasePage {
        val element = mozGetElement(selector)
        
        when (element) {
            is ViewInteraction -> element.perform(click())
            is UiObject -> element.click()
            // Add other element types as needed
        }
        
        return this
    }
    
    // Element finding and verification methods
    fun mozGetElement(selector: Selector): Any? {
        return when (selector.strategy) {
            SelectorStrategy.BY_ID -> onView(withId(resId(selector.value)))
            SelectorStrategy.BY_TEXT -> onView(withText(selector.value))
            SelectorStrategy.BY_CONTENT_DESC -> onView(withContentDescription(selector.value))
            SelectorStrategy.BY_RES -> mDevice.findObject(By.res(selector.value))
            SelectorStrategy.BY_CLASS -> mDevice.findObject(UiSelector().className(selector.value))
            SelectorStrategy.ESPRESSO_ALLOF -> {
                if (selector.value.contains("id:") && selector.value.contains("text:")) {
                    val id = selector.value.substringAfter("id:").substringBefore(",")
                    val text = selector.value.substringAfter("text:")
                    onView(allOf(withId(resId(id)), withText(text)))
                } else {
                    null
                }
            }
            SelectorStrategy.COMPOSE -> composeTestRule?.onNodeWithTag(selector.value)
            SelectorStrategy.UIAUTOMATOR2_BY_TEXT -> mDevice.findObject(UiSelector().text(selector.value))
            SelectorStrategy.UIAUTOMATOR2_BY_RES_ID -> mDevice.findObject(UiSelector().resourceId(packageName + ":" + selector.value))
        }
    }
    
    fun mozVerifyElement(selector: Selector): Boolean {
        val element = mozGetElement(selector)
        
        return when (element) {
            is ViewInteraction -> {
                try {
                    element.check(matches(isDisplayed()))
                    true
                } catch (e: Exception) {
                    false
                }
            }
            is UiObject -> element.exists()
            else -> false
        }
    }
}