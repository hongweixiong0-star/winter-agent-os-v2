"""Select the giant-beast tab only when the frame actually draws it.

Measured 2026-10-05 over the retained ledger, goal ``AVOID_STAMINA_WASTE``, skill
``SELECT_GIANT_BEAST_TAB``:

* 139 episodes, 128 of them FAILED with no goal progress;
* **106** carried ``action = {}`` and ``MAP -> None`` -- nothing was dispatched and no
  after-frame was read -- signed ``SEMANTIC_TARGET_NOT_VERIFIED``, about once every 30-60
  minutes from 10-02 to 10-05, still firing minutes before the fix;
* the other 33 did dispatch (``TAP_SEMANTIC GIANT_BEAST_SEARCH_TAB``, ``MAP -> MAP``), so the
  branch works when the tab is drawn.

``WorldState.resource_giant_beast_tab_norm`` is documented as "where the client drew the
冰原巨兽 tab", written from this frame's own OCR tab labels -- so ``None`` means the tab is
not on screen, which is exactly what the skill needs in order to have a target.  Every other
branch of ``_polar_step`` reads what the client drew (``words``, ``resource_selected_tab``,
``card``); this one did not.
"""

import unittest
from types import SimpleNamespace

from winter_agent_v2.models import Page
from winter_agent_v2.session_adapters import BearDomain, BearSessionAdapter
from winter_agent_v2.session_engine import STEP_OBSERVE_ONLY, STEP_SKILL

TAB = (0.31, 0.42)


def world(*, search_open=True, giant_tab_norm=None, selected_tab="MEAT"):
    return SimpleNamespace(
        page=Page.MAP,
        resource_search_open=search_open,
        resource_selected_tab=selected_tab,
        resource_giant_beast_tab_norm=giant_tab_norm,
        beast_search_result={},
    )


def domain(w):
    return BearDomain(world=w, rows=(), target="BEAR", joinable=(), list_visible=False,
                      idle_marches=2)


def polar_adapter():
    adapter = BearSessionAdapter()
    adapter._stamina_polar = True
    adapter._polar_words = ()
    return adapter


HOST = SimpleNamespace(now=lambda: 0.0)


def choose(w):
    return polar_adapter().choose_step(None, HOST, domain(w))


class TheGiantTabIsSelectedOnlyWhenDrawn(unittest.TestCase):
    def test_the_skill_is_dropped_when_the_frame_does_not_draw_the_tab(self):
        """The measured case: 106 dispatches with no action and no after-frame."""
        step = choose(world(giant_tab_norm=None))
        self.assertIsNotNone(step)
        self.assertNotEqual(step.kind, STEP_SKILL)
        self.assertEqual(step.kind, STEP_OBSERVE_ONLY)

    def test_the_skill_is_still_chosen_when_the_tab_is_drawn(self):
        step = choose(world(giant_tab_norm=TAB))
        self.assertIsNotNone(step)
        self.assertEqual(step.kind, STEP_SKILL)
        self.assertEqual(step.skill_id, "SELECT_GIANT_BEAST_TAB")

    def test_the_guard_is_about_the_tab_not_about_the_panel(self):
        """A closed panel keeps its own path; this guard must not swallow it."""
        step = choose(world(search_open=False, giant_tab_norm=None))
        self.assertIsNotNone(step)
        self.assertNotEqual(step.skill_id, "SELECT_GIANT_BEAST_TAB")

    def test_an_already_selected_giant_tab_is_untouched(self):
        """The earlier branch for a selected tab still wins."""
        step = choose(world(giant_tab_norm=TAB, selected_tab="GIANT_BEAST"))
        self.assertIsNotNone(step)
        self.assertNotEqual(step.skill_id, "SELECT_GIANT_BEAST_TAB")


if __name__ == "__main__":
    unittest.main()
