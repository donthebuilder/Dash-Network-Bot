"""L4 bot jobs cleanup (2026-11-09): the live runner's stop check, the live-price report's play times, game_sim's 4th positional.
Nothing here touches the network: curl is replaced by fixtures.
Run: PYTHONPATH=.:bots python3 tests/test_live_jobs_l4.py"""
import json, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bots"))
import live_edge as LE              # noqa: E402
import live_price_log as LP         # noqa: E402

# ---- 1. live_edge: the stop check -------------------------------------------------------------------------------
def ev(state, start):
    return {"id": start + state, "date": start, "status": {"type": {"state": state, "shortDetail": ""}, "period": 1, "clock": 0},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": "AAA", "displayName": "A A"}, "score": "0"},
                                              {"homeAway": "away", "team": {"abbreviation": "BBB", "displayName": "B B"}, "score": "0"}], "odds": []}]}

def boards(**by_sport):
    def fake(url):
        if "kalshi" in url:
            return {"markets": []}
        for sp, cfg in LE.SPORTS.items():
            if cfg["espn"] in url:
                v = by_sport.get(sp, [])
                return v if isinstance(v, dict) else {"events": v}
        return {}
    return fake

now = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)          # 10 pm ET
until = LE.cutoff_et(now)
assert until.astimezone(timezone.utc) == datetime(2026, 11, 10, 7, 30, tzinfo=timezone.utc), until   # 2:30 am EST

def check(**by_sport):
    LE.SCOREBOARD.clear(); LE.curl = boards(**by_sport); LE.once(0.04)
    return LE.nothing_left(until)

assert check(nba=[ev("post", "2026-11-10T00:00Z")], nhl=[ev("post", "2026-11-10T00:00Z")]), "all final -> done"
assert not check(nba=[ev("post", "2026-11-10T00:00Z"), ev("in", "2026-11-10T02:30Z")]), "a game in progress -> keep polling"
assert not check(nhl=[ev("pre", "2026-11-10T03:30Z")]), "a game still to start tonight -> keep polling"
assert not check(nba=[ev("pre", "2026-11-10T02:00Z")]), "a delayed game (pre, start passed) -> keep polling"
assert check(nfl=[ev("pre", "2026-11-13T01:15Z")], nba=[ev("post", "2026-11-10T00:00Z")]), "the week's NFL games after the cutoff do not hold the night open"
assert check(), "no games at all -> done"
assert not check(nba={}), "an unreadable scoreboard fails open"
LE.SCOREBOARD.clear()
assert not LE.nothing_left(until), "no pass yet -> keep polling"

# the loop: two idle passes in a row end it with DONE; without --stop-when-done it runs its minutes (the old behaviour)
with tempfile.TemporaryDirectory() as td:
    LE.curl = boards(nba=[ev("post", "2026-11-10T00:00Z")])
    LE.time.sleep = lambda s: None
    LE.cutoff_et = lambda now=None: until
    assert LE.loop(td, 0.002, 0, 0.04, stop_when_done=True) == LE.DONE
    assert (Path(td) / "_pre_margins.json").exists()
    assert not list(Path(td).glob("alerts_*.jsonl")), "no game in progress -> no alerts, same as before"
    t = LE.time.time()
    assert LE.loop(td, 0.002, 0, 0.04) == 0 and LE.time.time() - t >= 0.1

# ---- 2. live_price_log: NHL play times --------------------------------------------------------------------------
summ = {"plays": [
    {"scoringPlay": True, "participants": [{"athlete": {"displayName": "Skater One"}}], "wallclock": "2026-11-08T18:18:00Z", "modified": "2026-11-09T00:25Z"},
    {"scoringPlay": True, "participants": [{"athlete": {"displayName": "Skater Two"}}], "modified": "2026-11-09T00:25Z"},
]}
LP.curl = lambda url: summ
times = LP.event_times("nhl", "g1", {})
assert times["Skater One"] == ["2026-11-08T18:18:00Z"], times          # the play's own clock, not ESPN's edit time
assert times["Skater Two"] == ["2026-11-09T00:25:00Z"], times          # fallback: seconds before the Z (it was "...00:25Z:00Z" and crashed)
for v in times.values():
    LP.iso(v[0])

# ---- 3. game_sim: snapshot SPORT DAY DIR ------------------------------------------------------------------------
import game_sim as GS                # noqa: E402
seen = []
GS.snapshot = lambda sport, day, out_dir, sims=20000: seen.append((sport, day, out_dir))
sys.argv = ["game_sim.py", "snapshot", "nba", "2026-11-09", "/tmp/somewhere"]
GS.main()
assert seen == [("nba", "2026-11-09", "/tmp/somewhere")], seen
sys.argv = ["game_sim.py", "snapshot", "nhl", "2026-11-09"]
GS.main()
assert seen[-1] == ("nhl", "2026-11-09", "."), seen

print("test_live_jobs_l4: ok")
