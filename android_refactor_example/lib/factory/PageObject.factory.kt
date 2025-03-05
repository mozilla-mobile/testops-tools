object PageObjectFactory {
    private val driver = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    
    fun <T : BasePageObject> createPage(pageClass: Class<T>, state: Map<String, Any> = mapOf()): T {
        val constructor = pageClass.getConstructor(UiDevice::class.java)
        val page = constructor.newInstance(driver)
        page.setState(state)
        return page
    }
    
    // Navigate to a specific page
    fun <T : BasePageObject> navigateToPage(pageClass: Class<T>, state: Map<String, Any> = mapOf()): T {
        val page = createPage(pageClass, state)
        
        // Build navigation path
        val navigationPath = NavigationManager.buildPathTo(pageClass, state)
        
        // Execute navigation
        navigationPath.forEach { step -> 
            step.execute(driver)
        }
        
        // Verify page loaded correctly
        if (!page.waitForPageToLoad()) {
            throw NavigationException("Failed to navigate to ${pageClass.simpleName}")
        }
        
        return page
    }
}