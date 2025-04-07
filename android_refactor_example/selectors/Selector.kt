package org.mozilla.fenix.ui.efficiency.helpers

import org.mozilla.fenix.R

// Selector.kt
data class Selector(
    val strategy: SelectorStrategy,
    val value: String,
    val description: String,
    val groups: List<String> = listOf()
) {
    fun toResourceId(): Int {
        return try {
            val rClass = R.id::class.java
            val field = rClass.getField(value)
            field.getInt(null)
        } catch (e: Exception) {
            throw IllegalArgumentException("Resource ID not found for name: $value", e)
        }
    }
}

enum class SelectorStrategy {
    ESPRESSO_BY_ID,
    ESPRESSO_BY_TEXT,
    ESPRESSO_BY_CONTENT_DESC,
    UIAUTOMATOR2_BY_RES,
    UIAUTOMATOR2_BY_CLASS,
    UIAUTOMATOR2_BY_TEXT,
    UIAUTOMATOR2_BY_RES_ID,
}
