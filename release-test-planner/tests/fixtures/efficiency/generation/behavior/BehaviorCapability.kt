package org.mozilla.fenix.ui.efficiency.generation.behavior

object BehaviorCapabilityCatalog {
    val all: List<BehaviorCapability> = listOf(
        BehaviorCapability(
            id = "bookmarks.folder.create",
            feature = "bookmarks",
            entity = "folder",
            operation = BehaviorOperation.CREATE,
            pagePropertyName = "bookmarks",
            description = "Create a bookmark folder",
            action = { on.bookmarks.createFolder("x") },
        ),
        BehaviorCapability(
            id = "bookmarks.folder.delete",
            feature = "bookmarks",
            entity = "folder",
            operation = BehaviorOperation.DELETE,
            pagePropertyName = "bookmarks",
            description = "Delete a bookmark folder",
            action = { on.bookmarks.deleteFolder("x") },
        ),
    )
}
