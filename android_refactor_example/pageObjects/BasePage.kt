package org.mozilla.fenix.ui.efficiency.pageObjects

import org.mozilla.fenix.R
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.ViewInteraction
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withContentDescription
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiObject
import androidx.test.uiautomator.UiSelector
import org.mozilla.fenix.helpers.TestHelper.mDevice
import org.mozilla.fenix.helpers.TestHelper.packageName
import org.mozilla.fenix.ui.efficiency.helpers.NavigationStep
import org.mozilla.fenix.ui.efficiency.helpers.Selector
import org.mozilla.fenix.ui.efficiency.helpers.SelectorStrategy
import org.mozilla.fenix.ui.efficiency.helpers.perform

// BasePage.kt
abstract class BasePage {
    // Every page needs to define these
    abstract val navigationPath: List<NavigationStep>

    // Navigate to this page
    fun navigateToPage(): BasePage {
        // First check if we're already on this page
        if (mozWaitForPageToLoad()) {
            // Already on the page, just return
            return this
        }

        // Execute navigation steps
        executeNavigationPath()

        // Wait for page to load and verify
        if (!mozWaitForPageToLoad()) {
            throw AssertionError("Failed to navigate to ${this.javaClass.simpleName}")
        }

        return this
    }

    // Execute navigation path steps
    private fun executeNavigationPath() {
        navigationPath.forEach { step ->
            when (step) {
                is NavigationStep.Click -> mozClick(step.selector)
                is NavigationStep.Swipe -> perform(step.swipeAction)
                // Add other step types as needed
            }
        }
    }

    // Wait for page to load by checking required elements
    fun mozWaitForPageToLoad(timeout: Long = 10000): Boolean {
        val requiredSelectors = mozGetSelectorsByGroup("requiredForPage")
        val startTime = System.currentTimeMillis()
        var allFound = false

        while (!allFound && System.currentTimeMillis() - startTime < timeout) {
            allFound = requiredSelectors.all { mozVerifyElement(it) }
            if (!allFound) Thread.sleep(500)
        }

        return allFound
    }

    // Get selectors by group
    abstract fun mozGetSelectorsByGroup(group: String = "requiredForPage"): List<Selector>

    // Verify elements by group
    fun mozVerifyElementsByGroup(group: String = "requiredForPage"): BasePage {
        val selectors = mozGetSelectorsByGroup(group)
        val allPresent = selectors.all { mozVerifyElement(it) }

        if (!allPresent) {
            throw AssertionError("Not all elements in group '$group' are present")
        }

        return this
    }

    // Click an element
    fun mozClick(selector: Selector): BasePage {
        val element = mozGetElement(selector)

        when (element) {
            is ViewInteraction -> element.perform(click())
            is UiObject -> element.click()
            // Add other element types as needed
        }

        return this
    }

    // Element finding and verification methods
    fun mozGetElement(selector: Selector): Any? {
        return when (selector.strategy) {
            SelectorStrategy.ESPRESSO_BY_ID -> onView(withId(selector.toResourceId()))
            SelectorStrategy.ESPRESSO_BY_TEXT -> onView(withText(selector.value))
            SelectorStrategy.ESPRESSO_BY_CONTENT_DESC -> onView(withContentDescription(selector.value))
            SelectorStrategy.UIAUTOMATOR2_BY_CLASS -> mDevice.findObject(UiSelector().className(selector.value))
            SelectorStrategy.UIAUTOMATOR2_BY_TEXT -> mDevice.findObject(UiSelector().text(selector.value))
            SelectorStrategy.UIAUTOMATOR2_BY_RES -> mDevice.findObject(By.res(selector.value))
            SelectorStrategy.UIAUTOMATOR2_BY_RES_ID -> mDevice.findObject(UiSelector().resourceId(packageName + ":" + selector.value))
        }
    }

    fun mozVerifyElement(selector: Selector): Boolean {
        val element = mozGetElement(selector)

        return when (element) {
            is ViewInteraction -> {
                try {
                    element.check(matches(isDisplayed()))
                    true
                } catch (e: Exception) {
                    false
                }
            }
            is UiObject -> element.exists()
            else -> false
        }
    }
}
