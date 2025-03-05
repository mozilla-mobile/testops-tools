interface NavigationStep {
    val description: String
    fun execute(driver: UiDevice)
}

// Common navigation steps
class ClickElementStep(private val selector: Selector) : NavigationStep {
    override val description = "Click on ${selector.description}"
    
    override fun execute(driver: UiDevice) {
        val element = Element(driver, selector)
        element.click()
    }
}