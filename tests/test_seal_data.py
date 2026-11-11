"""seal_data.sh: the files that name tonight's calls are published sealed, never plain (move 1 2026-11-09, move 3 2026-11-11).

TEST data only. Checks: round trip, same file -> same sealed bytes (publish_data.sh's "nothing to publish" still
holds), a changed sealed file is refused, only listed files are sealed, the plain copy of a sealed file is removed
from the tree, a sealed copy whose plain file was trimmed goes, a job with no key refuses to publish a listed file,
and bots/sealed_data.py (the https readers) holds the same list and opens what seal_data.sh sealed.
"""
import os
import secrets
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "seal_data.sh"


def _run(cmd, key, cwd):
    env = dict(os.environ)
    env.pop("DATA_SEAL_KEY", None)
    if key:
        env["DATA_SEAL_KEY"] = key
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True)


def test_round_trip_and_same_bytes(tmp_path):
    key = secrets.token_hex(64)
    (tmp_path / "nfl_week.json").write_text('{"players": [{"name": "TEST player", "scores": {"TD": 70}}]}')
    fresh = tmp_path / "fresh"
    fresh.write_text("nfl_week.json\n")
    plain = (tmp_path / "nfl_week.json").read_text()
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}"', key, tmp_path)
    assert r.returncode == 0, r.stderr
    sealed = tmp_path / "nfl_week.json.sealed"
    first = sealed.read_text()
    assert first.startswith("DSEAL1.") and "TEST player" not in first
    assert not (tmp_path / "nfl_week.json").exists(), "the plain copy must not stay in the tree that is pushed"
    (tmp_path / "nfl_week.json").write_text(plain)          # the next run rebuilds the same file
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}"', key, tmp_path)
    assert sealed.read_text() == first
    r = _run(f'bash "{SCRIPT}" unseal "{sealed}" "{tmp_path / "back.json"}"', key, tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "back.json").read_text() == plain
    # the https readers open the same bytes
    import sys
    sys.path.insert(0, str(SCRIPT.parent.parent.parent / "bots"))
    import sealed_data
    os.environ["DATA_SEAL_KEY"] = key
    try:
        assert sealed_data.unseal(sealed.read_bytes()).decode() == plain
        assert sealed_data.open_body(plain.encode()) == plain.encode()
        try:
            sealed_data.unseal(first[:-4].encode() + b"AAAA"); raise AssertionError("a changed file must be refused")
        except sealed_data.SealError:
            pass
        os.environ.pop("DATA_SEAL_KEY")
        try:
            sealed_data.unseal(sealed.read_bytes()); raise AssertionError("no key must raise, not return")
        except sealed_data.SealError:
            pass
    finally:
        os.environ.pop("DATA_SEAL_KEY", None)
    assert sealed_data.sealed_url("https://x/y/pick_lock.json?t=1") == "https://x/y/pick_lock.json.sealed?t=1"
    assert sealed_data.sealed_url("https://x/y/graded_results_2026-10-01.json") == "https://x/y/graded_results_2026-10-01.json"
    sh_re = SCRIPT.read_text().split("SEALED_RE='", 1)[1].split("'", 1)[0]
    assert sealed_data.SEALED_RE.pattern == sh_re.replace("\\.", r"\.").replace("[0-9]", "[0-9]"), "the two lists differ"


def test_changed_or_wrong_key_is_refused(tmp_path):
    key = secrets.token_hex(64)
    (tmp_path / "pick_lock.json").write_text('{"TEST": 1}')
    _run(f'bash "{SCRIPT}" seal "{tmp_path / "pick_lock.json"}" "{tmp_path / "s"}"', key, tmp_path)
    r = _run(f'bash "{SCRIPT}" unseal "{tmp_path / "s"}" "{tmp_path / "o"}"', secrets.token_hex(64), tmp_path)
    assert r.returncode != 0
    body = (tmp_path / "s").read_text()
    (tmp_path / "s2").write_text(body[:-4] + ("AAAA" if not body.endswith("AAAA") else "BBBB"))
    r = _run(f'bash "{SCRIPT}" unseal "{tmp_path / "s2"}" "{tmp_path / "o"}"', key, tmp_path)
    assert r.returncode != 0


def test_only_listed_files_and_orphans(tmp_path):
    key = secrets.token_hex(64)
    (tmp_path / "nfl_logs.json").write_text("{}")
    (tmp_path / "por_rows_2026-10-28.jsonl").write_text('{"TEST": 1}\n')
    (tmp_path / "por_rows_2026-01-01.jsonl.sealed").write_text("DSEAL1.old")
    _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}"', key, tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "nfl_logs.json.sealed" not in names
    assert "por_rows_2026-10-28.jsonl.sealed" in names
    assert "por_rows_2026-01-01.jsonl.sealed" not in names
    assert "por_rows_2026-10-28.jsonl" not in names and "nfl_logs.json" in names


def test_no_key_never_publishes_a_listed_file(tmp_path):
    (tmp_path / "nfl_week.json").write_text("{}")
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}"', None, tmp_path)
    assert r.returncode != 0 and "::error::" in r.stderr, (r.returncode, r.stderr)
    # nothing listed staged (an odds-only job): carried sealed copies are left as they are
    (tmp_path / "nfl_week.json").unlink()
    (tmp_path / "nfl_picks.json.sealed").write_text("DSEAL1.carried")
    (tmp_path / "nba_odds_2026-11-11.json").write_text("{}")
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}"', None, tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "nfl_picks.json.sealed").read_text() == "DSEAL1.carried"
    assert (tmp_path / "nba_odds_2026-11-11.json").exists()


def test_run_logs_sealed_only_while_live(tmp_path):
    key = secrets.token_hex(64)
    live = ["nfl_prediction_log_2026-wk10.202108Z.gha-1.jsonl", "nfl_signal_log_2026-wk10.202108Z.gha-1.jsonl",
            "nfl_next_prediction_log_2026-wk11.202114Z.gha-1.jsonl", "prediction_log_2026-11-11.221951Z.gha-1.jsonl",
            "prediction_log_2026-11-10.221951Z.gha-1.jsonl", "nhl_sim_latest.json"]
    past = ["nfl_prediction_log_2026-wk09.202108Z.gha-1.jsonl", "nfl_signal_log_2026-wk09.202108Z.gha-1.jsonl",
            "prediction_log_2026-11-09.221951Z.gha-1.jsonl", "nfl_prediction_log_2026-09-04.1Z.gha-1.jsonl",
            "nfl_next_prediction_log_2026-wk09.202114Z.gha-1.jsonl"]
    plain = ["nfl_por_log_2026_w10.jsonl", "por_log_2026-11-11.jsonl", "graded_results_2026-11-10.json"]
    for n in live + past + plain:
        (tmp_path / n).write_text('{"TEST": "' + n + '"}\n')
    # an older log that was sealed while it was live: it goes back to plain
    (tmp_path / (past[0] + ".sealed")).write_text("DSEAL1.was-live")
    r = _run(f'source "{SCRIPT}"; SEAL_CUTOFF=2026-11-10 seal_tree "{tmp_path}"', key, tmp_path)
    assert r.returncode == 0, r.stderr
    names = {p.name for p in tmp_path.iterdir()}
    for n in live:
        assert n + ".sealed" in names and n not in names, n
    for n in past + plain:
        assert n in names and n + ".sealed" not in names, n
    assert not any(x.endswith(".sealed.sealed") for x in names)
    # again, same tree: nothing changes (a second publish finds nothing to publish)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    for n in live:
        (tmp_path / n).write_text('{"TEST": "' + n + '"}\n')      # carried forward opened, as the publish does
    _run(f'source "{SCRIPT}"; SEAL_CUTOFF=2026-11-10 seal_tree "{tmp_path}"', key, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    # no key: a live log is never published plain
    (tmp_path / live[0]).write_text("{}")
    r = _run(f'source "{SCRIPT}"; SEAL_CUTOFF=2026-11-10 seal_tree "{tmp_path}"', None, tmp_path)
    assert r.returncode != 0
    import sys
    sys.path.insert(0, str(SCRIPT.parent.parent.parent / "bots"))
    import sealed_data
    for n in live + past:
        assert sealed_data.is_sealed_name(n), n        # a reader asks for the sealed copy first, plain on a 404
    for n in plain:
        assert not sealed_data.is_sealed_name(n), n


if __name__ == "__main__":   # tests.yml runs each file as a script
    import tempfile
    for fn in (test_round_trip_and_same_bytes, test_changed_or_wrong_key_is_refused,
               test_only_listed_files_and_orphans, test_no_key_never_publishes_a_listed_file,
               test_run_logs_sealed_only_while_live):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("test_seal_data: ok")
