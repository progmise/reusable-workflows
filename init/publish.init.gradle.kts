import com.vanniktech.maven.publish.MavenPublishPlugin
import org.gradle.external.javadoc.StandardJavadocDocletOptions
import org.gradle.api.tasks.javadoc.Javadoc

// Publishing init script — applied only in CI:
//   ./gradlew publishToMavenCentral -I .github/publish.init.gradle.kts
//
// Injects the vanniktech maven-publish plugin at publish time, so
// build.gradle.kts stays free of any publishing configuration.
// All artifact metadata comes from gradle.properties (POM_* props,
// mavenCentralPublishing, signAllPublications).
//
// Credentials are read from ORG_GRADLE_PROJECT_* environment variables:
//   mavenCentralUsername / mavenCentralPassword     (Central Portal user token)
//   signingInMemoryKey / signingInMemoryKeyPassword (ASCII-armored GPG key)

initscript {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
    dependencies {
        classpath("com.vanniktech.maven.publish:com.vanniktech.maven.publish.gradle.plugin:0.34.0")
    }
}

allprojects {
    apply<MavenPublishPlugin>()

    // Sign only when a key is provided (CI release). JitPack and local
    // publishToMavenLocal runs without GPG env vars skip signing.
    if (providers.environmentVariable("ORG_GRADLE_PROJECT_signingInMemoryKey").isPresent) {
        extensions.configure<com.vanniktech.maven.publish.MavenPublishBaseExtension> {
            signAllPublications()
        }
    }

    tasks.withType<Javadoc>().configureEach {
        (options as StandardJavadocDocletOptions).addStringOption("Xdoclint:none", "-quiet")
    }
}
