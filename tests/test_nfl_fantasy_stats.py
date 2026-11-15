"""nfl_fantasy_stats.parse_game against a REAL Week 1 summary (TB@CIN,
2026-09-13, ESPN event 401872925, trimmed to the keys the parser reads).

Run: python3 tests/test_nfl_fantasy_stats.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bots" / "nfl"))
import nfl_fantasy_stats as fs  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "espn_summary_401872925_tb_cin_2026w1.json"


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    summary = json.loads(FIX.read_text())
    players, defense, notes = fs.parse_game(summary, "CIN", "TB", 33, 27)
    by_name = {v["_name"]: v for v in players.values()}

    # Baker Mayfield: 23/28 216 0 TD 0 INT, 3 fumbles lost, 9-yd rushing TD.
    bm = by_name["Baker Mayfield"]
    check(bm["passing_yards"] == 216 and bm["passing_touchdowns"] == 0 and bm["interceptions"] == 0, bm)
    check(bm["fumbles_lost"] == 3, bm)
    check(bm["rushing_touchdowns"] == 1, bm)

    # Bucky Irving: 8-45-1 rushing.
    bi = by_name["Bucky Irving"]
    check(bi["rushing_yards"] == 45 and bi["rushing_touchdowns"] == 1, bi)

    # Emeka Egbuka: 5-63-0 receiving.
    ee = by_name["Emeka Egbuka"]
    check(ee["receptions"] == 5 and ee["receiving_yards"] == 63, ee)

    # Kickers, placed by distance off scoringPlays: McLaughlin 34 + 51,
    # McPherson 20, 55, 58, 32. XP from the box (3/3, 3/3).
    cm = by_name["Chase McLaughlin"]
    check((cm["field_goals_0_39"], cm["field_goals_40_49"], cm["field_goals_50_plus"]) == (1, 0, 1), cm)
    check(cm["extra_points"] == 3, cm)
    em = by_name["Evan McPherson"]
    check((em["field_goals_0_39"], em["field_goals_40_49"], em["field_goals_50_plus"]) == (2, 0, 2), em)
    check(not [n for n in notes if "FG" in n], notes)

    # D/ST. TB's INT-return TD (Trotter) is a defensive TD for TB; CIN's
    # fumble-return TD (Knight) is one for CIN. Fumble recoveries are the
    # opponent's fumbles lost: TB lost 4 -> CIN recovered 4.
    check(defense["TB"]["points_allowed"] == 33 and defense["CIN"]["points_allowed"] == 27, defense)
    check(defense["TB"]["def_touchdowns"] == 1 and defense["CIN"]["def_touchdowns"] == 1, defense)
    check(defense["CIN"]["def_fumble_recoveries"] == 4, defense)
    check(defense["TB"]["def_interceptions"] >= 1, defense)

    # Every emitted key is one the site's fantasy_points_for_stats reads.
    for row in players.values():
        for k in fs.PLAYER_KEYS:
            check(isinstance(row[k], float), (k, row))

    # A scheduled game contributes nothing (build() skips it; parse_game on
    # an empty summary must not invent a line either).
    p2, d2, _ = fs.parse_game({}, "A", "B", 0, 0)
    check(p2 == {}, p2)
    check(d2["A"]["def_sacks"] == 0 and d2["A"]["points_allowed"] == 0, d2)

    print(f"ok  {len(players)} lines parsed, {len(notes)} note(s)")


def test_week_file():
    """THE WEEK FILE only gains (TEST data: made-up ids and lines)."""
    def g(gid, done):
        return {"game_id": gid, "week": 8, "home": "AAA", "away": "BBB", "home_score": 1, "away_score": 2,
                "state": "post" if done else "pre", "completed": done}
    base = {"season": 2026, "week": 8, "built_at": "t1", "source": "espn"}
    # Sunday: the Sunday game is final, Monday's has not started; the slate still lists the Monday clubs
    sunday = {**base, "games": [g("1", True), g("2", False)], "players": {"p-sun": {"receptions": 3}},
              "defense": {"AAA": {"def_sacks": 1}}, "player_game": {"p-sun": "1"}, "xw": {"e-sun": "p-sun", "e-mon": "p-mon"}}
    one = fs.merge_week(None, sunday)
    check(one["closed"] is False and one["counts"]["final_games"] == 1, one["counts"])
    # a later run: Monday's game is final, but this run's slate has moved on and no longer joins the Sunday man
    later = {**base, "built_at": "t2", "games": [g("1", True), g("2", True)], "players": {"p-mon": {"receptions": 7}},
             "defense": {"CCC": {"def_sacks": 2}}, "player_game": {"p-mon": "2"}, "xw": {"e-mon": "p-mon"}}
    two = fs.merge_week(one, later)
    check(two["closed"] is True, "every game final closes the week")
    check(two["players"] == {"p-sun": {"receptions": 3}, "p-mon": {"receptions": 7}}, "a line already joined is never lost")
    check(two["player_game"] == {"p-sun": "1", "p-mon": "2"} and two["xw"]["e-sun"] == "p-sun", "its game and its id stay too")
    check(set(two["defense"]) == {"AAA", "CCC"}, two["defense"])
    # a final game is never taken back; a copy of another week is ignored
    back = fs.merge_week(two, {**base, "built_at": "t3", "games": [g("1", True), g("2", False)], "players": {}, "defense": {}})
    check(back["closed"] is True, "a game the file has as final stays final")
    other = fs.merge_week({**two, "week": 7}, sunday)
    check(other["players"] == {"p-sun": {"receptions": 3}} and other["closed"] is False, "another week's copy is not merged in")
    check(fs.WEEK_FILE.format(season=2026, week=9) == "nfl_fantasy_stats_2026_w09.json", "the name the site asks for")
    print("ok  week file: only gains, closes when every game is final")


if __name__ == "__main__":
    main()
    test_week_file()
