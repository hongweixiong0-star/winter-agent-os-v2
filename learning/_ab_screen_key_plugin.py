"""A/B the two halves of the close-popup fix under pytest, without touching git or the manifest.

``AB_SCREEN_KEY=page`` makes this tree behave as it did before issue #109 was fixed: the ledger key
loses the screen and the reuse guard always agrees.

``AB_CLOSE_BAND=off`` removes the searching ``BTN_CLOSE`` record (``btn_close__popup_titlebar_band__0``)
from the vision layer's record list in memory, so a test that fails only *with* the new locator can
be told apart from one that was already red.  Nothing on disk is touched, which matters because the
running AUTO reads that manifest at process start.

A plugin rather than a script because the comparison has to happen in the same runner --
``tests/test_live_runtime.py`` reads ``knowledge/**``, which the running AUTO rewrites, so comparing
a pytest run against a unittest run compares the runner, not the change.

Usage:
    AB_SCREEN_KEY=page PYTHONPATH=learning pytest tests/test_live_runtime.py -p _ab_screen_key_plugin
    AB_CLOSE_BAND=off PYTHONPATH=learning pytest tests/test_march_recall_and_stamina.py -p _ab_screen_key_plugin
"""

from __future__ import annotations

import os

BAND_RECORD_ID = "btn_close__popup_titlebar_band__0"


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest's hook signature
    if os.environ.get("AB_ENTRY_GATE", "") == "off":
        from winter_agent_v2 import entry_badges as eb
        from winter_agent_v2 import goal_library

        # The pre-change semantics, stated site by site rather than approximated: the goal layer was
        # not gated at all, the mail branch skipped only on a readable ABSENT, and the gifts branch
        # opened the panel whatever the tile said.  A single "always PRESENT" patch would have
        # reproduced neither (it would have broken the one mail case that already worked), and a
        # baseline that is not the real baseline is worse than none.
        goal_library.entry_badges.ENTRY_GATED_GOALS = {}

        def _old_semantics(goal_id, red_dots):  # noqa: ANN001
            if str(goal_id) == "MAIL_ROUTINE":
                state = str(((red_dots or {}).get("BTN_OPEN_MAIL") or {}).get("state") or "")
                return ("ABSENT", ()) if state == "ABSENT" else ("PRESENT", ())
            return ("PRESENT", ())

        eb.entry_gate = _old_semantics  # type: ignore[assignment]
        print("\nAB_ENTRY_GATE=off: the entry badge decides nothing (pre-change behaviour)")

    if os.environ.get("AB_UNRESOLVED_GUARD", "") == "off":
        from winter_agent_v2.runtime import LiveRuntime

        # A bound out of reach makes the guard inert, which is the pre-change behaviour: the same
        # control is re-derived for every goal until the board runs out of goals.
        LiveRuntime.MAX_UNRESOLVED_ATTEMPTS = 10 ** 9
        print("\nAB_UNRESOLVED_GUARD=off: a resolved-to-nothing control is re-derived as before")

    if os.environ.get("AB_CLOSE_BAND", "") == "off":
        from winter_agent_v2.vision import SemanticROIVision

        original = SemanticROIVision.__init__

        def without_the_band(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            original(self, *args, **kwargs)
            self.records = [row for row in self.records if row.get("template_id") != BAND_RECORD_ID]

        SemanticROIVision.__init__ = without_the_band
        print(f"\nAB_CLOSE_BAND=off: {BAND_RECORD_ID} removed from the record list")

    if os.environ.get("AB_WINDOW_STATUS", "") == "off":
        from winter_agent_v2 import goal_library as gl

        # This round's change, reverted at the module boundary: the five sites that now name a
        # window or a game condition used to collapse it into READY/COMPLETE, and a known activity
        # was not on the board at all unless the current frame printed it.
        #
        # The remap is exact rather than approximate, and that is checkable: before this round
        # *nothing* in production set SCHEDULED_NOT_OPEN, EXPIRED or BLOCKED -- only tests
        # constructed BLOCKED by hand -- so mapping those three back to the label each site used to
        # write reproduces the old board rather than paraphrasing it.
        gl.GoalLibrary._append_known_activities = staticmethod(lambda goals: None)  # noqa: ARG005
        _legacy_names = {
            gl.GoalStatus.SCHEDULED_NOT_OPEN: gl.GoalStatus.READY,
            gl.GoalStatus.EXPIRED: gl.GoalStatus.COMPLETE,
            gl.GoalStatus.BLOCKED: gl.GoalStatus.COMPLETE,
        }
        _real_goal_state = gl.GoalState

        def _legacy_goal(*args, **kwargs):  # noqa: ANN002, ANN003
            if "status" in kwargs:
                kwargs["status"] = _legacy_names.get(kwargs["status"], kwargs["status"])
            elif len(args) >= 2:
                args = (args[0], _legacy_names.get(args[1], args[1]), *args[2:])
            return _real_goal_state(*args, **kwargs)

        gl.GoalState = _legacy_goal  # type: ignore[assignment]
        print("\nAB_WINDOW_STATUS=off: a window or a game condition is labelled READY/COMPLETE again")

    if os.environ.get("AB_SCREEN_KEY", "") != "page":
        return
    from winter_agent_v2 import control_experience as ce

    ce.reusable_on_this_screen = lambda experience, screen: True  # noqa: ARG005
    ce.control_key = lambda page, control, screen="": (  # noqa: ARG005
        f"{ce.label(page) or '?'}|{ce.label(control) or ce.UNNAMED}"
    )
    print("\nAB_SCREEN_KEY=page: the ledger key is the page alone (pre-#109 behaviour)")
