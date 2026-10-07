import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("multiplatform")
    kotlin("plugin.serialization")
    id("com.android.kotlin.multiplatform.library")
    id("org.jetbrains.compose")
    id("org.jetbrains.kotlin.plugin.compose")
}

kotlin {
    android {
        namespace = "kr.ac.kongju.knupick.shared"
        compileSdk = 37
        minSdk = 26
        compilerOptions.jvmTarget.set(JvmTarget.JVM_17)
    }
    jvm {
        compilerOptions.jvmTarget.set(JvmTarget.JVM_17)
    }
    if (providers.gradleProperty("enableIos").orNull == "true") {
        listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
            target.binaries.framework {
                baseName = "KnuShared"
                isStatic = true
            }
        }
    }
    sourceSets {
        commonMain.dependencies {
            implementation(compose.runtime)
            implementation(compose.foundation)
            implementation(compose.material3)
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")
            implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
            implementation("io.ktor:ktor-client-core:3.3.3")
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
            implementation("io.ktor:ktor-client-mock:3.3.3")
        }
        if (providers.gradleProperty("enableIos").orNull == "true") {
            getByName("iosMain").dependencies {
                implementation("io.ktor:ktor-client-darwin:3.3.3")
            }
        }
    }
}
