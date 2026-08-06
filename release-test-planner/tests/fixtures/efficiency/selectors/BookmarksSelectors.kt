package org.mozilla.fenix.ui.efficiency.selectors

object BookmarksSelectors {
    val ADD_FOLDER = Selector(strategy = COMPOSE_BY_TAG, value = "addFolder")
    val FOLDER_TITLE = Selector(strategy = COMPOSE_BY_TAG, value = "folderTitle")
}
