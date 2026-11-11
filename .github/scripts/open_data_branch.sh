#!/usr/bin/env bash
# open_data_branch.sh -- after a fetch of the data branch, make the sealed files readable in THIS clone only.
#
# Seal move 3 (2026-11-11): the data branch no longer carries a plain copy of the files that name tonight's calls
# (seal_data.sh SEALED_RE), only <name>.sealed. Every job here reads the branch with `git show origin/data:<file>`,
# `git archive origin/data` or `git ls-tree origin/data`. So that none of those lines has to change, this builds a
# local commit that is the fetched tree PLUS the opened plain copy of each sealed file, and points
# refs/remotes/origin/data at it. Nothing is pushed; the commit lives in the runner's clone and dies with it.
#   refs/remotes/origin/data            the opened tree (what readers use)
#   refs/remotes/origin/data-published  the commit GitHub really holds (publish_data.sh's lease and tree check)
#
#   exit 0  opened, or nothing on the branch is sealed, or there is no data branch
#   exit 1  sealed files are there and could not be opened (no DATA_SEAL_KEY in this step, wrong key, changed
#           file). Callers treat that like a failed fetch: a sealed file that cannot be read is NOT an absent one.
set -euo pipefail
REF=refs/remotes/origin/data
real="$(git rev-parse --verify -q "$REF^{commit}" 2>/dev/null)" || exit 0
# run twice with no fetch between: origin/data is already the opened commit
case "$(git log -1 --format=%s "$real" 2>/dev/null)" in "opened "*) exit 0 ;; esac
git update-ref refs/remotes/origin/data-published "$real"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git ls-tree --name-only "$real" public/data/current/ | grep '\.sealed$' > "$work/sealed" || true
: > "$work/todo"
while read -r p; do
  [ -n "$p" ] || continue
  git cat-file -e "$real:${p%.sealed}" 2>/dev/null || echo "$p" >> "$work/todo"
done < "$work/sealed"
[ -s "$work/todo" ] || exit 0

# shellcheck source=/dev/null
source "${DATA_SEAL_LIB:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/seal_data.sh}"
if ! _keys_ok; then
  echo "::error::the data branch holds $(wc -l < "$work/todo" | tr -d ' ') sealed file(s) and DATA_SEAL_KEY is not set in this step, so they cannot be read. Nothing was treated as missing." >&2
  exit 1
fi
export GIT_INDEX_FILE="$work/index"
git read-tree "$real"
n=0
while read -r p; do
  git show "$real:$p" > "$work/s"
  unseal_file "$work/s" "$work/p" || { echo "::error::could not open $p" >&2; exit 1; }
  blob="$(git hash-object -w "$work/p")"
  git update-index --add --cacheinfo "100644,$blob,${p%.sealed}"
  n=$((n + 1))
done < "$work/todo"
tree="$(git write-tree)"
commit="$(GIT_AUTHOR_NAME=data GIT_AUTHOR_EMAIL=data@local GIT_COMMITTER_NAME=data GIT_COMMITTER_EMAIL=data@local \
  git commit-tree "$tree" -m "opened $real")"
unset GIT_INDEX_FILE
git update-ref "$REF" "$commit"
echo "data branch: opened $n sealed file(s) for this job"
