// CI-only init script: enables Gradle dependency locking so the publish
// workflow can generate a gradle.lockfile (--write-locks) for the Trivy
// vulnerability scan. The lockfile is produced in the CI VM only and is
// never committed — the repository stays free of locking configuration.
//
// Usage: ./gradlew dependencies --write-locks -I .github/security.init.gradle.kts

beforeProject {
    dependencyLocking {
        lockAllConfigurations()
    }
}
