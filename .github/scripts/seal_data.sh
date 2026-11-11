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

SEALED_RE='^(nfl_(next_)?(week|game_calls|picks)\.json|(today|tomorrow)_slim\.json|results_live\.json|pick_changes\.json|pair_builder_latest\.json|nfl_pick_lock\.json|pick_lock\.json|nhl_board_latest\.json|nba_board_latest\.json|nba_first_board_latest\.json|(nhl|nba)_sim_latest\.json|nfl_(next_)?picks_[0-9]{4}_w[0-9]{2}\.json|nfl_td_log_[0-9]{4}\.jsonl|nfl_game_calls_log_[0-9]{4}_w[0-9]{2}\.jsonl|por_rows_[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl)$'

# RUN LOGS (2026-11-11, Donovan: "Yes, seal them"): every model run's per-player scores. Sealed only while LIVE:
#   ..._<season>-wkNN.<run>.jsonl  while NN is the newest week on the branch or later (nfl_next_* is next week's, so it is)
#   ..._<YYYY-MM-DD>.<run>.jsonl   while the date is yesterday (Phoenix) or later
# An older log is a past game: it goes back to plain and its sealed copy is dropped, so the branch does not carry
# 260 MB of logs as text that cannot be compressed. por_log / nfl_por_log are left plain: a lock line names a run,
# it holds no score, and it is written after the game starts.
LOG_RE='^(nfl_(next_)?(prediction|signal)_log|prediction_log)_.*\.jsonl$'
seal_cutoff() {   # yesterday in Phoenix (UTC-7), GNU date or BSD date; SEAL_CUTOFF overrides (tests)
  [ -n "${SEAL_CUTOFF:-}" ] && { echo "$SEAL_CUTOFF"; return; }
  date -u -d '-31 hours' +%F 2>/dev/null || date -u -v-31H +%F
}
live_week() {     # the newest "<season>-wkNN" among the dir's nfl_prediction_log files, or ''
  local f b best=""
  for f in "$1"/nfl_prediction_log_*-wk[0-9][0-9].*; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"; b="${b#nfl_prediction_log_}"; b="${b%%.*}"
    [[ "$b" > "$best" ]] && best="$b"
  done
  echo "$best"
}
log_is_live() {   # name live_week cutoff
  local n="$1"
  if [[ "$n" =~ _([0-9]{4}-wk[0-9]{2})\. ]]; then [[ ! "${BASH_REMATCH[1]}" < "$2" ]]; return; fi
  if [[ "$n" =~ _([0-9]{4}-[0-9]{2}-[0-9]{2})\. ]]; then [[ ! "${BASH_REMATCH[1]}" < "$3" ]]; return; fi
  return 0        # a shape this does not know: seal it
}

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

# seal_tree <dir>: seal every listed file and every live run log in <dir>, then remove its plain copy. Returns 1
# (publish nothing) when one of those is staged and this job has no key.
seal_tree() {
  local dir="$1" f base n=0 aged=0 wk cut want="$(mktemp)"
  wk="$(live_week "$dir")"; cut="$(seal_cutoff)"
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    base="$(basename "$f")"
    case "$base" in *.sealed) continue ;; esac
    if [[ "$base" =~ $SEALED_RE ]]; then echo "$f" >> "$want"
    elif [[ "$base" =~ $LOG_RE ]]; then
      if log_is_live "$base" "$wk" "$cut"; then echo "$f" >> "$want"; else echo "$f" >> "$want.aged"; fi
    fi
  done
  if ! _keys_ok; then
    [ -s "$want" ] || { echo "seal: no key in this job and nothing listed to seal"; rm -f "$want" "$want.aged"; return 0; }
    echo "::error::seal: $(wc -l < "$want" | tr -d ' ') file(s) that name tonight's calls are staged and DATA_SEAL_KEY is not set in this job. They are never published in plain text, so nothing was published." >&2
    rm -f "$want" "$want.aged"
    return 1
  fi
  while read -r f; do
    [ -n "$f" ] || continue
    seal_file "$f" "$f.sealed"; n=$((n + 1))
  done < "$want"
  # a run log whose game is over goes back to plain
  if [ -f "$want.aged" ]; then
    while read -r f; do
      [ -f "$f.sealed" ] && { rm -f "$f.sealed"; aged=$((aged + 1)); }
    done < "$want.aged"
  fi
  rm -f "$want" "$want.aged"
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
  echo "seal: $n sealed, plain copies left out (run logs: week $wk and later, dates $cut and later; $aged older log(s) back to plain)"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    unseal) _keys_ok || { echo "DATA_SEAL_KEY not set" >&2; exit 2; }; unseal_file "$2" "$3" ;;
    seal) _keys_ok || { echo "DATA_SEAL_KEY not set" >&2; exit 2; }; seal_file "$2" "$3" ;;
    *) echo "usage: seal_data.sh seal|unseal <in> <out>" >&2; exit 2 ;;
  esac
fi
