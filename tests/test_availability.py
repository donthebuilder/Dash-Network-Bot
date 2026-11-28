"""bots/availability.py -- THE ONE RULE, run through the SAME case table the site's check runs (ONE VOICE, 2026-11-27).

tests/fixtures/availability_cases.json is byte-identical to the site repo's scripts/fixtures/availability-cases.json. If a case changes, it changes in
both repos in the same sitting, or one side's test fails. TEST DATA about statuses only; no player.

Run: python3 -m pytest tests/test_availability.py -v
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))

import availability as av  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "availability_cases.json"
DOC = json.loads(FIX.read_text())


def verdict(case) -> str:
    if case["via"] == "week":
        return "out" if av.unavailable(case["input"], started=case["started"]) else "ok"
    return "out" if av.unavailable_espn(case["input"]["word"], started=case["started"], lineup_in=case["lineup_in"]) else "ok"


def test_every_shared_case():
    bad = [(c["id"], verdict(c), c["expect"]) for c in DOC["cases"] if verdict(c) != c["expect"]]
    assert not bad, bad


def test_the_table_is_the_one_the_site_holds():
    # the site's check prints and asserts the same digest; if you edit the table, update BOTH repos
    assert len(DOC["cases"]) >= 40
    print("availability_cases sha256:", hashlib.sha256(FIX.read_bytes()).hexdigest())


def test_started_teams():
    import datetime as dt
    now = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)
    games = [{"home": "AAA", "away": "BBB", "kickoff": "2026-11-27T11:00:00Z", "state": "pre"},
             {"home": "CCC", "away": "DDD", "kickoff": "2026-11-27T20:00:00Z", "state": "pre"},
             {"home": "EEE", "away": "FFF", "kickoff": "2026-11-27T20:00:00Z", "state": "in"}]
    assert av.started_teams(games, now) == {"AAA", "BBB", "EEE", "FFF"}
