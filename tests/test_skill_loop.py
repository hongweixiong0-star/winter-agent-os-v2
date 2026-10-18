"""The skill loop reads only what is new, and promotes only what was measured.

These tests pin the two properties that make the loop safe to leave running: the cursor cannot
silently skip a row, and replay can never earn a promotion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import skill_loop  # noqa: E402


def _row(skill: str, result: str, *, verified: bool | None = True, mode: str = "LIVE",
         failure: str | None = None, popup: str | None = None) -> dict:
    return {
        "skill": skill,
        "result": result,
        "verifier_ok": verified,
        "mode": mode,
        "failure_type": failure,
        "state_before": {"popup": popup} if popup else {},
    }


def _write_ledger(path: Path, rows: list[dict]) -> None:
    # newline="" so the byte length the test asserts is the byte length on disk on every
    # platform: the ledger's cursor is a byte offset and Windows would otherwise add a \r.
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="")


def test_cursor_reads_only_appended_rows(tmp_path):
    ledger = tmp_path / "episodes.jsonl"
    _write_ledger(ledger, [_row("A", "SUCCESS"), _row("B", "FAILURE", verified=False)])

    first, offset = skill_loop.read_new_episodes({"episodes_offset": 0}, path=ledger)
    assert [r["skill"] for r in first] == ["A", "B"]

    again, offset_again = skill_loop.read_new_episodes({"episodes_offset": offset}, path=ledger)
    assert again == []
    assert offset_again == offset

    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_row("C", "SUCCESS")) + "\n")
    third, _ = skill_loop.read_new_episodes({"episodes_offset": offset}, path=ledger)
    assert [r["skill"] for r in third] == ["C"]


def test_partial_last_line_is_not_consumed(tmp_path):
    ledger = tmp_path / "episodes.jsonl"
    good = json.dumps(_row("A", "SUCCESS")) + "\n"
    ledger.write_text(good + '{"skill": "B", "resu', encoding="utf-8", newline="")

    rows, offset = skill_loop.read_new_episodes({"episodes_offset": 0}, path=ledger)
    assert [r["skill"] for r in rows] == ["A"]
    assert offset == len(good.encode())


def test_truncated_ledger_restarts_instead_of_reading_nothing(tmp_path):
    ledger = tmp_path / "episodes.jsonl"
    _write_ledger(ledger, [_row("A", "SUCCESS")])
    rows, offset = skill_loop.read_new_episodes({"episodes_offset": 10_000}, path=ledger)
    assert [r["skill"] for r in rows] == ["A"]
    assert offset > 0


def test_unknown_requests_are_seen_once(tmp_path):
    gold = tmp_path / "unknown_requests"
    gold.mkdir()
    (gold / "a.json").write_text(json.dumps({"request_id": "r1", "page_label": "UNKNOWN"}),
                                 encoding="utf-8")
    (gold / "b.json").write_text(json.dumps({"request_id": "r2", "page_label": "使用"}),
                                 encoding="utf-8")

    fresh = skill_loop.read_new_unknowns({"seen_requests": []}, directory=gold)
    assert {u["request_id"] for u in fresh} == {"r1", "r2"}

    again = skill_loop.read_new_unknowns({"seen_requests": ["r1", "r2"]}, directory=gold)
    assert again == []


def test_summary_separates_simulation_from_production_and_keeps_failure_kinds():
    rows = [
        _row("A", "SUCCESS"),
        _row("A", "SUCCESS"),
        _row("A", "FAILURE", verified=False, failure="SEMANTIC_TARGET_NOT_VERIFIED"),
        _row("B", "SUCCESS", mode="REPLAY"),
    ]
    summary = skill_loop.summarise_episodes(rows)
    assert summary["rows"] == 4
    assert summary["simulation_rows_excluded"] == 1
    assert summary["by_skill"]["A"] == {"success": 2, "failure": 1, "unknown": 0}
    assert summary["verified_by_skill"]["A"] == 2
    assert summary["failures"] == [
        {"skill": "A", "failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 1}
    ]
    assert "B" not in summary["by_skill"]


def test_promotion_requires_verified_passes_and_no_recent_failure():
    empty = skill_loop.promotion_verdict("A", [])
    assert empty["promote"] is False and empty["reason"] == "NO_PRODUCTION_ROWS"

    two = [_row("A", "SUCCESS")] * 2
    assert skill_loop.promotion_verdict("A", two)["reason"] == "NOT_ENOUGH_VERIFIED_PASSES"

    three = [_row("A", "SUCCESS")] * 3
    assert skill_loop.promotion_verdict("A", three)["promote"] is True

    with_failure = three + [_row("A", "FAILURE", verified=False, failure="X")]
    assert skill_loop.promotion_verdict("A", with_failure)["reason"] == "RECENT_FAILURE"

    unverified = [_row("A", "SUCCESS", verified=False)] * 4
    assert skill_loop.promotion_verdict("A", unverified)["reason"] == \
        "NOT_ENOUGH_VERIFIED_PASSES"


def test_replay_cannot_earn_a_promotion():
    replay = [_row("A", "SUCCESS", mode="REPLAY")] * 10
    verdict = skill_loop.promotion_verdict("A", replay)
    assert verdict["promote"] is False
    assert verdict["reason"] == "NO_PRODUCTION_ROWS"


def test_brief_names_every_popup_it_cannot_cover(tmp_path):
    rows = [_row("BACK", "SUCCESS", popup="GET_MORE_STAMINA"),
            _row("BACK", "SUCCESS", popup="SOMETHING_NEW"),
            _row("CLOSE_POPUP", "SUCCESS", popup="PURCHASE_POPUP")]
    brief = skill_loop.build_brief(rows, [], cursor={"episodes_offset": 0, "seen_requests": []})

    assert brief["popups_seen"] == ["GET_MORE_STAMINA", "PURCHASE_POPUP", "SOMETHING_NEW"]
    # GET_MORE_STAMINA now has a named skill; the invented one must be reported, not hidden.
    assert "SOMETHING_NEW" in brief["popups_without_named_skill"]
    assert "DISMISS_GET_MORE_STAMINA" in brief["popup_skill_coverage"]["GET_MORE_STAMINA"]
    # A purchase popup answered only by the generic X is a fallback, not a capability.
    assert "PURCHASE_POPUP" in brief["popups_generic_fallback_only"]
    assert "PURCHASE_POPUP" not in brief["popups_without_named_skill"]
    assert brief["counts"]["episode_rows"] == 3


def test_outcome_ledger_appends_one_line_per_decision(tmp_path, monkeypatch):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setattr(skill_loop, "OUTCOME_PATH", ledger)

    skill_loop.record_outcome("DISMISS_GET_MORE_STAMINA", verdict="VERIFIED",
                              evidence={"episode_id": "e1"}, request_id="r1", note="live")
    skill_loop.record_outcome("DISMISS_GET_MORE_STAMINA", verdict="FAILED",
                              evidence={"episode_id": "e2"}, note="verifier said no")

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [r["verdict"] for r in rows] == ["VERIFIED", "FAILED"]
    assert rows[0]["evidence"]["episode_id"] == "e1"
    assert rows[1]["request_id"] is None
