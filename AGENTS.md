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
  `ci.yml`, `integration.yml`, `release.yml`, `telemetry.yml` (shared
  tracing job called by ci/release)
- `init/` — Gradle init scripts fetched by the workflows via `curl` at
  `@v1` (`ci` = JaCoCo, `security` = dependency locking, `publish` = plugin +
  signing + POM)
- `scripts/` — Python 3 stdlib only (no pip installs):
  `emit-telemetry.py` (OTLP spans/gauges → Grafana Cloud),
  `ci-summary.py` (run summary: tests, coverage, findings, API compat),
  `junit-summary.py` (failed-tests section, called by ci-summary),
  `validate-release.py` (release version validation: semver, SNAPSHOT,
  tag/published-exists, monotonic vs latest release),
  `api-compat.py` (japicmp API diff vs latest Central artifact; `--gate`
  mode fails on semver-violating bumps — used by release.yml)

## Conventions

- **Zero hard dependencies on consumer files**: workflows fetch `init/` and
  `scripts/` from this repo at runtime (`raw.githubusercontent.com/.../@v1`).
  Only `build.gradle.kts`/`gradlew`/`gradle.properties` come from the caller.
- **Never read a secret into logs**; `GRAFANA_OTLP_AUTH` etc. only reach
  `Authorization` headers.
- `secrets: inherit` propagates consumer secrets; when a reusable workflow
  calls another reusable workflow, repeat `secrets: inherit` on the inner call.
- Reusable workflows pin the `@v1` tag when self-fetching scripts — when
  changing a fetched file, move `v1` to the new commit.

## Verify before done

```bash
python -c "import yaml,glob; [yaml.safe_load(open(f).read()) for f in glob.glob('.github/workflows/*.yml')]"
python -m py_compile scripts/emit-telemetry.py
```

## Release

Consumers pin `@v1`. To ship a change: commit → `git tag -f v1 && git push -f
origin v1` → the next run in any consumer picks it up. For a breaking change
(mandatory inputs, renamed secrets), bump a new tag and update callers instead
of moving `v1` silently — see the `workflow-release` skill.
