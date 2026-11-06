"""TUDDY PREPLAY's inputs (2026-11-04). Donovan: "how come the football ... can't do the pregame simulators? hook that up."

Every real snap each offence ran and each defence allowed this season (thin early weeks filled from last season), plus
the league's special teams and 4th-down choices from the last three seasons, as compact JSON the site's simulator reads
(lib/nfl/preplay.js on the site; measured in claude/PREPLAY-TUDDY-MEASURED-2026-11-04.txt).

    python bots/nfl/nfl_preplay_pools.py --season 2026 --out public/data/current/nfl_preplay_pools_2026.json

Pools use every game played so far (the next week's games are the ones it simulates). nflverse play-by-play only:
nothing scraped, nothing invented.
"""
from __future__ import annotations
import argparse, json
import numpy as np
import pandas as pd

COLS = ['game_id','play_id','season','week','season_type','posteam','defteam','home_team','away_team','down','ydstogo','yardline_100','yards_gained',
        'touchdown','td_player_id','td_team','interception','fumble_lost','sack','play_type','qb_kneel','qb_spike','receiver_player_id',
        'receiver_player_name','rusher_player_id','rusher_player_name','passer_player_id','game_seconds_remaining','half_seconds_remaining','qtr',
        'field_goal_result','kick_distance','extra_point_result','punt_blocked','touchback','drive','fixed_drive_result','return_yards','safety',
        'kickoff_attempt','punt_attempt','field_goal_attempt','incomplete_pass','complete_pass','two_point_attempt','penalty','penalty_team',
        'penalty_yards','first_down_penalty','two_point_conv_result']
D: dict[int, pd.DataFrame] = {}


def load(seasons):
    import nflreadpy as nfl
    import polars as pl
    for y in seasons:
        d = nfl.load_pbp([y]).filter(pl.col("season_type") == "REG").select(COLS).to_pandas()
        d = d[d.week.notna()].sort_values(["game_id", "play_id"]).reset_index(drop=True)
        nxt = d.groupby("game_id").game_seconds_remaining.shift(-1)
        dur = (d.game_seconds_remaining - nxt).clip(lower=0)
        d["dur"] = dur.where((dur > 0) & (dur <= 50), np.nan)
        D[y] = d


def dist_b(t):
    t = int(t)
    return 0 if t <= 2 else 1 if t <= 6 else 2 if t <= 10 else 3
def snaps(d):
    # real snaps, plus the flags that wiped a snap out (a defensive flag moves the ball and can hand out a first down)
    flag = (d.play_type == 'no_play') & (d.penalty == 1) & d.penalty_yards.notna()
    s = d[(d.play_type.isin(['pass','run']) | flag) & (d.qb_kneel != 1) & (d.qb_spike != 1) & d.down.notna() & (d.two_point_attempt != 1)].copy()
    s = s[s.half_seconds_remaining > 120]   # no two-minute drill / kneel-downs: the engine has no clock management
    return s
def row(r):
    if r.play_type == 'no_play':
        y = int(r.penalty_yards) if r.penalty_team == r.defteam else -int(r.penalty_yards)
        return ['f', int(r.down), dist_b(r.ydstogo), int(r.yardline_100), y, 0, 0, 5, '', '', 1 if r.first_down_penalty == 1 else 0, '', 0]
    kind = 'k' if r.sack == 1 else ('p' if r.play_type == 'pass' else 'r')
    who = r.receiver_player_id if kind == 'p' else (r.rusher_player_id if kind == 'r' else None)
    name = r.receiver_player_name if kind == 'p' else (r.rusher_player_name if kind == 'r' else None)
    to = 1 if (r.interception == 1 or r.fumble_lost == 1) else 0
    td = 1 if (r.touchdown == 1 and r.td_team == r.posteam) else 0
    inc = 1 if r.incomplete_pass == 1 else 0
    dur = r.dur if r.dur == r.dur else (6 if inc else 32)
    who = '' if (who is None or pd.isna(who)) else who
    name = '' if (name is None or pd.isna(name)) else name
    g = 0 if pd.isna(r.yards_gained) else int(r.yards_gained)
    dtd = 1 if (to and r.touchdown == 1 and r.td_team == r.defteam) else 0   # returned for a touchdown
    return [kind, int(r.down), dist_b(r.ydstogo), int(r.yardline_100), g, td, to, int(round(dur)), who, name, inc, '', dtd]   # slot 11 (the source game) left empty in the published file: ~0.5 MB smaller

def pools(season, before_week, fill=260):
    cur = snaps(D[season][D[season].week < before_week])
    prev = snaps(D[season - 1]) if (season - 1) in D else cur.iloc[:0]
    out = {}
    teams = sorted(set(D[season].posteam.dropna()))
    for t in teams:
        o = cur[cur.posteam == t]; df = cur[cur.defteam == t]
        po = prev[prev.posteam == t]; pd_ = prev[prev.defteam == t]
        # thin early season: fill from last season's most recent snaps (rosters change; said in the caption)
        if len(o) < fill: o = pd.concat([po.tail(fill - len(o)), o])
        if len(df) < fill: df = pd.concat([pd_.tail(fill - len(df)), df])
        out[t] = {'off': [row(r) for r in o.itertuples()], 'def': [row(r) for r in df.itertuples()]}
    return out

def league(season=2026, before_week=99):
    parts = [D[y] for y in D if y < season] + [D[season][D[season].week < before_week]]
    L = pd.concat(parts).reset_index(drop=True)
    # field goals: make share by distance (5-yd buckets)
    fg = L[L.field_goal_attempt == 1]
    fgb = fg.assign(b=(fg.kick_distance // 5 * 5).clip(15, 65)).groupby('b').field_goal_result.apply(lambda s: round(float((s == 'made').mean()), 3)).to_dict()
    xp = L[L.extra_point_result.notna()]
    xp_rate = round(float((xp.extra_point_result == 'good').mean()), 3)
    # the two-point try (2026-11-06, the site's PREPLAY v2 goes for two at the standard margins late): the league's real rate
    # over the same seasons, every regular-season try
    tp = L[(L.two_point_attempt == 1) & L.two_point_conv_result.notna()]
    two_rate = round(float((tp.two_point_conv_result == 'success').mean()), 3) if len(tp) >= 100 else None
    # where the next drive starts after a kickoff / a punt (the receiving club's yards to go), real samples
    # the next SCRIMMAGE snap's spot and club (skips timeouts, penalties on the kick, end of quarter rows)
    scr = L.play_type.isin(['pass','run'])
    ny = L.yardline_100.where(scr); npos = L.posteam.where(scr)
    nxt = ny.groupby(L.game_id).shift(-1).groupby(L.game_id).bfill()
    nxt_pos = npos.groupby(L.game_id).shift(-1).groupby(L.game_id).bfill()
    ko = L[(L.kickoff_attempt == 1)].assign(n=nxt, np_=nxt_pos)
    ko = ko[ko.np_.notna() & (ko.np_ == ko.posteam) & ko.n.notna()]   # nflverse: a kickoff's posteam is the RECEIVING club
    # kickoff rules changed in 2024 and 2025: the newest season with enough kicks
    k26 = ko[ko.season == season] if (ko.season == season).sum() > 200 else ko[ko.season == ko.season.max() - (0 if (ko.season == ko.season.max()).sum() > 200 else 1)]
    pu = L[(L.punt_attempt == 1)].assign(n=nxt, np_=nxt_pos)
    pu = pu[pu.np_.notna() & (pu.np_ != pu.posteam) & pu.n.notna() & pu.yardline_100.notna()]
    punt = {int(b): [int(v) for v in g.n.tolist()] for b, g in pu.assign(b=(pu.yardline_100 // 10 * 10).clip(30, 90)).groupby('b')}
    # 4th down: what clubs really chose, by field position and yards to go (outside the last 2 minutes of a half)
    f4 = L[(L.down == 4) & (L.half_seconds_remaining > 120) & L.yardline_100.notna()]
    ch = np.where(f4.punt_attempt == 1, 'punt', np.where(f4.field_goal_attempt == 1, 'fg', np.where(f4.play_type.isin(['pass','run']), 'go', 'x')))
    f4 = f4.assign(ch=ch); f4 = f4[f4.ch != 'x']
    f4 = f4.assign(yb=(f4.yardline_100 // 10 * 10).clip(0, 90), tb=f4.ydstogo.apply(dist_b))
    fourth = {}
    for (yb, tb), g in f4.groupby(['yb','tb']):
        c = g.ch.value_counts(); n = int(c.sum())
        fourth[f'{int(yb)}|{int(tb)}'] = {k: round(float(c.get(k, 0)) / n, 3) for k in ('go','fg','punt')}
    return {'fg': {int(k): v for k, v in fgb.items()}, 'xp': xp_rate, **({'two': two_rate} if two_rate is not None else {}), 'kickoff': [int(v) for v in k26.n.tolist()], 'punt': punt, 'fourth': fourth}



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    load([a.season - 2, a.season - 1, a.season])
    w = int(D[a.season].week.max()) + 1        # every game played so far feeds the next week's sims
    out = {"season": a.season, "week": w, "version": "preplay-nfl-v1", "pools": pools(a.season, w), "league": league(a.season, w)}
    n = sum(len(v["off"]) for v in out["pools"].values())
    if len(out["pools"]) < 32 or n < 32 * 200:
        raise SystemExit(f"refusing to publish: {len(out['pools'])} clubs, {n} snaps")   # a thin feed fails loudly, never ships
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"), allow_nan=False)
    print(f"preplay pools: week {w}, {len(out['pools'])} clubs, {n} offensive snaps -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
