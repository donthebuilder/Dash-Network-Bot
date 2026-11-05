#!/usr/bin/env python3
"""
slot_covered.py -- has another run already done this schedule slot? (2026-11-05)

GitHub starts scheduled runs hours late (measured Nov 1-5: the 22:17 UTC odds slot ran ~02:25, the 12:20 report ~19:45) or not at all,
so the site's restarter (site lib/gh/dispatch.js) starts a dropped slot itself 10-25 min after it was due. GitHub's own late run
still arrives later. For a job that spends a paid quota (the odds fetches) that second run is waste: this tells it to stand down.

    python bots/slot_covered.py "<cron of this run>"       # in a workflow step, with GITHUB_TOKEN set (permissions: actions: read)

Writes covered=true|false to $GITHUB_OUTPUT (and prints the reason). covered=true when another run of the same workflow was CREATED
after this slot came due and before this run. No cron (a hand-started run), any API error, or nothing found -> false (the run goes ahead).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def _field(field, value, lo, hi):
    for part in field.split(","):
        rng, _, step = part.partition("/")
        step = int(step) if step else 1
        if rng == "*":
            a, b = lo, hi
        else:
            x, _, y = rng.partition("-")
            a = int(x)
            b = int(y) if y else (hi if step > 1 else a)
        if a <= value <= b and (value - a) % step == 0:
            return True
    return False


def fires(expr, d):
    """Does a 5-field UTC cron fire at minute d? Pure (no names, no L/W/#)."""
    f = expr.split()
    if len(f) != 5:
        return False
    mi, h, dom, mo, dow = f
    wd = (d.weekday() + 1) % 7                     # cron: Sunday = 0 (or 7)
    return (_field(mi, d.minute, 0, 59) and _field(h, d.hour, 0, 23) and _field(dom, d.day, 1, 31) and _field(mo, d.month, 1, 12)
            and (_field(dow, wd, 0, 7) or (wd == 0 and _field(dow, 7, 0, 7))))


def last_fire(expr, now, back_hours=24):
    """The latest minute <= now that `expr` fires, within back_hours; None if none. Pure."""
    t = now.replace(second=0, microsecond=0)
    for _ in range(back_hours * 60 + 1):
        if fires(expr, t):
            return t
        t -= timedelta(minutes=1)
    return None


def out(covered, why):
    print(f"slot covered: {covered} -- {why}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"covered={'true' if covered else 'false'}\n")


def main():
    cron = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not cron:
        return out(False, "no slot (hand-started run)")
    now = datetime.now(timezone.utc)
    slot = last_fire(cron, now)
    if slot is None:
        return out(False, f"no fire of '{cron}' in the last 24 h")
    try:
        repo = os.environ["GITHUB_REPOSITORY"]
        me = int(os.environ["GITHUB_RUN_ID"])
        wf = os.environ["GITHUB_WORKFLOW_REF"].split("@")[0].rsplit("/", 1)[-1]      # owner/repo/.github/workflows/x.yml@ref -> x.yml
        q = urllib.parse.quote(f">={(slot - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=20&created={q}",
                                     headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            runs = json.loads(r.read()).get("workflow_runs") or []
    except Exception as exc:  # never block a run on this check
        return out(False, f"check failed ({type(exc).__name__})")
    mine = next((r for r in runs if r.get("id") == me), None)
    my_created = (mine or {}).get("created_at") or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    earlier = [r for r in runs if r.get("id") != me and (r.get("created_at") or "") < my_created]
    if earlier:
        r = earlier[-1]
        return out(True, f"run {r.get('id')} ({r.get('event')}, {r.get('created_at')}) already did the {slot:%H:%M} UTC slot")
    return out(False, f"first run for the {slot:%H:%M} UTC slot")


if __name__ == "__main__":
    main()
