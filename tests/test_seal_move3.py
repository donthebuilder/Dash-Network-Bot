"""Seal move 3 end to end (2026-11-11): the data branch carries no plain copy of a file that names tonight's calls,
and every reader still reads it.

TEST data only. The REAL publish_data.sh, fetch_data_branch.sh, open_data_branch.sh and seal_data.sh run against a
throw-away local "origin". Nothing is fetched from or pushed to GitHub.
Run: PYTHONPATH=.:bots python3 tests/test_seal_move3.py"""
import os, secrets, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUR = "public/data/current"
base_env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
base_env.pop("DATA_SEAL_KEY", None)
KEY = secrets.token_hex(64)
LOCK = '{"TEST": "lock ledger", "date": "2026-01-01"}'
WEEK = '{"TEST": "week", "games": []}'


def sh(cmd, cwd, key=KEY, check=False):
    e = dict(base_env)
    if key:
        e["DATA_SEAL_KEY"] = key
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, (cmd, r.returncode, r.stdout[-600:], r.stderr[-600:])
    return r


def runner(td, origin, name):
    """A fresh Actions runner: a clone of main, nothing in public/data."""
    w = td / name
    sh(["git", "clone", "-q", str(origin), str(w)], td, check=True)
    (w / CUR).mkdir(parents=True)
    return w


def branch_files(td, origin):
    r = sh(["git", "--git-dir", str(origin), "ls-tree", "--name-only", "data", CUR + "/"], td, check=True)
    return {p.rsplit("/", 1)[-1] for p in r.stdout.split()}


def tip(td, origin):
    return sh(["git", "--git-dir", str(origin), "rev-parse", "data"], td, check=True).stdout.strip()


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    origin = td / "origin.git"
    sh(["git", "init", "-q", "--bare", "-b", "main", str(origin)], td, check=True)
    seed = td / "seed"
    sh(["git", "clone", "-q", str(origin), str(seed)], td, check=True)
    shutil.copytree(ROOT / ".github/scripts", seed / ".github/scripts")
    (seed / ".gitignore").write_text("public/data/\n")
    sh(["git", "add", "-A"], seed, check=True); sh(["git", "commit", "-qm", "main"], seed, check=True)
    sh(["git", "push", "-q", "origin", "HEAD:main"], seed, check=True)

    # the branch as it stood before move 3: plain AND sealed side by side
    old = td / "old"; (old / CUR).mkdir(parents=True)
    sh(["git", "init", "-q", "-b", "data", str(old)], td, check=True)
    (old / CUR / "pick_lock.json").write_text(LOCK)
    (old / CUR / "nfl_week.json").write_text(WEEK)
    (old / CUR / "nfl_logs.json").write_text('{"TEST": "not listed"}')
    for n in ("pick_lock.json", "nfl_week.json"):
        sh(["bash", str(ROOT / ".github/scripts/seal_data.sh"), "seal", str(old / CUR / n), str(old / CUR / (n + ".sealed"))], td, check=True)
    sh(["git", "add", "-A"], old, check=True); sh(["git", "commit", "-qm", "before move 3"], old, check=True)
    sh(["git", "push", "-q", str(origin), "data:data"], old, check=True)
    sealed_lock = (old / CUR / "pick_lock.json.sealed").read_text()

    # 1) a publisher that rebuilt only an unlisted file: the plain copies leave the branch, the sealed ones stay as they were
    w = runner(td, origin, "w1")
    (w / CUR / "nfl_logs.json").write_text('{"TEST": "not listed", "run": 2}')
    r = sh(["bash", ".github/scripts/publish_data.sh", "TEST publish"], w)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])
    files = branch_files(td, origin)
    assert "pick_lock.json" not in files and "nfl_week.json" not in files, files
    assert {"pick_lock.json.sealed", "nfl_week.json.sealed", "nfl_logs.json"} <= files, files
    got = sh(["git", "--git-dir", str(origin), "show", f"data:{CUR}/pick_lock.json.sealed"], td, check=True).stdout
    assert got == sealed_lock, "a carried sealed file must come through byte for byte"
    assert "TEST" not in got

    # 2) a reader with the key: git show / archive / cat-file read the plain file as before; the real tip is kept apart
    rd = runner(td, origin, "r1")
    assert sh(["bash", ".github/scripts/fetch_data_branch.sh"], rd).returncode == 0
    assert sh(["git", "show", f"origin/data:{CUR}/pick_lock.json"], rd, check=True).stdout == LOCK
    assert sh(["git", "cat-file", "-e", f"origin/data:{CUR}/nfl_week.json"], rd).returncode == 0
    sh(["bash", "-c", f"mkdir x && git archive origin/data public/data | tar -x -C x"], rd, check=True)
    assert (rd / "x" / CUR / "nfl_week.json").read_text() == WEEK
    assert sh(["git", "rev-parse", "refs/remotes/origin/data-published"], rd, check=True).stdout.strip() == tip(td, origin)
    assert sh(["bash", ".github/scripts/open_data_branch.sh"], rd).returncode == 0      # twice is harmless
    assert sh(["git", "rev-parse", "refs/remotes/origin/data-published"], rd, check=True).stdout.strip() == tip(td, origin)

    # 3) a reader with NO key: the fetch fails. A sealed file is never read as an absent one.
    rd2 = runner(td, origin, "r2")
    r = sh(["bash", ".github/scripts/fetch_data_branch.sh"], rd2, key=None)
    assert r.returncode == 1 and "::error::" in r.stderr, (r.returncode, r.stderr)
    r = sh(["bash", ".github/scripts/fetch_data_branch.sh"], rd2, key=secrets.token_hex(64))
    assert r.returncode == 1, "a wrong key must fail the fetch"

    # 4) a publisher that rebuilt a listed file: the new sealed copy opens to the new file; still no plain copy
    w = runner(td, origin, "w2")
    week2 = '{"TEST": "week", "games": [{"TEST": 1}]}'
    (w / CUR / "nfl_week.json").write_text(week2)
    r = sh(["bash", ".github/scripts/publish_data.sh", "TEST publish"], w)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])
    files = branch_files(td, origin)
    assert "nfl_week.json" not in files and "pick_lock.json" not in files, files
    rd = runner(td, origin, "r3")
    sh(["bash", ".github/scripts/fetch_data_branch.sh"], rd, check=True)
    assert sh(["git", "show", f"origin/data:{CUR}/nfl_week.json"], rd, check=True).stdout == week2
    assert sh(["git", "show", f"origin/data:{CUR}/pick_lock.json"], rd, check=True).stdout == LOCK

    # 5) the same files again: "Nothing to publish", the branch does not move
    before = tip(td, origin)
    w = runner(td, origin, "w3")
    (w / CUR / "nfl_week.json").write_text(week2)
    r = sh(["bash", ".github/scripts/publish_data.sh", "TEST publish"], w)
    assert r.returncode == 0 and "Nothing to publish" in r.stdout, (r.stdout[-800:], r.stderr[-800:])
    assert tip(td, origin) == before

    # 6) a publisher with NO key: nothing is published and the branch does not move
    w = runner(td, origin, "w4")
    (w / CUR / "nfl_week.json").write_text('{"TEST": "would leak"}')
    r = sh(["bash", ".github/scripts/publish_data.sh", "TEST publish"], w, key=None)
    assert r.returncode != 0, "a job with no key must not publish"
    assert tip(td, origin) == before
    assert "nfl_week.json" not in branch_files(td, origin)

    # 7) the first publish ever (no data branch) with a listed file: sealed only
    origin2 = td / "origin2.git"
    sh(["git", "clone", "-q", "--bare", str(origin), str(origin2)], td, check=True)
    sh(["git", "--git-dir", str(origin2), "update-ref", "-d", "refs/heads/data"], td, check=True)
    w = runner(td, origin2, "w5")
    (w / CUR / "pick_lock.json").write_text(LOCK)
    r = sh(["bash", ".github/scripts/publish_data.sh", "TEST publish"], w)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])
    assert branch_files(td, origin2) == {"pick_lock.json.sealed"}, branch_files(td, origin2)
print("test_seal_move3: ok")
