"""TUDDY'S TD BOARD AT THE LOCK, GRADED -> Supabase nfl_td_log (2026-11-03).

Donovan: "I don't know why we haven't been treating it just like NHL, with how we're tracking each called pick for each game,
so we could do the research like we did." LAMP stores every rated skater per game (lamp_goal_log); TUDDY only kept the two CALLED
picks per game, as JSON on the data branch. This writes the NFL twin: one row per rated player per game, at the lock, graded.

THE LOCK: the last archived nfl_prediction_log run (mode week) generated before HIS game's kickoff (nflverse schedule, ET -> UTC).
  Runs are ordered by their own generated_at, not by file name: a week's file names carry only the time of day.
RANK: every player with a TD score in that run, score desc then name (the order lib/nfl/tdFeed.js boardRankFor() uses).
STATUS: called = one of the bot's graded game calls (nfl_game_calls_graded_<season>_wNN.json, role TOP/TD) · on_board = top third of
  that run's board · not_on_board = everyone else.
GRADE: rushing + receiving TDs from nflverse play-by-play. dressed = he played offensive snaps; not dressed -> hit null (void).
Only games that are final in play-by-play are written. Rows are INSERTED, never updated: a graded row is never rewritten
(Prefer: resolution=ignore-duplicates). A new model is a new model_version, so it gets its own rows.

Usage (bot repo root, data branch fetched: git fetch origin data):
    python bots/nfl/nfl_td_log.py --season 2026                    # dry run: builds, checks against the bot's own grades, prints
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python bots/nfl/nfl_td_log.py --season 2026 --apply
Undo: delete from nfl_td_log where source = 'nfl_td_log.py';
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SOURCE = "nfl_td_log.py"
FIX_TEAM = {"LAR": "LA", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA", "WSH": "WAS"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def data_files(prefix: str) -> list[str]:
    out = []
    for line in git("ls-tree", "--name-only", "origin/data", "public/data/current/").splitlines():
        n = line.rsplit("/", 1)[-1]
        if n.startswith(prefix):
            out.append(n)
    return sorted(out)


def show(name: str) -> str:
    return git("show", f"origin/data:public/data/current/{name}")


def runs(season: int) -> list[dict]:
    """Every weekly run's TD board: [{run_id, week, generated_at, board:[rows ranked]}]."""
    out = []
    for n in data_files(f"nfl_prediction_log_{season}-wk"):
        if not n.endswith(".jsonl"):
            continue
        lines = show(n).splitlines()
        if not lines:
            continue
        head = json.loads(lines[0])
        if head.get("mode") != "week" or head.get("season") != season:
            continue
        td = []
        for line in lines[1:]:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("market") == "TD" and isinstance(r.get("score"), (int, float)):
                td.append(r)
        td.sort(key=lambda x: (-x["score"], x.get("player") or ""))
        out.append({"run_id": head["run_id"], "week": int(head["week"]), "file": n,
                    "generated_at": dt.datetime.fromisoformat(head["generated_at"].replace("Z", "+00:00")), "board": td})
    out.sort(key=lambda r: r["generated_at"])
    return out


def calls(season: int) -> dict[tuple[int, str], dict]:
    out = {}
    for n in data_files(f"nfl_game_calls_graded_{season}_w"):
        d = json.loads(show(n))
        for g in d.get("games", []):
            for c in g.get("calls", []):
                out[(int(d["week"]), c["player_id"])] = {"role": c.get("role"), "espn_game_id": str(g.get("game_id")),
                                                        "bot_result": c.get("result")}
    return out


def nflverse(season: int):
    import nflreadpy as nfl
    import polars as pl
    sch = nfl.load_schedules().filter((pl.col("season") == season) & (pl.col("game_type") == "REG"))
    games = []
    for r in sch.iter_rows(named=True):
        if not r["gameday"] or not r["gametime"]:
            continue
        ko = dt.datetime.strptime(f"{r['gameday']} {r['gametime']}", "%Y-%m-%d %H:%M").replace(tzinfo=ET).astimezone(dt.timezone.utc)
        games.append({"game_id": r["game_id"], "week": int(r["week"]), "date": r["gameday"], "kick": ko,
                      "home": FIX_TEAM.get(r["home_team"], r["home_team"]), "away": FIX_TEAM.get(r["away_team"], r["away_team"])})
    pbp = nfl.load_pbp([season]).filter((pl.col("season_type") == "REG") & (pl.col("two_point_attempt") != 1))
    final = set(pbp.get_column("game_id").unique().to_list())
    tds: dict[tuple[str, str], int] = {}
    for r in pbp.filter(pl.col("td_player_id").is_not_null()).select(
            ["game_id", "play_type", "td_player_id", "rusher_player_id", "receiver_player_id"]).iter_rows(named=True):
        scorer = r["td_player_id"]
        if (r["play_type"] == "run" and scorer == r["rusher_player_id"]) or (r["play_type"] == "pass" and scorer == r["receiver_player_id"]):
            tds[(r["game_id"], scorer)] = tds.get((r["game_id"], scorer), 0) + 1
    pfr = {r["pfr_id"]: r["gsis_id"] for r in nfl.load_players().select(["pfr_id", "gsis_id"]).iter_rows(named=True) if r["pfr_id"] and r["gsis_id"]}
    played = set()
    for r in nfl.load_snap_counts([season]).filter((pl.col("game_type") == "REG") & (pl.col("offense_snaps") > 0)).select(
            ["game_id", "pfr_player_id"]).iter_rows(named=True):
        g = pfr.get(r["pfr_player_id"])
        if g:
            played.add((r["game_id"], g))
    return games, final, tds, played


def build(season: int) -> tuple[list[dict], dict]:
    R = runs(season)
    C = calls(season)
    games, final, tds, played = nflverse(season)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows, check = [], {"called": 0, "agree": 0, "disagree": []}
    for g in games:
        if g["game_id"] not in final:
            continue
        lock = [r for r in R if r["week"] == g["week"] and r["generated_at"] < g["kick"]]
        if not lock:
            continue
        run = lock[-1]
        n = len(run["board"])
        team_rank: dict[str, int] = {}
        for i, p in enumerate(run["board"]):
            team = FIX_TEAM.get(p.get("team"), p.get("team"))
            if team not in (g["home"], g["away"]):
                continue
            team_rank[team] = team_rank.get(team, 0) + 1
            pid = p["player_id"]
            c = C.get((g["week"], pid))
            status = "called" if c else ("on_board" if i + 1 <= n / 3 else "not_on_board")
            dressed = (g["game_id"], pid) in played
            t = tds.get((g["game_id"], pid), 0)
            hit = (t > 0) if dressed else None
            if c:
                check["called"] += 1
                if c["bot_result"] == "void" or (c["bot_result"] == "hit") == bool(hit):
                    check["agree"] += 1
                else:
                    check["disagree"].append((g["week"], p.get("player"), c["bot_result"], hit))
            rows.append({
                "game_id": g["game_id"], "player_id": pid, "model_version": p.get("model_version") or "nfl_td_v2",
                "season": season, "week": g["week"], "game_date": g["date"], "start_utc": g["kick"].isoformat(),
                "espn_game_id": c["espn_game_id"] if c else None,
                "team": team, "opp": g["away"] if team == g["home"] else g["home"], "home": team == g["home"],
                "name": p.get("player"), "pos": p.get("position"), "score": p["score"], "pct": p.get("components"),
                "rank_in_team": team_rank[team], "slate_rank": i + 1, "slate_n": n,
                "status": status, "role": c["role"] if c else None, "questionable": bool(p.get("questionable")),
                "run_id": run["run_id"], "locked_at": run["generated_at"].isoformat(),
                "dressed": dressed, "tds": t, "hit": hit, "graded_at": now, "source": SOURCE,
            })
    return rows, check


def insert(rows: list[dict], url: str, key: str) -> None:
    import urllib.request
    for i in range(0, len(rows), 500):
        req = urllib.request.Request(f"{url}/rest/v1/nfl_td_log?on_conflict=game_id,player_id,model_version", method="POST",
                                     data=json.dumps(rows[i:i + 500]).encode())
        for k, v in {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Prefer": "resolution=ignore-duplicates,return=minimal"}.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        print(f"  inserted (or kept existing) rows {i + 1}-{min(i + 500, len(rows))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", help="also write the rows to this .jsonl file")
    a = ap.parse_args()
    rows, check = build(a.season)
    by = {}
    for r in rows:
        if r["hit"] is None:
            continue
        s = by.setdefault(r["status"], [0, 0])
        s[0] += 1
        s[1] += int(r["hit"])
    print(f"{len(rows)} rows, {len({r['game_id'] for r in rows})} games")
    for k, (n, h) in sorted(by.items()):
        print(f"  {k:13s} {h}/{n} = {100 * h / n:.1f}%")
    print(f"check vs the bot's own grade: {check['agree']}/{check['called']} CALLED rows agree; disagree: {check['disagree'][:10]}")
    if check["disagree"]:
        print("REFUSING to write: the grade disagrees with the bot's graded calls", file=sys.stderr)
        return 1
    if a.out:
        with open(a.out, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    if a.apply:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing", file=sys.stderr)
            return 2
        insert(rows, url, key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
