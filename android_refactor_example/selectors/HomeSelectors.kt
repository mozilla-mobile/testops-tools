// HomeSelectors.kt
object HomeSelectors {
    val THREE_DOT_MENU = Selector(
        strategy = SelectorStrategy.BY_ID,
        value = "menu_button",
        description = "Three Dot Menu",
        groups = listOf("requiredForPage")
    )
    
    val SETTINGS_BUTTON = Selector(
        strategy = SelectorStrategy.BY_TEXT,
        value = "Settings",
        description = "Settings Menu Item",
        groups = listOf("menuItems")
    )
    
    val TOP_SITE_TOP_ARTICLES = Selector(
        strategy = SelectorStrategy.ESPRESSO_ALLOF,
        value = "id:top_site_title,text:Top Articles",
        description = "Top Articles Top Site",
        groups = listOf("topSites", "requiredForPage")
    )

    val TOP_SITE_GOOGLE = Selector(
        strategy = SelectorStrategy.ESPRESSO_ALLOF,
        value = "id:top_site_title,text:Google",
        description = "Google Top Site",
        groups = listOf("topSites", "requiredForPage")
    )
    
    // All selectors list for filtering
    val all = listOf(
        THREE_DOT_MENU,
        SETTINGS_BUTTON,
        TOP_SITE_TOP_ARTICLES,
        TOP_SITE_GOOGLE
    )
}