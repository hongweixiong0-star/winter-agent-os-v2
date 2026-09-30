"""Skill repair: when it is allowed to be asked for, and what it is allowed to write.

Directive 2026-10-01 sections 16-17.  The two rules that matter most are both negative -- repair
analysis must not be triggered by failures a screenshot cannot explain, and its answer must not be
able to become a production skill -- so both are pinned here rather than left to the call site.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import skill_repair as sr


def _fail(failure_type: str = "SEMANTIC_TARGET_NOT_FOUND", **overrides):
    row = {
        "skill": "CLAIM_LOGIN_GIFT",
        "verifier_ok": False,
        "failure_type": failure_type,
        "before_screenshot": "f.png",
        "goal_id": "DAILY",
        "recorded_at": "2026-10-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


class TriggerTests(unittest.TestCase):
    def test_one_failure_is_not_a_repair(self):
        self.assertIsNone(sr.should_escalate("S", [_fail()]))

    def test_a_game_state_failure_never_escalates(self):
        """A full march queue is not a perception problem, and a screenshot cannot explain it."""
        rows = [_fail("QUEUE_FULL")] * 6
        self.assertIsNone(sr.should_escalate("S", rows))

    def test_a_run_of_perception_failures_escalates(self):
        rows = [_fail() for _ in range(sr.REPAIR_TRIGGER_FAILURES)]
        trigger = sr.should_escalate("S", rows)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.consecutive_failures, sr.REPAIR_TRIGGER_FAILURES)
        self.assertIn("SEMANTIC_TARGET_NOT_FOUND", trigger.failure_kinds)

    def test_a_pass_resets_the_run(self):
        """A skill that has since worked is not broken; only the *trailing* run counts."""
        rows = [_fail(), _fail(), _fail(), _fail(), {"verifier_ok": True, "result": "SUCCESS"},
                _fail()]
        self.assertIsNone(sr.should_escalate("S", rows))


class ReplyTests(unittest.TestCase):
    def _request(self) -> sr.RepairRequest:
        return sr.RepairRequest(request_id="repair__x__y", skill_id="X", page_key="Y", goal_id="G")

    def test_a_judgement_outside_the_vocabulary_is_refused(self):
        parsed = sr.parse_repair_reply(
            json.dumps({"judgement": "THE_SKILL_IS_BAD", "reason": "r"}), request=self._request()
        )
        self.assertFalse(parsed.ok)
        self.assertIn("REPAIR_JUDGEMENT_UNKNOWN", parsed.error)

    def test_a_pixel_region_is_refused(self):
        """The same 0..1 rule the planner applies: a pixel cannot ride in on the region channel."""
        parsed = sr.parse_repair_reply(
            json.dumps({"judgement": "ENTRY_MOVED", "reason": "r",
                        "candidate_bbox_norm": [340, 812, 60, 40]}),
            request=self._request(),
        )
        self.assertFalse(parsed.ok)
        self.assertIn("REPAIR_BOX_NOT_NORMALISED", parsed.error)

    def test_a_valid_reply_is_read(self):
        parsed = sr.parse_repair_reply(
            json.dumps({"judgement": "TARGET_TEXT_CHANGED", "reason": "r",
                        "new_semantic_target": "领取奖励",
                        "candidate_bbox_norm": [0.4, 0.5, 0.2, 0.06]}),
            request=self._request(),
        )
        self.assertTrue(parsed.ok)
        assert parsed.proposal is not None
        self.assertEqual(parsed.proposal.judgement, "TARGET_TEXT_CHANGED")
        self.assertFalse(parsed.proposal.is_route_change)

    def test_a_route_judgement_is_marked_as_one(self):
        parsed = sr.parse_repair_reply(
            json.dumps({"judgement": "NOT_THIS_PAGE", "reason": "r"}), request=self._request()
        )
        assert parsed.proposal is not None
        self.assertTrue(parsed.proposal.is_route_change)


class WritingTests(unittest.TestCase):
    def _proposal(self) -> sr.RepairProposal:
        return sr.RepairProposal(
            request_id="repair__x__y", skill_id="X", judgement="ENTRY_MOVED",
            reason="the entry is one row lower now", new_semantic_target="活动",
        )

    def test_the_patch_is_a_candidate_and_carries_its_evidence(self):
        """§17: the file has to let a reviewer re-judge it months later, which needs the trigger."""
        with tempfile.TemporaryDirectory() as tmp:
            request = sr.RepairRequest(
                request_id="repair__x__y", skill_id="X", page_key="HOME", goal_id="DAILY",
                old_semantic="ORDINARY_CONTROL[活动]", verifier_expectation="page_is_event",
                failure_kinds=("SEMANTIC_TARGET_NOT_FOUND",), consecutive_failures=3,
            )
            path = sr.file_candidate_patch(self._proposal(), request, out_dir=tmp)
            assert path is not None
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "CANDIDATE_PATCH")
        self.assertEqual(payload["trigger"]["consecutive_failures"], 3)
        self.assertIn("not been grounded", payload["proposed"]["not_yet"])

    def test_the_patch_never_lands_in_the_registry_tree(self):
        """A repair is knowledge about a *skill*, and must not be loadable as one.

        Compared by path *parts* rather than by string: the separator differs on Windows, and a
        string check would pass on one platform and fail on the other for no real reason.
        """
        parts = sr.CANDIDATE_PATCH_DIR.parts
        self.assertEqual(parts[:3], ("knowledge", "skills", "repairs"))
        self.assertNotIn("registry", parts)
        # The one directory a skill loader walks is ``knowledge/skills`` itself; a patch lives one
        # level below it, under a name that says what it is.
        self.assertNotEqual([*parts][-1], "skills")


if __name__ == "__main__":
    unittest.main()
