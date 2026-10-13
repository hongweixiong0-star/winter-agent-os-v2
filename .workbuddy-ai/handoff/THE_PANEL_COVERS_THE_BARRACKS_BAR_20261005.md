# The quick panel covers the barracks bar, and the route kept sending the step there

**Date:** 2026-10-05
**Change:** `winter_agent_v2/brain.py` (one guard in the TRAIN route),
`tests/test_a_panel_does_not_cover_the_barracks_bar.py`
**Family:** `KEEP_TRAINING_PRODUCTIVE / OPEN_INFANTRY_TRAINING / SEMANTIC_TARGET_NOT_VERIFIED`
**Ledger size at measurement:** 114 rows — 49 successes, 65 failures

---

## 1. What was wrong

`OPEN_INFANTRY_TRAINING` taps `BTN_OPEN_TRAINING_FROM_CAMP` — the 训练 control on the selected
barracks' action bar, drawn at the bottom-left of the city frame. Every failure:

```
failure_type       SEMANTIC_TARGET_NOT_VERIFIED
recognition_error  UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING
decision_reason    panel_open_but_training_unread_so_the_page_that_answers_it_is_the_step
duration           0.06 - 0.13 s
after_screenshot   ""                  <- no tap was sent at all
```

The decision was right about *which page* it wanted. It was wrong about being able to reach it
from *that* frame.

## 2. The measurement — the panel's state is the only discriminator

```
quick_panel.open = False    49/54 SUCCESS   (91%)
quick_panel.open = True      0/60 SUCCESS   (0%)
```

Total, not statistical. Over the whole history, **not one attempt with the panel open succeeded**,
and the two states never mix: the panel's being open is a *sufficient* condition for failure.

The frame says why. `20261005_172103_372127_step_015_before_…png` (720×1280) draws the panel open
on the **野外** tab — 专家 / 英雄招募 / 宠物寻宝 / 我的奖励 — with `read_quick_panel` returning no
`camps` section, no camp row among the four rows it did read, and the barracks action bar under
the pane. The camp rows live on the **城镇** tab.

## 3. The change

One guard, in the branch that decides the training entry, before the dispatch:

```python
if (world.quick_panel or {}).get("open") is True \
        and not _panel_draws_the_training_section(world.quick_panel or {}):
    return Decision(
        "SAFE_STOP",
        "quick_panel_is_open_on_a_tab_without_the_training_entry_so_the_camp_bar_is_covered",
        1.0,
        "switch_task",
    )
```

plus a small module-level reader, `_panel_draws_the_training_section(panel)`, which answers yes for
a row keyed `TRAINING` / one of the three camp keys, or a row whose `label` carries 训练.

**The condition is not "the panel is open", and that distinction is the whole finding.** See §4.

This is the same shape as the `close_resource_search_*` guards the map branch already carries,
added when the resource-search panel covered the 回城 door
(`test_route_goal_requires_home.test_an_open_resource_search_panel_is_closed_first`): **a goal whose
entry sits on the city HUD must not be sent there while something is covering it.** A guard rather
than a detour, and the same reason: a dispatch into a control that provably cannot be resolved is a
retry that can never succeed.

Placement matters and is deliberate. The panel's **own** row path sits above this branch and is
untouched: when the panel can reach a camp's task page it still does, and the guard is never
consulted.

## 4. The first version of this guard was wrong, and the A/B is what said so

The first version refused **every** open panel. It was written on the clean separation in §2 and it
looked right. Then the regression A/B — 155 test files run with and without the guard, compared
position by position — came back with a **one-character difference at test #2138**:

```
tests/test_unanswered_training_opens_the_training_page.py::test_an_unanswered_training_question_opens_the_training_page
```

That file pins a *deliberate, previously measured* change: on a frame whose panel draws the
``部队训练`` row, going to the training page is the step that answers the goal, and it records
"57 runs, 57 successes, every after-frame carrying the camps reading". Its frame is

```python
{"open": True, "rows": [{"key": "TRAINING", "label": "部队训练"}], ...}
```

— the panel on the tab that **does** draw the training section. Refusing that case contradicts a
decided behaviour on the strength of a measurement that cannot see it.

Measured again with the distinction drawn:

| | surviving ledger |
|---|---|
| panel closed | 50/55 SUCCESS |
| panel open, training section **not** drawn | **0/61 SUCCESS** |
| panel open, training section drawn | **no surviving row** |

The third row is the honest part: that shape appears in no frame still in the ledger, so the guard
is written to **leave it alone** rather than to decide it. The failing frames are all the other tab
— 专家 / 英雄招募 / 宠物寻宝 / 我的奖励 — where no training word is on screen at all.

**What this cost to learn, and why it is worth recording:** the ledger is live and gets rewritten
(the same query returned 108 rows and later 107 for another skill on the same day), so a measurement
taken now cannot refute a measurement recorded six hours ago. When a live test encodes a decided
behaviour, the safe move is the narrowest change that both measurements accept — not the cleanest
one that the fresher data supports.

## 4. Evidence

* `tests/test_a_panel_does_not_cover_the_barracks_bar.py`, 5 tests, driven through
  `RuleBrain(...).decide(...)` rather than by asserting the source: the closed panel still
  dispatches (the 49-success path is preserved), the open panel stops across all four training goal
  ids, the reason names the cover, and the panel's own row still wins when it can answer.
* Mutation, on a **copy of the tree** (the pin worktree is production, so neither code nor data is
  mutated in place). The control run first: the unmutated copy is **5/5**. With the guard removed,
  exactly the three tests that require it go red and the two that assert the closed-panel path and
  the panel's own row stay green -- as predicted before the run.

## 5. What this does NOT do — the capability it records

The goal still cannot be served while the panel is open. The way to serve it is *inside* the panel:
switch it to the **城镇** tab, where the camp rows are, and the branch above takes over.

`knowledge/ui/semantic_dictionary.json` already declares `QUICK_PANEL_TAB_CITY` and
`QUICK_PANEL_TAB_WILDERNESS` — from **one** measured frame, with numeric `x` ranges — and
**nothing in the codebase reads either of them**. `_dictionary_hint` refuses the declared-coordinate
branch by name (`§一.2`, `§八`), and its own docstring records the gap: *"Both tabs are still
reachable the constitutional way -- by reading the strip on the current frame -- which is the
capability gap this refusal records rather than hides."*

So the next step, when this is picked up: read the panel's tab strip on the current frame in
`read_quick_panel` (it already OCRs the frame and already decides which sections it can see),
surface it on `WorldState.quick_panel`, and answer `QUICK_PANEL_TAB_CITY` from that reading with a
band-exact test — no stored coordinate. Then a skill for it, and a verifier that proves the panel
now shows a city-tab section (`building` or `camps` present), and the brain hop.

The other candidate, closing the panel, needs the same shape (`QUICK_PANEL_HANDLE` already resolves
to the toggle point) but serves the goal less directly: it would re-derive the reading instead of
taking the one the panel is holding.

## 6. Acceptance criteria for a later reader

* `OPEN_INFANTRY_TRAINING` **shall not** be dispatched on a frame whose `quick_panel.open` is `True`
  **and** whose panel rows draw no training section; the tick must record
  `quick_panel_is_open_on_a_tab_without_the_training_entry_so_the_camp_bar_is_covered` instead.
* A panel that **does** draw the training section (`TRAINING` / a camp key / a 训练 label) must keep
  dispatching -- `test_unanswered_training_opens_the_training_page` owns that decision, and this
  guard must not widen over it. If that file goes red, the guard has been widened again.
* The closed-panel path must keep working: a `SUCCESS` with a non-empty `after_screenshot` and a
  duration in seconds.
