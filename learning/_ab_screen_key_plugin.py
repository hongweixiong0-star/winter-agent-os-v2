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
    if os.environ.get("AB_CLOSE_BAND", "") == "off":
        from winter_agent_v2.vision import SemanticROIVision

        original = SemanticROIVision.__init__

        def without_the_band(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            original(self, *args, **kwargs)
            self.records = [row for row in self.records if row.get("template_id") != BAND_RECORD_ID]

        SemanticROIVision.__init__ = without_the_band
        print(f"\nAB_CLOSE_BAND=off: {BAND_RECORD_ID} removed from the record list")

    if os.environ.get("AB_SCREEN_KEY", "") != "page":
        return
    from winter_agent_v2 import control_experience as ce

    ce.reusable_on_this_screen = lambda experience, screen: True  # noqa: ARG005
    ce.control_key = lambda page, control, screen="": (  # noqa: ARG005
        f"{ce.label(page) or '?'}|{ce.label(control) or ce.UNNAMED}"
    )
    print("\nAB_SCREEN_KEY=page: the ledger key is the page alone (pre-#109 behaviour)")
