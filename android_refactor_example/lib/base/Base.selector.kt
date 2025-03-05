data class Selector(
    val strategy: SelectorStrategy,
    val value: String,
    val description: String
)

enum class SelectorStrategy {
    BY_ID, BY_TEXT, BY_CONTENT_DESC, BY_RESOURCE_ID, BY_CLASS, ESPRESSO, COMPOSE, UIAUTOMATOR2
}