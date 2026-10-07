# AGENTS.md

Guide for working on **reusable-workflows** — the central GitHub Actions
workflows repo for `progmise` Java libraries.

## Golden rule

Every consumer repo calls these workflows via `@v1` (`uses:` + `secrets:
inherit`). A change here affects **all libs at once** — breaking a job breaks
every consumer's CI. Consumer `.github/` dirs intentionally hold only thin
~15-line callers; keep it that way.

## Layout

- `.github/workflows/` — reusable workflows (`on: workflow_call` only):
  - libs: `ci.yml`, `integration.yml`, `release.yml`
  - apps (APIs, SPAs, CLIs — anything dockerized): `app-ci.yml` (adds Build image + CSA vs lib ci), `app-integration.yml`
    (+ Publish Image → Docker Hub + Deploy to non-pro envs from
    `vars.DEPLOY_ENVIRONMENTS`), `app-release.yml` (+ Publish Image +
    tag/Release — **never deploys**), `app-deploy.yml` (manual deploy of a
    tag to one env, validated against `DEPLOY_ENVIRONMENTS`)
  - orchestrator: `orch-ci.yml`/`orch-release.yml`/`orch-deploy.yml` — called
    only by `deploy-manifest` (manifest validation → draft release →
    topo-sorted dispatch of each repo's `deploy.yml`, level by level);
    needs `ORCHESTRATOR_TOKEN` (PAT with `actions:write` on consumers)
  - `ci-core.yml` / `app-ci-core.yml` hold the check jobs only (no
    Tracing/Summary) — `ci.yml`/`app-ci.yml` wrap them for PRs;
    `release.yml`/`app-release.yml`/`app-integration.yml` call the core
    directly so Tracing/Summary never appear twice in a run
  - tracing is an inline job in every workflow — a `uses:` nested call would
    show "tracing / tracing"; Tracing/Summary always run last, in that order
  - job display names are Title Case (`Setup`, `Build artifact`, `SAST`,
    `SCA`, `CSA`, `Publish Image`, `Deploy`, `Tracing`, `Summary`)
- `init/` — Gradle init scripts fetched by the workflows via `curl` at
  `@v1` (`ci` = JaCoCo, `security` = dependency locking, `publish` = plugin +
  signing + POM) — **Gradle only**; Maven libs carry equivalent config in
  `pom.xml` (JaCoCo + central-publishing + `release` profile for signing)
- `scripts/` — Python 3 stdlib only (no pip installs):
  `emit-telemetry.py` (OTLP spans/gauges → Grafana Cloud),
  `ci-summary.py` (run summary: tests, coverage, findings, API compat),
  `junit-summary.py` (failed-tests section, called by ci-summary),
  `validate-release.py` (release version validation: semver, SNAPSHOT,
  tag/published-exists, monotonic vs latest release; `--kind api` skips the
  Central checks for API repos),
  `api-compat.py` (japicmp API diff vs latest Central artifact; `--gate`
  mode fails on semver-violating bumps — used by release.yml),
  `topo-deploy.py` (`validate`/`plan`/`deploy` for `deploy-manifest` — strict
  stdlib parser for `manifest.yml`: `version` + `environments` +
  `infrastructures` + `components` sections; Kahn topo levels, mermaid,
  `gh workflow
  run` dispatch + conclusion polling).
  `jitpack-install.sh` (bash) is the exception: JitPack install step for
  Maven libs, invoked by each repo's `jitpack.yml` via curl.
- `docs/` — `flows.md` (mermaid map of every pipeline — keep synced when
  jobs change), `orchestrator.md` (Gluon/OAM analysis + `deploy-manifest`
  design — implemented: `orch-*` workflows + `topo-deploy.py`).

## Conventions

- **Zero hard dependencies on consumer files**: workflows fetch `init/` and
  `scripts/` from this repo at runtime (`raw.githubusercontent.com/.../@v1`).
  Only the build files come from the caller: `pom.xml`+`mvnw` (Maven libs) or
  `build.gradle.kts`/`gradlew`/`gradle.properties` (Gradle libs); API repos
  additionally ship a self-contained root `Dockerfile` (multi-stage source
  build — CI, compose and Vercel all use the same file).
- **Multi build tool**: every build step exists in two variants gated by
  `if: hashFiles('pom.xml')` — Maven when the pom exists, Gradle otherwise.
  Keep both branches in sync when touching a step.
- **Never read a secret into logs**; `GRAFANA_OTLP_AUTH` etc. only reach
  `Authorization` headers.
- `secrets: inherit` propagates consumer secrets; when a reusable workflow
  calls another reusable workflow, repeat `secrets: inherit` on the inner call.
- Reusable workflows pin the `@v1` tag when self-fetching scripts — when
  changing a fetched file, move `v1` to the new commit.
- **Empty matrix jobs fail the run**: a `matrix` that expands to `[]` marks
  the job failed (it doesn't even appear in the job list). Guard matrix jobs
  with a job-level `if:` on the setup output (see `app-integration` deploy).

## Verify before done

```bash
python -c "import yaml,glob; [yaml.safe_load(open(f).read()) for f in glob.glob('.github/workflows/*.yml')]"
python -m py_compile scripts/emit-telemetry.py
```

## Branches

Single `main`, no `development`. Small safe changes may go straight to `main`;
otherwise use a short-lived branch `<type>/<snake_description>` + PR —
`feature/`, `fix/`, `chore/`, `docs/`, `refactor/`.

## Release

Consumers pin `@v1`. To ship a change: commit → `git tag -f v1 && git push -f
origin v1` → the next run in any consumer picks it up. For a breaking change
(mandatory inputs, renamed secrets), bump a new tag and update callers instead
of moving `v1` silently — see the `workflow-release` skill.

**`v1` must stay a lightweight tag.** An annotated tag resolves to the tag
*object* SHA (not the commit), so `uses: …@v1` fails with `startup_failure`
and zero jobs. `git tag -f v1` (no `-a`) is lightweight — correct.
