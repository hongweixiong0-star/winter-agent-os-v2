"""The cross-account handoff must stay structurally valid.

A new WorkBuddy account has no chat history: `START_HERE.md` and
`.workbuddy-ai/handoff/*` are the only map it gets.  If a regeneration pass
duplicates an AUTO block, drops a required file, or overwrites hand-written
reasoning, the next account silently inherits a corrupted map — and the failure
is invisible until someone spends hours reconstructing state by hand.

These tests assert the invariants `tools/verify_handoff.py` checks, so a broken
handoff fails CI instead of the next human.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_handoff import AUTO_FILES, REQUIRED, audit  # noqa: E402


def test_handoff_directory_satisfies_every_invariant() -> None:
    _lines, failures = audit(ROOT)
    assert not failures, "handoff invariants violated:\n" + "\n".join(failures)


def test_audit_actually_detects_a_missing_file(tmp_path: Path) -> None:
    """Negative control: the audit must fail on a broken handoff, not always pass."""
    handoff = tmp_path / ".workbuddy-ai" / "handoff"
    handoff.mkdir(parents=True)
    (tmp_path / "START_HERE.md").write_text("x" * 400, encoding="utf-8")
    _lines, failures = audit(tmp_path)
    assert failures, "audit passed on an almost-empty handoff directory"
    assert any(name in failure for failure in failures for name in REQUIRED)


@pytest.mark.parametrize("name,block", sorted(AUTO_FILES.items()))
def test_each_auto_block_has_exactly_one_marker_pair(name: str, block: str) -> None:
    path = ROOT / ".workbuddy-ai" / "handoff" / name
    if not path.is_file():
        pytest.skip(f"{name} not present")
    text = path.read_text(encoding="utf-8")
    assert text.count(f"<!-- AUTO:{block} -->") == 1, f"{name}: duplicate/absent opening marker"
    assert text.count(f"<!-- /AUTO:{block} -->") == 1, f"{name}: duplicate/absent closing marker"


def test_start_here_documents_steps_that_actually_exist() -> None:
    """START_HERE.md must not send a new account to a command that is missing.

    The entry point is the only map a fresh account gets; a stale tool path in it
    is worse than no path, because the account wastes time debugging the docs.
    """
    start = ROOT / "START_HERE.md"
    assert start.is_file()
    text = start.read_text(encoding="utf-8")
    for relative in ("tools/update_workbuddy_handoff.py", "tools/truth_audit.py"):
        assert relative in text, f"START_HERE.md does not mention {relative}"
        assert (ROOT / relative).is_file(), f"START_HERE.md points at a missing file: {relative}"
    # The continuation files it tells the reader to open must exist too.
    for name in ("01_CURRENT_TRUTH.md", "03_NEXT_ACTION.md", "04_OPEN_ISSUES.md", "10_LAST_HANDOFF.md"):
        assert name in text, f"START_HERE.md does not reference {name}"
        assert (ROOT / ".workbuddy-ai" / "handoff" / name).is_file(), f"referenced but missing: {name}"


def test_every_handoff_file_is_reachable_from_start_here() -> None:
    """No handoff file may be orphaned: a new account only reads START_HERE first."""
    start = (ROOT / "START_HERE.md").read_text(encoding="utf-8")
    referenced = {
        "00_MASTER_RULES.md", "01_CURRENT_TRUTH.md", "02_CURRENT_PROGRESS.md", "03_NEXT_ACTION.md",
        "04_OPEN_ISSUES.md", "05_RECENT_CHANGES.md", "06_DECISIONS.md", "07_EXTERNAL_REUSE.md",
    }
    missing = sorted(name for name in referenced if name not in start)
    assert not missing, f"START_HERE.md does not lead to: {missing}"


def test_handoff_is_regenerable_without_prior_chat_context() -> None:
    """Everything machine-owned must be derivable from the repository alone."""
    metrics = ROOT / ".workbuddy-ai" / "handoff" / "08_LIVE_METRICS.json"
    truth = ROOT / ".workbuddy-ai" / "handoff" / "01_CURRENT_TRUTH.md"
    if not metrics.is_file():
        pytest.skip("run tools/update_workbuddy_handoff.py first")
    import json

    payload = json.loads(metrics.read_text(encoding="utf-8"))
    for key in ("generated_at", "source", "commit", "episodes", "skills", "evidence_integrity"):
        assert key in payload, f"08_LIVE_METRICS.json lost {key}"
    assert payload["source"], "metrics must name the script that produced them"
    assert truth.is_file()
    text = truth.read_text(encoding="utf-8")
    # The truth file must expose the sections a new account reads first.
    for heading in ("## A. Version control", "## C. Episode stream", "## F. Goal capability coverage",
                    "## G. Evidence integrity"):
        assert heading in text, f"01_CURRENT_TRUTH.md lost section: {heading}"


class FailureRecencyTests:
    """Top-failure ranking must be readable as *current*, not cumulative.

    Ranking failure types by all-time count alone sent a whole working session
    after `SEMANTIC_TARGET_NOT_VERIFIED x112`, of which 0 had happened on the
    day of the session and whose last live occurrence was three days earlier;
    `MARCH_PAGE_NOT_OPEN x59` was likewise entirely one dead day.  The fields
    below are what makes that visible without re-deriving it by hand.

    NOTE: these are module-level functions on purpose -- this suite collects
    pytest-style functions, and a `class XxxTests` (no `Test` prefix) would
    silently never run.
    """


def test_recent_zero_is_reported_as_historical() -> None:
    from tools.update_workbuddy_handoff import failure_rank_line

    line = failure_rank_line(
        {"failure_type": "MARCH_PAGE_NOT_OPEN", "count": 59, "recent": 0, "last_seen": "2026-09-12T09:00:00+00:00"},
        {"recent_window_days": 2},
    )
    assert "HISTORICAL" in line
    assert "0 in the last 2 day(s)" in line
    assert "59 all-time" in line


def test_recent_failures_are_reported_as_current() -> None:
    from tools.update_workbuddy_handoff import failure_rank_line

    line = failure_rank_line(
        {"failure_type": "RESOURCE_NOT_FOUND", "count": 30, "recent": 30, "last_seen": "2026-09-14T06:42:03+00:00"},
        {"recent_window_days": 2},
    )
    assert "HISTORICAL" not in line
    assert "30 in the last 2 day(s)" in line


def test_missing_recency_data_falls_back_to_the_bare_count() -> None:
    from tools.update_workbuddy_handoff import failure_rank_line

    assert failure_rank_line({"failure_type": "X", "count": 3}, {}) == "X x3"
    assert failure_rank_line(None, {}) == "no production failures recorded"


def test_the_rendered_ranking_is_ordered_by_recency() -> None:
    import json

    path = ROOT / ".workbuddy-ai" / "handoff" / "03_NEXT_ACTION.md"
    if not path.is_file():
        pytest.skip("run tools/update_workbuddy_handoff.py first")
    text = path.read_text(encoding="utf-8")
    payload = None
    for line in text.splitlines():
        if line.startswith("TOP FAILURE: "):
            payload = json.loads(line[len("TOP FAILURE: "):])
            break
    assert payload is not None, "03_NEXT_ACTION.md lost its TOP FAILURE line"
    for key in ("recent", "last_seen", "dates"):
        assert key in payload, f"TOP FAILURE lost {key}; recency ranking would regress"
    assert "TOP FAILURE IS RANKED BY RECENT FIRST" in text
