// SettingsHomeSelectors.kt
object SettingsHomeSelectors {
    val TITLE = Selector(
        strategy = SelectorStrategy.ESPRESSO_BY_TEXT,
        value = "Settings",
        description = "Settings Page Title",
        groups = listOf("requiredForPage")
    )
    
    val HOMEPAGE_SETTING = Selector(
        strategy = SelectorStrategy.ESPRESSO_BY_TEXT,
        value = "Homepage",
        description = "Homepage Setting Option",
        groups = listOf("settings", "requiredForPage")
    )
    
    // All selectors list for filtering
    val all = listOf(
        TITLE,
        HOMEPAGE_SETTING
    )
}