# daily_tab_switch_20260916 — the 任务 panel's own tab, and the skill that switches it

**Why these frames exist.** `OPEN_DAILY` opens the tabbed 任务 panel, and the page
classifier names the page `DAILY` from the literal string `每日任务` that the client draws
on the tab **bar** — so `page is DAILY` has never meant "the daily tab is showing". Every
daily skill was calibrated on the daily tab (`dataset/raw/live_cycle2_daily_tasks.png` and
friends), and the panel opens on **章节任务**. The cost is measurable: on 2026-09-16 the
account stood at activity 285 with its three chests (80/160/270) already passed, and the
agent could not see any of it.

**Files**

| file | what it is |
|---|---|
| `01_before_*.png` | the panel on 章节任务 — the state `SELECT_DAILY_TAB` must act on |
| `02_after_chapter_tap_*.png` | after one measured tap, still 章节任务 (the probe is idempotent) |
| `probe_*.json` | both readings, the tap coordinate, and the probe's own self-limits |

**What settled it.** The two tab states are distinguishable in the frames themselves —
unselected is a dark blue pill with white text, selected is a light pill with dark text —
so both are registered as templates from the archived before/after pair in
`daily_tasks_tab_20260916/` (`tools/register_daily_tab_template.py`):

| semantic | role | corpus matches (3503 frames) |
|---|---|---|
| `BTN_DAILY_TAB_TASKS` | tap target of `SELECT_DAILY_TAB` | 4 — all four panel-on-章节任务 frames of 13:44 / 13:51 |
| `TAB_DAILY_TASKS_SELECTED` | the drawn state the verifier reads | 5 — the 13:47 probe frame plus the four of the 16:33 run |

Zero matches anywhere else in the tree.

**A defect the live run caught in this very registration.** The first crop was the whole
pill, `x 481..704`, which includes the bottom-right corner where the client draws its red
claimable badge (measured on `live_runtime_step_003_before_20260916T163330128917`: badge
centre ≈ (688, 1158), r ≈ 9). It matched only 3 of that run's 13 frames — exactly the ones
where the badge was absent — which is the same defect that froze `BTN_OPEN_DAILY` for eight
days. The crop now stops at x=670: one record covers the badge and no-badge states (both
verified, d=0 on all five selected frames).

**Live evidence of the skill itself** (2026-09-16T16:4x, `run_live.py --goal DAILY`):

```
1 SELECT_DAILY_TAB  DAILY -> DAILY   verifier OK
    before: tab=NOT_TASKS, status=AVAILABLE, claimable_count=0
    after : tab=TASKS, task_id=ALLIANCE_CONTRIBUTE_5, progress=0, activity=10
    action: TAP_SEMANTIC BTN_DAILY_TAB_TASKS (ADB, 37.5 ms)
2 BACK              DAILY -> HOME    verifier OK
3 SAFE_STOP         daily_panel_already_read_not_actionable
```

The `after` reading is the point of the whole change: the daily tab's own content
(`task_id`, `progress`, `activity`) only becomes visible once the tab is switched.

**Also from the same day, in passing.** The 16:33 run opened on a spontaneously appearing
`REAL_MONEY_OFFER` popup, dismissed it with the hard block (`DISMISS_REAL_MONEY_OFFER`,
verifier OK), and then claimed a daily reward on the first attempt
(`DAILY_CLAIM_REWARDS`, verifier OK, `claimable_before` + `reward_visible`) — the first
traceable live daily claim in the stream; every earlier row for that skill was written by
the legacy writer that has no `recorded_at`, no screenshots and no verifier.
