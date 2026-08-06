/* Fixture for the corpus parser tests. Mirrors the shape of a real Fenix UI
 * test: robot imports, TestRail link comments, and mixed annotations. */

package org.mozilla.fenix.ui

import org.junit.Ignore
import org.junit.Test
import org.mozilla.fenix.customannotations.SmokeTest
import org.mozilla.fenix.ui.robots.downloadRobot

class SampleFeatureTest {

    // TestRail link: https://mozilla.testrail.io/index.php?/cases/view/3205329
    @SmokeTest
    @Test
    fun smokeTest() {
        on.downloads.navigateToPage()
            .verifySomething()
    }

    @Test
    fun plainTest() {
        downloadRobot {
            doSomething()
        }
    }

    @Ignore("Bug 123456 - disabled while flaky")
    @Test
    fun disabledTest() {
        on.downloads.navigateToPage()
    }

    private fun notATest() {
        // A helper, not annotated with @Test - must not be counted.
    }
}
