// TestTagMatcher.kt
package com.example.browserperformancetest

import android.view.View
import androidx.test.espresso.matcher.BoundedMatcher
import org.hamcrest.Description
import org.hamcrest.Matcher
import android.util.Log

object TestTagMatcher {
    fun withTestTag(testTag: String): Matcher<View> {
        return object : BoundedMatcher<View, View>(View::class.java) {
            override fun describeTo(description: Description) {
                description.appendText("with test tag: $testTag")
            }

            override fun matchesSafely(view: View): Boolean {
                val tag = view.getTag(R.id.compose_test_tag)
                Log.d("TestTagMatcher", "View Tag: $tag")
                return testTag == tag
            }
        }
    }
}
