package org.mozilla.fenix.ui.efficiency.generation.behavior

object BehaviorContextMatrix {

    private fun smoke(): List<BehaviorContextVariant> = listOf(
        defaultContext(),
    )

    private fun baseFlags(): List<BehaviorContextVariant> = listOf(
        defaultContext(),
        defaultContext("PocketEnabled" to "false"),
    )

    private fun pairwisePreview(): List<BehaviorContextVariant> = listOf(
        defaultContext(),
        defaultContext("BrowserMode" to "Private"),
        defaultContext("DeviceClass" to "Tablet"),
    )

    private fun exhaustivePreview(): List<BehaviorContextVariant> {
        val browserModes = listOf("Default", "Private")
        val deviceClasses = listOf("Phone", "Tablet")

        return buildList {
            for (browserMode in browserModes) {
                for (deviceClass in deviceClasses) {
                    add(defaultContext(browserMode, deviceClass))
                }
            }
        }
    }
}
