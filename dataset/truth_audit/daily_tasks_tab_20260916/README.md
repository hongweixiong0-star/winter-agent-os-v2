# daily_tasks_tab_20260916 — what is behind the 任务 panel, and how to leave it

**Why these frames exist.** Making `OPEN_DAILY` work (see the sibling set
`daily_entry_template_20260916`) let the live client reach the 任务 panel for the first
time, and that immediately raised two questions nobody could answer from the code:

1. The panel's own tabs were never observed.  Every frame the daily-mission skills were
   calibrated on (`live_cycle2_daily_tasks.png` and friends) shows the **每日任务** tab,
   but the panel as the client actually opens it lands on **章节任务** — so the skills'
   expected screen may never be the screen the agent gets.
2. The panel had nothing claimable, so the run ended `SAFE_STOP
   daily_no_claimable_rewards` — **inside** the panel.  That is the `Page.BEAST` dead end
   again: nothing moves the client, so every following run, for any goal, stops in a few
   seconds.

**How they were obtained.** One bounded probe (`tools/probe_daily_tasks_tab.py`,
2026-09-16T13:46Z): it aborts unless the page is already DAILY, taps exactly one control
at a coordinate measured from a live frame, and taps nothing else.  Where BACK goes was
measured with one press of the existing probe (`tools/probe_back_from_beast.py`, same
shape, one keystroke).

| file | what it is |
|---|---|
| `01_before_20260916_134609.png` | the panel as `OPEN_DAILY` leaves it: **章节任务** selected |
| `02_after_tap_20260916_134609.png` | after one tap on the **每日任务** tab (px 590,1127) |
| `03_panel_before_the_back.png` | immediately before the Back |
| `04_home_after_the_back.png` | after one Back: **Page.HOME** |
| `probe_20260916_134609.json` | both states, the tap coordinate, the probe's own self-limits, and the raw OCR token dump of the daily tab (tokens are ROI-local; the band started at y=0.28×1280=358 px) |

**What the measurement settled.**

* The panel is tabbed: 章节任务 / 成长任务 / 每日任务 on one row at y≈1117–1154 px.
  The tab row was located by OCR (token boxes are ROI-local, the band started at
  y=358 px), and the geometry was confirmed by eye on a 2× crop of the same frame
  (`dataset/probe_output/daily_entry/daily_tabbar_zoom.png`) before anything was tapped.
* On the daily tab the vision reads `daily = {"status": "AVAILABLE", "claimable_count": 0,
  "activity": 285}`; on the chapter tab it reads `{"status": "AVAILABLE",
  "claimable_count": 0}` with no activity.  The account had **nothing claimable today**:
  the four daily missions sat at 16/20, 25/40, 0/10, 0/10 and the three activity chests
  (80/160/270) were already open, i.e. claimed.  This is Feature Availability, not a
  defect — recorded so the next session does not go hunting for a bug.
* One Back from the panel lands on **HOME**, and `verify_safe_back` accepts that
  transition, which is what makes the exit a verifiable step rather than a hopeful one.

**What that produced in the product.** `brain.RuleBrain._leave_daily_panel_once` plus a
one-shot flag (`daily_panel_not_actionable_left`), and — the part the beast card never
needed — the DAILY goal refusing to re-open the panel it has just judged empty.  Live
run 2026-09-16T13:44Z: `OPEN_DAILY` (OK) → `BACK` (OK) → `SAFE_STOP
daily_panel_already_read_not_actionable`, client left on HOME.
`tests/test_daily_panel_dead_end_recovery.py` pins all of it.

**Still open, and now measurable.** Nothing in the registry can switch the panel's tabs,
so on a day when a daily mission *is* complete the agent will still be looking at the
章节任务 tab.  The tab row geometry, the selected/unselected appearances and the two
states are all in these frames — that is the next step, not a re-measurement.
