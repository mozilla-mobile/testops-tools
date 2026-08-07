package org.mozilla.fenix.ui.efficiency.helpers

class PageContext(private val composeRule: ComposeRule) {
    val bookmarks = BookmarksPage(composeRule)
    val downloads = DownloadsPage(composeRule)
}
