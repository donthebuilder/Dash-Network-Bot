#!/usr/bin/env python3
"""
slate_live.py -- which sports still have a game going tonight (2026-11-05).

    python bots/slate_live.py [--sports nba nhl nfl mlb] [--lead-hours 6]

Prints the sports (space-separated) that have a game IN PROGRESS, or one that STARTS within --lead-hours, on ESPN's scoreboard for the
Eastern date today and yesterday (a game that began at 10:30 PM ET is still yesterday's after midnight ET). Exit 0 when at least one, 1 when
none. Used by the evening loops (live-prices.yml, live-edge.yml) so they run to the last final whistle instead of a fixed 5.5 hours, and stop
at once on a night with nothing on.

FAILS OPEN: a sport whose scoreboard can't be read counts as live (losing a night's prices costs more than a few extra polls).
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ESPN = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl", "mlb": "baseball/mlb"}
ET = ZoneInfo("America/New_York")


def scoreboard(sport, day):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard?dates={day:%Y%m%d}&limit=200"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read()).get("events") or []


def live_or_soon(events, now, lead):
    """True when any event is in progress, or scheduled to start within `lead` of now. Pure."""
    for ev in events:
        state = (((ev.get("status") or {}).get("type") or {}).get("state") or "").lower()
        if state == "in":
            return True
        if state == "pre":
            try:
                start = datetime.fromisoformat(str(ev.get("date")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if now - timedelta(minutes=30) <= start <= now + lead:   # 30 min back: a late first pitch / delayed tip still counts
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", nargs="*", default=["nba", "nhl", "nfl", "mlb"])
    ap.add_argument("--lead-hours", type=float, default=6)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    out = []
    for s in a.sports:
        if s not in ESPN:
            continue
        try:
            events = scoreboard(s, today) + scoreboard(s, today - timedelta(days=1))
        except Exception as exc:  # fail open
            print(f"{s}: scoreboard unreadable ({type(exc).__name__}), counting it as live", file=sys.stderr)
            out.append(s)
            continue
        if live_or_soon(events, now, timedelta(hours=a.lead_hours)):
            out.append(s)
    print(" ".join(out))
    sys.exit(0 if out else 1)


if __name__ == "__main__":
    main()
