"""A failed step must say *why* the control was not found.

Measured 2026-10-02 over the day's 1586 production steps: 92 failures, of which 47 were
``SEMANTIC_TARGET_NOT_VERIFIED`` -- every one with an empty ``after_screenshot``, so the step never
reached the device, and **not one** carrying any stated reason.  The ledger could not tell
"the registered locator missed" from "the advisor was never allowed to be asked because its panel
is closed", and the project had been answering that question in source comments instead of in data.

Two layers already knew the answer and both were throwing it away:

* ``executor_router.last_recognition_error`` -- read only by four manual ``tools/device_*.py``;
* ``runtime._unknown_navigation_target``'s own guards -- returning a bare ``None``.

These tests pin the vocabulary, the recorder property (no verdict, no point, changes), and the
episode field that carries it.
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.learning import Episode  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime, _recognition_error  # noqa: E402


class _Holder:
    def __init__(self, owner: str) -> None:
        self.owner = owner


class _Lease:
    def __init__(self, owner: str) -> None:
        self._owner = owner

    def holder(self):
        return _Holder(self._owner)


def _runtime(**attrs) -> LiveRuntime:
    """A runtime with only the attributes ``_unknown_navigation_target`` reads."""
    rt = object.__new__(LiveRuntime)
    rt.role_id = "1061663148"
    rt.role_scope = "FRESH_RUNTIME"
    rt._committed_goal = "AVOID_STAMINA_WASTE"
    rt.execution_mode = "PRODUCTION"
    rt.device_lease = None
    rt._owns_the_lease = lambda holder: False
    rt._unknown_semantic_target = ""
    rt._unknown_skill_id = ""
    rt._advised_learn_context = {}
    rt._advised_request_id = ""
    for key, value in attrs.items():
        setattr(rt, key, value)
    return rt


def _refusal(rt: LiveRuntime, semantic: str, frame: WorldState, skill_id: str) -> str:
    rt._unknown_navigation_target(semantic, frame, Path("frame.png"), skill_id=skill_id)
    return getattr(rt, "_unknown_navigation_refusal", "<not recorded>")


class TheRefusalIsNamedTests(unittest.TestCase):
    """Every guard that returns ``None`` also says which guard it was."""

    def test_a_non_navigation_skill_is_named(self):
        rt = _runtime()
        code = _refusal(rt, "SOMETHING", WorldState(page=Page.MAP), "TRY_ORDINARY_CONTROL")
        self.assertEqual(code, "UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION_OR_TRANSIENT_PAGE")

    def test_a_transient_page_is_named(self):
        rt = _runtime()
        code = _refusal(rt, "BTN_X", WorldState(page=Page.LOADING), "OPEN_SOMETHING")
        self.assertEqual(code, "UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION_OR_TRANSIENT_PAGE")

    def test_a_panel_dependent_target_with_its_panel_closed_is_named(self):
        """The measured 2026-10-02 case: the control is not drawn until its panel is open, so the
        honest answer is about the client's screen, not about the locator."""
        rt = _runtime()
        frame = WorldState(page=Page.MAP, resource_search_open=False)
        code = _refusal(rt, "BEAST_SEARCH_TAB", frame, "OPEN_BEAST_SEARCH_TAB")
        self.assertEqual(code, "UNKNOWN_NAV:PANEL_DEPENDENT_TARGET_PANEL_CLOSED")

    def test_a_missing_committed_goal_is_named(self):
        rt = _runtime(_committed_goal="")
        code = _refusal(rt, "BTN_X", WorldState(page=Page.MAP), "OPEN_SOMETHING")
        self.assertEqual(code, "UNKNOWN_NAV:NO_COMMITTED_GOAL_OR_ROLE")

    def test_a_lease_held_by_someone_else_is_named(self):
        rt = _runtime(device_lease=_Lease("SOMEONE_ELSE"))
        code = _refusal(rt, "BTN_X", WorldState(page=Page.MAP), "OPEN_SOMETHING")
        self.assertEqual(code, "UNKNOWN_NAV:LEASE_HELD_BY_SOMEONE_ELSE")

    def test_development_validation_without_the_lease_is_named(self):
        rt = _runtime(execution_mode="DEVELOPMENT_VALIDATION")
        code = _refusal(rt, "BTN_X", WorldState(page=Page.MAP), "OPEN_SOMETHING")
        self.assertEqual(code, "UNKNOWN_NAV:DEVELOPMENT_VALIDATION_WITHOUT_LEASE")

    def test_a_provider_with_no_answer_is_named_apart_from_a_guard_refusal(self):
        """Every guard permitted the question and the advisor still answered nothing.  That is the
        fact that tells the next reader whether to fix a guard, a provider or a frame."""
        rt = _runtime()
        rt._advised_control = lambda *a, **k: None
        code = _refusal(rt, "BTN_X", WorldState(page=Page.MAP), "OPEN_SOMETHING")
        self.assertEqual(code, "UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING")

    def test_a_provider_that_raises_is_named(self):
        rt = _runtime()

        def boom(*args, **kwargs):
            raise RuntimeError("provider exploded")

        rt._advised_control = boom
        code = _refusal(rt, "BTN_X", WorldState(page=Page.MAP), "OPEN_SOMETHING")
        self.assertEqual(code, "UNKNOWN_NAV:PROVIDER_RAISED")


class TheRecorderIsNotADecisionTests(unittest.TestCase):
    """Recording must not be able to change what the resolver returns."""

    def test_a_provider_that_answers_still_returns_the_same_point_and_clears_the_refusal(self):
        rt = _runtime()
        rt._advised_control = lambda *a, **k: (0.5, 0.25)
        point = rt._unknown_navigation_target(
            "BTN_X", WorldState(page=Page.MAP), Path("frame.png"), skill_id="OPEN_SOMETHING")
        self.assertEqual(point, (0.5, 0.25))
        self.assertEqual(getattr(rt, "_unknown_navigation_refusal", ""), "")

    def test_a_refusal_still_returns_none(self):
        rt = _runtime()
        rt._advised_control = lambda *a, **k: (0.5, 0.25)
        self.assertIsNone(rt._unknown_navigation_target(
            "BTN_X", WorldState(page=Page.MAP), Path("frame.png"), skill_id="NOT_NAVIGATION"))

    def test_the_codes_are_within_one_namespace_so_a_reader_can_filter_on_the_prefix(self):
        rt = _runtime()
        codes = {
            _refusal(rt, "SOMETHING", WorldState(page=Page.MAP), "TRY_ORDINARY_CONTROL"),
            _refusal(_runtime(_committed_goal=""), "BTN_X", WorldState(page=Page.MAP), "OPEN_X"),
            _refusal(rt, "BEAST_SEARCH_TAB", WorldState(page=Page.MAP), "OPEN_BEAST_SEARCH_TAB"),
        }
        self.assertEqual(len(codes), 3)
        for code in codes:
            self.assertTrue(code.startswith("UNKNOWN_NAV:"), code)


class TheEpisodeCarriesItTests(unittest.TestCase):
    def _episode(self, **kwargs) -> Episode:
        return Episode(
            skill="OPEN_X", state_before={}, action={}, state_after={},
            result="FAILURE", failure_type="SEMANTIC_TARGET_NOT_VERIFIED",
            duration=0.03, mode="PRODUCTION", **kwargs,
        )

    def test_the_field_exists_and_defaults_to_empty(self):
        self.assertEqual(self._episode().recognition_error, "")

    def test_it_is_serialised_into_the_ledger_row(self):
        """``EpisodeStore.append`` writes ``asdict(episode)``, so a field that is not in the
        dataclass is a field no reader will ever see."""
        row = asdict(self._episode(recognition_error="UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING"))
        self.assertEqual(row["recognition_error"], "UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING")

    def test_the_router_reason_wins_because_it_names_the_attempt(self):
        self.assertEqual(
            _recognition_error("LIST_DYNAMIC:NO_ROWS", "RESOLVER:LOCATOR_MISSED"),
            "LIST_DYNAMIC:NO_ROWS")

    def test_the_resolver_reason_stands_when_the_router_has_none(self):
        self.assertEqual(
            _recognition_error(None, "UNKNOWN_NAV:PANEL_DEPENDENT_TARGET_PANEL_CLOSED"),
            "UNKNOWN_NAV:PANEL_DEPENDENT_TARGET_PANEL_CLOSED")

    def test_nothing_refused_is_the_empty_string_not_a_word(self):
        self.assertEqual(_recognition_error("", None), "")
        self.assertEqual(_recognition_error(None, None), "")


if __name__ == "__main__":
    unittest.main()
