"""spring_training.py -- SPRING TRAINING IS ITS OWN THING (2026-11-28, Donovan: "I don't want them to count as data, but we do need to keep track and let spring training be its own thing").

pybaseball's Statcast pulls ask Savant for game types R | PO | S (the URL it builds carries hfGT=R%7CPO%7CS%7C), so every spring-training pitch was inside the bot's "season"
numbers (barrel %, exit velocity, pitch mix, recent form) from SEASON_START = March 1 until opening day -- on a real batter 97 of 245 pitches between Feb 15 and Apr 5 were spring.
The MLB Stats API is not affected: its season / game-log stats default to the regular season (spring is gameType S, asked for by name).

THE RULE: a Savant frame loses its spring ('S') and exhibition ('E') rows before anything reads it. The postseason (F / D / L / W) stays, as before. The spring rows are not thrown away:
they are counted per player in a run-level record (SPRING) that write_record() saves as outputs/spring_training_<season>.json -- local only, never published, so a Spring page can be built from it
later without touching a single season number. No game_type column (an old cache, a changed feed) = the frame is returned as it came: this never empties a read.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

SPRING_TYPES = {"S", "E"}

# {"batter": {pid: {"pitches": n, "hr": n}}, "pitcher": {pid: {"pitches": n}}} -- this run's spring rows, by player
SPRING: Dict[str, Dict[str, Dict[str, int]]] = {"batter": {}, "pitcher": {}}


def split_spring(df) -> Tuple[Any, Any]:
    """(regular-season rows, spring rows). A frame with no `game_type` column (or no frame) comes back whole with no spring rows."""
    if df is None or not hasattr(df, "columns") or "game_type" not in df.columns or len(df) == 0:
        return df, None
    is_spring = df["game_type"].astype(str).str.upper().isin(SPRING_TYPES)
    if not bool(is_spring.any()):
        return df, None
    return df[~is_spring], df[is_spring]


def _note(kind: str, pid, spring) -> None:
    if spring is None or len(spring) == 0:
        return
    rec = SPRING[kind].setdefault(str(pid), {"pitches": 0} if kind == "pitcher" else {"pitches": 0, "hr": 0})
    rec["pitches"] = max(rec["pitches"], int(len(spring)))     # the same player is read more than once a run: the widest read wins, never a sum
    if kind == "batter" and "events" in spring.columns:
        rec["hr"] = max(rec["hr"], int((spring["events"].astype(str) == "home_run").sum()))


def regular_season_only(fn: Callable, kind: str) -> Callable:
    """Wrap pybaseball.statcast_batter / statcast_pitcher (start, end, player_id): same signature, spring rows removed, the spring rows noted."""
    def wrapped(start_dt=None, end_dt=None, player_id=None, *a, **k):
        df = fn(start_dt, end_dt, player_id, *a, **k)
        kept, spring = split_spring(df)
        _note(kind, player_id, spring)
        return kept
    wrapped.__name__ = getattr(fn, "__name__", kind)
    wrapped.__wrapped__ = fn
    return wrapped


def summary() -> Dict[str, Any]:
    return {"batters": len(SPRING["batter"]), "pitchers": len(SPRING["pitcher"]),
            "spring_pitches": sum(r["pitches"] for k in SPRING.values() for r in k.values())}


def write_record(path: Path, season: int) -> bool:
    """Merge this run's spring counts into outputs/spring_training_<season>.json (the larger count per player wins). False when there was nothing to write."""
    if not any(SPRING.values()):
        return False
    old: Dict[str, Any] = {}
    try:
        old = json.loads(Path(path).read_text())
    except Exception:
        old = {}
    out = {"season": season, "note": "spring-training pitches the season numbers leave out (bots/spring_training.py); local only", "batter": old.get("batter", {}), "pitcher": old.get("pitcher", {})}
    for kind in ("batter", "pitcher"):
        for pid, rec in SPRING[kind].items():
            cur = out[kind].get(pid, {})
            out[kind][pid] = {k: max(int(cur.get(k, 0)), int(v)) for k, v in rec.items()}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, indent=1, sort_keys=True))
    return True
