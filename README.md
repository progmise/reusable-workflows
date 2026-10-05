# reusable-workflows

Central reusable workflows for the `progmise` Java libraries. Consumer repos
keep only thin callers in their `.github/workflows/` — all pipeline logic
lives here, versioned via the `v1` tag.

## Workflows

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | `workflow_call` (libs): Setup → Build+test (JaCoCo) → SCA (Trivy) ‖ SAST (Semgrep) ‖ API Compat (japicmp) → Tracing → Summary |
| `.github/workflows/integration.yml` | `workflow_call` (libs): ci + JitPack SHA report |
| `.github/workflows/release.yml` | `workflow_call` (libs): Setup → Validate (semver + monotonic + not-published) → CI → Compat gate → Publish to Maven Central → tag + GH Release → Tracing → Summary |
| `.github/workflows/api-ci.yml` | `workflow_call` (APIs): Setup → Build artifact → Build image → SAST ‖ SCA ‖ CSA (Trivy image) → Tracing → Summary (`inputs.final-report: false` suppresses the last two when the caller adds its own) |
| `.github/workflows/api-integration.yml` | `workflow_call` (APIs): ci + Publish Image to Docker Hub (`:<sha>`, `:edge`/`:latest`) → Deploy non-pro envs (Vercel; `DEPLOY_ENVIRONMENTS` minus `pro`) → Tracing → Summary |
| `.github/workflows/api-release.yml` | `workflow_call` (APIs): Setup → Validate → CI → Publish Image (`:<version>` + `:latest`) → tag + GH Release → Tracing → Summary. **Never deploys** — production deploys run via `api-deploy` / the orchestrator |
| `.github/workflows/api-deploy.yml` | `workflow_call` (APIs): manual deploy of a released tag to one env — Validate (env in `DEPLOY_ENVIRONMENTS` + tag + image) → Deploy (Vercel, `--prod` only for `pro`) → Tracing → Summary |
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

API consumers additionally need: a self-contained `Dockerfile` at the repo
root (multi-stage source build — the same file is used by `docker build`,
compose and Vercel, which builds it automatically), secret `DOCKER_TOKEN`
(image publish) and optional secret
`VERCEL_TOKEN`, and vars `DOCKER_USERNAME` (image namespace — public info,
kept as var so image names aren't masked in logs), `VERCEL_ORG_ID`/
`VERCEL_PROJECT_ID` + `DEPLOY_ENVIRONMENTS` (JSON list; `["pro"]` default —
add `"cert"`/`"pre"` to extend). Deploy jobs skip silently when the Vercel
vars are unset.
