"""2026-11-05: the evening jobs after the Nov 1 clock change -- bots/slate_live.py (run to the last final whistle) and bots/slot_covered.py
(a slot GitHub starts hours late after the site's restarter already ran it stands down), plus the schedules they belong to."""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bots"))

from slate_live import live_or_soon  # noqa: E402
from slot_covered import fires, last_fire  # noqa: E402

UTC = timezone.utc


def ev(state, iso):
    return {"status": {"type": {"state": state}}, "date": iso}


def test_live_or_soon():
    now = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)          # 11 PM ET
    lead = timedelta(hours=6)
    assert live_or_soon([ev("in", "2026-11-06T03:00Z")], now, lead)               # a West Coast tip still on
    assert live_or_soon([ev("pre", "2026-11-06T09:00Z")], now, lead)              # starts inside 6 h
    assert not live_or_soon([ev("pre", "2026-11-06T11:00Z")], now, lead)          # too far off
    assert not live_or_soon([ev("post", "2026-11-06T03:00Z")], now, lead)         # final
    assert not live_or_soon([], now, lead)


def test_slot_matcher():
    d = datetime(2026, 11, 6, 2, 25, tzinfo=UTC)
    assert last_fire("17 17,21,23 * * *", d) == datetime(2026, 11, 5, 23, 17, tzinfo=UTC)
    assert fires("8,23,38,53 0-1 * * 0", datetime(2026, 11, 8, 0, 23, tzinfo=UTC))        # Saturday night ET = Sunday UTC
    assert not fires("8,23,38,53 0-1 * * 0", datetime(2026, 11, 9, 0, 23, tzinfo=UTC))
    assert fires("8,23,38,53 16-20 27 11 *", datetime(2026, 11, 27, 18, 38, tzinfo=UTC))  # Black Friday
    assert last_fire("", d) is None


def crons(name):
    """The quoted strings on `- cron:` lines, and the file's text (plain text: CI has no PyYAML, KNOWN-ISSUES #117)."""
    text = (ROOT / ".github" / "workflows" / name).read_text()
    return re.findall(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", text, re.M), text


def test_schedules():
    lp, _ = crons("live-prices.yml")
    assert "30 4 * * *" in lp and "45 23 * * 1" not in lp and "45 23 * * 4" not in lp       # late pickup in, Mon/Thu duplicates out
    le, _ = crons("live-edge.yml")
    assert "35 4 * * *" in le and "30 23 * * 1" not in le
    sn, _ = crons("shadow-nba.yml")
    assert "0,30 0-3 * * *" in sn                                                            # first basket refreshed to 03:30Z
    for f in ("nhl-odds.yml", "nba-odds.yml"):
        c, text = crons(f)
        assert c == ["17 17,21,23 * * *", "52 23 * * *"]                                      # the same Eastern times in EST
        assert "  actions: read" in text and "steps.slot.outputs.covered != 'true'" in text
    nfl, text = crons("nfl.yml")
    assert "33 6 * * 5" in nfl and "33 4 * * 5" not in nfl                                  # TNF graded after the final whistle
    assert "8,23,38,53 16-20 27 11 *" in nfl and "8,23,38,53 15-23 25 12 *" in nfl            # Black Friday + Christmas pregame
    assert re.search(r"^      cron:\n", text, re.M)                                          # the restarter's slot input
    log = text[text.index("- name: TD board log"):text.index("- name: PREPLAY pools")]
    assert "33 6 * * 2" in log                                                              # Sunday's games logged Tuesday, not Friday


def test_mode_by_slot_not_clock():
    for f in ("live-prices.yml", "live-edge.yml", "shadow-nhl.yml", "shadow-nba.yml"):
        text = (ROOT / ".github" / "workflows" / f).read_text()
        assert 'SLOT="${{ github.event.schedule || inputs.cron }}"' in text, f
