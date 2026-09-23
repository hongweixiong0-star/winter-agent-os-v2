"""What the quick panel actually changed in the running AUTO, measured from production episodes.

Operator directive 2026-09-23 (快捷面板作为城内任务主要状态与导航入口), final report:

    哪些 Goal 已改为优先使用快捷面板状态？
    哪些旧的周期性页面进入已消除？
    哪些任务真正通过面板对应行进入并完成？
    哪些仅能读取状态，尚未打通执行？
    旧实力详情路线现在还会在什么条件下触发？
    正式 AUTO 中无意义的页面进入减少了多少？

Every number comes from artifacts on disk; the split between before and after is the mtime of
``winter_agent_v2/brain.py`` (the file that carries the decision) rather than a remembered date, so a
re-measurement after another edit cannot silently use a stale boundary.

    python tools/measure_quick_panel_priority.py
    python tools/measure_quick_panel_priority.py --since 2026-09-23T14:40:00+00:00 --out <dir>

Read-only: no device, no clicks, no writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"

#: The steps that only exist because a goal went to look at a page in order to learn a state.
STATE_QUERY_REASONS = (
    "train_goal_power_overview",
    "research_goal_power_overview",
    "training_goal_requires_power_route",
    "research_goal_requires_power_route",
)
#: The route the directive names (加成总览 -> 实力详情 -> the barracks / the lab).
POWER_ROUTE_SKILLS = ("OPEN_POWER_OVERVIEW", "OPEN_POWER_DETAILS")


def _rows() -> list[dict]:
    out: list[dict] = []
    try:
        handle = EPISODES.open(encoding="utf-8")
    except OSError:
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("recorded_at"):
                out.append(row)
    return out


def _landed_at() -> str:
    try:
        stamp = (ROOT / "winter_agent_v2/brain.py").stat().st_mtime
    except OSError:
        return "1970-01-01T00:00:00+00:00"
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def _window(rows: list[dict], since: str, until: str) -> list[dict]:
    """Rows in ``[since, until)``; an empty bound is unbounded (``stamp < ""`` is always False)."""
    out = []
    for row in rows:
        stamp = str(row.get("recorded_at") or "")
        if since and stamp < since:
            continue
        if until and stamp >= until:
            continue
        out.append(row)
    return out


def _panel(row: dict) -> dict:
    value = (row.get("state_before") or {}).get("quick_panel")
    return value if isinstance(value, dict) else {}


def q_states(rows: list[dict]) -> None:
    """Q1/Q2: the panel is now a state source, and the state-query detours are gone."""
    print("===== Q1/Q2  面板作为状态来源；旧的「只为查询状态」进入")
    carried = Counter()
    for row in rows:
        panel = _panel(row)
        if not panel.get("open"):
            continue
        for section in ("building", "camps", "research", "alliance_donation", "hero_recruit"):
            if panel.get(section):
                carried[section] += 1
    print(f"      面板展开的帧: {sum(1 for row in rows if _panel(row).get('open'))}"
          f"  各区块有读数: {dict(carried)}")
    for skill in POWER_ROUTE_SKILLS:
        steps = [row for row in rows if str(row.get("skill")) == skill]
        print(f"      {skill:<22} 步数 {len(steps):>4}"
              f"   结果 {dict(Counter(str(r.get('result')) for r in steps))}")
    reasons = Counter(str(row.get("decision_reason")) for row in rows
                      if str(row.get("decision_reason")) in STATE_QUERY_REASONS)
    print(f"      只为查询状态的进入（理由）: {dict(reasons) or '{}'}")
    refused = Counter(str(row.get("decision_reason")) for row in rows
                      if "so_the_power_route_is_not_a_refresh" in str(row.get("decision_reason"))
                      or "draws_no_enter_control" in str(row.get("decision_reason")))
    print(f"      被「面板已答过」挡下的进入: {dict(refused) or '{}'}")


def q_row_entries(rows: list[dict]) -> None:
    """Q3/Q4: which rows really entered their page, and which are state-only."""
    print("===== Q3/Q4  真正通过面板行进入并完成；仅能读状态的")
    entries = [row for row in rows if "OPEN_TASK_FROM_QUICK_PANEL" in str(row.get("skill"))]
    by_row: dict[str, Counter] = defaultdict(Counter)
    for row in entries:
        by_row[str(row.get("skill"))][str(row.get("result"))] += 1
    if not by_row:
        print("      （语料里没有面板行进入步）")
    for skill, counts in sorted(by_row.items()):
        print(f"      {skill:<40} {json.dumps(dict(counts), ensure_ascii=False)}")

    from winter_agent_v2.brain import _QUICK_PANEL_ROW_SKILL, _QUICK_PANEL_ROW_CLAIM_SKILL
    from winter_agent_v2.ocr import QUICK_PANEL_READ_SECTIONS, SECTION_ROW_KEYS

    print(f"      读取器声明的区块: {list(QUICK_PANEL_READ_SECTIONS)}")
    print(f"      能产出'行'的区块: {dict(SECTION_ROW_KEYS)}")
    print(f"      可进入的行键:     {sorted(_QUICK_PANEL_ROW_SKILL)}")
    print(f"      可领取的行键:     {sorted(_QUICK_PANEL_ROW_CLAIM_SKILL)}"
          f"   ← 空集是量出来的：绿勾中心点过，是死点（见 brain.py 该表上方的记录）")
    rows_seen: Counter = Counter()
    for row in rows:
        for item in (_panel(row).get("rows") or []):
            rows_seen[(str(item.get("kind")), str(item.get("status")), str(item.get("control")))] += 1
    print(f"      面板产出的行（kind,status,control）: {dict(rows_seen)}")


def q_old_route_triggers(rows: list[dict]) -> None:
    """Q5: the conditions under which the power route still fires."""
    print("===== Q5  旧实力详情路线现在还会在什么条件下触发")
    print("      代码上只剩两个触发点，且理由自己说明是哪一种：")
    print("        panel_did_not_serve_this_goal_so_the_power_route_is_the_fallback  (§一.6：面板没在给这个目标干活)")
    print("        以及面板的把手都读不出来时，走 OPEN_POWER_OVERVIEW 兜底")
    live = Counter(str(row.get("decision_reason")) for row in rows
                   if str(row.get("skill")) in POWER_ROUTE_SKILLS)
    print(f"      语料里这些步的理由: {dict(live.most_common(8))}")


def q_waste(before: list[dict], after: list[dict]) -> None:
    """Q6: how much pointless page entry went away."""
    print("===== Q6  无意义的页面进入减少了多少")
    for label, slice_ in (("BEFORE", before), ("AFTER", after)):
        old = [row for row in slice_ if str(row.get("skill")) in POWER_ROUTE_SKILLS]
        query = [row for row in slice_ if str(row.get("decision_reason")) in STATE_QUERY_REASONS]
        opens = [row for row in slice_ if str(row.get("skill")) == "TRY_ORDINARY_CONTROL"
                 and "quick_panel" in str(row.get("decision_reason"))]
        entries = [row for row in slice_ if "OPEN_TASK_FROM_QUICK_PANEL" in str(row.get("skill"))]
        print(f"      {label:<6} steps {len(slice_):>5}   "
              f"实力详情路线 {len(old):>4}   只为查状态 {len(query):>3}   "
              f"展开面板 {len(opens):>3}   面板行进入 {len(entries):>3}")
    old_b = [row for row in before if str(row.get("skill")) in POWER_ROUTE_SKILLS]
    old_a = [row for row in after if str(row.get("skill")) in POWER_ROUTE_SKILLS]
    if old_b:
        rate_b = len(old_b) / max(1, len(before)) * 100
        rate_a = len(old_a) / max(1, len(after)) * 100
        print(f"      => 实力详情路线占比 {rate_b:.2f}% → {rate_a:.2f}%"
              f"（每千步 {len(old_b) / max(1, len(before)) * 1000:.0f} → {len(old_a) / max(1, len(after)) * 1000:.0f} 步）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None,
                        help="when the decision changed (default: brain.py's mtime)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rows = _rows()
    if not rows:
        print("no episodes on file")
        return 1
    rows.sort(key=lambda row: str(row.get("recorded_at")))
    split = args.since or _landed_at()
    before = _window(rows, "", split)
    after = _window(rows, split, "")
    print(f"corpus: {len(rows)} steps, {rows[0].get('recorded_at')} .. {rows[-1].get('recorded_at')}")
    print(f"split at {split}" + ("" if args.since else "   (brain.py mtime; pass --since to move it)"))
    if not after:
        print("NOTE: the AFTER window is empty -- the running AUTO has not yet executed this change,")
        print("      and a before/after comparison needs it to have actually run.")
    print()

    q_states(rows)
    print()
    q_row_entries(rows)
    print()
    q_old_route_triggers(rows)
    print()
    q_waste(before, after)

    if args.out:
        from winter_agent_v2.brain import _QUICK_PANEL_ROW_CLAIM_SKILL, _QUICK_PANEL_ROW_SKILL

        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "quick_panel_priority.json"
        target.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "split": split,
            "corpus": {"steps": len(rows), "from": rows[0].get("recorded_at"), "to": rows[-1].get("recorded_at")},
            "before": {"steps": len(before),
                       "power_route": sum(1 for r in before if str(r.get("skill")) in POWER_ROUTE_SKILLS),
                       "state_query": sum(1 for r in before if str(r.get("decision_reason")) in STATE_QUERY_REASONS),
                       "panel_entries": sum(1 for r in before if "OPEN_TASK_FROM_QUICK_PANEL" in str(r.get("skill")))},
            "after": {"steps": len(after),
                      "power_route": sum(1 for r in after if str(r.get("skill")) in POWER_ROUTE_SKILLS),
                      "state_query": sum(1 for r in after if str(r.get("decision_reason")) in STATE_QUERY_REASONS),
                      "panel_entries": sum(1 for r in after if "OPEN_TASK_FROM_QUICK_PANEL" in str(r.get("skill")))},
            "enter_skills": sorted(_QUICK_PANEL_ROW_SKILL),
            "claim_skills": sorted(_QUICK_PANEL_ROW_CLAIM_SKILL),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print()
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
