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
| `scripts/emit-telemetry.sh` | OTLP spans + gauges to Grafana Cloud (fetched via curl by the tracing job) |

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

Consumers must provide (they live in the consumer repo, not here):

- `.github/publish.init.gradle.kts` — injects publishing + signing
- `.github/security.init.gradle.kts` — dependency locking for Trivy
- `.github/ci.init.gradle.kts` — JaCoCo
- Secrets: `SONATYPE_*`, `GPG_*`, optional `GRAFANA_OTLP_AUTH`;
  variable `GRAFANA_OTLP_ENDPOINT`
