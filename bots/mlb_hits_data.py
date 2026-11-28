#!/usr/bin/env python3
"""
mlb_hits_data.py -- the full-slate data for the MLB hit / H+R+RBI / total-bases models. Pulls once into CACHE_DIR.

    python bots/mlb_hits_data.py CACHE_DIR

  games.json       {gamePk: {date, venue, home_team, away_team, home_lineup[9 ids in batting order], away_lineup[...], home_sp, away_sp}}   2024 through the current regular season, grown a day at a time (see INCREMENTAL below)
  hit_<season>_<pid>.json   each hitter's game log: date, pk, home, pa, ab, h, r, rbi, tb, bb, k, hr, 2b, 3b
  pit_<season>_<pid>.json   each pitcher's game log: date, pk, started, outs, h, bf, k, bb, hr, er
  people_<season>.json      id, name, bat side, pitch hand
"""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

# INCREMENTAL (2026-11-28, MLB opening-day readiness). This used to be a one-time pull: games.json was skipped once it existed, the spans ended 2026-09-27, the seasons were
# (2024, 2025, 2026), and the workflow cache key was dash-mlbhits-2026 -- so the live hit-lane board would have scored 2027 from end-of-2026 form all year, with no 2027 game and
# no 2027 rookie in it. Now: a finished season is pulled once and never touched; the CURRENT season grows a day at a time (the last two days are re-read, a late finish lands);
# the game logs of the players in the newly added games are re-pulled and nobody else's; the player list of the current season is refreshed weekly. Out of season it is a no-op.
FIRST_SEASON = 2024
SEASON_OPENS = (3, 15)       # no regular-season game before this in any year the bot covers (2024: Mar 20, 2025: Mar 18, 2026: Mar 25)
SEASON_SWEPT = (11, 5)       # after this the season is over and its schedule is not asked again (the World Series ends first week of November at the latest)
PEOPLE_MAX_AGE_DAYS = 7


def seasons(today=None):
    """The seasons the cache covers: FIRST_SEASON through this one, once the calendar is past the earliest opening day (Jan-Mar 14 is still last season's cache)."""
    today = today or date.today()
    last = today.year if (today.month, today.day) >= SEASON_OPENS else today.year - 1
    return list(range(FIRST_SEASON, last + 1))


def jget(url):
    return json.loads(subprocess.run(["curl", "-s", "-m", "60", "--retry", "2", url], capture_output=True, text=True).stdout)


def schedule(c, today=None, get=None):
    """Grow games.json. Returns the set of gamePks added or changed this run (the players in them are the ones whose logs need a re-pull)."""
    get = get or jget
    today = today or date.today()
    out = Path(c) / "games.json"
    games = json.loads(out.read_text()) if out.exists() else {}
    by_season = {}
    for pk, g in games.items():
        by_season.setdefault(int(g["date"][:4]), []).append(g["date"])
    days = []
    for season in seasons(today):
        have = by_season.get(season, [])
        if season < today.year or (today.month, today.day) > SEASON_SWEPT:
            if have:
                continue                                  # a finished season is pulled once, never again
            a, b = date(season, *SEASON_OPENS), date(season, *SEASON_SWEPT)   # an empty cache (or a season never pulled): the whole season
        else:
            a = (date.fromisoformat(max(have)) - timedelta(days=1)) if have else date(season, *SEASON_OPENS)
            b = min(today - timedelta(days=1), date(season, *SEASON_SWEPT))
        days += [(a + timedelta(i)).isoformat() for i in range((b - a).days + 1)]
    changed = set()

    def one(day):
        res = {}
        j = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day}&hydrate=lineups,probablePitcher")
        for dd in j.get("dates", []):
            for g in dd["games"]:
                if g.get("gameType") != "R" or g["status"]["abstractGameState"] != "Final":
                    continue
                lu = g.get("lineups") or {}
                t = g["teams"]
                res[str(g["gamePk"])] = {"date": day, "venue": (g.get("venue") or {}).get("id"), "home_team": t["home"]["team"]["id"], "away_team": t["away"]["team"]["id"],
                                         "home_lineup": [p["id"] for p in lu.get("homePlayers", [])], "away_lineup": [p["id"] for p in lu.get("awayPlayers", [])],
                                         "home_sp": (t["home"].get("probablePitcher") or {}).get("id"), "away_sp": (t["away"].get("probablePitcher") or {}).get("id")}
        return res
    if days:
        with ThreadPoolExecutor(12) as ex:
            for r in ex.map(one, days):
                for pk, g in r.items():
                    if games.get(pk) != g:
                        changed.add(pk)
                games.update(r)
        out.write_text(json.dumps(games))
    print(f"schedule: {len(days)} days read, {len(changed)} games new or changed, {len(games)} in the cache, {sum(1 for g in games.values() if len(g['home_lineup']) == 9 and len(g['away_lineup']) == 9)} with both lineups, "
          f"{sum(1 for g in games.values() if g['home_sp'] and g['away_sp'])} with both starters")
    return changed


def people(c, season, today=None):
    f = Path(c) / f"people_{season}.json"
    today = today or date.today()
    stale = season == today.year and f.exists() and (time.time() - f.stat().st_mtime) > PEOPLE_MAX_AGE_DAYS * 86400   # this year's player list gains rookies
    if not f.exists() or stale:
        ps = jget(f"https://statsapi.mlb.com/api/v1/sports/1/players?season={season}")["people"]
        f.write_text(json.dumps([{"id": p["id"], "name": p.get("fullName"), "bats": (p.get("batSide") or {}).get("code"), "throws": (p.get("pitchHand") or {}).get("code"),
                                  "pos": (p.get("primaryPosition") or {}).get("abbreviation")} for p in ps]))
    return json.load(open(f))


def logs(c, changed=None, today=None):
    """Pull the game logs. A log file that exists is kept -- except the logs of players in `changed` games (this run's new games), which are re-pulled so they hold the new game."""
    c = Path(c)
    changed = changed or set()
    games = json.load(open(c / "games.json"))
    redo = set()
    for pk in changed:
        g = games.get(str(pk))
        if g:
            redo.update(g["home_lineup"]); redo.update(g["away_lineup"])
            redo.update(x for x in (g["home_sp"], g["away_sp"]) if x)
    for season in seasons(today):
        ps = people(c, season, today)
        lineup_ids = set()
        sp_ids = set()
        for g in games.values():
            if g["date"].startswith(str(season)):
                lineup_ids.update(g["home_lineup"]); lineup_ids.update(g["away_lineup"])
                for k in ("home_sp", "away_sp"):
                    if g[k]:
                        sp_ids.add(g[k])

        def hit(pid):
            f = c / f"hit_{season}_{pid}.json"
            if f.exists() and not (season == (today or date.today()).year and pid in redo):
                return
            try:
                sp = jget(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&group=hitting&season={season}")["stats"][0]["splits"]
            except Exception:
                sp = []
            f.write_text(json.dumps([{"date": x["date"], "pk": (x.get("game") or {}).get("gamePk"), "home": bool(x.get("isHome")), "pa": x["stat"].get("plateAppearances", 0),
                                      "ab": x["stat"].get("atBats", 0), "h": x["stat"].get("hits", 0), "r": x["stat"].get("runs", 0), "rbi": x["stat"].get("rbi", 0),
                                      "tb": x["stat"].get("totalBases", 0), "bb": x["stat"].get("baseOnBalls", 0), "k": x["stat"].get("strikeOuts", 0),
                                      "hr": x["stat"].get("homeRuns", 0)} for x in sp]))

        def pit(pid):
            f = c / f"pit_{season}_{pid}.json"
            if f.exists() and not (season == (today or date.today()).year and pid in redo):
                return
            try:
                sp = jget(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&group=pitching&season={season}")["stats"][0]["splits"]
            except Exception:
                sp = []
            f.write_text(json.dumps([{"date": x["date"], "pk": (x.get("game") or {}).get("gamePk"), "started": x["stat"].get("gamesStarted", 0), "outs": x["stat"].get("outs", 0),
                                      "h": x["stat"].get("hits", 0), "bf": x["stat"].get("battersFaced", 0), "k": x["stat"].get("strikeOuts", 0), "bb": x["stat"].get("baseOnBalls", 0),
                                      "hr": x["stat"].get("homeRuns", 0), "er": x["stat"].get("earnedRuns", 0)} for x in sp]))
        with ThreadPoolExecutor(12) as ex:
            list(ex.map(hit, sorted(lineup_ids)))
            list(ex.map(pit, sorted(sp_ids)))
        print(f"{season}: {len(lineup_ids)} lineup hitters, {len(sp_ids)} starters")


if __name__ == "__main__":
    c = sys.argv[1]
    Path(c).mkdir(parents=True, exist_ok=True)
    changed = schedule(c)
    logs(c, changed)
    print("done")
