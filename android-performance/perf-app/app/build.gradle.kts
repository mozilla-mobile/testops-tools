// build.gradle.kts (Module-level: app/build.gradle.kts)
import com.android.build.gradle.internal.cxx.configure.gradleLocalProperties
import java.io.FileInputStream
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.example.browserperformancetest"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.browserperformancetest"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
        }

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        testInstrumentationRunnerArguments += mapOf("clearPackageData" to "false")
    }


    signingConfigs {
        create("release") {
            try {
                val keystoreProperties = Properties()
                val keystorePropertiesFile = rootProject.file("keystore.properties")
                keystoreProperties.load(FileInputStream(keystorePropertiesFile))

                println("Debug: Loading keystore properties from ${keystorePropertiesFile.absolutePath}")

                storeFile = rootProject.file(keystoreProperties["RELEASE_STORE_FILE"].toString())
                storePassword = keystoreProperties["RELEASE_STORE_PASSWORD"].toString()
                keyAlias = keystoreProperties["RELEASE_KEY_ALIAS"].toString()
                keyPassword = keystoreProperties["RELEASE_KEY_PASSWORD"].toString()

                println("Debug: Keystore file exists: ${storeFile?.exists()}")
                println("Debug: Keystore file path: ${storeFile?.absolutePath}")

                // Enable both V1 and V2 signing
                enableV1Signing = true
                enableV2Signing = true
            } catch (e: Exception) {
                println("Error loading signing config: ${e.message}")
                e.printStackTrace()
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    sourceSets {
        getByName("main") {
            jniLibs.srcDirs("src/main/jniLibs")
            assets.srcDirs("src/main/assets")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = libs.versions.kotlinCompilerExtensionVersion.get()
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
        jniLibs {
            useLegacyPackaging = true
        }
    }
}

dependencies {
    // Core AndroidX Dependencies
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity)
    implementation(libs.material)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.browser)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.webkit)
    implementation("eu.chainfire:libsuperuser:1.1.1")

    // Jetpack Compose
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.runtime)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.activity.compose)
    debugImplementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.test.manifest)

    // Networking
    implementation(libs.okhttp.v4110)
    implementation(libs.nanohttpd)
    implementation(libs.moshi.kotlin)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.coroutines.core)

    // Testing Dependencies
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.espresso.idling.resource)
    androidTestImplementation(libs.androidx.uiautomator)
    androidTestImplementation(libs.androidx.junit.v113)
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.monitor)

    // Browser Engines
    implementation(libs.geckoview.arm64.v8a)
    implementation(libs.cronet.embedded)
}