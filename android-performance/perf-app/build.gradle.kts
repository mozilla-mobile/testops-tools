buildscript {
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("https://maven.mozilla.org/maven2/org/mozilla/geckoview/geckoview-arm64-v8a/")
        }
        maven {
            url = uri("https://jitpack.io")
        }
    }
}