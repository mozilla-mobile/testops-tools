open class BasePageObject(val driver: UiDevice) {
    // Logger with color support
    protected val logger = TestLogger()
    
    // Track current page state
    protected var pageState: MutableMap<String, Any> = mutableMapOf()
    
    // Basic element interaction methods
    open fun findElement(selector: Selector): Element {
        logger.debug("Finding element: ${selector.description}")
        return Element(driver, selector)
    }
    
    open fun waitForPageToLoad() {
        logger.info("Waiting for page to load: ${this.javaClass.simpleName}")
        // Implementation
    }
    
    // Method to verify required elements exist
    open fun verifyRequiredElements(requiredElements: List<Element>): Boolean {
        logger.info("Verifying required elements for ${this.javaClass.simpleName}")
        
        requiredElements.forEach { element ->
            logger.debug("Checking element: ${element.description}")
            if (!element.exists()) {
                logger.error("Required element not found: ${element.description}")
                logger.debug("Current app state: ${pageState}")
                return false
            }
            logger.success("Found element: ${element.description}")
        }
        
        logger.success("All required elements found for ${this.javaClass.simpleName}")
        return true
    }
}