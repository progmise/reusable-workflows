// CI-only init script: enables JaCoCo coverage so the `test` task produces
// reports for the workflow summary without adding any config to
// build.gradle.kts.
//
// Usage: ./gradlew test -I .github/ci.init.gradle.kts

import org.gradle.api.tasks.testing.Test
import org.gradle.testing.jacoco.plugins.JacocoPlugin
import org.gradle.testing.jacoco.plugins.JacocoPluginExtension
import org.gradle.testing.jacoco.tasks.JacocoReport

beforeProject {
    pluginManager.withPlugin("java") {
        pluginManager.apply(JacocoPlugin::class.java)

        extensions.configure(JacocoPluginExtension::class.java) {
            toolVersion = "0.8.12"
        }

        tasks.withType(Test::class.java).configureEach {
            finalizedBy("jacocoTestReport")
        }

        tasks.withType(JacocoReport::class.java).configureEach {
            reports {
                xml.required.set(true)
                csv.required.set(true)
            }
        }
    }
}
