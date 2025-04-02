// PageContext.kt
class PageContext {
    // Properties for page objects
    val HomePage = HomePage
    val SettingsHomePage = SettingsHomePage
    // Add other page objects as needed
}

// Usage in a test class
abstract class BaseTest {
    // Context for pages
    lateinit var on: PageContext
    
    @Before
    fun setup() {
        on = PageContext()
    }
}