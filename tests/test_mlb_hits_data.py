"""The MLB hit-lane cache grows a day at a time (2026-11-28, bots/mlb_hits_data.py). TEST data only: a fake StatsAPI, a temp cache. No network.
Run: python3 tests/test_mlb_hits_data.py (or pytest)."""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))
import mlb_hits_data as D  # noqa: E402


def game(day, hp=(1, 2), sp=(11, 12)):
    return {"date": day, "venue": 5, "home_team": 100, "away_team": 200, "home_lineup": list(range(1, 10)), "away_lineup": list(range(21, 30)), "home_sp": sp[0], "away_sp": sp[1]}


def fake_get(requested, finals=None):
    finals = finals or {}

    def get(url):
        if "schedule?sportId=1&date=" in url:
            day = url.split("date=")[1].split("&")[0]
            requested.append(day)
            gs = [{"gamePk": pk, "gameType": "R", "status": {"abstractGameState": "Final"}, "venue": {"id": 5}, "lineups": {"homePlayers": [{"id": i} for i in range(1, 10)], "awayPlayers": [{"id": i} for i in range(21, 30)]},
                   "teams": {"home": {"team": {"id": 100}, "probablePitcher": {"id": 11}}, "away": {"team": {"id": 200}, "probablePitcher": {"id": 12}}}} for pk in finals.get(day, [])]
            return {"dates": [{"games": gs}] if gs else []}
        raise AssertionError(f"unexpected url {url}")
    return get


def test_seasons_turn_over_at_the_earliest_opening_day():
    assert D.seasons(date(2027, 1, 10)) == [2024, 2025, 2026]
    assert D.seasons(date(2027, 3, 14)) == [2024, 2025, 2026]
    assert D.seasons(date(2027, 3, 15)) == [2024, 2025, 2026, 2027]
    assert D.seasons(date(2026, 11, 28)) == [2024, 2025, 2026]


def test_in_season_it_reads_only_the_new_days_and_the_two_before_them(tmp_path):
    games = {"1": game("2024-09-29"), "2": game("2025-09-28"), "3": game("2026-09-27"), "4": game("2027-04-08")}
    (tmp_path / "games.json").write_text(json.dumps(games))
    req = []
    changed = D.schedule(tmp_path, today=date(2027, 4, 10), get=fake_get(req, {"2027-04-09": [5], "2027-04-08": [4]}))
    assert sorted(req) == ["2027-04-07", "2027-04-08", "2027-04-09"], req      # the last game's day minus one, through yesterday; no finished season is touched
    assert changed == {"5"}                                                     # the re-read of 04-08 returned the same game: not "changed"
    assert set(json.loads((tmp_path / "games.json").read_text())) == {"1", "2", "3", "4", "5"}


def test_out_of_season_it_reads_nothing(tmp_path):
    (tmp_path / "games.json").write_text(json.dumps({"1": game("2024-09-29"), "2": game("2025-09-28"), "3": game("2026-09-27")}))
    req = []
    assert D.schedule(tmp_path, today=date(2026, 11, 28), get=fake_get(req)) == set() and req == []
    assert D.schedule(tmp_path, today=date(2027, 2, 20), get=fake_get(req)) == set() and req == []


def test_a_fresh_cache_in_season_pulls_every_finished_season_once_and_this_one_to_yesterday(tmp_path):
    req = []
    D.schedule(tmp_path, today=date(2027, 3, 20), get=fake_get(req))
    years = {d[:4] for d in req}
    assert years == {"2024", "2025", "2026", "2027"}
    assert max(d for d in req if d.startswith("2027")) == "2027-03-19" and min(d for d in req if d.startswith("2027")) == "2027-03-15"


def test_new_games_re_pull_only_their_players_this_season(tmp_path, monkeypatch=None):
    (tmp_path / "games.json").write_text(json.dumps({"5": game("2027-04-09")}))
    for f in ("hit_2027_1.json", "hit_2026_1.json", "hit_2027_40.json", "pit_2027_11.json"):
        (tmp_path / f).write_text("[]")
    for s in D.seasons(date(2027, 4, 10)):
        (tmp_path / f"people_{s}.json").write_text("[]")
    pulled = []
    real = D.jget

    def fake(url):
        pulled.append(url)
        return {"stats": [{"splits": []}]}
    D.jget = fake
    try:
        D.logs(tmp_path, changed={"5"}, today=date(2027, 4, 10))
    finally:
        D.jget = real
    mine = [u for u in pulled if "/people/" in u and "/stats?" in u]
    ids = {int(u.split("/people/")[1].split("/")[0]) for u in mine}
    assert 1 in ids and 11 in ids and 21 in ids                                # the players of the new game are re-pulled
    assert 40 not in ids                                                       # a player not in it is not
    assert not any("season=2026" in u and "/people/1/" in u for u in mine)    # a finished season's log is never re-pulled once it exists


def test_the_loader_reads_every_season_on_disk():
    src = (Path(__file__).resolve().parent.parent / "bots" / "mlb_hits_study.py").read_text()
    assert 'glob("people_*.json")' in src and "(2024, 2025, 2026)" not in src.split("def load")[1].split("class Series")[0]


if __name__ == "__main__":
    import tempfile
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            params = v.__code__.co_varnames[:v.__code__.co_argcount]
            v(Path(tempfile.mkdtemp())) if "tmp_path" in params else v()
            n += 1
    print(f"{n}/{n} checks passed")
