# reusable-workflows

Central reusable workflows for the `progmise` Java libraries, deployable
services (APIs, SPAs, CLIs — anything dockerized) and the deploy orchestrator.
Consumer repos
keep only thin callers in their `.github/workflows/` — all pipeline logic
lives here, versioned via the `v1` tag.

## Workflows

| File | Purpose |
|---|---|
| `.github/workflows/ci-core.yml` | `workflow_call` (libs, internal): Setup → Build+test (JaCoCo) → SCA (Trivy) ‖ SAST (Semgrep) ‖ API Compat (japicmp) — the check jobs only |
| `.github/workflows/ci.yml` | `workflow_call` (libs): ci-core + Tracing → Summary (for PRs) |
| `.github/workflows/integration.yml` | `workflow_call` (libs): ci + JitPack SHA report |
| `.github/workflows/release.yml` | `workflow_call` (libs): Setup → Validate (semver + monotonic + not-published) → CI → Compat gate → Publish to Maven Central → tag + GH Release → Tracing → Summary |
| `.github/workflows/app-ci-core.yml` | `workflow_call` (deployable services, internal): Setup → Build artifact → Build image → SAST ‖ SCA ‖ CSA (Trivy image) — the check jobs only |
| `.github/workflows/app-ci.yml` | `workflow_call` (deployable services): app-ci-core + Tracing → Summary (for PRs) |
| `.github/workflows/app-integration.yml` | `workflow_call` (deployable services): ci + Publish Image to Docker Hub (`:<sha>`, `:edge`/`:latest`) → Deploy non-pro envs (Vercel; `DEPLOY_ENVIRONMENTS` minus `pro`) → Tracing → Summary |
| `.github/workflows/app-release.yml` | `workflow_call` (deployable services): Setup → Validate → CI → Publish Image (`:<version>` + `:latest`) → tag + GH Release → Tracing → Summary. **Never deploys** — production deploys run via `app-deploy` / the orchestrator |
| `.github/workflows/app-deploy.yml` | `workflow_call` (deployable services): manual deploy of a released tag to one env — Validate (env in `DEPLOY_ENVIRONMENTS` + tag + image) → Deploy (Vercel, `--prod` only for `pro`) → Tracing → Summary |
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

App consumers additionally need: a self-contained `Dockerfile` at the repo
root (multi-stage source build — the same file serves `docker build`,
compose, and Vercel; set the project's Framework Preset to `Container`),
and optionally:
secret `DOCKER_TOKEN` + var `DOCKER_USERNAME` (image namespace — public info,
kept as var so image names aren't masked in logs) for Publish Image —
**skipped entirely when unset**, so templates run CI green with zero
credentials; secret `VERCEL_TOKEN` + vars `VERCEL_ORG_ID`/`VERCEL_PROJECT_ID`
+ `DEPLOY_ENVIRONMENTS` (JSON list; `["pro"]` default — add `"cert"`/`"pre"`
to extend) for Deploy — also skipped when unset.

Consumers pinning `@v1`: `api-commons`, `java-maven-lib-template` (libs:
`ci`/`integration`/`release`), `loans-api`, `java-maven-api-template`,
`node-react-app-template`, `node-express-api-template`, `deploy-dashboard`,
`deploy-orchestrator-api` (apps: `app-*`), `deploy-manifest` (`orch-*`).
