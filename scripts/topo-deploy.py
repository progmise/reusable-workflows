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
  environments:                    # optional — declared deploy targets
    - name: pro
      type: production
      infrastructures:             # infra targets under this env
        - id: loans-api-pro
          type: vercel             # vercel | artifact-store | kubernetes | ...
          properties:              # free-form provider fields (OAM style)
            project: loans-api
            credentialsId: VERCEL_TOKEN  # name of the secret in the consumer
            orgId: VERCEL_ORG_ID         # name of the variable in the consumer
  components:
    - name: loans-api
      repo: progmise/loans-api
      tag: "0.1.0"
      needs: [other-api]
      infra: [loans-api-pro]       # required — ci_ids binding the component to
                                   # infrastructures[].id (which env it deploys to)
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SECTIONS = ("components", "environments")
LIST_FIELDS = {"needs", "infra"}


def parse(path):
    """Strict stdlib parser for the manifest schema above.

    Indentation contract: top-level keys at column 0, section items at
    `  - `, item fields at `    `, and inside an environment item an
    `infrastructures:` list whose entries sit at `      - ` with fields
    at `        ` — plus a `properties:` map at `        ` whose keys
    live at `          `.
    """
    manifest = {s: [] for s in SECTIONS}
    section = None
    current = None      # open item of the current section
    sub = None          # open infrastructures[] item
    in_sub = False      # inside an environment's infrastructures: list
    in_props = False    # inside an infra item's properties: map

    def flush_sub():
        nonlocal sub, in_sub, in_props
        if sub is not None:
            current["infrastructures"].append(sub)
            sub = None
        in_sub = in_props = False

    def flush_item():
        nonlocal current
        flush_sub()
        if current is not None:
            manifest[section].append(current)
            current = None

    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        key_val = re.match(r"^(\w[\w-]*):\s*(.*)$", line.strip())
        if not line.startswith(" "):
            flush_item()
            if line.startswith("version:"):
                manifest["version"] = line.split(":", 1)[1].strip().strip('"')
            elif key_val and key_val.group(1) in SECTIONS:
                section = key_val.group(1)
            else:
                fail(f"line {n}: unexpected content: {raw.rstrip()}")
        elif line.startswith("      - ") and in_sub and current is not None:
            if sub is not None:
                current["infrastructures"].append(sub)
            sub = {}
            in_props = False
            m = re.match(r"^      - (\w[\w-]*):\s*(.*)$", line)
            if not m:
                fail(f"line {n}: bad infrastructure entry: {raw.rstrip()}")
            sub[m.group(1)] = m.group(2).strip().strip('"')
        elif line.startswith("          ") and in_props and sub is not None \
                and key_val:
            sub["properties"][key_val.group(1)] = \
                key_val.group(2).strip().strip('"')
        elif line.startswith("        ") and sub is not None and key_val:
            k, v = key_val.group(1), key_val.group(2).strip()
            if k == "properties" and not v:
                sub["properties"] = {}
                in_props = True
            else:
                in_props = False
                sub[k] = v.strip('"')
        elif line.startswith("  - ") and section:
            flush_item()
            current = {}
            m = re.match(r"^  - (\w[\w-]*):\s*(.*)$", line)
            if not m:
                fail(f"line {n}: bad {section[:-1]} entry: {raw.rstrip()}")
            current[m.group(1)] = m.group(2).strip().strip('"')
        elif line.startswith("    ") and current is not None and key_val:
            k, v = key_val.group(1), key_val.group(2).strip()
            if k == "infrastructures" and not v and section == "environments":
                current.setdefault("infrastructures", [])
                in_sub = True
            else:
                flush_sub()
                if k in LIST_FIELDS:
                    current[k] = [x.strip().strip('"') for x in
                                  v.strip("[]").split(",") if x.strip()]
                else:
                    current[k] = v.strip('"')
        else:
            fail(f"line {n}: unexpected content: {raw.rstrip()}")
    flush_item()
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
    env_names = [e.get("name", "") for e in manifest["environments"]]
    if len(env_names) != len(set(env_names)):
        errors.append("duplicate environment names")
    infra_ids = []
    for e in manifest["environments"]:
        for field in ("name", "type"):
            if not e.get(field):
                errors.append(f"environment {e.get('name', '?')}: "
                              f"missing '{field}'")
        for i in e.get("infrastructures", []):
            infra_ids.append(i.get("id", ""))
            for field in ("id", "type"):
                if not i.get(field):
                    errors.append(f"infrastructure in env "
                                  f"'{e.get('name', '?')}': missing '{field}'")
    if len(infra_ids) != len(set(infra_ids)):
        errors.append("duplicate infrastructure ids")
    token = os.environ.get("GH_TOKEN")
    for c in manifest["components"]:
        for field in ("name", "repo", "tag"):
            if not c.get(field):
                errors.append(f"{c.get('name','?')}: missing '{field}'")
        if not c.get("infra"):
            errors.append(f"{c.get('name', '?')}: missing 'infra' — bind the "
                          "component to at least one infrastructures[].id")
        for ref in c.get("infra", []):
            if ref not in infra_ids:
                errors.append(f"{c.get('name', '?')}: unknown infrastructure "
                              f"'{ref}'")
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
    """Newest workflow_dispatch run of deploy.yml created after `since`.

    Uses `gh run list` rather than `gh api` — same auth path as
    `gh workflow run` (a PAT that can dispatch can also list).
    """
    r = gh("run", "list", "-R", repo, "--workflow", "deploy.yml",
           "--event", "workflow_dispatch", "--limit", "5",
           "--json", "databaseId,status,conclusion,createdAt,url")
    for run in json.loads(r.stdout):
        if run["createdAt"] >= since:
            run["html_url"] = run["url"]
            return run
    return None


def deploy(manifest, env):
    envs = manifest["environments"]
    if envs and env not in {e.get("name") for e in envs}:
        fail(f"environment '{env}' not declared in manifest environments")
    infra_by_id = {i.get("id"): (e.get("name"), i)
                   for e in envs for i in e.get("infrastructures", [])}
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results = {}
    for i, level in enumerate(topo_levels(manifest["components"]), 1):
        print(f"--- level {i}: {[c['name'] for c in level]}")
        for c in level:
            bound = c.get("infra") or []
            targets = [x for x in bound
                       if infra_by_id.get(x, (None,))[0] == env]
            if not targets:
                return results, False, (f"{c['name']}: no infrastructure "
                                        f"binding for env '{env}'")
            for ci_id in targets:
                gh("workflow", "run", "deploy.yml", "-R", c["repo"],
                   "-f", f"version={c['tag']}", "-f", f"environment={env}",
                   "-f", f"ci_id={ci_id}")
                print(f"dispatched {c['repo']}@{c['tag']} → {env} ({ci_id})")
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
                return results, False, "deploy run failed"
    return results, True, ""


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
        results, ok, reason = deploy(manifest, env)
        if reason:
            print(f"::error::{reason}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            open(summary, "a").write(
                f"### Deploy {manifest['version']} → `{env}`\n\n"
                + "\n".join(f"- {n}: {u}" for n, u in results.items()) + "\n")
        sys.exit(0 if ok else 1)
    else:
        fail(__doc__)


main()
