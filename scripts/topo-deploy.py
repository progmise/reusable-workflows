#!/usr/bin/env python3
"""Deploy-manifest helper for the orchestrator workflows.

Stdlib only. Subcommands:

  validate <manifest>          PR checks: schema, semver, tags/images exist
  plan <manifest>              Print topo levels JSON + mermaid to step summary
  deploy <manifest> --env ENV  Dispatch api-deploy per component, level by level,
                               polling each run to conclusion (ORCHESTRATOR_TOKEN
                               in GH_TOKEN env).

Manifest shape (strict):

  version: 1.2.3
  components:
    - name: loans-api
      repo: progmise/loans-api
      tag: "0.1.0"
      needs: [other-api]
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def parse(path):
    """Strict stdlib parser for the manifest schema above."""
    manifest = {"components": []}
    current = None
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        key_val = re.match(r"^(\w[\w-]*):\s*(.*)$", line.strip())
        if not line.startswith(" ") and line.startswith("version:"):
            manifest["version"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("components:"):
            pass
        elif line.startswith("  - "):
            if current is not None:
                manifest["components"].append(current)
            current = {}
            m = re.match(r"^  - (\w[\w-]*):\s*(.*)$", line)
            if not m:
                fail(f"line {n}: bad component entry: {raw.rstrip()}")
            current[m.group(1)] = m.group(2).strip().strip('"')
        elif line.startswith("    ") and current is not None and key_val:
            k, v = key_val.group(1), key_val.group(2).strip()
            if k == "needs":
                current[k] = [x.strip().strip('"') for x in
                              v.strip("[]").split(",") if x.strip()]
            else:
                current[k] = v.strip('"')
        else:
            fail(f"line {n}: unexpected content: {raw.rstrip()}")
    if current is not None:
        manifest["components"].append(current)
    return manifest


def fail(msg, code=1):
    print(f"::error::{msg}")
    sys.exit(code)


def get(url, token=None):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r), 200
    except urllib.error.HTTPError as e:
        return None, e.code


def topo_levels(components):
    """Kahn's algorithm → list of levels (each a list of component dicts)."""
    by_name = {c["name"]: c for c in components}
    pending = {c["name"]: set(c.get("needs", [])) for c in components}
    for name, deps in pending.items():
        for d in deps:
            if d not in by_name:
                fail(f"{name}: unknown need '{d}'")
    levels = []
    done = set()
    while pending:
        level = sorted(n for n, deps in pending.items() if deps <= done)
        if not level:
            fail(f"dependency cycle among: {sorted(pending)}")
        levels.append([by_name[n] for n in level])
        done.update(level)
        for n in level:
            del pending[n]
    return levels


def mermaid(components):
    lines = ["graph BT"]
    names = {c["name"] for c in components}
    for c in components:
        deps = c.get("needs") or []
        if not deps:
            lines.append(f"    {c['name']}")
        for d in deps:
            if d in names:
                lines.append(f"    {d} --> {c['name']}")
    return "\n".join(lines)


def validate(manifest):
    errors = []
    if not SEMVER.match(manifest.get("version", "")):
        errors.append(f"version '{manifest.get('version')}' is not semver")
    names = [c["name"] for c in manifest["components"]]
    if len(names) != len(set(names)):
        errors.append("duplicate component names")
    token = os.environ.get("GH_TOKEN")
    for c in manifest["components"]:
        for field in ("name", "repo", "tag"):
            if not c.get(field):
                errors.append(f"{c.get('name','?')}: missing '{field}'")
        repo, tag = c.get("repo", ""), c.get("tag", "")
        _, code = get(f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}",
                      token)
        if code != 200:
            errors.append(f"{repo}: tag '{tag}' not found (HTTP {code})")
        who = os.environ.get("DOCKER_USERNAME")
        if who:
            _, code = get(
                f"https://hub.docker.com/v2/repositories/{who}/{repo.split('/')[-1]}"
                f"/tags/{tag}")
            if code != 200:
                errors.append(f"docker.io/{who}/{repo.split('/')[-1]}:{tag} "
                              f"not found (HTTP {code})")
    return errors


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        fail(f"gh {' '.join(args)} → {r.stderr.strip()}")
    return r


def latest_run(repo, since):
    """Newest workflow_dispatch run of deploy.yml created after `since`."""
    r = gh("api", f"repos/{repo}/actions/workflows/deploy.yml/runs",
           "-f", "event=workflow_dispatch", "-f", "per_page=5")
    for run in json.loads(r.stdout).get("workflow_runs", []):
        if run["created_at"] >= since:
            return run
    return None


def deploy(manifest, env):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results = {}
    for i, level in enumerate(topo_levels(manifest["components"]), 1):
        print(f"--- level {i}: {[c['name'] for c in level]}")
        for c in level:
            gh("workflow", "run", "deploy.yml", "-R", c["repo"],
               "-f", f"version={c['tag']}", "-f", f"environment={env}")
            print(f"dispatched {c['repo']}@{c['tag']} → {env}")
        for c in level:  # poll every component of the level to conclusion
            run = None
            for _ in range(120):  # up to ~20 min per component
                run = latest_run(c["repo"], ts)
                if run and run["status"] == "completed":
                    break
                time.sleep(10)
            ok = run and run["conclusion"] == "success"
            results[c["name"]] = run["html_url"] if run else "not found"
            print(f"{c['name']}: {run and run['conclusion'] or 'timeout'}")
            if not ok:
                return results, False
    return results, True


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    manifest = parse(sys.argv[2] if len(sys.argv) > 2 else "manifest.yml")
    if cmd == "validate":
        errs = validate(manifest)
        for e in errs:
            print(f"::error::{e}")
        sys.exit(bool(errs))
    if cmd == "plan":
        levels = topo_levels(manifest["components"])
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            open(summary, "a").write(
                f"### Deploy plan — {manifest['version']}\n\n"
                f"```mermaid\n{mermaid(manifest['components'])}\n```\n\n"
                + "\n".join(f"- **level {i}**: "
                            + ", ".join(f"`{c['name']}:{c['tag']}`"
                                        for c in lv)
                            for i, lv in enumerate(levels, 1))
                + "\n")
        print(json.dumps({"levels": [[c["name"] for c in lv]
                                     for lv in levels]}))
    elif cmd == "deploy":
        env = next((a.split("=", 1)[1] for a in sys.argv if
                    a.startswith("--env=")), "pro")
        results, ok = deploy(manifest, env)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            open(summary, "a").write(
                f"### Deploy {manifest['version']} → `{env}`\n\n"
                + "\n".join(f"- {n}: {u}" for n, u in results.items()) + "\n")
        sys.exit(0 if ok else 1)
    else:
        fail(__doc__)


main()
