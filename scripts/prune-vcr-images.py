#!/usr/bin/env python3
"""Prune the project's Vercel Container Registry repo below the image cap.

vcr.vercel.com caps images per repository; once full, `vercel deploy` fails
at push time with 'maximum allowed number of images'. Runs before the deploy
step so a retry self-heals. Best-effort: never fails the build.

env: VERCEL_TOKEN (required), VERCEL_PROJECT_ID or REPO (project name),
     REPO_NAME (default: dockerfile), KEEP (default: 3)
"""
import json
import os
import subprocess
import sys

KEEP = int(os.environ.get("KEEP", "3"))
REPO = os.environ.get("REPO_NAME", "dockerfile")
PROJECT = os.environ.get("VERCEL_PROJECT_ID") or os.environ.get("REPO", "")
TOKEN = os.environ.get("VERCEL_TOKEN", "")

if not TOKEN or not PROJECT:
    sys.exit("vcr prune: no VERCEL_TOKEN/project — skipping")


def vcr(*args):
    return subprocess.run(
        ["vercel", "vcr", *args, "--project", PROJECT, "--token", TOKEN],
        capture_output=True, text=True)


subprocess.run(["npm", "i", "-g", "vercel@62"],
               capture_output=True, shell=(os.name == "nt"))

images = []
try:
    out = vcr("image", "ls", REPO, "--format", "json")
    data = json.loads(out.stdout or "[]")
    images = data if isinstance(data, list) else data.get("images", [])
except (json.JSONDecodeError, TypeError):
    pass

images.sort(key=lambda i: i.get("createdAt") or i.get("created_at") or "",
            reverse=True)
stale = [i.get("id") or i.get("imageId") for i in images[KEEP:]]
stale = [i for i in stale if i]

if not stale:
    sys.exit(f"vcr prune: {len(images)} image(s), nothing to delete")

for img_id in stale:
    ok = vcr("image", "rm", REPO, img_id, "--yes").returncode == 0
    print(f"vcr prune: {'deleted' if ok else 'failed (ignored)'} {img_id}")
