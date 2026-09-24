# Two traps that made a working click look like a dead one (measured 2026-09-24)

Both were found by measuring, and both had already cost three rounds of wrong conclusions. They are
recorded together because each one *hides the other*: the transient response made the click look
dead, and the quit dialog made a page look un-exitable.

---

## 1. The response is real and short: the 登录好礼 panel opens for ~0.75 s

Controlled click first, on a control whose response is unambiguous — the bottom-nav **探险** entry:

```
before page MAP
tap (0.1000, 0.9824) -> executed=True px=(72, 1257)
  after_0 (+0.00s) page=MAP
  after_1 (+0.35s) page=EXPLORATION      <- the client responded
  after_2 (+1.20s) page=MAP
  after_3 (+2.50s) page=MAP
```

So the input path is sound end to end: MAA sent the tap, the client acted on it, and the action was
visible in the picture. (`executed=True` alone would not have shown that, which is why the burst
exists.)

The same measurement on the **登录好礼** icon, with frames every 0.25 s:

```
tap (0.7695, 0.1184) -> executed=True px=(554, 152)
  +0.00s page=MAP      frame_delta=25.30
  +0.25s page=ALLIANCE frame_delta=61.96  region_delta=74.03   <- the panel is open
  +0.50s page=ALLIANCE frame_delta=61.97
  +0.75s page=ALLIANCE frame_delta=61.97
  +1.00s page=MAP      frame_delta=25.32                        <- and gone again
  +1.25 .. +2.25s page=MAP
```

and the frame at +0.25 s is the **登录好礼 page itself** — title bar 超值活动, the page title
登录好礼, 每日登录游戏，即可领取大量奖励！, the 免费/天数/史诗 tabs, day 3 highlighted, day 2 already
claimed (green tick), and a ¥6.00 purchase banner (never touched).  Kept as
`dataset/truth_audit/login_gift_entry_20260924/key/login_gift_PANEL_OPENED_20260924T040458.png`.

**Consequences, both of which were previously recorded as something else:**

* "The tap did nothing / `HOME -> HOME`" was a **sampling artefact**.  Every earlier verification
  captured at ≥1.0 s, after the panel had already closed.  The click was never dead.
* The page model reads that panel as **ALLIANCE**.  So even at the right moment the *reading* is
  wrong, which is its own defect (the panel has no page entry; it is being matched to the nearest
  panel-shaped model).  Two separate reasons a correct action looked like a failure.
* §7.3 of `docs/LOCAL_PLANNER_ACCEPTANCE.md` blamed HUD drift.  That was wrong and is now corrected:
  a drift series with **no input at all** measures the icon at the *identical* position across
  frames (`dx=0.0000 dy=0.0000`, match score 0.98).

**Rule this leaves behind:** a response may be shorter than the interval you sample at.  Any
verification of a UI action must take a **burst** starting immediately at the tap, and compare the
frame against the frame the tap was sent from — never two frames taken a settle apart.  The
implementation is in `tools/probe_live_operation.py` (`--burst`, `--burst-every`), and it reports a
whole-frame delta and a target-region delta per frame so "something changed" is a number.

## 2. System BACK raises the game's quit dialog, and then nothing can leave the page

Reported as "MAIL cannot be exited", then again on INTEL: repeated `press_back()` left the client on
the same page.  The screenshot at that moment:

```
  确认退出游戏吗?        [取消]  [确定]        X
```

**BACK on those pages is the game's exit request.** It opens a confirmation dialog; pressing BACK
again does not dismiss it (it re-asks), so the page looks permanently stuck while the dialog waits
for an answer.  Nothing is wrong with the page, the navigation model or the input path.

**Rule:** never use repeated `press_back()` as a way out of a page.  One BACK, then look at the
frame: if the quit dialog is up, answer it by **recognising** 取消 and tapping that control (never
by position, and never 确定 — that terminates the client).  Kept as
`dataset/truth_audit/login_gift_entry_20260924/key/quit_game_CONFIRM_DIALOG_20260924T040947.png`.

## 3. What is still unknown, stated as unknown

The panel closed by itself between +0.75 s and +1.00 s with **no input of any kind** in that window
(the burst only screenshots).  Recorded as `UNKNOWN`; the candidates are that the panel is a
hub/preview that returns automatically, or that the game closes it because today's reward is already
taken (day 2 is ticked and there is no obvious claim control for day 3).  **Not guessed at, and no
claim was attempted** — claiming blind on a purchase-bearing panel is exactly what the safety rules
forbid.

## 4. Evidence retention

Key frames now live under `dataset/truth_audit/<round>_<date>/key/`, which `.gitignore` already
exempts by convention (`dataset/truth_audit/login_gift_entry_20260924/key/**/*.png` added).  Four
frames are version-managed: the opened panel, the map after it closed, the quit dialog, and the
controlled click's response.  Everything else stays in the capped local
`dataset/truth_audit/live_ops/<op_id>/` tree, which is what an operation id is for.
