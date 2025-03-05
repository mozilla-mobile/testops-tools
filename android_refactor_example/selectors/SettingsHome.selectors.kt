val generalHeading = Selector(
    strategy = SelectorStrategy.BY_TEXT, 
    value = "General", 
    description = "General heading",
    state = "privateBrowsing"
)
    
val searchButton = Selector(
    strategy = SelectorStrategy.BY_TEXT, 
    value = "Search", 
    description = "Search button",
    state = [ "default", "privateBrowsing" ]
)

val customizeButton = Selector(
    strategy = SelectorStrategy.BY_TEXT, 
    value = "Customize", 
    description = "Customize button",
    state = "experiment_1"
)