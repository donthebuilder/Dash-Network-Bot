#!/usr/bin/env python3
"""SLOT GATE (2026-11-05). One small check in front of the evening jobs.

1. CLOCK CHANGE. GitHub crons are UTC; our slots are Eastern-time moments
   ("6:52 pm ET, inside the 7 pm drop"). Each slot is listed twice in the
   workflow (EDT hour and EST hour, one hour apart) and --want names the ET
   times. A run whose own cron line maps to an ET time not in --want is the
   other season's twin and exits. Late runs keep their slot: the time comes
   from the cron line that started the run (github.event.schedule, or the
   `slot` input the Vercel restarter passes), never from the clock.
2. LATE RUNS. GitHub started Nov 3's 22:xx slots after 02:00Z, with every
   NHL game in progress, and the job saved in-game numbers as pregame.
   With --sports, a scheduled run skips when that ET day has games and
   every one of them has started. Fails open: an unreadable scoreboard
   runs the job.

A hand-started run (no slot) always goes.
Writes run=true|false to $GITHUB_OUTPUT.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ESPN = {
    "nhl": "hockey/nhl",
    "nba": "basketball/nba",
    "nfl": "football/nfl",
    "mlb": "baseball/mlb",
}


def slot_et(slot, now_utc):
    """ET 'HH:MM' of a single-hour, single-minute cron line, or None."""
    f = (slot or "").split()
    if len(f) != 5 or not f[0].isdigit() or not f[1].isdigit():
        return None
    off = now_utc.astimezone(ET).utcoffset()
    t = dt.datetime(2000, 1, 2, int(f[1]), int(f[0]), tzinfo=dt.timezone.utc) + off
    return t.strftime("%H:%M")


def games(sport, day):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard?dates={day:%Y%m%d}"
    with urllib.request.urlopen(url, timeout=15) as r:
        ev = (json.loads(r.read()) or {}).get("events") or []
    return [((e.get("status") or {}).get("type") or {}).get("state") for e in ev]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--want", default="", help="comma list of ET HH:MM slots this job is for")
    ap.add_argument("--sports", default="", help="comma list: skip when all of that ET day's games started")
    a = ap.parse_args()
    slot = (os.environ.get("SLOT") or "").strip()
    now = dt.datetime.now(dt.timezone.utc)
    run, why = True, "hand-started run"
    if slot:
        why = f"slot '{slot}'"
        want = [w.strip() for w in a.want.split(",") if w.strip()]
        et = slot_et(slot, now)
        if want and et and et not in want:
            run, why = False, f"slot '{slot}' is {et} ET today, not one of {want} (the other season's twin)"
        elif a.sports:
            day = now.astimezone(ET).date()
            states = []
            try:
                for s in [x.strip() for x in a.sports.split(",") if x.strip()]:
                    states += games(s, day)
                if states and all(st not in ("pre",) for st in states):
                    run, why = False, f"all {len(states)} games on {day} have started ({a.sports})"
                else:
                    why += f", {sum(st == 'pre' for st in states)} of {len(states)} games not started"
            except Exception as exc:  # fail open
                why += f", scoreboard unreadable ({type(exc).__name__}) -- running"
    print(f"slot gate: {'GO' if run else 'skip'} -- {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
