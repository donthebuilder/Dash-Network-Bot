"""availability.py -- A MAN WHO IS NOT GOING TO PLAY IS NEVER CALLED (2026-11-27, Donovan).

ONE VOICE WITH THE SITE. The site (dash-network repo, lib/calledAvailability.js, lib/injuries/statuses.js,
lib/nfl/injury.js weekFileAvailability) and this bot must answer "may this man be called?" the same way, or the
two disagree on who is CALLED -- which is how Kenneth Walker III was a CALLED pick on 2026-11-26 while ESPN had him
OUT (the site locked him 19 minutes after the report listed him; this bot's nfl_game_calls.td_board only skipped
men on a bye and had even written "he was listed questionable at lock" into a call's reasoning).

THE RULE (identical on both sides; tests/fixtures/availability_cases.json is the SAME file in both repos and both
repos' tests run every case through their own code):

  OUT, IL (injured list / reserve / suspension / PUP / NFI), DOUBTFUL, on a bye   never CALLED, at any time.
  QUESTIONABLE, DAY-TO-DAY                                                         not CALLED before his game starts.
                                                                                   Once it has started he is not hidden (he may be
                                                                                   playing, and a man who played and hit still grades).
  a posted, confirmed lineup (MLB / NHL / NBA `lineup_in`)                         keeps a day-to-day / questionable man; never an OUT man.
  not listed / no report                                                           the rule adds nothing. A dead feed never empties a list.

It gates ELIGIBILITY only: no score, no rank, no published row is rewritten. A man left out is replaced by the
next healthy man (he is simply not a candidate); a board's ranks stay as they were.
"""
from __future__ import annotations

import datetime as dt
import re

# ── the two vocabularies ─────────────────────────────────────────────────────

# the NFL week file's own codes (bots/nfl/nfl_injuries.py STATUS_MAP and the site's lib/nfl/injury.js OUT_CODES)
NFL_OUT_CODES = {"OUT", "IR", "SUSP", "PUP", "NFI"}

# ESPN's raw words -> the closed set (the site's lib/injuries/statuses.js RAW, word for word). Anything else: None, never guessed.
_RAW = {
    "out": "OUT",
    "doubtful": "DOUBTFUL",
    "questionable": "QUESTIONABLE",
    "day to day": "DAY_TO_DAY",
    "injured reserve": "IL",
    "7 day il": "IL", "10 day il": "IL", "15 day il": "IL", "60 day il": "IL",
    "suspension": "IL", "suspended": "IL",
    "paternity": "OUT",
}
_ALWAYS = {"OUT", "IL", "DOUBTFUL"}      # lib/injuries/statuses.js BLOCKS


def _key(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str("" if s is None else s).lower()).strip()


def classify(raw) -> "str | None":
    """ESPN's raw status word -> OUT / DOUBTFUL / QUESTIONABLE / DAY_TO_DAY / IL, or None (Active, or a word we do not know)."""
    return _RAW.get(_key(raw))


# ── the rule ─────────────────────────────────────────────────────────────────

def blocks(status: "str | None", started: bool = False, lineup_in: bool = False) -> bool:
    """True when a man with this status (one of classify()'s) may NOT be called. The site's statusProblem, line for line."""
    if not status:
        return False
    if status in _ALWAYS:
        # a confirmed MLB lineup trumps a doubtful tag (lib/dash/namingChecks.js mlbNamingProblem); OUT and IL never
        return not (lineup_in and status == "DOUBTFUL")
    return not (started or lineup_in)         # QUESTIONABLE / DAY_TO_DAY: pregame only


def week_status(row: dict, started: bool = False) -> "str | None":
    """THE NFL WEEK FILE'S OWN WORDS (site: lib/nfl/injury.js weekFileAvailability).
    'out' (OUT / IR / SUSP / PUP / NFI, or on his bye) | 'doubtful' (D) | 'questionable' (Q, only before his game starts) | None."""
    if row.get("on_bye"):
        return "out"
    tag = str(row.get("injury_status") or ("Q" if row.get("questionable") else "")).strip().upper()
    if tag in NFL_OUT_CODES:
        return "out"
    if tag == "D":
        return "doubtful"
    if tag == "Q" and not started:
        return "questionable"
    return None


def unavailable(row: dict, started: bool = False) -> bool:
    """An NFL week-file row that may not be called / picked."""
    return week_status(row, started=started) is not None


def unavailable_espn(raw_status, started: bool = False, lineup_in: bool = False) -> bool:
    """A man carrying ESPN's raw word (MLB / NHL / NBA feeds: bots/injury_status.py `status`)."""
    return blocks(classify(raw_status), started=started, lineup_in=lineup_in)


# ── which games have started ─────────────────────────────────────────────────

def _ts(s) -> "dt.datetime | None":
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def started_teams(games: list, now: "dt.datetime | None" = None) -> set:
    """Clubs whose game has started (kickoff passed, or ESPN no longer says 'pre'). A club with no readable game is NOT started."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out: set = set()
    for g in games or []:
        if not isinstance(g, dict):
            continue
        ko = _ts(g.get("kickoff"))
        if (g.get("state") not in (None, "pre")) or (ko is not None and ko <= now):
            out.update(t for t in (g.get("home"), g.get("away")) if t)
    return out


# ── the boards: a man on ESPN's injury report (MLB / NHL / NBA) ──────────────

def report_block(name, team, injuries: list, started: bool = False, lineup_in: bool = False) -> "str | None":
    """ESPN's raw status word when this man (matched by his normalised name, and by club when the name is on the report for more than one club)
    may NOT be picked, called or ranked on a board under THE RULE; None when he may. `injuries` are bots/injury_status.py fetch() rows.
    No report (a dead feed, an empty list) = None, always: the rule never empties a board."""
    if not injuries:
        return None
    from injury_status import key as _key           # one normaliser for both sides
    k = _key(name or "")
    hits = [r for r in injuries if r.get("key") == k]
    if len(hits) > 1:
        hits = [r for r in hits if r.get("team") == str(team or "")]
    for r in hits:
        if unavailable_espn(r.get("status"), started=started, lineup_in=lineup_in):
            return r.get("status")
    return None


def started_at(start_utc, now: "dt.datetime | None" = None) -> bool:
    """True when a game's start time has passed. An unreadable time is NOT started (the safe side of a pregame rule)."""
    t = _ts(start_utc)
    return t is not None and t <= (now or dt.datetime.now(dt.timezone.utc))


# ── MLB: the role map's candidates (2026-11-27) ──────────────────────────────

def mlb_unavailable(hitter, injuries: list, now: "dt.datetime | None" = None) -> bool:
    """True when this HitterRecord-like man (name, team, game_time, lineup_confirmed) may not be a TOP / HR / HIT / HRR / CONTACT pick."""
    return report_block(getattr(hitter, "name", ""), getattr(hitter, "team", ""), injuries,
                        started=started_at(getattr(hitter, "game_time", ""), now),
                        lineup_in=bool(getattr(hitter, "lineup_confirmed", False))) is not None


def playable_hitters(hitters: list, injuries: list, now: "dt.datetime | None" = None) -> list:
    """The hitters left once the unavailable men are out. Never pads, never reorders; a game with nobody left returns []."""
    return [h for h in hitters if not mlb_unavailable(h, injuries, now)]
