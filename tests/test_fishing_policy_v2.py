"""FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 (operator directive 2026-09-30).

The directive is a *policy*, not a feature request, and §4 states the distinction in the
terms this project has to keep straight::

    以下Goal不得进入READY：USE_FREE_SPECIAL_FISHING / USE_SPECIAL_FISHING /
    TREASURE_FISHING / USE_TREASURE_TICKET
    统一标记：POLICY_DISABLED_BY_USER
    不是：CAPABILITY_GAP
    因为这是明确策略禁止，不需要WorkBuddy继续开发它。

So there are two failure modes to pin, and they pull in opposite directions:

* the goals must never be *executable* -- the operator forbids special bait, treasure
  tickets and Treasure Mode even when the attempt is free, and the acceptance list is
  ``NORMAL_BAIT_SPECIAL_USED = 0`` / ``GEMS_SPENT = 0`` / ``REAL_MONEY_SPENT = 0``;
* they must never be *advertised as work* -- if a forbidden action shows up in the
  capability-gap ledger, the agent's own development loop will go and build it, which is
  precisely what the operator ruled out.

A third property is what makes both of those hold across a restart: the prohibition lives
in ``config/policy_state.json``, a file this panel rewrites.  ``_save_policy_state`` used
to rebuild that file from scratch and ``__init__`` used to ignore what was saved, so the
prohibition would have been erased within seconds of every panel start.  Measured
2026-09-30 at 09:46:02: the file was rewritten with all eight categories forced on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGISTRY = ROOT / "knowledge/events/event_registry.json"
RULES = ROOT / "knowledge/events/fishing_tournament_rules.json"
POLICY = ROOT / "config/policy_state.json"

SPECIAL_MODE_GOALS = (
    "USE_FREE_SPECIAL_FISHING",
    "USE_SPECIAL_FISHING",
    "TREASURE_FISHING",
    "USE_TREASURE_TICKET",
)


def _registry_record() -> dict:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return next(e for e in payload["events"] if e["event_id"] == "FISHING_TOURNAMENT")


# --------------------------------------------------------------- the registry side


def test_special_mode_is_not_listed_as_a_task() -> None:
    """A forbidden action must not sit in ``tasks``: that list is what feeds the plan."""
    tasks = _registry_record()["tasks"]
    for goal_id in SPECIAL_MODE_GOALS:
        assert goal_id not in tasks, f"{goal_id} is still advertised as a fishing task"


def test_special_mode_is_recorded_as_policy_disabled() -> None:
    """Removing the task is not enough -- the *reason* has to be on file."""
    block = _registry_record()["policy_disabled_tasks"]
    assert block["reason"] == "POLICY_DISABLED_BY_USER"
    assert set(SPECIAL_MODE_GOALS) <= set(block["tasks"])


def test_the_activity_no_longer_advertises_special_mode() -> None:
    """``known_activities`` is the only reader of the registry; it must not carry them."""
    from winter_agent_v2.event_goal import known_activities

    fishing = next(a for a in known_activities() if a.event_id == "FISHING_TOURNAMENT")
    for goal_id in SPECIAL_MODE_GOALS:
        assert goal_id not in fishing.tasks


def test_a_forbidden_task_is_not_reported_as_a_capability_gap() -> None:
    """The whole point of §4: the plan must not list these as unregistered *work*."""
    from winter_agent_v2.event_goal import known_activities
    from winter_agent_v2.goal_library import _registered_activity_flow

    fishing = next(a for a in known_activities() if a.event_id == "FISHING_TOURNAMENT")
    plan = _registered_activity_flow(fishing)
    for goal_id in SPECIAL_MODE_GOALS:
        assert goal_id not in plan["unregistered_skill_ids"], (
            f"{goal_id} is still reported as missing capability, so the development loop "
            "would try to build a capability the operator forbade"
        )


def test_normal_bait_is_the_only_allowed_spend() -> None:
    record = _registry_record()
    assert record["policy"]["allowed_spend"] == ["NORMAL_BAIT"]
    for forbidden in ("special_bait", "treasure_ticket", "gems", "real_money"):
        assert forbidden in record["policy"]["forbidden_spend"]


def test_the_treasure_stage_control_is_marked_undrivable() -> None:
    """The measured coordinate stays as evidence, but must be flagged as not-to-tap."""
    geometry = _registry_record()["entry_geometry_720x1280"]
    assert geometry["treasure_stage_policy"] == "POLICY_DISABLED_BY_USER"


def test_rules_file_carries_the_v2_objective() -> None:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    assert rules["resource_model"]["bait"]["id"] == "NORMAL_BAIT"
    assert rules["levels"]["宝藏关卡"]["policy"] == "POLICY_DISABLED_BY_USER"
    assert rules["levels"]["普通关卡"]["policy"] == "ALLOWED"
    assert rules["policy_v2"]["only_allowed_spend"] == "NORMAL_BAIT"
    assert rules["policy_v2"]["core_metric"] == (
        "points_per_bait = points_gain / normal_bait_used"
    )


# ------------------------------------------------------------- the runtime side


def _bare_runtime():
    """A ``LiveRuntime`` without a device, enough to ask its policy verdict."""
    from winter_agent_v2.runtime import LiveRuntime

    return LiveRuntime.__new__(LiveRuntime)


@pytest.mark.parametrize("goal_id", SPECIAL_MODE_GOALS)
def test_the_runtime_refuses_every_forbidden_goal(goal_id: str) -> None:
    runtime = _bare_runtime()
    assert runtime._policy_allows(goal_id) is False


@pytest.mark.parametrize("goal_id", SPECIAL_MODE_GOALS)
def test_the_refusal_reads_as_the_operators_verdict(goal_id: str) -> None:
    """It must not be reportable as a capability gap, so the reason has to say so."""
    runtime = _bare_runtime()
    assert runtime._policy_refusal(goal_id) == "POLICY_DISABLED_BY_USER"


def test_the_prohibition_wins_over_the_category_default() -> None:
    """No category is assigned to these ids, so the old code returned True early.

    This is the exact defect the directive would have hit: ``_policy_allows`` answered
    ``True`` from the category lookup before it ever read the file.
    """
    runtime = _bare_runtime()
    assert runtime._policy_refusal("USE_FREE_SPECIAL_FISHING") is not None


def test_ordinary_goals_are_untouched_by_the_prohibition() -> None:
    runtime = _bare_runtime()
    for goal_id in ("CLEAR_INTEL", "KEEP_TRAINING_PRODUCTIVE", "CLAIM_FREE_FISHING_REWARD"):
        assert runtime._policy_allows(goal_id) is True


def test_a_paused_category_is_a_different_verdict_from_a_prohibition(tmp_path,
                                                                    monkeypatch) -> None:
    """The two refusals must stay distinguishable, or an audit cannot tell them apart."""
    import winter_agent_v2.runtime as runtime_module

    policy = tmp_path / "policy_state.json"
    policy.write_text(json.dumps({"goal_categories": {"PVE": False}}), encoding="utf-8")
    monkeypatch.setattr(runtime_module, "POLICY_STATE_PATH", policy)

    runtime = _bare_runtime()
    assert runtime._policy_refusal("AVOID_STAMINA_WASTE") == "POLICY_CATEGORY_DISABLED"
    # ...and a category that is on is still allowed, so the switch is not a blanket refusal.
    assert runtime._policy_refusal("CLEAR_INTEL") is None


def test_a_corrupt_policy_file_allows_rather_than_crashing(tmp_path, monkeypatch) -> None:
    """A file a run cannot parse is a gap in the policy, not a reason for the run to die."""
    import winter_agent_v2.runtime as runtime_module

    policy = tmp_path / "policy_state.json"
    policy.write_text("{ truncated", encoding="utf-8")
    monkeypatch.setattr(runtime_module, "POLICY_STATE_PATH", policy)

    runtime = _bare_runtime()
    assert runtime._policy_allows("CLEAR_INTEL") is True


# ------------------------------------------------------------- the policy file side


def test_the_policy_file_names_the_forbidden_goals() -> None:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    disabled = payload["disabled_goals"]
    for goal_id in SPECIAL_MODE_GOALS:
        assert disabled[goal_id] == "POLICY_DISABLED_BY_USER"


def test_a_panel_save_cannot_erase_the_prohibition(tmp_path) -> None:
    """The panel rewrites this file on every start; the merge is what protects §4."""
    from tools.control_panel import read_policy_state, write_policy_state

    path = tmp_path / "policy_state.json"
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "goal_categories": {"日常低保": False},
        "disabled_goals": {g: "POLICY_DISABLED_BY_USER" for g in SPECIAL_MODE_GOALS},
    }), encoding="utf-8")

    write_policy_state(path, goal_categories={"日常低保": True},
                       reward_policy="FREE_CLAIM_FIRST", real_money="PERMANENTLY_BLOCKED")

    after = read_policy_state(path)
    assert after["disabled_goals"] == {g: "POLICY_DISABLED_BY_USER" for g in SPECIAL_MODE_GOALS}
    assert after["goal_categories"] == {"日常低保": True}


def test_saved_categories_survive_a_restart(tmp_path) -> None:
    """``__init__`` used to build every toggle as True and immediately overwrite them."""
    from tools.control_panel import load_policy_categories, write_policy_state

    path = tmp_path / "policy_state.json"
    path.write_text(json.dumps({"goal_categories": {"PVE": False, "限时活动": True}}),
                    encoding="utf-8")
    loaded = load_policy_categories(path, ("PVE", "限时活动", "日常低保"))
    assert loaded == {"PVE": False, "限时活动": True, "日常低保": True}

    # And a save followed by a reload is a fixed point, which it was not before.
    write_policy_state(path, goal_categories=loaded)
    assert load_policy_categories(path, tuple(loaded)) == loaded


def test_an_unreadable_policy_file_keeps_every_category_on(tmp_path) -> None:
    """A broken file is a gap in the policy, never a reason to die or to over-refuse."""
    from tools.control_panel import load_policy_categories, write_policy_state

    path = tmp_path / "policy_state.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_policy_categories(path, ("PVE",)) == {"PVE": True}
    # ...and writing over it still produces a readable file.
    write_policy_state(path, goal_categories={"PVE": True})
    assert load_policy_categories(path, ("PVE",)) == {"PVE": True}


# ----------------------------------------------------------- no execution path leaks


def test_no_code_path_names_a_special_mode_action_as_executable() -> None:
    """Nothing in the package may hold one of these ids as something it can run.

    The knowledge files and this test are the only places allowed to mention them: a hit
    in ``winter_agent_v2/`` or ``tools/`` would mean an executable reference to a
    forbidden action, which is how a policy silently becomes a click.
    """
    offenders: list[str] = []
    for directory in ("winter_agent_v2", "tools"):
        for path in sorted((ROOT / directory).glob("*.py")):
            if path.name == "register_fishing_event.py":
                # The one-shot historical registrar.  It is allowed to *name* the ids because
                # it has to explain why they are absent, and it is not an execution path: it
                # writes the registry, it never drives the device.
                continue
            text = path.read_text(encoding="utf-8")
            for goal_id in SPECIAL_MODE_GOALS:
                if goal_id in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {goal_id}")
    assert not offenders, "forbidden actions referenced as code: " + "; ".join(offenders)
