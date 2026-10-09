#!/usr/bin/env bash
# prune-vcr-images.sh — keep the project's Vercel Container Registry repo
# below the image cap. Deletes all but the newest KEEP images in REPO_NAME.
# Best-effort: never fails the build (the cap error happens at push time —
# pruning before deploy lets a retry self-heal).
#
# env: VERCEL_TOKEN (required), VERCEL_PROJECT_ID or REPO (project name),
#      REPO_NAME (default: dockerfile), KEEP (default: 3)
set -u

KEEP="${KEEP:-3}"
REPO_NAME="${REPO_NAME:-dockerfile}"
PROJECT="${VERCEL_PROJECT_ID:-$REPO}"

[ -n "${VERCEL_TOKEN:-}" ] || { echo "no VERCEL_TOKEN — skipping prune"; exit 0; }

npm i -g vercel@62 >/dev/null 2>&1
VCR="vercel vcr image ls $REPO_NAME --project $PROJECT --format json --token $VERCEL_TOKEN"

IDS=$($VCR 2>/dev/null | jq -r '
  sort_by(.createdAt // .created_at // "") | reverse | .['"$KEEP"':] |
  .[] | .id // .imageId // empty')
[ -z "$IDS" ] && { echo "vcr prune: nothing to delete (or repo absent)"; exit 0; }

echo "$IDS" | while read -r id; do
  vercel vcr image rm "$REPO_NAME" "$id" --project "$PROJECT" --yes \
    --token "$VERCEL_TOKEN" >/dev/null 2>&1 \
    && echo "vcr prune: deleted $id" || echo "vcr prune: failed $id (ignored)"
done
