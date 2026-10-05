---
name: workflow-release
description: Ship a change to the central reusable workflows safely — verify locally, move or bump the pinned tag, and confirm consumers pick it up. Use whenever editing workflows, init scripts, or scripts/ in this repo.
---

# Workflow release — shipping central CI changes

Consumers pin `@v1` via `uses:` and runtime `curl` of `init/` + `scripts/`.
There is no install step: the tag *is* the release.

## Checklist

1. **Classify the change**
   - *Safe to move `v1`*: bugfixes, new jobs that only run in new contexts,
     script improvements, new optional secrets/vars (skipping gracefully when
     absent).
   - *Needs a new tag* (`v2`): renamed/removed jobs or workflows, mandatory
     new inputs, renamed secrets, permission bumps — anything that breaks a
     caller that hasn't updated.

2. **Verify locally**
   ```bash
   python -c "import yaml,glob; [yaml.safe_load(open(f).read()) for f in glob.glob('.github/workflows/*.yml')]"
   python -m py_compile scripts/emit-telemetry.py
   ```
   For init scripts, run them against a consumer clone:
   `cd <consumer> && ./gradlew build -I <this-repo>/init/security.init.gradle.kts`

3. **Ship**
   ```bash
   git tag -f v1 && git push -f origin v1   # same-major change
   # or: git tag v2 && git push origin v2   # breaking — then update callers
   ```

4. **Confirm a real run** — re-run a consumer's workflow (`POST
   /repos/<org>/<repo>/actions/runs/<id>/rerun`) and check the job log fetched
   the new asset (`curl` URL in the log shows the tag).

## Gotchas

- `secrets: inherit` only forwards secrets defined in the **caller** repo —
  a new secret requirement means updating every consumer's secrets AND its
  docs.
- `vars.*` in a reusable workflow resolves to the **caller's** variables.
- The `tracing` job needs `actions: read` — callers must keep that scope in
  their top-level `permissions`.
- Forgetting to move the tag is the #1 silent failure: the run passes but
  uses the old code. Check the commit SHA the tag points to when in doubt.
