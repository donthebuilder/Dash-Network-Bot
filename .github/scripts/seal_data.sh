#!/usr/bin/env bash
# seal_data.sh -- seal the data-branch files that name tonight's calls (2026-11-09, the site's lockdown;
# site repo claude/LOCKDOWN-PLAN-2026-11-09.txt, lib/data/sealed.js holds the same list).
#
# The repo is public, so every file on the `data` branch is public. These files carry tonight's CALLED picks
# (or let anyone work them out), so each also goes out as <name>.sealed: AES-256-CBC + HMAC-SHA256 under
# DATA_SEAL_KEY (128 hex chars: the first 64 the cipher key, the last 64 the MAC key). Only the bot and the
# site's server hold the key. Format (one line): DSEAL1.<iv hex>.<tag hex>.<ciphertext base64>
#   iv  = first 16 bytes of HMAC(mac, "iv|" + plaintext): the same file seals to the same bytes, so a run with
#         nothing new still finds "nothing to publish" (publish_data.sh's tree check)
#   tag = HMAC(mac, "tag|" + iv + "." + ciphertext base64), checked before anything is decrypted
#
# MOVE 3 (2026-11-11): the plain copy is NOT published. seal_tree seals each listed file and then removes the plain
# one from the tree about to be pushed. Readers in this repo open the sealed copies after they fetch
# (open_data_branch.sh for git reads, bots/sealed_data.py for reads over https). A job with no key never publishes a
# listed file: seal_tree stops the publish instead.
#
#   source seal_data.sh; seal_tree <dir> <fresh-list-file>
#   seal_data.sh unseal <in.sealed> <out>        (also used by tests)
set -euo pipefail

SEALED_RE='^(nfl_(next_)?(week|game_calls|picks)\.json|(today|tomorrow)_slim\.json|results_live\.json|pick_changes\.json|pair_builder_latest\.json|nfl_pick_lock\.json|pick_lock\.json|nhl_board_latest\.json|nba_board_latest\.json|nba_first_board_latest\.json|nfl_(next_)?picks_[0-9]{4}_w[0-9]{2}\.json|nfl_td_log_[0-9]{4}\.jsonl|nfl_game_calls_log_[0-9]{4}_w[0-9]{2}\.jsonl|por_rows_[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl)$'

_hmac() { openssl dgst -sha256 -mac HMAC -macopt "hexkey:$1" | awk '{print $NF}'; }
_keys_ok() { [[ "${DATA_SEAL_KEY:-}" =~ ^[0-9a-fA-F]{128}$ ]]; }

seal_file() {   # in out
  local enc="${DATA_SEAL_KEY:0:64}" mac="${DATA_SEAL_KEY:64:64}" iv ct tag
  iv="$({ printf 'iv|'; cat "$1"; } | _hmac "$mac" | cut -c1-32)"
  ct="$(openssl enc -aes-256-cbc -K "$enc" -iv "$iv" -in "$1" | base64 | tr -d '\n')"
  tag="$(printf 'tag|%s.%s' "$iv" "$ct" | _hmac "$mac")"
  printf 'DSEAL1.%s.%s.%s' "$iv" "$tag" "$ct" > "$2"
}

unseal_file() {   # in.sealed out
  local enc="${DATA_SEAL_KEY:0:64}" mac="${DATA_SEAL_KEY:64:64}" body v iv tag ct want
  body="$(cat "$1")"
  IFS='.' read -r v iv tag ct <<< "$body"
  [ "$v" = "DSEAL1" ] || { echo "unseal: $1 is not a sealed file" >&2; return 1; }
  want="$(printf 'tag|%s.%s' "$iv" "$ct" | _hmac "$mac")"
  [ "$want" = "$tag" ] || { echo "unseal: $1 failed its check (wrong key or changed)" >&2; return 1; }
  printf '%s' "$ct" | base64 -d | openssl enc -d -aes-256-cbc -K "$enc" -iv "$iv" > "$2"
}

# seal_tree <dir>: seal every listed file in <dir>, then remove its plain copy. Returns 1 (publish nothing) when a
# listed plain file is there and this job has no key.
seal_tree() {
  local dir="$1" f base n=0 listed=0
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    [[ "$(basename "$f")" =~ $SEALED_RE ]] && listed=$((listed + 1))
  done
  if ! _keys_ok; then
    [ "$listed" -eq 0 ] && { echo "seal: no key in this job and nothing listed to seal"; return 0; }
    echo "::error::seal: $listed file(s) that name tonight's calls are staged and DATA_SEAL_KEY is not set in this job. They are never published in plain text, so nothing was published." >&2
    return 1
  fi
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    base="$(basename "$f")"
    [[ "$base" =~ $SEALED_RE ]] || continue
    seal_file "$f" "$f.sealed"; n=$((n + 1))
  done
  # a sealed copy whose plain file is gone (trimmed by the keep caps) goes too
  for f in "$dir"/*.sealed; do
    [ -f "$f" ] || continue
    [ -f "${f%.sealed}" ] || rm -f "$f"
  done
  # the plain copies stay on the runner; they do not go out
  for f in "$dir"/*.sealed; do
    [ -f "$f" ] || continue
    rm -f "${f%.sealed}"
  done
  echo "seal: $n sealed, plain copies left out"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    unseal) _keys_ok || { echo "DATA_SEAL_KEY not set" >&2; exit 2; }; unseal_file "$2" "$3" ;;
    seal) _keys_ok || { echo "DATA_SEAL_KEY not set" >&2; exit 2; }; seal_file "$2" "$3" ;;
    *) echo "usage: seal_data.sh seal|unseal <in> <out>" >&2; exit 2 ;;
  esac
fi
