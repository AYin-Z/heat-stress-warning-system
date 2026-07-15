plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.heatstress.watch"
    compileSdk = 34

    signingConfigs {
        create("platform") {
            storeFile = file("../keystore/platform.jks")
            storePassword = "android"
            keyAlias = "android_platform"
            keyPassword = "android"
        }
    }

    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "com.heatstress.watch"
        minSdk = 27        // Android 8.1 (A80)
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        // MQTT 配置 — 通过 -Pmqtt_url=... 覆盖
        val mqttUrl = project.findProperty("mqtt_url") as String? ?: "tcp://39.105.86.77:1883"
        val mqttUser = project.findProperty("mqtt_user") as String? ?: ""
        val mqttPass = project.findProperty("mqtt_pass") as String? ?: ""
        buildConfigField("String", "MQTT_BROKER_URL", "\"$mqttUrl\"")
        buildConfigField("String", "MQTT_USERNAME", "\"$mqttUser\"")
        buildConfigField("String", "MQTT_PASSWORD", "\"$mqttPass\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            isDebuggable = false
            signingConfig = signingConfigs.getByName("platform")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isDebuggable = true
            signingConfig = signingConfigs.getByName("platform")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // MQTT
    implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5")
    implementation("org.eclipse.paho:org.eclipse.paho.android.service:1.1.1")

    // AndroidX
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.lifecycle:lifecycle-service:2.7.0")

    // JSON
    implementation("com.google.code.gson:gson:2.10.1")
}
