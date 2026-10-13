# The panel's tab was already answerable — the capability only needed a skill

> ## OUTCOME (added 18:45, after the measurement that refuted this）
>
> **This change was reverted** — commit `b4c4b3b`, "Revert feat(panel): the quick panel's tab is
> switchable…", which carries the full reasoning. The guard from `c873ab0` stands and is restored.
>
> **What was wrong**: the premise. The panel is **one continuous list**, not one-sections-per-tab.
> A single frame shows 部队训练 (射手) / 科技研究 / 联盟捐献 / 专家 / 英雄招募 stacked in the *same*
> scrollable list (`...20261003_095422_116635_step_010_after_...png`), and over the 3205 surviving
> open-panel frames the city sections and the wilderness rows co-occur in ~200 of them —
> `city=['camps','research']` with a `HERO_RECRUIT` row, and so on. Two tabs cannot draw each
> other's rows. The row keys appear on both sides: `ALLIANCE_DONATION`, `HERO_RECRUIT`,
> `HERO_RECRUIT_EPIC`, `RESEARCH`.
>
> So `city_sections` measures **the visible band, i.e. the scroll position** — and a verifier keyed
> on it while claiming to prove a *tab* would credit a tap that did nothing as soon as the panel
> happened to be scrolled to the city group. That is the one thing a verifier must not do.
>
> **The reframed cause, measured**: of the 61 panel-open training failures, **59 had
> `OPEN_QUICK_PANEL` → `SCROLL_QUICK_PANEL_TASKS` earlier in the same run**. The sweep scrolls the
> panel **down** to reveal the rows other goals want; the training section is **above**, so the
> training goal arrives looking at 宠物寻宝 / 我的奖励 / 生命结晶收集 and cannot see its own section.
> The panel's scroll position is a side effect of the sweep.
>
> **The reframed target**: move the band **back up**. `QUICK_PANEL_SCROLL_CURRENT` derives its
> gesture from the current frame but the resolver refuses anything whose `gesture[1] <= gesture[3]`
> — i.e. it can only scroll *down*. So the capability is an upward counterpart (its own semantic and
> skill), and the honest verifier for it is exactly the condition this file got wrong for a tab:
> **the band changed and the training section came into view** — which is a claim about the band,
> and therefore true here.
>
> Everything below about the dictionary's printed word is still measured and still useful: a tab tap
> would need no new reader, only a skill. It is kept because it is independent of the refuted
> premise.

**Date:** 2026-10-05
**Change:** `winter_agent_v2/skills.py` (one skill), `winter_agent_v2/verifier.py` (one verifier +
one shared constant), `winter_agent_v2/runtime.py` (one binding), `winter_agent_v2/brain.py`
(one bounded hop), `tests/test_a_panel_does_not_cover_the_barracks_bar.py`
**Follows:** `THE_PANEL_COVERS_THE_BARRACKS_BAR_20261005.md`, whose guard this replaces with the
capability it was standing in for.

---

## 1. What was missing

`KEEP_TRAINING_PRODUCTIVE` needs the panel's **部队训练** section — either to read the camp rows or to
reach a barracks' action bar. The panel draws one tab's sections at a time:

| tab | rows `read_quick_panel` returns |
|---|---|
| **野外** | `HERO_RECRUIT`, `HERO_RECRUIT_EPIC`, `PET_TREASURE`, `MY_REWARDS` |
| **城镇** | `BUILDING`, `SHIELD_CAMP`, `LANCER_CAMP`, `MARKSMAN_CAMP`, `RESEARCH` |

On the 野外 tab the camp rows are absent, the section is not drawn, and the barracks action bar is
behind the pane. Measured: **0/61** attempts in that state ever succeeded (an empty
`after_screenshot` every time — no tap was sent), against **50/55** with the panel closed.

Nothing could change the tab. `knowledge/ui/semantic_dictionary.json` declared
`QUICK_PANEL_TAB_CITY` and `QUICK_PANEL_TAB_WILDERNESS` from one measured frame, and the previous
round's handoff recorded that "nothing in the codebase reads either of them".

## 2. The finding: no new reader was needed

It turned out the reading already existed. The dictionary's record is not just a coordinate:

```json
{"id": "QUICK_PANEL_TAB_CITY", "type": "TAB", "ocr": ["城镇"], "pages": ["HOME", "MAP"],
 "actions": ["SELECT_TAB"], "position_hint": {"basis": "MEASURED_ON_ONE_FRAME", ...}}
```

and `_client_printed_control` answers a semantic from **the word the client printed on the control**
whenever the dictionary declares one and the page matches. So the resolver already had an answer,
and only the *declared-coordinate* branch was (correctly) refusing. Reproduced read-only through the
production resolver on the two frames that decided this:

```
[printed] ... QUICK_PANEL_TAB_CITY       located by the word '城镇' at 0.1618,0.2129 on HOME
[printed] ... QUICK_PANEL_TAB_WILDERNESS located by the word '野外' at 0.4653,0.2129 on HOME
```

— both frames, both semantics, at the centre the dictionary's own one-frame measurement recorded
(`x 0.125-0.196` and `0.432-0.499`, `y 0.212`). **The gap was a missing skill, not a missing
reader.** The previous round's write-up assumed the reader had to be written; it did not.

## 3. What the labels may NOT be used for

Both tab labels are drawn **whichever tab is active** — 城镇 at (0.1618, 0.2129) read at 0.999 and
野外 at (0.4653, 0.2129) at 1.000, on both frames. So a verifier keyed on the labels would pass on
either tab and credit a tap that did nothing.

Measured via `read_quick_panel` on the same two frames, the discriminator is what the panel *draws*:

| frame | `city_sections` | rows |
|---|---|---|
| 野外 | `[]` | HERO_RECRUIT / …_EPIC / MY_REWARDS / PET_TREASURE |
| 城镇 | `['building', 'camps', 'research']` | BUILDING / **SHIELD_CAMP / LANCER_CAMP / MARKSMAN_CAMP** / RESEARCH |

So `verify_quick_panel_city_tab_selected` insists on the **transition** — city sections appearing
where there were none — rather than on the state. A panel that already showed 建筑队列 was not
switched by this tap, and saying OK there would credit a tap that did nothing.

## 4. The change

* `skills.py` — `SELECT_QUICK_PANEL_CITY_TAB`, `Page.HOME`, `Action("TAP_SEMANTIC",
  "QUICK_PANEL_TAB_CITY")`, `risk="LOW"`, `CANDIDATE`. Its target is the semantic the resolver
  already answers; the test ties the skill's target, the dictionary's page list and the dictionary's
  printed word together, so a rename on any one side fails rather than silently disabling the hop.
* `verifier.py` — `verify_quick_panel_city_tab_selected`, plus `QUICK_PANEL_CITY_SECTIONS` extracted
  from the inline tuple the panel-open evidence already carried (one declaration, two callers).
* `runtime.py` — the binding, and the `QUICK_PANEL_TAB_CITY` refusal path is untouched (the
  declared-coordinate branch still refuses).
* `brain.py` — the branch that used to only refuse now **switches the tab**, bounded to
  `MAX_PANEL_TAB_ATTEMPTS_PER_RUN` (2, mirroring the panel-row bound). When the skill is missing or
  the bound is spent it falls back to the previous `SAFE_STOP` with the cover named.

Placement is unchanged from the guard: the panel's **own** row path above still wins whenever the
panel can answer.

## 5. Evidence

* **Real frames, all four steps**: the resolver answers the tap (both frames, §2); `read_quick_panel`
  shows the sections appearing (§3); the 城镇 frame carries the camp rows the branch above waits for.
* `tests/test_a_panel_does_not_cover_the_barracks_bar.py` — the branch: closed panel dispatches,
  panel drawing the training section dispatches, panel without it **switches**, the switch is bounded
  and then stops naming the cover, the skill is bound, and its target agrees with the dictionary.
  The verifier: sections appearing is the proof, an already-present section is not credited, no
  section means not switched, and a tap that left the city is not a tab switch.
* Regression A/B over the 180 test files that touch these four modules, run with and without the
  change and compared position by position.

## 6. First live attempt (10:16) — the plumbing worked, the tab did not switch

One production episode exists, and it is worth reading in full because it separates what works from
what is unproven.

```
skill              SELECT_QUICK_PANEL_CITY_TAB
decision_reason    quick_panel_is_on_a_tab_without_the_training_section_so_the_other_tab_is_selected
action             TAP_SEMANTIC / QUICK_PANEL_TAB_CITY
duration           13.28 s              <- a real tap plus an observation
after_screenshot   present              <- unlike the 65 failures at 0.06 s and no frame
recognition_error  ''
verifier_evidence  city_sections_before [] , city_sections_after []
failure_type       QUICK_PANEL_CITY_TAB_NOT_PROVEN
```

So the chain ran end to end: the brain dispatched it, the resolver answered from the printed word,
the tap was sent, the frame was captured, and the verifier **refused honestly** — the panel drew no
city section afterwards. That refusal is the feature working, not failing.

**But the tab did not switch.** The before-frame and the after-frame are, in the panel region,
essentially identical — same list at the same scroll position (宠物寻宝 / 我的奖励 / 生命结晶收集 /
晨曦回礼 / 地心探险), same tab strip. Both are
``20261005_181440_330696_step_009_{before,after_refresh_2}_…png``.

Three candidates, in the order they should be checked, **none of them measured yet**:

1. **The panel was already on 城镇 and scrolled.** The city sections sit at the *top* of the list
   (measured: 建筑队列 at y 0.251, directly under the tab strip), so a scrolled panel on the city
   tab would show none of them while still being on that tab — and then there is nothing to switch
   and the tap is a no-op. **This is the first measurement to make**: does the panel's scroll
   position decide `city_sections`, or does the tab?
2. **The label's box centre is not the tappable tile.** The point used is the printed word's own box
   centre, (0.1618, 0.2129); a tab tile is usually larger than its word. Worth probing the word box
   against the tile on a frame where the tab demonstrably does change.
3. **The selection marker is a bracket, not a fill.** The client shows *both* tab labels whichever
   tab is active (0.999 / 1.000 on both frames), and the two tab-strip fills look the same in the
   before/after pair, so the fill is not the marker. This project already reads exactly this kind of
   marker on the resource strip — ``_bracket_strokes`` / ``selected_tab_from_live_labels``, written
   for the 冰原巨兽 tab — and **that** is the machinery to reuse rather than invent.

Until (1) is answered the verifier's condition may be too strict: it requires the sections to be
*visible in the reading*, which a scrolled panel defeats for reasons that are not the tab. That is a
false-negative risk in the verifier, and it is named here rather than left for a reader to discover
from `QUICK_PANEL_CITY_TAB_NOT_PROVEN` rows.

## 6b. An attribution hazard found while reading that row

The episode stamps ``repo_revision = c873ab0c`` — a commit that **does not contain** this skill.
``run_live.py`` reads ``PROCESS_CODE_REVISION`` from git HEAD at process start while importing the
modules from the working tree, so in-place edits that have not been committed yet produce episodes
stamped with a commit that lacks the behaviour they exercised. Today's own earlier fixes were
attributed by code-level arguments (which reader could possibly have produced this row), not by the
stamp, so they stand — but any future attribution that leans on ``repo_revision`` alone has to
account for this.

## 7. Not done here

* The reverse hop is not added: nothing switches the panel back to 野外. No goal has needed it, and
  a hop nobody's goal asks for is machinery this project does not add speculatively.
* The **野外** tab's own sections are read but nothing keys on them beyond the existing rows.
* `QUICK_PANEL_TAB_WILDERNESS` is answerable the same way (`SELECT_TAB` is in its `actions`) but has
  no skill: it is recorded here as reachable rather than wired.

## 7. Acceptance criteria for a later reader

* On a frame whose panel is open without the training section, the tick must dispatch
  `SELECT_QUICK_PANEL_CITY_TAB`, and the **next** tick must find the panel's camp rows drawn
  (`camps` or a `SHIELD_CAMP`/`LANCER_CAMP`/`MARKSMAN_CAMP` row present).
* `QUICK_PANEL_CITY_TAB_NOT_PROVEN` must mean what it says: the city sections did not appear. A
  verifier that ever passes on a frame still showing only the 野外 rows has been loosened.
* No more than `MAX_PANEL_TAB_ATTEMPTS_PER_RUN` switches per run; the step after the bound stops
  with `quick_panel_is_open_on_a_tab_without_the_training_entry_so_the_camp_bar_is_covered`.
