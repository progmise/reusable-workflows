---
name: maintain-agents-doc
description: Reconcile this repo's AGENTS.md/README.md with reality (workflow inventory, fetched assets, secrets/vars contract, consumers). Use when workflows, init scripts, or scripts change, or when docs drift from the repo.
---

# Maintain AGENTS.md — keep the doc honest

`AGENTS.md` documents the contract between this repo and its consumers. After
any structural change, reconcile it:

## Reconciliation checklist

- **Workflow inventory** — every file in `.github/workflows/` listed in
  AGENTS.md's Layout table, with its trigger (`workflow_call`) and purpose.
  Remove entries for deleted workflows.
- **Fetched assets** — `init/*.init.gradle.kts` and `scripts/*` referenced by
  the workflows must exist and be fetched from the matching `@v1` path.
  Grep for `raw.githubusercontent.com` URLs and confirm each target exists.
- **Secrets/vars contract** — every `secrets.*` / `vars.*` referenced anywhere
  in the workflows documented for consumers (`SONATYPE_*`, `GPG_*`,
  `GRAFANA_OTLP_*`, `GH_TOKEN` is automatic). New secret ⇒ document it AND
  flag that every consumer repo must add it.
- **Permissions** — job-level `permissions:` in sync with what the job does
  (checkout → `contents`, Jobs API → `actions`, tag/release → `contents:
  write`).
- **Consumers** — which repos pin `@v1` (currently `java-lib-template`,
  `api-utils`); update README/AGENTS when the list grows.

## Rules

- Verify each claim against the repo — never document from memory.
- Mirror the existing terse style; AGENTS.md stays short and actionable.
