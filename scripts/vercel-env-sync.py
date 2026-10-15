#!/usr/bin/env python3
"""Upsert KEY=value pairs (stdin) as environment variables on a Vercel project.

Usage:  cm-config.py env pro | vercel-env-sync.py <project> <target>

  <project>  Vercel project name or id (the manifest infra's properties.project)
  <target>   vercel target: production | preview | development

Env:  VERCEL_TOKEN (required), VERCEL_ORG_ID (teamId, optional for personal).

Only upserts — keys removed from the config file are NOT deleted from the
project (manual/dashboard-set vars are left untouched).
"""
import json
import os
import sys
import urllib.request


def fail(msg, code=1):
    print(f"::error::{msg}")
    sys.exit(code)


def main():
    if len(sys.argv) < 3:
        fail("usage: vercel-env-sync.py <project> <target>  (KEY=value on stdin)")
    project, target = sys.argv[1], sys.argv[2]
    if target not in ("production", "preview", "development"):
        fail(f"invalid target '{target}' — production|preview|development")
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        fail("VERCEL_TOKEN is required")
    org = os.environ.get("VERCEL_ORG_ID", "")

    pairs = []
    for line in sys.stdin:
        line = line.strip()
        if line and "=" in line:
            k, _, v = line.partition("=")
            pairs.append((k.strip(), v.strip()))
    if not pairs:
        fail("no KEY=value pairs on stdin")

    url = (f"https://api.vercel.com/v10/projects/{project}/env"
           f"?upsert=true&teamId={org}")
    upserted = 0
    for key, value in pairs:
        body = json.dumps({
            "key": key, "value": value,
            "type": "plain", "target": [target],
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
        except urllib.error.HTTPError as e:
            fail(f"upsert {key} → {project} failed: HTTP {e.code} {e.read()[:200]}")
        upserted += 1
        print(f"  {key} → {project} ({target})")
    print(f"{upserted} env var(s) upserted into {project} [{target}]")


main()
