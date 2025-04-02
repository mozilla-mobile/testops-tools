// Selector.kt
data class Selector(
    val strategy: SelectorStrategy,
    val value: String,
    val description: String,
    val groups: List<String> = listOf()
)

enum class SelectorStrategy {
    BY_ID,
    BY_TEXT,
    BY_CONTENT_DESC,
    BY_RES,
    BY_CLASS,
    ESPRESSO_ALLOF,
    COMPOSE,
    UIAUTOMATOR2_BY_TEXT,
    UIAUTOMATOR2_BY_RES_ID
}