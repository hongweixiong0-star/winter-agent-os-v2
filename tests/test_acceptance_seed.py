"""Breaking the cold-start deadlock, once, and closing the exception behind it.

The deadlock, stated exactly: the preloader may not dispatch until the main loop is proven, and
the main loop cannot be proven until something travels it.  With nothing open -- measured
2026-09-19: `current_development_trace()` = None and every record terminal -- the loop has no
input, so it can never be proven, so the first trace is never dispatched, and waiting for a
random runtime gap turns acceptance into a coincidence.

The exception has to be *one-shot* and it has to *close itself*, or it stops being an exception.
These tests are mostly about the closing.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.capability_bootstrap import (  # noqa: E402
    PROVEN_ONCE_PATH, SEED_ARMED, acceptance_seed_allowed, arm_state,
)


def _seedable(tmp_path: Path) -> Path:
    """A root where every other seed condition holds, so one variable can be changed at a time."""
    (tmp_path / "learning/control_panel").mkdir(parents=True, exist_ok=True)
    (tmp_path / "learning/knowledge_bootstrap").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "learning/workbuddy_escalations.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "config/control_panel_state.json").write_text(
        json.dumps({"operator_intent": "RUNNING"}), encoding="utf-8")
    (tmp_path / "learning/control_panel/pump.json").write_text("{}", encoding="utf-8")
    (tmp_path / "learning/control_panel/gateway.json").write_text(
        json.dumps({"available": True, "reason": "OK"}), encoding="utf-8")
    return tmp_path


def test_a_system_with_nothing_open_may_seed(tmp_path: Path):
    """The intended case: no trace, no job, no lease, operator running, GUI alive, gateway healthy."""
    ok, why = acceptance_seed_allowed(_seedable(tmp_path))
    assert ok is True, why
    assert "冷启动种子条件全部成立" in why


@pytest.mark.parametrize("missing, expect", [
    ("pump", "面板心跳已过期"),
    ("gateway", "网关不是 HEALTHY"),
    ("intent", "操作员当前为"),
])
def test_each_condition_blocks_on_its_own(tmp_path: Path, missing: str, expect: str):
    """A gate that cannot say which condition failed is a gate nobody can act on."""
    root = _seedable(tmp_path)
    if missing == "pump":
        stale = time.time() - 600
        import os
        os.utime(root / "learning/control_panel/pump.json", (stale, stale))
    elif missing == "gateway":
        (root / "learning/control_panel/gateway.json").write_text(
            json.dumps({"available": False, "reason": "HTTP_403"}), encoding="utf-8")
    else:
        (root / "config/control_panel_state.json").write_text(
            json.dumps({"operator_intent": "STOPPED"}), encoding="utf-8")
    ok, why = acceptance_seed_allowed(root)
    assert ok is False
    assert expect in why, why


def test_an_open_trace_means_no_seed_is_needed(tmp_path: Path):
    root = _seedable(tmp_path)
    (root / "learning/workbuddy_escalations.jsonl").write_text(json.dumps({
        "event": "escalation_created", "key": "A|F|S", "capability": "A", "state": "NEW",
        "recorded_at": "2026-09-19T00:00:00+00:00",
    }) + "\n", encoding="utf-8")
    ok, why = acceptance_seed_allowed(root)
    assert ok is False
    assert "不需要种子" in why, why


def test_a_real_production_reuse_closes_the_seed_permanently(tmp_path: Path):
    """§七: the exception exists to produce one proof, and the proof retires it.

    The marker is written the moment the evidence is seen, not on some later start -- an
    exception that survives its own success is a rule.
    """
    root = _seedable(tmp_path)
    (root / "learning/workbuddy_escalations.jsonl").write_text(json.dumps({
        "event": "production_reuse", "key": "A|F|S", "capability": "A",
        "production_reuse_episode_id": "ep-1", "recorded_at": "2026-09-19T00:00:00+00:00",
    }) + "\n", encoding="utf-8")

    ok, why = acceptance_seed_allowed(root)
    assert ok is False
    assert "永久关闭" in why, why
    assert (root / PROVEN_ONCE_PATH).exists(), "the marker must be written, not merely reported"

    # And once the marker exists, the seed stays closed even if the reuse row were gone.
    (root / "learning/workbuddy_escalations.jsonl").write_text("", encoding="utf-8")
    ok, why = acceptance_seed_allowed(root)
    assert ok is False
    assert "已经用过" in why, why


def test_the_seed_arms_the_gate_but_only_after_the_real_ladder(tmp_path: Path):
    """A proven loop still wins, and the seed never overrides a human STOP.

    Order asserted structurally: the ladder is checked first, then the seed, then the operator
    override -- because the seed is a product mechanism, not an operator decision.
    """
    source = (ROOT / "winter_agent_v2/capability_bootstrap.py").read_text(encoding="utf-8")
    body = source[source.find("def arm_state("):source.find("SEED_ARMED = ")]
    ladder = body.find("MAIN_LOOP_P0_PASS")
    seed = body.find("acceptance_seed_allowed(base)")
    override = body.find("OPERATOR_OVERRIDE")
    assert -1 < ladder < seed < override, (ladder, seed, override)

    # And the refusal path still names the outstanding stages rather than going quiet.
    armed, reason, detail = arm_state(tmp_path, p0={"stages": {
        "P0-A 主循环": {"verdict": "PARTIAL"}, "P0-D 验证": {"verdict": "NOT PROVEN"}}})
    assert armed is False
    assert reason == "NOT_ARMED_MAIN_LOOP_P0"
    assert "P0-A=PARTIAL" in detail and "P0-D=NOT PROVEN" in detail


def test_the_seed_reason_is_its_own_name(tmp_path: Path):
    """A reader must be able to tell "armed because proven" from "armed because seeded"."""
    assert SEED_ARMED == "P0_ACCEPTANCE_SEED"
