"""Backend provenance must answer its own question, on every path.

Origin: WB-EXECUTOR-EVIDENCE-AUDIT (2026-09-15).  An audit of the day's 280
production episodes found 271 complete and 9 not, and the 9 split into three
causes -- two of them defects in the current write path, both fixed here:

Cause 1 -- six failed TAP_SEMANTIC steps whose target never resolved all
reported ``capture_backend=""`` while a real before frame sat on disk.  The field
is documented as "the channel that produced THIS episode's frames", but the
runtime gated it on ``execution.executed``, which is a different question.  Empty
already meant "no action reached a backend", so two meanings collapsed into one
value and neither could be read.

Cause 2 -- two successful BACK steps reported ``recognition_backend=""`` while
their sibling MAA steps reported ``"NONE"``.  The router says NONE for a system
key; the bare executor omitted the argument.  So the same action recorded
different provenance depending on which path ran it.

The third cause (a SAFE_STOP that issued nothing at all) is correct as it stands
and is asserted here too, so the fix is not mistaken for "every field must be
non-empty".
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.executor import Executor
from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.models import Action, Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


class _Device:
    """Minimal device. ``capture_backend`` is what the episode should report."""

    capture_backend = "MAA_MUMU_EXTRAS"

    def __init__(self, connected: bool = True):
        self._connected = connected
        self.backs = 0
        self.taps = []

    def status(self):
        return type(
            "S", (), {"connected": self._connected, "resolution": (720, 1280) if self._connected else None}
        )()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs += 1

    def swipe(self, *a, **k):
        pass

    def screenshot(self, path):
        path.touch()
        return path


class CauseTwoTheSystemKeyDeclaresNoRecognitionTests(unittest.TestCase):
    def test_press_back_reports_none(self):
        device = _Device()
        result = Executor(production=True, dry_run=False, device=device).execute(Action("PRESS_BACK"))
        self.assertTrue(result.executed)
        self.assertEqual(result.recognition_backend, "NONE")

    def test_a_semantic_tap_still_reports_its_real_recogniser(self):
        # Negative control: the fix must not blanket-label everything NONE.
        device = _Device()
        result = Executor(
            production=True,
            dry_run=False,
            device=device,
            target_resolver=lambda semantic: (0.5, 0.5) if semantic == "BTN_X" else None,
        ).execute(Action("TAP_SEMANTIC", "BTN_X"))
        self.assertTrue(result.executed)
        self.assertEqual(result.recognition_backend, "V2")

    def test_a_failed_action_still_reports_no_backend(self):
        # Cause 1's other half, asserted so the fix cannot overreach: an action
        # that never reached a backend must keep saying so.
        device = _Device()
        result = Executor(
            production=True, dry_run=False, device=device, target_resolver=lambda _s: None
        ).execute(Action("TAP_SEMANTIC", "BTN_MISSING"))
        self.assertFalse(result.executed)
        self.assertEqual(result.backend, "")
        self.assertEqual(result.capture_backend, "")
        self.assertEqual(result.recognition_backend, "")


class _NoMatch:
    def find(self, _path, _semantic):
        return None

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _Vision:
    def __init__(self, states):
        self.states = list(states)

    def observe(self, _path):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


class CauseOneTheFramesStillHaveAChannelTests(unittest.TestCase):
    """Assert on the recorded Episode: `LiveStep` carries no backend fields.

    The store is pointed at a temporary file on purpose.  ``LiveRuntime`` skips
    episode recording entirely when no store is given, so these tests can never
    append to ``learning/episodes.jsonl``.
    """

    def _episodes(self, states, allowed, brain=None):
        device = _Device()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "episodes.jsonl"
            LiveRuntime(
                device=device,
                vision=_Vision(states),
                semantic_vision=_NoMatch(),
                capture_dir=Path(temp),
                brain=brain or RuleBrain(current_goal="INTEL"),
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(path),
            ).run(max_actions=1, allowed_skills=allowed)
            if not path.exists():
                return device, []
            return device, [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]

    def test_a_failed_action_still_reports_which_channel_captured_its_frames(self):
        map_state = WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99)
        _, episodes = self._episodes([map_state, map_state], {"OPEN_INTEL"})

        self.assertEqual(len(episodes), 1, "exactly one step should be recorded")
        ep = episodes[0]
        self.assertEqual(ep["result"], "FAILURE")
        self.assertEqual(ep["failure_type"], "SEMANTIC_TARGET_NOT_VERIFIED")
        # The frames exist, so the field that describes them must not be blank.
        self.assertEqual(ep["capture_backend"], "MAA_MUMU_EXTRAS")
        # ...and the fact that nothing reached a backend is still reported.
        self.assertEqual(ep["executor_backend"], "")

    def test_a_safe_stop_never_becomes_an_episode(self):
        """The third audit cause cannot be produced by the runtime at all.

        Today's one all-empty-backend row (``codex_0ba_20260915_1230``,
        SAFE_STOP / NO_EXECUTION) therefore came from another writer.  Pinned
        here because it matters to anyone computing failure rates from the
        stream: the runtime returns at ``runtime.py`` before ``_record_episode``
        for SAFE_STOP, so an all-empty row is not a runtime artefact.
        """
        card = WorldState(
            page=Page.BEAST,
            beast={
                "name": "大师悬赏",
                "level": 20,
                "available": False,
                "blocked_reason": "POWER_BELOW_RECOMMENDED",
            },
            confidence=0.99,
        )
        # The once-per-run guard is pre-set so the brain answers SAFE_STOP.
        brain = RuleBrain(current_goal="INTEL")
        brain.beast_card_not_actionable_left = True
        _, episodes = self._episodes([card, card], {"BACK"}, brain=brain)

        self.assertEqual(episodes, [], "a SAFE_STOP step must not be recorded as an episode")

    def test_a_blocked_card_without_the_guard_still_records_its_back(self):
        # Contrast with the test above: the same page, before the guard is set,
        # produces a BACK step that *is* recorded -- and now carries a capture
        # channel because a real frame exists.
        card = WorldState(
            page=Page.BEAST,
            beast={
                "name": "大师悬赏",
                "level": 20,
                "available": False,
                "blocked_reason": "POWER_BELOW_RECOMMENDED",
            },
            confidence=0.99,
        )
        map_state = WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99)
        _, episodes = self._episodes([card, map_state], {"BACK"})

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["skill"], "BACK")
        self.assertEqual(episodes[0]["capture_backend"], "MAA_MUMU_EXTRAS")


if __name__ == "__main__":
    unittest.main()
