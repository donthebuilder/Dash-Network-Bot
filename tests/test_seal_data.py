"""seal_data.sh: the sealed copies of the files that name tonight's calls (2026-11-09, the site's lockdown).

TEST data only. Checks: round trip, same file -> same sealed bytes (publish_data.sh's "nothing to publish" still
holds), a changed sealed file is refused, only listed files are sealed, a sealed copy with no plaintext goes, and
with no key a file this run rebuilt loses its stale sealed copy.
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
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}" "{fresh}"', key, tmp_path)
    assert r.returncode == 0, r.stderr
    sealed = tmp_path / "nfl_week.json.sealed"
    first = sealed.read_text()
    assert first.startswith("DSEAL1.") and "TEST player" not in first
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}" "{fresh}"', key, tmp_path)
    assert sealed.read_text() == first
    r = _run(f'bash "{SCRIPT}" unseal "{sealed}" "{tmp_path / "back.json"}"', key, tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "back.json").read_text() == (tmp_path / "nfl_week.json").read_text()


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
    _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}" /dev/null', key, tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "nfl_logs.json.sealed" not in names
    assert "por_rows_2026-10-28.jsonl.sealed" in names
    assert "por_rows_2026-01-01.jsonl.sealed" not in names


def test_no_key_drops_stale_copies_of_rebuilt_files(tmp_path):
    (tmp_path / "nfl_week.json").write_text("{}")
    (tmp_path / "nfl_week.json.sealed").write_text("DSEAL1.stale")
    (tmp_path / "nfl_picks.json").write_text("{}")
    (tmp_path / "nfl_picks.json.sealed").write_text("DSEAL1.carried")
    fresh = tmp_path / "fresh"
    fresh.write_text("nfl_week.json\n")
    r = _run(f'source "{SCRIPT}"; seal_tree "{tmp_path}" "{fresh}"', None, tmp_path)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "nfl_week.json.sealed").exists()
    assert (tmp_path / "nfl_picks.json.sealed").read_text() == "DSEAL1.carried"


if __name__ == "__main__":   # tests.yml runs each file as a script
    import tempfile
    for fn in (test_round_trip_and_same_bytes, test_changed_or_wrong_key_is_refused,
               test_only_listed_files_and_orphans, test_no_key_drops_stale_copies_of_rebuilt_files):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("test_seal_data: ok")
