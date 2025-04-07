package org.mozilla.fenix.ui.efficiency.selectors

import org.mozilla.fenix.ui.efficiency.helpers.Selector
import org.mozilla.fenix.ui.efficiency.helpers.SelectorStrategy

// HomeSelectors.kt
object HomeSelectors {
    val THREE_DOT_MENU = Selector(
        strategy = SelectorStrategy.ESPRESSO_BY_ID,
        value = "menu_button",
        description = "Three Dot Menu",
        groups = listOf("requiredForPage")
    )

    val SETTINGS_BUTTON = Selector(
        strategy = SelectorStrategy.ESPRESSO_BY_TEXT,
        value = "Settings",
        description = "Settings Menu Item",
        groups = listOf("menuItems")
    )

    // All selectors list for filtering
    val all = listOf(
        THREE_DOT_MENU,
        SETTINGS_BUTTON
    )
}
