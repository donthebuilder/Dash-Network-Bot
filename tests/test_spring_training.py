"""Spring training is its own thing (2026-11-28, bots/spring_training.py): Statcast frames lose their spring rows, the rows are counted aside, nothing else changes.
TEST data only: made-up frames in Savant's column shape. Run: python3 tests/test_spring_training.py (or pytest)."""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))
import spring_training as st  # noqa: E402


def frame(types, events=None):
    n = len(types)
    return pd.DataFrame({"game_type": types, "events": events or [""] * n, "game_date": ["2027-03-10"] * n})


def setup_function(_f=None):
    st.SPRING["batter"].clear(); st.SPRING["pitcher"].clear()


def test_spring_and_exhibition_rows_leave_the_season_frame_and_postseason_stays():
    kept, spring = st.split_spring(frame(["S", "R", "E", "R", "F", "D", "L", "W", "s"]))
    assert list(kept["game_type"]) == ["R", "R", "F", "D", "L", "W"]
    assert len(spring) == 3


def test_no_spring_means_the_same_frame_back():
    df = frame(["R", "R"])
    kept, spring = st.split_spring(df)
    assert kept is df and spring is None


def test_no_game_type_column_or_no_frame_is_never_emptied():
    df = pd.DataFrame({"events": ["home_run"]})
    kept, spring = st.split_spring(df)
    assert kept is df and spring is None
    assert st.split_spring(None) == (None, None)
    empty = frame([])
    assert st.split_spring(empty)[0] is empty


def test_the_wrapper_keeps_the_signature_and_counts_the_spring_rows_aside():
    setup_function()
    seen = {}

    def fake(start, end, pid):
        seen["args"] = (start, end, pid)
        return frame(["S", "S", "R"], ["home_run", "single", "home_run"])
    w = st.regular_season_only(fake, "batter")
    out = w("2027-03-01", "2027-04-01", 123)
    assert seen["args"] == ("2027-03-01", "2027-04-01", 123)
    assert list(out["game_type"]) == ["R"]
    assert st.SPRING["batter"]["123"] == {"pitches": 2, "hr": 1}
    w("2027-03-01", "2027-04-01", 123)                    # the same player read twice in a run is not summed
    assert st.SPRING["batter"]["123"]["pitches"] == 2


def test_the_record_merges_and_keeps_the_larger_count(tmp_path):
    setup_function()
    st.SPRING["pitcher"]["9"] = {"pitches": 40}
    p = tmp_path / "spring_training_2027.json"
    assert st.write_record(p, 2027)
    st.SPRING["pitcher"]["9"] = {"pitches": 25}           # a later, narrower read must not lower it
    st.SPRING["batter"]["1"] = {"pitches": 10, "hr": 2}
    assert st.write_record(p, 2027)
    d = json.loads(p.read_text())
    assert d["pitcher"]["9"]["pitches"] == 40 and d["batter"]["1"] == {"hr": 2, "pitches": 10} and d["season"] == 2027


def test_nothing_to_write_writes_nothing(tmp_path):
    setup_function()
    assert st.write_record(tmp_path / "x.json", 2027) is False and not (tmp_path / "x.json").exists()


def test_the_dashboard_reads_statcast_through_the_filter():
    src = open(os.path.join(os.path.dirname(__file__), "..", "bots", "mlb_dashboard.py")).read()
    assert "spring_training.regular_season_only(statcast_batter" in src and "spring_training.regular_season_only(statcast_pitcher" in src


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            setup_function()
            v(Path(tempfile.mkdtemp())) if "tmp_path" in v.__code__.co_varnames[:v.__code__.co_argcount] else v()
            n += 1
    print(f"{n}/{n} checks passed")
