"""What the panel row entries actually reached -- the acceptance evidence for §八.2/§八.3.

Not a test: an instrument.  Answers, from the corpus alone:

  * each ``OPEN_TASK_FROM_QUICK_PANEL_*`` step: what its **own verifier** said, and which surface the
    after-frame showed -- the task's action bar in the city, or the task's page;
  * what the same run did on the next few steps (did it act on what it reached?);
  * the camp rows that carried a *scanned* enter arrow, against the camp entries that succeeded.

The first version of this instrument compared ``after.page`` against the expected page and reported
"35 of 35 did not land".  That was the instrument being wrong, not the system: a barracks row's
measured outcome is the city with that barracks selected and its action bar (详情 / 升级 / 训练) open,
which the reader names as ``training.menu_open`` with ``page=HOME`` -- see
``verifier.verify_panel_row_task_bar_opened``'s docstring, which records the measurement
(2026-09-22 23:42:41, 矛兵).  One tap cannot produce ``Page.TRAINING``; that page is behind the bar's
own 训练 button.  So this reports the verifier's own verdict and the evidence it recorded, and lets the
reader see which surface was reached instead of grading the step against a page it was never meant to
open.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"


def _page(state: dict) -> str:
    value = (state or {}).get("page")
    return str(value.get("value") if isinstance(value, dict) else value or "")


def _reached(evidence: dict, skill: str) -> str:
    """Which surface the row's own verifier accepted, in words."""
    if "task_bar_open_after" in evidence:
        if evidence.get("task_page_open_after"):
            return "the training page"
        if evidence.get("task_bar_open_after"):
            return "the barracks action bar in the city"
        return "nothing"
    if "lab_bar_open_after" in evidence:
        if evidence.get("research_page_open_after"):
            return "the research page"
        if evidence.get("lab_bar_open_after"):
            return "the lab action bar in the city"
        return "nothing"
    return str(evidence.get("arrived") or "?")


def main() -> int:
    rows = []
    for line in EPISODES.open(encoding="utf-8"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.sort(key=lambda row: str(row.get("recorded_at")))
    runs: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        runs[str(row.get("episode_id"))].append(row)

    entries = [row for row in rows if "OPEN_TASK_FROM_QUICK_PANEL" in str(row.get("skill"))]
    print(f"corpus: {len(rows)} steps   panel row entries: {len(entries)}")
    print()
    summary: Counter = Counter()
    for row in entries:
        evidence = row.get("verifier_evidence") or {}
        verdict = _reached(evidence if isinstance(evidence, dict) else {}, str(row.get("skill")))
        summary[verdict] += 1
        print("  {} {:<40} {:<8} verifier_ok={:<5} reached {}".format(
            str(row.get("recorded_at"))[11:19], str(row.get("skill")), str(row.get("result")),
            str(row.get("verifier_ok")), verdict))
        if str(row.get("result")) != "SUCCESS":
            continue
        siblings = runs[str(row.get("episode_id"))]
        index = next((i for i, item in enumerate(siblings)
                      if str(item.get("recorded_at")) == str(row.get("recorded_at"))), None)
        if index is None:
            continue
        for follower in siblings[index + 1:index + 4]:
            print("         -> {} {:<32} {:<8} on {}".format(
                str(follower.get("recorded_at"))[11:19], str(follower.get("skill")),
                str(follower.get("result")), _page(follower.get("state_before"))))
    print()
    print(f"surfaces reached: {dict(summary)}")
    print()

    armed: Counter = Counter()
    for row in rows:
        panel = (row.get("state_before") or {}).get("quick_panel") or {}
        if not panel.get("open"):
            continue
        for item in panel.get("rows") or []:
            if str(item.get("kind")) != "CAMP":
                continue
            armed[(str(item.get("key")), str(item.get("status")), str(item.get("control")),
                   str(item.get("arrow_basis")))] += 1
    print("camp rows by (key, status, control, arrow_basis):")
    for key, count in armed.most_common():
        print(f"  {count:>4}  {key}")
    usable = sum(count for key, count in armed.items()
                 if key[2] == "ARROW" and key[3] == "ROW_BUTTON_SCAN")
    print(f"  camp rows this project may enter (control=ARROW and a located button): {usable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

