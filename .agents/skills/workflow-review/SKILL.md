---
name: workflow-review
description: Review GitHub Actions workflows for maintainability — when inline `run:` code should be extracted to scripts/, missing summaries/artifacts, duplicated steps, permissions, and pinning. Use when adding or refactoring workflow steps, or when a `run:` block starts feeling like a program.
---

# Workflow review — when YAML stops being config and starts being code

Thin is good for **callers**; inside the reusable workflows, the smell is
*inline code that grew past glue*. This skill is the checklist.

## The extraction rule — `run:` → `scripts/<name>.py`

Extract a `run:` block to `scripts/` when **any** of these hold:

- **It transforms data** — builds/parses JSON, XML, CSV (that's what
  `emit-telemetry.py` and `junit-summary.py` are). Bash+jq is for plumbing,
  not payloads.
- **> ~15 lines**, or > 3 levels of nesting, or loops accumulating state.
- **It needs quoting gymnastics** — nested quotes, heredocs inside
  `run: |` blocks (heredocs break YAML indentation rules — real bug we hit).
- **It would benefit from a local run** — a file can be `py_compile`'d /
  `bash -n`'d and tested offline; inline YAML can't.
- **Two jobs need it** — never copy-paste a script between jobs; one file,
  two `curl | run` steps.

Keep inline when it's real glue: `curl` fetches, `echo` to
`$GITHUB_STEP_SUMMARY`, simple `git`/`grep` checks, single commands.

## Review checklist

- **Extraction**: any `run:` matching the rules above → propose
  `scripts/<name>.py` fetched via `curl ... @v1`.
- **Observability**: every check job produces a JSON/CSV artifact
  (`*-report*`, `if: always()`, 30d) AND the `summary` job surfaces its
  findings — a red job must explain itself without opening logs.
- **Permissions**: job-level `permissions:` minimal (`contents: read` only
  when checking out, `actions: read` for the Jobs/artifacts API); remember
  that restricting one scope implicitly denies the rest (the checkout
  incident).
- **Pinning**: third-party actions pinned to a tag (`@v4`, `@v0.33.1`), not
  floating `@main`/`@latest`; direct-download tools pinned to a version.
- **Fragility**: steps that may legitimately fail produce artifacts with
  `if: always()` *before* the workflow stops; downloads use
  `continue-on-error` + guards (`test -f` / `next(..., None)`).
- **Self-reference**: files fetched via `raw.githubusercontent.com` use the
  `@v1` tag, and moving the tag is part of the change (see
  `workflow-release`).
- **Duplication across ci/integration/release**: shared sequences belong in
  a nested `workflow_call` or a script — not copied blocks.
- **Naming**: job ids are the contract — callers' `needs:` and the telemetry
  spans use them. Renaming a job is a breaking change.
