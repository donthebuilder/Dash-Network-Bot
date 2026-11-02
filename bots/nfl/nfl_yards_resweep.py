#!/usr/bin/env python3
"""nfl_yards_resweep.py -- were REC_YDS / RUSH_YDS re-tuned for their new bar?

THE QUESTION (Donovan, 2026-11-01: receiving yards 100+ and rushing yards
100+ "barely beating recent form"). nfl_backtest.py confirms it with real
data, both markets, at the Card's own depth (top 5/week):

    python nfl_backtest.py --season 2024 --topk 5
    python nfl_backtest.py --season 2025 --topk 5

    2024  Receiving yards  100+   model 17.8%  FORM 16.7%  vs FORM +1.1
          Rushing yards    100+   model 32.2%  FORM 36.7%  vs FORM -4.4  (flagged: NOT BEATING FORM)
    2025  Receiving yards  100+   model 21.1%  FORM 25.6%  vs FORM -4.4  (flagged)
          Rushing yards    100+   model 25.6%  FORM 27.8%  vs FORM -2.2  (flagged)

Both markets' bars moved from 40/50 to 100 on 2026-10-17 (nfl_scoring.py).
RUSH_YDS picked up oppr_rush_soft in that same change, swept "at the 100
bar" per its own comment. REC_YDS's weights (f_wopr .42, f_receiving_yards
.36, f_receiving_air_yards .12, implied_total .06, opp_pass_soft .04) carry
no such note -- nothing indicates they were ever re-swept for 100+ specifically,
as opposed to inherited from the 40-yard tune.

THE PROTOCOL, same as nfl_td_lab.py and the 2026-09-13 TD reweight: tune the
weight vector on one season, grade it on the OTHER, ship nothing that does
not improve the season it was not tuned on. No new features -- only the
components already in the live model (context must never select; this is
a reweight, not a redesign).

    python nfl_yards_resweep.py --market REC_YDS
    python nfl_yards_resweep.py --market RUSH_YDS
"""
from __future__ import annotations
import argparse
import random

import polars as pl

from nfl_features import build
from nfl_scoring import MODELS, OUTCOME, derive, _pctile

SEASONS = (2024, 2025)
TOPK = 5  # the Card's own depth per market (DASH-MASTER-INSTRUCTIONS: "5 calls per market")


def _components(market: str) -> list[str]:
    return [raw.lstrip("-") for raw in MODELS[market]["w"]]


def _score_with(d: pl.DataFrame, market: str, weights: dict[str, float]) -> pl.DataFrame:
    """Same arithmetic as nfl_scoring.score(), with a caller-supplied weight vector
    over the SAME components the live model already has a percentile column for."""
    parts = []
    for raw, wgt in weights.items():
        invert = raw.startswith("-")
        name = f"c_{raw.lstrip('-')}" + ("_inv" if invert else "")
        parts.append(pl.col(name) * wgt)
    total = parts[0]
    for p in parts[1:]:
        total = total + p
    return d.with_columns((total * 100).alias("score"))


def _prep(season: int, market: str) -> pl.DataFrame:
    tbl = build(season)
    m = MODELS[market]
    d = derive(tbl).filter(pl.col("position").is_in(m["pos"]))
    for raw in m["w"]:
        invert = raw.startswith("-")
        col = raw.lstrip("-")
        name = f"c_{col}" + ("_inv" if invert else "")
        d = d.with_columns(_pctile(d, col, invert).alias(name))
    d = d.with_columns(OUTCOME[market].alias("y"))
    return d.with_columns((pl.col("y") >= m["bar"]).cast(pl.Int8).alias("hit"))


def grade(d: pl.DataFrame, market: str, weights: dict[str, float], topk: int = TOPK):
    """(top-k hit%, FORM top-k hit%, n weeks) -- FORM proxy is the market's own trailing stat,
    the same column nfl_backtest.py uses."""
    from nfl_backtest import FORM_PROXY
    scored = _score_with(d, market, weights)
    weeks = sorted(scored["week"].unique().to_list())
    mp = mh = fp = fh = 0
    for w in weeks:
        live = scored.filter(pl.col("week") == w)
        if live.height == 0:
            continue
        sel = live.sort("score", descending=True).head(topk)
        mp += sel.height
        mh += int(sel["hit"].sum())
        fsel = live.sort(FORM_PROXY[market], descending=True).head(topk)
        fp += fsel.height
        fh += int(fsel["hit"].sum())
    return (100 * mh / max(1, mp), 100 * fh / max(1, fp), len(weeks))


def random_weights(comps: list[str], rng: random.Random) -> dict[str, float]:
    xs = [rng.random() + 0.05 for _ in comps]  # keep every term's floor above 0
    s = sum(xs)
    return dict(zip(comps, [x / s for x in xs]))


def sweep(market: str, n: int = 4000, seed: int = 13) -> None:
    comps = _components(market)
    rng = random.Random(seed)
    live = MODELS[market]["w"]
    data = {s: _prep(s, market) for s in SEASONS}

    print(f"\n{market} -- live weights: {live}")
    for tune_on in SEASONS:
        test_on = [s for s in SEASONS if s != tune_on][0]
        d_tune, d_test = data[tune_on], data[test_on]
        live_tune = grade(d_tune, market, live)
        live_test = grade(d_test, market, live)
        best = (live, live_tune[0] - live_tune[1])
        for _ in range(n):
            w = random_weights(comps, rng)
            mo, fo, _ = grade(d_tune, market, w)
            if mo - fo > best[1]:
                best = (w, mo - fo)
        cand_tune = grade(d_tune, market, best[0])
        cand_test = grade(d_test, market, best[0])
        print(f"\n  tuned on {tune_on}, graded on {test_on} (top {TOPK}/wk, n={live_tune[2]} weeks each):")
        print(f"    live weights   tune {live_tune[0]:.1f}% vs FORM {live_tune[1]:.1f}% ({live_tune[0]-live_tune[1]:+.1f})"
              f"  ->  test {live_test[0]:.1f}% vs FORM {live_test[1]:.1f}% ({live_test[0]-live_test[1]:+.1f})")
        print(f"    best candidate tune {cand_tune[0]:.1f}% vs FORM {cand_tune[1]:.1f}% ({cand_tune[0]-cand_tune[1]:+.1f})"
              f"  ->  test {cand_test[0]:.1f}% vs FORM {cand_test[1]:.1f}% ({cand_test[0]-cand_test[1]:+.1f})")
        print(f"    candidate weights: { {k: round(v, 3) for k, v in best[0].items()} }")
        ships = cand_test[0] - cand_test[1] > live_test[0] - live_test[1]
        print(f"    {'SHIPS -- beats live on the untuned season too' if ships else 'does NOT ship -- no better than live on the season it was not tuned on'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["REC_YDS", "RUSH_YDS"])
    ap.add_argument("--n", type=int, default=4000)
    args = ap.parse_args()
    sweep(args.market, n=args.n)
