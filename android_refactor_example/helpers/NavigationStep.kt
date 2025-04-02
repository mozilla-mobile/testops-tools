// NavigationStep.kt
sealed class NavigationStep {
    data class Click(val selector: Selector) : NavigationStep()
    data class Swipe(val swipeAction: () -> Unit) : NavigationStep()
    // Add other navigation step types as needed
}

// Helper extension functions for creating navigation steps
fun mozClick(selector: Selector): NavigationStep = NavigationStep.Click(selector)
fun swipeUp(): () -> Unit = { /* implementation */ }
fun swipeDown(): () -> Unit = { /* implementation */ }
fun perform(action: () -> Unit): NavigationStep = NavigationStep.Swipe(action)