#!/usr/bin/env bash
# Commit the given paths and push to main, tolerating a concurrent updater.
#
#   scripts/publish.sh "<commit message>" <path> [path...]
#
# The three scheduled updaters all commit to main, and GitHub's scheduler drifts
# enough under load that two can land in the same minute — which is exactly how
# the first run of these workflows failed. Whoever pushes second gets
# "! [rejected] (fetch first)". Rebasing onto the other's commit and retrying is
# safe here because the updaters touch disjoint files.
#
# Exits 0 when there was nothing to commit.
set -euo pipefail

MSG="$1"
shift

git config user.name  "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add -- "$@"

if git diff --cached --quiet; then
  echo "No change — nothing to publish."
  exit 0
fi

git commit -m "$MSG"

for attempt in 1 2 3 4 5; do
  if git push origin HEAD:main; then
    echo "Published on attempt $attempt."
    exit 0
  fi
  echo "Push rejected (attempt $attempt) — another updater got there first; rebasing."
  git pull --rebase --autostash origin main
  sleep $((attempt * 3))
done

echo "Could not publish after 5 attempts." >&2
exit 1
