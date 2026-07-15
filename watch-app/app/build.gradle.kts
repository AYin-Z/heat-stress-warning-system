plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val platformStoreFile = System.getenv("JUWEI_PLATFORM_STORE_FILE")
val platformStorePassword = System.getenv("JUWEI_PLATFORM_STORE_PASSWORD")
val platformKeyAlias = System.getenv("JUWEI_PLATFORM_KEY_ALIAS")
val platformKeyPassword = System.getenv("JUWEI_PLATFORM_KEY_PASSWORD")
val hasPlatformSigning =
    !platformStoreFile.isNullOrBlank() &&
        !platformStorePassword.isNullOrBlank() &&
        !platformKeyAlias.isNullOrBlank() &&
        !platformKeyPassword.isNullOrBlank() &&
        file(platformStoreFile!!).exists()

fun escapedBuildConfigString(value: String): String =
    "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

android {
    compileSdkVersion(31)

    defaultConfig {
        applicationId = "com.heatstress.watch"
        minSdkVersion(27)
        targetSdkVersion(27)
        versionCode = 2
        versionName = "1.1.0-a80"

        val mqttUrl = project.findProperty("mqtt_url") as String? ?: "tcp://39.105.86.77:1883"
        val mqttFallbackUrl = project.findProperty("mqtt_fallback_url") as String? ?: ""
        val mqttUser = project.findProperty("mqtt_user") as String? ?: ""
        val mqttPass = project.findProperty("mqtt_pass") as String? ?: ""
        val deviceId = project.findProperty("device_id") as String? ?: ""
        buildConfigField("String", "MQTT_BROKER_URL", escapedBuildConfigString(mqttUrl))
        buildConfigField("String", "MQTT_FALLBACK_URL", escapedBuildConfigString(mqttFallbackUrl))
        buildConfigField("String", "MQTT_USERNAME", escapedBuildConfigString(mqttUser))
        buildConfigField("String", "MQTT_PASSWORD", escapedBuildConfigString(mqttPass))
        buildConfigField("String", "DEVICE_ID", escapedBuildConfigString(deviceId))
    }

    signingConfigs {
        create("juweiPlatform") {
            if (hasPlatformSigning) {
                storeFile = file(platformStoreFile!!)
                storePassword = platformStorePassword
                keyAlias = platformKeyAlias
                keyPassword = platformKeyPassword
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hasPlatformSigning) {
                signingConfig = signingConfigs.getByName("juweiPlatform")
            }
        }
        getByName("debug") {
            if (hasPlatformSigning) {
                signingConfig = signingConfigs.getByName("juweiPlatform")
            }
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    lintOptions {
        isCheckReleaseBuilds = false
        isAbortOnError = false
    }
}

dependencies {
    implementation("org.jetbrains.kotlin:kotlin-stdlib:1.6.21")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.5.2")
    implementation("androidx.core:core-ktx:1.6.0")
    implementation("androidx.localbroadcastmanager:localbroadcastmanager:1.0.0")
    implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5")
    implementation("com.google.code.gson:gson:2.8.9")
    testImplementation("junit:junit:4.13.2")
}
