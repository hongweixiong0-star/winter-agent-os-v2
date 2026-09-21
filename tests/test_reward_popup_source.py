"""The client's shared 获得奖励 dialog must not be labelled by its contents.

Defect (measured 2026-09-16T23:53Z and 2026-09-17T00:26Z).  Two live Intel runs
claimed a reward successfully and then failed on the *dismiss* step:

    step 3  INTEL_CLAIM_REWARDS  INTEL -> POPUP  verifier OK   (a reward was claimed)
    step 4  DISMISS_DAILY_REWARD -> INTEL        verifier FALSE
            DAILY_REWARD_ADVANCE_NOT_PROVEN                     (exit 2)

The cause was not the tap: the tap worked and returned to the Intel page.  It was
the label.  ``vision.py`` tested ``POPUP_DAILY_REWARD_CURRENT`` before the generic
banner, and that record's ROI is the whole reward-GRID area
(x 0.08 y 0.20 w 0.84 h 0.40), so it answers "do these items look like the ones I
was cut from" -- a content question -- instead of "who produced this dialog".  It
matched 8 of 8 production frames that carried a reward popup over a non-daily
page, so a reward popup over the Intel page read ``DAILY_REWARD``, the brain
routed it to the *daily* dismiss, and that verifier -- which requires the DAILY
page afterwards -- rejected a dismissal that had actually worked.

What the artwork can and cannot say, measured over 103 labelled production
frames (65 GENERIC_REWARD / 18 INTEL_REWARD / 12 EXPLORATION_REWARD /
8 labelled DAILY_REWARD):

    semantic                          DAILY  EXPLOR  GENERIC  INTEL
    BTN_DISMISS_INTEL_REWARD (footer)    8/8   12/12    65/65  17/18
    POPUP_GENERIC_REWARD_HEADER          5/8    8/12    64/65   1/18
    POPUP_INTEL_REWARD_TITLE (gate 22)   6/8   10/12    58/65  17/18
    POPUP_DAILY_REWARD_CURRENT           8/8    0/12     0/65   0/18
    POPUP_EXPLORATION_REWARD             7/8   12/12     1/65   0/18

(The ``POPUP_INTEL_REWARD_TITLE`` row is historical: that signal is no longer
consulted at all, see "The same class, one signal later" below.)

Only the footer is present on essentially every one of them (102/103 at
distance <= 2).  Neither the banner nor any grid template identifies a source --
the same dialog is simply drawn for all of them, which is why
``verifier.py`` already carries the comment "the source is therefore proven by
the *before* state ... any reward popup counts as the feedback" and why
``REWARD_POPUPS`` deliberately omits ``DAILY_REWARD``.

So ``vision.py`` now reports the goal-neutral label from the source-independent
signals and lets the brain choose the dismiss from goal context, which is what
every ``*_reward_dismissed`` verifier was already written to accept.

The same class, one signal later (2026-09-20)
--------------------------------------------
The grid template was removed, but the branch that had consulted it was also
consulting a second content crop -- ``POPUP_INTEL_REWARD_TITLE``, ROI
x 0.30 y 0.215 w 0.40 h 0.085, the peach title band of the same dialog -- and
that one carried its own tolerance of 22 in ``semantic_max_distance``.  On the
mail inbox the band lands across the mail list, and the rows there are the same
peach colour, so the crop answered "there is a peach band here" and the frame
became ``POPUP / INTEL_REWARD``.  The executor then asked for
``POPUP_GENERIC_REWARD_HEADER``, which is not on the frame, returned
``SEMANTIC_TARGET_NOT_VERIFIED`` without tapping, the verifier never ran, and
the panel re-armed 30 s later: ~20 identical rounds under ``AUTO`` and, under
the other skill name, the whole of ``DISMISS_INTEL_REWARD``'s 35 all-time
failures.

Measured over all 6747 corpus frames (``tools/probe_reward_popup_gate.py``):

    POPUP_INTEL_REWARD_TITLE (gate 22)
      217 frames carrying the shared dialog   min 0   p50 18  max 26
      304 frames carrying the mail inbox      min 20  p50 30  (70 at d=20)

The populations overlap on 20..26, so no tolerance separates them: 22 excluded
the mail page only by luck, and a gate of 19 would already have cost 85 of the
217 real dialogs.  The separator is the page identity, which matches the mail
frame at distance 0, and the whole-dialog ``POPUP_INTEL_REWARD``, which is the
only content signal that separates *at its gate* (61 frames at <=8, every one of
them also carrying the dialog chrome, and 0 mail frames at <=8 at all).  The
title crop is therefore no longer consulted anywhere, and the branch is now the
fallback for a dialog whose chrome is degraded rather than a second way to name
Intel.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.image_hash import hamming, phash
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import (
    verify_daily_reward_advanced,
    verify_intel_reward_dismissed,
    verify_popup_closed,
)
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
KEY = ROOT / "dataset" / "truth_audit" / "reward_popup_source_20260917" / "key"

# One frame per source, all three the same dialog.
DAILY_POPUP = KEY / "01_daily_reward_popup_163338.png"
INTEL_POPUP_RUN1 = KEY / "02_intel_reward_popup_run1.png"
INTEL_POPUP_RUN2 = KEY / "03_intel_reward_popup_run2.png"
POPUPS = (DAILY_POPUP, INTEL_POPUP_RUN1, INTEL_POPUP_RUN2)

# The mail inbox the AUTO loop burned ~20 rounds on (2026-09-20): title 邮件,
# 系统 tab selected, a list of claimable rewards, and 一键已读&领取 along the
# bottom.  There is no dialog on it at all.
MAIL_INBOX = (
    ROOT / "dataset" / "raw" / "control_panel" / "runtime_auto"
    / "20260920_123335_422288"
    / "20260920_123335_422288_step_001_before_20260920T043338114548.png"
)

# The footer that is drawn on every one of them.  Its manifest name mentions
# Intel because it was registered from an Intel frame; the measurement above is
# what shows the name is a misnomer.
FOOTER = "BTN_DISMISS_INTEL_REWARD"
BANNER = "POPUP_GENERIC_REWARD_HEADER"
GRID = "POPUP_DAILY_REWARD_CURRENT"
TITLE = "POPUP_INTEL_REWARD_TITLE"
WHOLE_DIALOG = "POPUP_INTEL_REWARD"

# The frame the 2026-09-20 outage happened on, archived as evidence rather than
# read from the live capture directory the panel's retention trims (issue #46:
# a test that reads those frames changes its own verdict depending on when it
# runs).  See dataset/truth_audit/reward_popup_exit_20260920/README.md.
EXIT_FRAME = (
    ROOT / "dataset" / "truth_audit" / "reward_popup_exit_20260920" / "key"
    / "01_shared_reward_popup_step_001_before_20260920T124146.png"
)
FOOTER_BOX = (214, 1135, 510, 1175)
BANNER_BOX = (180, 215, 545, 310)

# The bare world map the 2026-09-21 run burned seven dismiss steps on.  Archived,
# not read live, for the retention reason above (issue #46).
_BARE_MAP_DIR = (
    ROOT / "dataset" / "truth_audit" / "reward_popup_band_false_positive_20260921" / "key"
)
BARE_MAP_FRAMES = (
    _BARE_MAP_DIR / "01_bare_map_band_false_positive_step_007_before_20260921T113000717351.png",
    _BARE_MAP_DIR / "02_bare_map_band_false_positive_step_006_before_20260921T112959358612.png",
)

# The two reviewed BANNER parents: real 获得奖励 dialogs, each a full-screen dim.
DIALOG_FRAME = (
    ROOT / "dataset" / "raw" / "live_deploy_mail_generic_reward_v2" / "step_006_before.png"
)
DIALOG_FRAME_2 = ROOT / "dataset" / "raw" / "live_20260908_daily_reward.png"


def _hud_strip_std(frame: Path) -> float:
    """The standard deviation of the top 5% of the frame.

    This is the measurement ``vision.an_overlay_covers_the_screen`` gates on: a
    dimmed HUD is near-flat as well as near-black, so the spread separates the
    two populations more widely than the mean does.
    """
    import numpy as np

    with Image.open(frame) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        strip = np.asarray(image.crop((0, 0, width, max(1, int(0.05 * height)))))
    return float(strip.astype("float32").std())


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


def _records(semantic: str) -> list[dict]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [row for row in payload["records"] if row.get("semantic") == semantic]


def _raw_distance(frame: Path, semantic: str) -> int:
    """The distance ``find`` would compute for ``semantic``, gate or no gate.

    ``find`` returns None above the tolerance, which is exactly the value under
    test when a gate is removed; measuring the distance itself keeps the pinned
    evidence independent of whatever tolerance is declared.
    """
    best = None
    with Image.open(frame) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        for row in _records(semantic):
            roi = row["roi_norm"]
            box = (
                round(roi["x_norm"] * width),
                round(roi["y_norm"] * height),
                round((roi["x_norm"] + roi["w_norm"]) * width),
                round((roi["y_norm"] + roi["h_norm"]) * height),
            )
            with Image.open(row["template_path"]) as template:
                distance = hamming(phash(image.crop(box)), phash(template.convert("RGB")))
            best = distance if best is None else min(best, distance)
    assert best is not None, f"{semantic} has no phash record in the manifest"
    return best


def _decide(world: WorldState, goal: str):
    return RuleBrain(current_goal=goal).decide(world, v2_registry())


class TheSharedDialogIsLabelledByItsSignalsNotItsContentsTests(unittest.TestCase):
    def test_every_source_reads_the_shared_label(self):
        """A daily popup and an Intel popup are the same dialog, so they agree."""
        vision = _vision()
        for frame in POPUPS:
            with self.subTest(frame=frame.name):
                state = vision.observe(frame)
                self.assertIs(state.page, Page.POPUP)
                self.assertEqual(state.popup, "GENERIC_REWARD")

    def test_the_footer_is_drawn_on_all_of_them(self):
        """It is the one signal present whatever produced the dialog."""
        vision = _vision()
        for frame in POPUPS:
            with self.subTest(frame=frame.name):
                match = vision.semantic.find(frame, FOOTER)
                self.assertIsNotNone(match)
                self.assertLessEqual(match.distance, 2)

    def test_the_grid_template_is_what_used_to_mislabel_them(self):
        """Pin the defect itself, not only its repair.

        ``POPUP_DAILY_REWARD_CURRENT`` answers a content question -- "do these
        items look like the ones I was cut from" -- so it matched the Intel
        popups a live run produced, and it was tested before the generic banner.
        It does not even match the genuine daily popup in this directory, which is
        the tell that it was never a source detector at all.
        """
        vision = _vision()
        self.assertIsNone(
            vision.semantic.find(DAILY_POPUP, GRID),
            "the record named after the daily reward does not match a daily reward",
        )
        for frame in (INTEL_POPUP_RUN1, INTEL_POPUP_RUN2):
            with self.subTest(frame=frame.name):
                self.assertIsNotNone(
                    vision.semantic.find(frame, GRID),
                    "it matched the Intel popups instead -- the false positive",
                )

    def test_the_artwork_cannot_name_the_source(self):
        """The footer and banner regions are the same drawing in both frames.

        This is why the repair is goal-context rather than a better crop: there
        is no region of this dialog that differs by source.
        """
        from PIL import Image

        daily = Image.open(DAILY_POPUP).convert("RGB")
        intel = Image.open(INTEL_POPUP_RUN2).convert("RGB")
        footer = hamming(
            phash(daily.crop(FOOTER_BOX)), phash(intel.crop(FOOTER_BOX))
        )
        banner = hamming(
            phash(daily.crop(BANNER_BOX)), phash(intel.crop(BANNER_BOX))
        )
        self.assertLessEqual(footer, 6, "the 点击任意位置退出 bar is identical")
        self.assertLessEqual(banner, 8, "the 获得奖励 banner is the same artwork")


class TheMailInboxIsNotARewardDialogTests(unittest.TestCase):
    """Labelled negative: an ordinary mail inbox, with no dialog on it.

    The label is the evidence, not the file name -- the screenshot shows 邮件,
    the 战争/联盟/系统/报告/收藏 tabs with 系统 selected, a list of claimable
    rewards and 删除所有已读 / 一键已读&领取 along the bottom.  The runtime
    nonetheless recorded ``page=POPUP popup=INTEL_REWARD`` on it for ~20 rounds
    of the 2026-09-20 AUTO loop, because the Intel reward *title* crop covers
    the mail list and its rows are the same peach colour.  This frame is one of
    70 corpus mail frames the old tolerance accepted, so it is a population, not
    one unlucky screenshot.
    """

    def test_the_frame_classifies_as_the_mail_page(self):
        state = _vision().observe(MAIL_INBOX)
        self.assertIs(state.page, Page.MAIL)
        self.assertIsNone(state.popup)

    def test_the_mail_identity_is_an_exact_signal_on_that_frame(self):
        match = _vision().semantic.find(MAIL_INBOX, "PAGE_MAIL")
        self.assertIsNotNone(match)
        self.assertEqual(match.distance, 0)

    def test_the_content_title_crop_is_what_used_to_decide_it(self):
        """Pin the defect, independent of any tolerance.

        The crop still measures inside its old 22 on this frame -- the peach
        band is genuinely there -- which is why no tolerance could have fixed
        it: the same range also holds 178 of the 217 real dialogs.
        """
        distance = _raw_distance(MAIL_INBOX, TITLE)
        self.assertLessEqual(distance, 22, "the crop still matches the mail list")
        self.assertGreater(
            distance, 8,
            "and it matches it too loosely to be a dialog identity: it is well "
            "outside the default tolerance every other semantic uses",
        )

    def test_the_surviving_signal_rejects_the_frame(self):
        """The branch that remains asks about the whole dialog, not the band."""
        distance = _raw_distance(MAIL_INBOX, WHOLE_DIALOG)
        self.assertGreater(distance, 8, "not a reward dialog at all")

    def test_the_content_crop_no_longer_has_a_tolerance_of_its_own(self):
        """A tolerance of 22 on a content crop is the trap itself."""
        self.assertNotIn(TITLE, _vision().semantic.semantic_max_distance)

    def test_the_brain_is_never_asked_to_dismiss_a_popup_here(self):
        """The consequence the loop was made of: a dismiss was dispatched."""
        state = _vision().observe(MAIL_INBOX)
        for goal in ("MAIL", "INTEL", "DAILY"):
            with self.subTest(goal=goal):
                decision = _decide(state, goal)
                self.assertNotIn("DISMISS", decision.skill)


class TheBareMapIsNotARewardDialogTests(unittest.TestCase):
    """The same content-crop trap, on a world-map frame with no dialog at all.

    Defect (live run 2026-09-21T11:29Z, revision ``fa06cc1``).  The 11:28 run
    reported ``POPUP / GENERIC_REWARD`` with confidence 0.99 on a bare world map
    -- the frame shows the HUD, a chat banner reading '系统消息: xx退出了联盟',
    the beast strip and 搜索, and nothing modal anywhere.  The brain answered
    ``DISMISS_SHARED_REWARD`` seven times over a map it could not dismiss, the
    run hit ``MAX_ACTIONS`` on those steps and ended ``SEMANTIC_TARGET_NOT_EXIT``
    -> ``SEMANTIC_TARGET_NOT_VERIFIED`` without ever opening a search.

    The cause is the third instance of the class this file documents: ``BANNER``
    is a content crop -- a 518x115 peach band at y 0.21-0.30 -- so it answers
    "is there a peach band here" rather than "did a dialog open".  On the map
    that band lands on bare snow, a beast sprite and event icons and scores 16,
    which is inside the default tolerance.

    What separates the two populations is whether a modal is actually covering
    the client.  Every reward dialog is a full-screen dim, so the HUD strip at
    the top of the frame is no longer drawn at its own brightness:

        frame                                   strip mean   strip std
        the two reviewed BANNER parents           17.9/18.7    4.9/5.0
        the bare map (this defect)                 111.7       67.2

    A 5x gap on both statistics, so the gate is not delicate.  The frames are
    archived under ``dataset/truth_audit/reward_popup_band_false_positive_20260921``
    rather than read from the live capture directory, for the same retention
    reason as ``EXIT_FRAME`` (issue #46).
    """

    def test_the_bare_map_classifies_as_the_map(self):
        for frame in BARE_MAP_FRAMES:
            with self.subTest(frame=frame.name):
                state = _vision().observe(frame)
                self.assertIs(state.page, Page.MAP, f"{frame.name} is a bare map")
                self.assertIsNone(state.popup)

    def test_the_band_still_matches_the_map(self):
        """Pin the defect independent of any tolerance: the peach band is there.

        It is genuinely inside the default tolerance, which is why the gate is
        about whether a dialog is covering the screen rather than about the band.
        """
        for frame in BARE_MAP_FRAMES:
            with self.subTest(frame=frame.name):
                self.assertLessEqual(_raw_distance(frame, BANNER), 24)

    def test_the_hud_strip_separates_the_bare_map_from_a_real_dialog(self):
        """The measurement the gate is built on, asserted on both populations."""
        bare = [_hud_strip_std(frame) for frame in BARE_MAP_FRAMES]
        dialog = [_hud_strip_std(frame) for frame in (DIALOG_FRAME, DIALOG_FRAME_2)]
        self.assertTrue(all(value > 40.0 for value in bare), bare)
        self.assertTrue(all(value <= 24.0 for value in dialog), dialog)

    def test_a_real_reward_dialog_still_classifies_as_one(self):
        """The gate must not buy the map frame by losing the dialogs."""
        for frame in (DIALOG_FRAME, DIALOG_FRAME_2):
            with self.subTest(frame=frame.name):
                state = _vision().observe(frame)
                self.assertIs(state.page, Page.POPUP)
                self.assertEqual(state.popup, "GENERIC_REWARD")

    def test_the_brain_is_never_asked_to_dismiss_a_popup_here(self):
        """The consequence the aborted round was made of: a dismiss was dispatched."""
        for frame in BARE_MAP_FRAMES:
            state = _vision().observe(frame)
            for goal in ("BEAST_HUNT", "AVOID_STAMINA_WASTE", "MAIL"):
                with self.subTest(frame=frame.name, goal=goal):
                    self.assertNotIn("DISMISS", _decide(state, goal).skill)


class TheBrainChoosesTheDismissFromGoalContextTests(unittest.TestCase):
    """The label is goal-neutral, so the goal has to select the dismiss."""

    def _reward(self) -> WorldState:
        return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)

    def test_an_intel_run_uses_the_intel_dismiss(self):
        decision = _decide(self._reward(), "INTEL")
        self.assertEqual(decision.skill, "DISMISS_INTEL_GENERIC_REWARD")

    def test_a_daily_run_uses_the_daily_dismiss(self):
        decision = _decide(self._reward(), "DAILY")
        self.assertEqual(decision.skill, "DISMISS_DAILY_GENERIC_REWARD")

    def test_the_other_three_goals_that_share_the_dialog_are_covered(self):
        for goal, skill in (("MAIL", "DISMISS_MAIL_GENERIC_REWARD"),
                            ("EXPLORATION", "DISMISS_EXPLORATION_GENERIC_REWARD"),
                            ("ALLIANCE", "DISMISS_ALLIANCE_GENERIC_REWARD")):
            with self.subTest(goal=goal):
                self.assertEqual(_decide(self._reward(), goal).skill, skill)

    def test_without_goal_context_it_closes_the_dialog_by_its_own_exit(self):
        """Documented, not hidden: this is the goal-neutral close.

        Every goal that can produce this dialog is named above.  A goal that
        cannot name the page under it -- TRAIN, RESEARCH, KEEP_TRAINING_PRODUCTIVE,
        GATHER, MARCH, and AUTO_DISCOVERY, which meets the dialog constantly --
        used to stop the run (``SAFE_STOP``), and stopping was wrong for a reason
        the client states on the dialog itself: it says 点击任意位置退出, so the
        exit is declared by the client rather than inferred by us, and clearing a
        blocker is not a guess about which page to return to.

        Measured live 2026-09-20 (open issue #64): five of six AUTO rounds inside
        twenty minutes ended on this dialog, four of them from goals with no
        domain dismiss, and each one ended the run instead of clearing it -- so
        the next round met the same dialog again.

        TRAIN and RESEARCH used to reach ``CLOSE_POPUP`` instead, chosen when no
        skill existed whose target was on this dialog at all.  See
        ``test_the_dismiss_taps_the_exit_the_dialog_declares`` for why that tap
        could never have worked.
        """
        for goal in ("TRAIN", "RESEARCH", "KEEP_TRAINING_PRODUCTIVE", "GATHER",
                     "MARCH", "AUTO_DISCOVERY", "SOMETHING_ELSE"):
            with self.subTest(goal=goal):
                decision = _decide(self._reward(), goal)
                self.assertEqual(decision.skill, "DISMISS_SHARED_REWARD")
                self.assertEqual(decision.expected_result, "underlying_page_restored")

    def test_the_dismiss_taps_the_exit_the_dialog_declares(self):
        """The footer band, never the title band.

        ``vision.py`` recognises this dialog by ``banner OR footer``, so the
        footer alone reports ``POPUP/GENERIC_REWARD`` -- but every dismiss asked
        the executor for the banner, and the banner rides its own tolerance (14,
        16, 18, 20, 26 across six live dialog frames, against 16) while the footer
        scores 0-2 against 8.  The consequence is in the live log: 45 of the 51
        all-time failures of the old target are ``SEMANTIC_TARGET_NOT_VERIFIED``,
        i.e. the dialog was recognised and no tap could be aimed at it.

        This is *not* the claim that the banner is inert.  On
        2026-09-20T13:09:49Z a banner tap did close the dialog.  The fix is to aim
        at the signal that actually matched.
        """
        registry = v2_registry()
        for name in ("DISMISS_SHARED_REWARD", "DISMISS_MAIL_GENERIC_REWARD",
                     "DISMISS_DAILY_GENERIC_REWARD", "DISMISS_INTEL_GENERIC_REWARD",
                     "DISMISS_EXPLORATION_GENERIC_REWARD",
                     "DISMISS_ALLIANCE_GENERIC_REWARD"):
            with self.subTest(skill=name):
                self.assertEqual(registry.get(name).action.target, FOOTER)

    def test_the_goal_neutral_close_can_actually_be_dispatched(self):
        """A skill with no VERIFIED_ATOMIC entry is a skill nothing schedules."""
        from winter_agent_v2.runtime import LiveRuntime

        self.assertIs(
            LiveRuntime.VERIFIED_ATOMIC["DISMISS_SHARED_REWARD"], verify_popup_closed
        )

    def test_the_dismiss_lands_on_the_exit_band_not_the_title(self):
        """The landing point itself, on the frame the outage happened on.

        ``runtime.py`` resolves a ``TAP_SEMANTIC`` through
        ``SemanticWorldVision.find(...).center_norm``, so which record a skill
        names *is* the coordinate that reaches the device -- there is no second
        chance for the executor to aim better.  Naming the title band resolves to
        (360, 326); naming the exit band resolves to (360, 1197).  Both are on the
        frame, which is why the difference between them is a *choice about which
        signal to trust*, not a difference in whether the click lands.
        """
        vision = _vision()
        exit_match = vision.semantic.find(EXIT_FRAME, FOOTER)
        self.assertIsNotNone(exit_match, "the exit the client declares must resolve")
        centre_x, centre_y = exit_match.center_norm
        self.assertAlmostEqual(centre_x, 0.50, places=2)
        self.assertGreater(centre_y, 0.9, "点击任意位置退出 is along the footer")
        title_match = vision.semantic.find(EXIT_FRAME, BANNER)
        self.assertIsNotNone(title_match)
        self.assertLess(title_match.center_norm[1], 0.3, "获得奖励 is at the top")
        self.assertGreater(
            centre_y - title_match.center_norm[1], 0.6,
            "the two bands are at opposite ends of the dialog, not one nudge apart",
        )

    def test_the_footer_is_the_signal_that_survives_where_the_banner_does_not(self):
        """Why the exit band is the one to aim at: it is the one that matched.

        The measured failure class is not "the tap did nothing", it is "no tap
        could be aimed": the banner sits *at* its own tolerance on live frames, so
        the footer reported the dialog and the banner could not be found.  On the
        frame of one such step the two signals disagree by an order of magnitude.
        """
        vision = _vision()
        # dataset/raw/control_panel/runtime_auto/20260919_132726_620764/…_step_004_before_…
        # archived as key/02_.
        failure_frame = (
            ROOT / "dataset" / "truth_audit" / "reward_popup_exit_20260920" / "key"
            / "02_banner_18_footer_2_tap_could_not_resolve_20260919T052809.png"
        )
        banner = _raw_distance(failure_frame, BANNER)
        footer = _raw_distance(failure_frame, FOOTER)
        # The gate-independent numbers, then the production verdicts: the banner
        # cannot be found, the footer can -- which is the whole defect, because the
        # dismissal was asking for the banner.
        self.assertGreater(banner, footer)
        self.assertIsNone(vision.semantic.find(failure_frame, BANNER),
                          "the banner is outside its gate on this frame")
        self.assertIsNotNone(vision.semantic.find(failure_frame, FOOTER),
                             "the footer is the signal that matched")
        # ...and the dialog was nonetheless recognised, which is the defect: the
        # dismissal was selected on a signal it could not tap.
        state = vision.observe(failure_frame)
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "GENERIC_REWARD")


class TheDismissVerifiersAlreadyAcceptTheSharedLabelTests(unittest.TestCase):
    def _reward(self) -> WorldState:
        return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)

    def test_the_intel_dismiss_is_proved_by_the_page_it_returns_to(self):
        intel = WorldState(page=Page.INTEL, popup=None, confidence=0.99)
        self.assertTrue(verify_intel_reward_dismissed(self._reward(), intel).ok)

    def test_the_intel_dismiss_rejects_returning_to_the_wrong_page(self):
        """The exact 2026-09-16 failure: a working dismissal, rejected.

        The daily verifier was run against a popup that sat over the Intel page,
        so it demanded the DAILY page and failed even though the popup was gone.
        """
        daily_page = WorldState(page=Page.DAILY, popup=None, confidence=0.99)
        intel_dismiss = verify_intel_reward_dismissed(self._reward(), daily_page)
        self.assertFalse(intel_dismiss.ok)
        self.assertEqual(intel_dismiss.evidence["after_page"], "DAILY")
        # And the old pairing is exactly what produced DAILY_REWARD_ADVANCE_NOT_PROVEN.
        daily_dismiss = verify_daily_reward_advanced(self._reward(), WorldState(
            page=Page.INTEL, popup=None, confidence=0.99))
        self.assertFalse(daily_dismiss.ok)
        self.assertEqual(daily_dismiss.reason, "DAILY_REWARD_ADVANCE_NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
