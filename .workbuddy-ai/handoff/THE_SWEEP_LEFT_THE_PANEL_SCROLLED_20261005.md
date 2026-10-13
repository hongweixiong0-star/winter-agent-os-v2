# The sweep left the panel scrolled, and the training section was above it

**Date:** 2026-10-05
**Change:** `winter_agent_v2/ocr.py` (one field), `runtime.py` (one resolver branch + one binding),
`skills.py` (one skill), `verifier.py` (one verifier), `brain.py` (one bounded hop),
`tests/test_a_panel_does_not_cover_the_barracks_bar.py`
**Supersedes the aim of:** `THE_PANEL_TAB_SWITCH_20261005.md`, whose tab hypothesis was refuted and
reverted (`b4c4b3b`). This is the same family with the cause measured first.

---

## 1. What was wrong

`OPEN_INFANTRY_TRAINING` and the per-camp training goals need the panel's **部队训练** section. The
quick panel is **one continuous list**, and the section sits directly under the tab strip
(建筑队列 at y 0.251) — but the frames that failed showed 宠物寻宝 / 我的奖励 / 生命结晶收集 /
晨曦回礼, i.e. the list four sections further down.

## 2. The cause, measured

```
of the 61 panel-open training failures, 59 had
    OPEN_QUICK_PANEL  →  SCROLL_QUICK_PANEL_TASKS
earlier in the same run.
```

`SCROLL_QUICK_PANEL_TASKS` exists so a goal can reach the rows it wants, and it drags the content
**up** — revealing what is *below* the band. Then the panel stays where the sweep left it. A goal
whose own section is *above* that band had no way back: the panel covers the barracks action bar it
would otherwise tap, and its own rows are off-screen.

## 3. The change

**Reader** (`ocr.py`, `read_quick_panel`): alongside `scroll_swipe_norm`, return
`scroll_back_swipe_norm` — the same two endpoints the other way round, under the same
band guard. Derived from this frame's own first and last visible row centres, so it is a reading and
not a coordinate:

```
frame 20261005_172103_372127_step_015   rows y 0.3625 .. 0.5949
  scroll_swipe_norm      [0.3891, 0.6449, 0.3891, 0.4025]   drags up  (reveal below)
  scroll_back_swipe_norm [0.3891, 0.4025, 0.3891, 0.6449]   drags down (reveal above)
```

**Resolver**: `QUICK_PANEL_SCROLL_BACK_CURRENT`, mirroring the forward branch — same page/panel
guards, same re-read of the frame in hand, opposite direction guard (`gesture[1] < gesture[3]`).

**Skill**: `SCROLL_QUICK_PANEL_BACK` (`Page.HOME`, `SWIPE QUICK_PANEL_SCROLL_BACK_CURRENT`, LOW).

**Verifier**: `verify_quick_panel_scrolled_back`. The forward verifier accepts *any* change in the
visible rows; this one **must not**, which is the whole difference — a second downward scroll would
otherwise be credited as undoing the first. It requires the direction:

* a row visible in both readings whose `y_norm` **grew by ≥ 0.04** (the content moved down under the
  finger), or
* a row that was not visible and now sits **above the previous band's top** (revealed from above).

**Brain**: the branch that only refused now asks for the backward drag, bounded to
`MAX_PANEL_SCROLL_BACK_ATTEMPTS_PER_RUN` (3 — the sweep can leave the panel four sections past, and
a swipe moves about two rows), falling back to the previous `SAFE_STOP` with the cover named.

## 4. Evidence

* **Real frames**: both gestures derive on the frame that decided the cause, and are each other's
  reverse; the resolver answers both. A frame with only two measurable rows returns `None` for both
  — the band is what makes a gesture, and two rows do not make one (see §5).
* **Tests** (15 in the file, up from 5): the branch dispatches the backward drag across all four
  training goals, is bounded and then stops naming the cover, the skill is bound; the verifier
  credits rows moving down and rows revealed above, and **refuses** a second downward scroll, no
  change, and a swipe that left the city; and a frame-based test pins that the two gestures are the
  same reading reversed.
* **Mutations, on a copy of the tree** (control first: the unmutated copy is 15/15):
  * the reader stops producing the backward gesture → exactly `test_the_two_gestures_are_the_same_reading_reversed` fails;
  * the verifier drops its direction check (`added` accepted like the forward one) → exactly
    `test_a_second_downward_scroll_is_not_credited` fails.
* **Regression A/B** over the 180 test files that touch these five modules, with and without.

## 5. What this does NOT do — named, not hidden

* **A frame with no derivable band gets no gesture.** Measured: `20261005_181440_330696_step_009`
  carried two measurable rows (宠物寻宝 0.3023, 我的奖励 0.3902), below the reader's ≥3-row /
  ≥0.12-span guard, so both gestures are `None` there and the step cannot be dispatched. That is
  honest — there is no measured band to drag — and the bound keeps it from becoming a loop.
* **The direction is a claim about where the section is, not a measurement of it.** The hop asks
  for "back" whenever the training section is not drawn; if a frame ever has the section *below* the
  band, the swipe goes the wrong way. The verifier refuses it (nothing moved down), the bound stops
  it after three ticks, and the ledger will show it — but it is a cost this design accepts rather
  than a case it handles.
* The panel is never *closed*: no goal has needed that, and there is no skill for it (the
  `QUICK_PANEL_HANDLE` record refuses the toggle when the panel is already in the state its
  transition describes).

## 6. Acceptance criteria for a later reader

* On a panel-open frame without the training section, the tick must dispatch `SCROLL_QUICK_PANEL_BACK`
  and the next reading must show **either** a common row whose `y_norm` grew by ≥ 0.04 **or** a row
  revealed above the old band.
* `QUICK_PANEL_SCROLL_BACK_NOT_PROVEN` must mean the band did not move **in that direction**. A
  verifier that ever passes on rows moving up the screen has lost the direction and is crediting the
  sweep.
* No more than `MAX_PANEL_SCROLL_BACK_ATTEMPTS_PER_RUN` backward drags per run; the step after the
  bound stops with `quick_panel_is_open_on_a_tab_without_the_training_entry_so_the_camp_bar_is_covered`
  — a reason whose wording still says "tab" and should be renamed once this is confirmed on the
  device, because the measurement says tab is not what any of this is about.
