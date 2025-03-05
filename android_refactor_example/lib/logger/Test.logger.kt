class TestLogger {
    // ANSI color codes
    private val RESET = "\u001B[0m"
    private val RED = "\u001B[31m"
    private val GREEN = "\u001B[32m"
    private val YELLOW = "\u001B[33m"
    private val BLUE = "\u001B[34m"
    private val PURPLE = "\u001B[35m"
    private val CYAN = "\u001B[36m"
    
    fun info(message: String) {
        Log.i("TestLog", "$BLUE$message$RESET")
    }
    
    fun debug(message: String) {
        Log.d("TestLog", "$YELLOW$message$RESET")
    }
    
    fun success(message: String) {
        Log.i("TestLog", "$GREEN$message$RESET")
    }
    
    fun error(message: String) {
        Log.e("TestLog", "$RED$message$RESET")
    }
    
    fun action(message: String) {
        Log.i("TestLog", "$PURPLE$message$RESET")
    }
}