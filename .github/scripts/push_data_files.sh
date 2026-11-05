#!/usr/bin/env bash
# push_data_files.sh MESSAGE FILE... (2026-11-05, LEFTOVERS B7)
# Run inside a checkout of the `data` branch. Commits FILE... and pushes,
# retrying when another publisher moved the branch. The branch is one orphan
# commit that publish_data.sh force-pushes, so a rebase would replay the old
# orphan over the new one; instead this re-reads the branch and lays only
# these files on top of it again. A plain push (never --force): if the branch
# moved, the server refuses and we try again on the new tip.
set -euo pipefail
MSG="$1"; shift
KEEP=$(mktemp -d)
for f in "$@"; do if [ -e "$f" ]; then mkdir -p "$KEEP/$(dirname "$f")"; cp -p "$f" "$KEEP/$f"; fi; done
for i in 1 2 3 4 5; do
  for f in "$@"; do if [ -e "$KEEP/$f" ]; then mkdir -p "$(dirname "$f")"; cp -p "$KEEP/$f" "$f"; git add -f -- "$f"; fi; done
  if git diff --cached --quiet; then echo "nothing changed"; exit 0; fi
  git commit -qm "$MSG"
  if git push -q origin HEAD:data; then echo "pushed: $MSG"; exit 0; fi
  echo "data branch moved, retry $i"; sleep $((i * 5))
  git fetch -q --depth 1 origin data && git reset -q --hard FETCH_HEAD
done
echo "::error::could not push after 5 tries: $MSG"; exit 1
