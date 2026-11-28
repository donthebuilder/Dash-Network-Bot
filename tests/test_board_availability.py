"""The NHL and NBA boards leave out a man who is not going to play (2026-11-27, ONE VOICE WITH THE SITE: bots/availability.py).

TEST data only: labelled men and a fake injury report. report_block is the one door every board uses (nhl_live, nba_live, nba_first_live; the MLB role map
reads it through mlb_unavailable). Run: python3 tests/test_board_availability.py  (or pytest)
"""
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))
import availability as av  # noqa: E402
from injury_status import key  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FUTURE, PAST = "2099-01-01T23:00:00Z", "2020-01-01T23:00:00Z"


def inj(name, status, team="AAA"):
    return {"name": name, "key": key(name), "team": team, "status": status}


def test_out_il_doubtful_never_at_any_time():
    for word in ("Out", "10-Day-IL", "Injured Reserve", "Suspension", "Doubtful"):
        for started in (False, True):
            assert av.report_block("Test Man", "AAA", [inj("Test Man", word)], started=started), (word, started)


def test_day_to_day_pregame_only_and_a_posted_lineup_keeps_him():
    r = [inj("Test Man", "Day-To-Day")]
    assert av.report_block("Test Man", "AAA", r)
    assert not av.report_block("Test Man", "AAA", r, lineup_in=True)
    assert not av.report_block("Test Man", "AAA", r, started=True)
    assert av.report_block("Test Man", "AAA", [inj("Test Man", "Out")], lineup_in=True)       # never an OUT man


def test_no_report_and_no_match_remove_nobody():
    assert av.report_block("Test Man", "AAA", []) is None
    assert av.report_block("Test Man", "AAA", None) is None
    assert av.report_block("Test Man", "AAA", [inj("Someone Else", "Out")]) is None
    assert av.report_block("Test Man", "AAA", [inj("Test Man", "Active")]) is None


def test_same_name_on_two_clubs_needs_his_club():
    r = [inj("Test Man", "Out", team="ZZZ"), inj("Test Man", "Out", team="YYY")]
    assert av.report_block("Test Man", "AAA", r) is None
    assert av.report_block("Test Man", "ZZZ", r)


def test_started_at():
    assert av.started_at(PAST) and not av.started_at(FUTURE)
    assert not av.started_at(None) and not av.started_at("junk")      # unreadable = not started (the safe side of a pregame rule)


def test_every_board_goes_through_the_one_door():
    for f in ("nhl_live.py", "nba_live.py", "nba_first_live.py"):
        src = (ROOT / "bots" / f).read_text()
        assert "availability.report_block(" in src, f


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n}/{n} checks passed")
