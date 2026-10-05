# reusable-workflows

Central reusable workflows for the `progmise` Java libraries. Consumer repos
keep only thin callers in their `.github/workflows/` — all pipeline logic
lives here, versioned via the `v1` tag.

## Workflows

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | `workflow_call`: build+test (JaCoCo) ‖ Trivy ‖ Semgrep → summary → tracing |
| `.github/workflows/integration.yml` | `workflow_call`: ci + JitPack SHA report |
| `.github/workflows/release.yml` | `workflow_call`: validate → ci → publish to Maven Central → tag + GH Release → tracing |
| `scripts/emit-telemetry.py` | OTLP spans + gauges to Grafana Cloud (Python stdlib, fetched via curl by the tracing job) |
| `init/*.init.gradle.kts` | Gradle init scripts (JaCoCo / dependency-locking / publish+signing), fetched via curl and applied with `gradle -I` |

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
(`workflow-release`, `maintain-agents-doc`, `ponytail`).

Consumers only need `gradle.properties` POM metadata + secrets
(`SONATYPE_*`, `GPG_*`, optional `GRAFANA_OTLP_AUTH`) and the
`GRAFANA_OTLP_ENDPOINT` variable — everything else comes from this repo.
