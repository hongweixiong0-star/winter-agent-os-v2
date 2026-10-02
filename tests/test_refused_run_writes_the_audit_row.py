"""End to end: a run that ends on a refusal writes the audit row, on the device's own reason.

The gate widened in ``4851086`` is one comparison, and the test that covers it
(``tests/test_no_repeated_look_around.py``) exercises the *old* admission -- the
``NOTHING_LEFT_TO_LOOK_AT`` run.  So the path this file exists for is untested end to end: a
run whose last step is an ordinary ``SAFE_STOP`` for a reason that has nothing to do with
looking around.

That is the shape the 11.5% orphan rate was made of, measured 2026-10-03: three consecutive
Scheduler choices at 15:59:38 / :41 / :45, each an activity goal selected in the city where
the client drew no 常规活动 entry, each answered ``SAFE_STOP
event_route_goal_in_city_but_no_activity_entry_observed``, and none of the three left a row
in any of the three ledgers.  ``decisions.jsonl`` said the goal won; ``episodes.jsonl`` may
not carry it (``test_a_safe_stop_never_becomes_an_episode``); and the refusal reason itself
appears nowhere.

Why drive the runtime rather than assert on the gate's inputs: the predicate reads
``steps[-1]`` and ``audit_pages``, both of which are built deep inside ``run``.  A test that
calls the helper with hand-made values would pass while the run never populates them, which
is exactly the shape of failure this project keeps meeting -- a reader that is correct and
never called.

The client here is the project's own two-page stub, and the brain is the real ``RuleBrain``.
Only the scheduler's choice is forced, because forcing the whole chain would be testing a
different thing: what is under test is "the run ended on a refusal and the row appeared".
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import observation_store  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.capability_gate import DEFERRED, Deferral  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402


class _OnlyActivityGoalIsRunnable:
    """Defers everything except an activity goal, so one is genuinely selected.

    Constructing ``RuleBrain(current_goal="EVENT")`` is not enough: ``_sync_brain_goal``
    overwrites ``current_goal`` from the ranked board on every step, which is the runtime
    behaving correctly.  So the selection has to come from the board, and this gate is what
    puts an activity goal on it -- everything else is deferred, exactly as
    ``_EverythingDeferred`` does in the neighbouring test.
    """

    capabilities: dict = {}

    def blocks(self, goal, *, now=None):  # noqa: D102
        if str(goal.goal_id).startswith("SCHEDULED_"):
            return None
        return Deferral(goal_id=goal.goal_id, state=DEFERRED,
                        reason="this gate defers everything that is not an activity goal")




class _OnePageClient:
    """A client that stays in the city and offers nothing the brain can act on.

    It answers every observation with the same HOME frame, so the brain's activity-route
    branch is reached and refuses -- which is the production case, not a contrived one.
    """

    SIZE = (720, 1280)

    def __init__(self):
        self.page = Page.HOME
        self.taps = []
        self.backs = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": self.SIZE})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, *args, **kwargs):
        self.taps.append("swipe")

    #: The calendar row the client is drawing.  It is what puts a ``SCHEDULED_`` goal on the
    #: board, which is the only way an activity goal can be selected in this test -- the board
    #: is rebuilt from the frame on every step, and the runtime overwrites ``current_goal``
    #: from it, so a goal that is not discovered cannot be the one that refuses.
    CALENDAR_ROW = {"event_id": "ICEBOUND_TREASURE", "display_name": "冰封的宝藏"}

    def observe(self, _path):
        return WorldState(
            page=self.page, confidence=0.99, march_used=1, march_max=6,
            events={"calendar": {"recognized": True, "kind": "CALENDAR_GRID",
                                 "source": "LIVE_CLIENT_OCR",
                                 "entries": [dict(self.CALENDAR_ROW)]}},
        )

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def find(self, _path, semantic):
        return None

    def resource_cell_center_norm(self, _region):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _region):
        return 0.0


class ARefusedRunIsAuditedTests(unittest.TestCase):
    """The refusal row, produced by a real ``LiveRuntime.run`` rather than asserted."""

    def _run(self):
        client = _OnePageClient()
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            empty = temp / "observations.json"
            empty.write_text("{}", encoding="utf-8")
            previous = observation_store.STATE_PATH
            observation_store.STATE_PATH = empty
            try:
                brain = RuleBrain(current_goal="EVENT")
                brain.goal_id = "SCHEDULED_BROTHERS_IN_ARMS"
                audit_path = temp / "fruitless_run_audit.jsonl"
                result = LiveRuntime(
                    device=client,
                    vision=client,
                    semantic_vision=client,
                    capture_dir=temp / "captures",
                    sleeper=lambda _seconds: None,
                    episode_store=None,
                    capability_gate=_OnlyActivityGoalIsRunnable(),
                    fruitless_audit_path=audit_path,
                    brain=brain,
                ).run(max_actions=1, allowed_skills=frozenset({"OPEN_MAP", "BACK"}))
                rows = (
                    [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
                    if audit_path.exists() else []
                )
            finally:
                observation_store.STATE_PATH = previous
        return result, rows

    def test_a_run_that_ends_on_a_refusal_leaves_an_audit_row(self):
        result, rows = self._run()
        self.assertEqual(
            str(result.steps[-1].decision.skill), "SAFE_STOP",
            "this file tests the refusal path; if the run stopped for another reason it is "
            "exercising something else and the assertions below prove nothing",
        )
        self.assertEqual(
            len(rows), 1,
            f"a run that ended on a refusal must leave exactly one audit row, got {rows}",
        )

    def test_the_row_says_which_goal_was_refused_and_why(self):
        """The two facts that make the row worth having, and the ones nothing else records.

        The goal is asserted by shape rather than by name.  Which activity the board ranks
        first is the goal layer's business -- the calendar row this client draws produces
        every registered activity, not one -- and pinning a name here would make the test
        fail the day a registration is added, without anything about the audit having
        changed.
        """
        _result, rows = self._run()
        row = rows[0]
        per_page = row["per_page"][-1]
        self.assertEqual(per_page["attempted_skill"], "SAFE_STOP")
        self.assertEqual(per_page["verifier_result"]["status"], "NOT_ATTEMPTED")
        self.assertTrue(per_page["attempted_reason"], "a refusal with no reason says nothing")
        self.assertEqual(row["final_reason"], per_page["attempted_reason"])
        self.assertTrue(
            str(row["scheduler"]["selected_goal"]).startswith("SCHEDULED_"),
            "the refused goal is named, so an operator can see which one the loop gave up on",
        )
        # And it is the same goal the board selected -- the row is about this run's choice,
        # not a stale one.
        self.assertEqual(row["scheduler"]["selected_goal"], row["goal_id"])


    def test_the_refusal_is_not_an_episode(self):
        """The other half of the contract, checked here rather than assumed.

        ``test_a_safe_stop_never_becomes_an_episode`` pins this in the abstract; this run
        produces a real refusal, so it is the place to confirm the row went to the audit and
        not to the execution ledger.
        """
        result, _rows = self._run()
        for step in result.steps:
            self.assertIsNone(
                getattr(step, "execution", None),
                "a refusal issued nothing, and an episode claiming otherwise would corrupt "
                "every failure rate computed from the stream",
            )

    def test_a_refusal_mid_run_is_recorded_even_when_the_run_carries_on(self):
        """The shape the device actually produces, and the one the first gate missed.

        Measured 2026-10-02 16:20-16:44 on production, after the first version of the gate
        shipped: five runs, **none ending on a refusal** -- MAX_ACTIONS_REACHED twice (23 and
        22 steps), ROLE_SWITCHED_TO three times -- while ten Scheduler choices in the same
        window went to an episode for a different goal.  ``_yield_to_next_goal`` holds a
        refused goal back and the cycle continues, so a gate that asks "did the run *end* on a
        refusal" never fires: ``append_fruitless_audit`` is only called from ``finish``, and
        that run's finish reason was MAX_ACTIONS_REACHED.

        So the row is written for a run that refused *anything*, and the refusals are named
        at the top level -- a run that ends on MAX_ACTIONS_REACHED would otherwise report
        only its ending, and "what did it decline, and why" needs one hop rather than a scan
        through every page.  One row per run is the contract; the refusals are a list inside it.
        """
        result, rows = self._run()
        self.assertEqual(len(rows), 1, "still one row per run, whatever the run refused")
        refusals = rows[0]["refusals"]
        self.assertTrue(refusals, "a run that refused must name the refusal")
        for entry in refusals:
            self.assertTrue(entry["reason"], "each refusal carries its own reason")
            self.assertIn("page", entry)
            self.assertIn("goal_id", entry)
        # The refusals came out of per_page, so the two cannot disagree.
        from_page = [
            page for page in rows[0]["per_page"]
            if str(page.get("attempted_skill") or "") == "SAFE_STOP"
        ]
        self.assertEqual(len(refusals), len(from_page))

