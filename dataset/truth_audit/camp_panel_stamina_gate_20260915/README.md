# Camp panel: the price is measurable, so measure it before paying it

Two live runs against the real client (`com.gof.china`, MuMu Player 12,
720×1280), goal `INTEL`, both `exit 0`, all steps verifier `OK`.

## What was wrong

The Hero Journey camp panel (英雄之旅, a 探险 ⚡10 button) is a **map overlay**:
the world-map HUD stays on screen behind it, so its stamina gauge sits exactly
where it does on `Page.MAP`.  `HybridVision` only OCR-enriched stamina on
`Page.MAP` / `Page.RESOURCE_DETAIL`, and the panel classifies as
`Page.EXPLORATION`, so the reading was measured and then thrown away —
`stamina={}`.

Consequence, from `dataset/truth_audit/stamina_check_live_20260915`
(`2026-09-15T03:03:57Z`): the brain stood on a ⚡10 fight with 9 stamina, tapped
it, the client refused and opened 获取更多, and `verify_intel_hero_march_open`
recorded **OK** — a refusal recorded as a started fight.  The run then burned
its remaining three actions on the stamina panel and achieved nothing.

## Run 1 — the read works, and an affordable fight is not blocked

`out_live_camp.txt`, capture `camp_stamina_gate_20260915b`, 10 steps, 10/10 OK.

    step3  INTEL_HERO_START_MARCH / intel_hero_camp_panel
           before  EXPLORATION  stamina={'current': 16, 'source': 'CAMP_PANEL_HUD',
                                          'roi': {...}, 'gauge_pixels': 0}
                   exploration={'status': 'AVAILABLE', 'stamina_cost_displayed': 10}
           after   MARCH          <- 16 >= 10, the fight starts

`CAMP_PANEL_HUD` is the new source, and the read is what makes the gate below
possible.  The run did real work: `INTEL_HERO_DISPATCH` (hero fight dispatched),
`DISMISS` of the victory screen, `INTEL_CLAIM_REWARDS` (1 reward).  Stamina
16 → 7.

## Run 2 — the gate fires when the fight is not affordable

`out_live_gate.txt`, capture `camp_gate_live_20260915`, 6 steps, 6/6 OK.

    step3  BACK / camp_fight_unaffordable_go_get_free_stamina
           before  EXPLORATION  stamina={'current': 7, 'source': 'CAMP_PANEL_HUD'}
                   exploration={'stamina_cost_displayed': 10}      <- 7 < 10
           after   MAP
    step4  OPEN_STAMINA_SOURCES / free_stamina_gift_not_yet_checked_this_run
           MAP -> POPUP/GET_MORE_STAMINA
    step5  BACK / stamina_panel_without_a_free_gift   (free_claim_available: False)
    step6  OPEN_INTEL / intel_goal_from_world_map

Two things this proves beyond the gate itself:

* **`BACK` from the camp panel lands on MAP**, not HOME (step 3:
  `EXPLORATION -> MAP`).  The route to the free-stamina check is two actions,
  and it is measured rather than assumed.
* **The counterfactual is a dead run.**  Without the gate step 3 would have been
  `INTEL_HERO_START_MARCH`, the client would have refused, the refusal would be
  recorded honestly as `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA` — and
  `runtime.py` returns on the first failed verification, so the run would have
  ended at step 3 and never reached steps 4–5.  At stamina 7 the gate is what
  keeps the run productive.

## Run 3 — the free-stamina check runs again, in the runner the loop uses

`out_live_stamina2.txt`, capture `camp_stamina_gate_20260915`, 3 steps, 3/3 OK.
Started from `MAP`, stamina 16:

    step1  OPEN_STAMINA_SOURCES / free_stamina_gift_not_yet_checked_this_run
           MAP -> POPUP/GET_MORE_STAMINA
    step2  BACK / stamina_panel_without_a_free_gift
    step3  OPEN_INTEL -> INTEL  (pins: 6, available_count: 6)

This is the step `tools/run_intel_pins.py` used to disable with
`--no-stamina-check`.  It now runs.

## Frames

| file | what it shows |
| --- | --- |
| `01_camp_panel_stamina_read_live.png` | the camp panel whose `before.stamina` is now `CAMP_PANEL_HUD: 16` |
| `02_hero_fight_started_live.png` | `MARCH` after the affordable fight was started |
| `03_camp_panel_unaffordable_live.png` | the same panel at stamina 7 — the gate's input |
| `04_map_after_gate_back_live.png` | `MAP`, where `BACK` actually lands |
| `05_stamina_panel_no_gift_live.png` | 获取更多 with `free_claim_available: False` |

`live_run_records.json` holds the full step records for both runs.

## Still not live-verified

`CLAIM_FREE_STAMINA` has **zero** executions in the whole recorded corpus, and
the gift was not due in any of these runs (`free_claim_available: False` every
time).  Its verifier is calibrated from a live measurement
(`200/200 → 350/200`, the 领取 button replaced by 下次补给) but has never judged
a real claim.  See `04_OPEN_ISSUES.md` `0am`.
