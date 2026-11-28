"""A man who is not going to play is never an MLB pick (2026-11-27, ONE VOICE WITH THE SITE: bots/availability.py).

TEST data only (labelled men, a fake injury report). build_game_pick_role_map and game_pick_type_map draw from the game's hitters minus the men the
rule rules out: OUT / IL / DOUBTFUL always; DAY-TO-DAY before first pitch unless his lineup is posted; a posted lineup keeps a DOUBTFUL man, never an OUT one;
no report = no change; a dead feed never empties a slate. Run: python3 tests/test_mlb_role_availability.py  (or pytest)
"""
import dataclasses
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))
import bots.mlb_dashboard as md  # noqa: E402

FUTURE = "2099-01-01T23:00:00Z"
PAST = "2020-01-01T23:00:00Z"


def mk(**over) -> md.HitterRecord:
    kw = {}
    for f in dataclasses.fields(md.HitterRecord):
        if f.default is not dataclasses.MISSING:
            kw[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
            kw[f.name] = f.default_factory()  # type: ignore[misc]
        else:
            kw[f.name] = 0
    kw.update(over)
    return md.HitterRecord(**kw)


def inj(name, status, team="AAA"):
    from injury_status import key
    return {"name": name, "key": key(name), "team": team, "status": status}


def slate(game_time=FUTURE, lineup=False):
    kw = dict(game_pk=9, game_time=game_time, team="AAA", season_pa=500, lineup_confirmed=lineup)
    return [mk(player_id=1, name="Test One", season_iso=0.30, hr_score=80.0, board_score=97.0, **kw),
            mk(player_id=2, name="Test Two", season_iso=0.25, hr_score=70.0, board_score=90.0, **kw),
            mk(player_id=3, name="Test Three", season_iso=0.20, hr_score=60.0, board_score=80.0, **kw),
            mk(player_id=4, name="Test Four", season_iso=0.18, hr_score=50.0, board_score=70.0, **kw)]


def roles(rows, report):
    md._MLB_INJ_OVERRIDE = report
    try:
        return md.build_game_pick_role_map(rows), md.game_pick_type_map(rows)
    finally:
        md._MLB_INJ_OVERRIDE = None


def has(role_map, pid):
    return any(k[1] == pid for k in role_map)


def test_no_report_changes_nothing():
    base, _ = roles(slate(), [])
    assert has(base, 1) and has(base, 2)


def test_out_man_is_never_a_pick_and_the_next_man_takes_the_slot():
    rm, tm = roles(slate(), [inj("Test One", "Out")])
    assert not has(rm, 1) and 1 not in tm
    assert has(rm, 2)                                   # the next healthy man is TOP


def test_il_and_doubtful_never_even_with_lineup_for_il():
    for word in ("10-Day-IL", "Doubtful"):
        rm, _ = roles(slate(), [inj("Test One", word)])
        assert not has(rm, 1), word
    rm, _ = roles(slate(lineup=True), [inj("Test One", "Doubtful")])
    assert has(rm, 1)                                   # a posted lineup trumps a doubtful tag
    rm, _ = roles(slate(lineup=True), [inj("Test One", "Out")])
    assert not has(rm, 1)                               # never an OUT man


def test_day_to_day_pregame_out_but_kept_by_lineup_or_after_first_pitch():
    rm, _ = roles(slate(), [inj("Test One", "Day-To-Day")])
    assert not has(rm, 1)
    rm, _ = roles(slate(lineup=True), [inj("Test One", "Day-To-Day")])
    assert has(rm, 1)
    rm, _ = roles(slate(game_time=PAST), [inj("Test One", "Day-To-Day")])
    assert has(rm, 1)                                   # not hidden once the game has started


def test_everyone_out_means_no_pick_not_a_forced_one():
    rm, tm = roles(slate(), [inj(n, "Out") for n in ("Test One", "Test Two", "Test Three", "Test Four")])
    assert rm == {} or not any(k[0] == 9 for k in rm)
    assert not tm


def test_same_name_other_club_is_not_him():
    rm, _ = roles(slate(), [inj("Test One", "Out", team="ZZZ"), inj("Test One", "Active", team="AAA")])
    assert has(rm, 1)


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n}/{n} checks passed")
