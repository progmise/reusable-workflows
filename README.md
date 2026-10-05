# reusable-workflows

Central reusable workflows for the `progmise` Java libraries. Consumer repos
keep only thin callers in their `.github/workflows/` — all pipeline logic
lives here, versioned via the `v1` tag.

## Workflows

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | `workflow_call`: Setup → Build+test (JaCoCo) → SCA (Trivy) ‖ SAST (Semgrep) ‖ API Compat (japicmp) → Tracing → Summary |
| `.github/workflows/integration.yml` | `workflow_call`: ci + JitPack SHA report |
| `.github/workflows/release.yml` | `workflow_call`: Setup → Validate (semver + monotonic + not-published) → CI → Compat gate → Publish to Maven Central → tag + GH Release → Tracing → Summary |
| `scripts/*.py` | telemetry + run-summary emitters (Python stdlib, fetched via curl at `@v1`) |
| `scripts/jitpack-install.sh` | JitPack install step for Maven libs (sdkman maven + `mvn install`) — called from each repo's thin `jitpack.yml` |
| `init/*.init.gradle.kts` | Gradle init scripts (JaCoCo / dependency-locking / publish+signing), fetched via curl — Maven libs use their `pom.xml` config instead |

## Caller usage

```yaml
# .github/workflows/ci.yml in the consumer repo
name: CI Checks
on: pull_request
permissions: { contents: read, actions: read }
jobs:
  ci:
    uses: progmise/reusable-workflows/.github/workflows/ci.yml@v1
    secrets: inherit
```

Also ships `AGENTS.md`, `LICENSE` (Apache 2.0) and `.agents/skills/`
(`workflow-release`, `workflow-review`, `maintain-agents-doc`, `ponytail`).

Consumers only need their build files (`pom.xml`+`mvnw`, or Gradle equivalents) + secrets
(`SONATYPE_*`, `GPG_*`, optional `GRAFANA_OTLP_AUTH`) and the
`GRAFANA_OTLP_ENDPOINT` variable — everything else comes from this repo.
