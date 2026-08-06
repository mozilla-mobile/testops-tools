package org.mozilla.fenix.ui.efficiency.generation.behavior

object BehaviorTemplateCatalog {
    val all: List<BehaviorTemplate> = listOf(
        BehaviorTemplate(
            id = "entity.create.visible",
            automationSuffix = "create.visible",
            titlePattern = "{feature} - created {entity} is visible",
            requiredOperations = listOf(BehaviorOperation.CREATE),
            assertionKind = AssertionKind.PRESENT,
        ),
        BehaviorTemplate(
            id = "entity.delete.absent",
            automationSuffix = "delete.absent",
            titlePattern = "{feature} - deleted {entity} is gone",
            requiredOperations = listOf(BehaviorOperation.DELETE),
            assertionKind = AssertionKind.ABSENT,
        ),
    )
}
