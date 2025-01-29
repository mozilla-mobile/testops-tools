pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
        maven {
            url = uri("https://maven.mozilla.org/maven2/")
        }
        maven {
            url = uri("https://jitpack.io")
        }
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("https://maven.mozilla.org/maven2/")
            content {
                includeGroup("org.mozilla")
                includeGroup("org.mozilla.geckoview")
                includeGroup("org.mozilla.components")
            }
        }
        maven {
            url = uri("https://jitpack.io")
        }
    }
}

rootProject.name = "Browser Performance Test"
include(":app")
 