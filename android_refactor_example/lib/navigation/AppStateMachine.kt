class AppStateMachine {
    private var currentState: BasePageObject
    
    fun transition(action: UserAction): BasePageObject {
        val nextState = currentState.getNextState(action)
        action.perform()
        currentState = nextState
        return currentState
    }
}