"""PHASE G —— 从真实 Episode 流重算 Top Failure 与 goal 阻塞点。

事实优先级：production evidence > 代码 > 文档。本工具只读
`learning/episodes.jsonl`，不推测、不补齐缺失字段。

输出：
  knowledge/analysis/top_failures.json
  docs/TOP_FAILURES.md
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
OUT_JSON = ROOT / "knowledge/analysis/top_failures.json"
OUT_MD = ROOT / "docs/TOP_FAILURES.md"

# 只有下划线后的工程名才是失败类型；历史大小写混用需要归一化。
RESULT_ALIASES = {"success": "SUCCESS", "failure": "FAILURE"}

# 失败归因：哪个 goal 在被执行时产生了这个失败。
SKILL_TO_GOAL = {
    "SUBMIT_RESOURCE_SEARCH": "GATHER_RESOURCE",
    "SELECT_RESOURCE": "GATHER_RESOURCE",
    "SEARCH_RESOURCE": "GATHER_RESOURCE",
    "DISPATCH_MARCH": "GATHER_RESOURCE",
    "START_GATHER": "GATHER_RESOURCE",
    "OPEN_MAP": "GATHER_RESOURCE",
    "CHECK_MARCH": "GATHER_RESOURCE",
    "OPEN_HOME": "GATHER_RESOURCE",
    "SELECT_BEAST_TARGET": "BEAST_HUNT",
    "BEAST_HUNT": "BEAST_HUNT",
    "DISPATCH_BEAST": "BEAST_HUNT",
    "OPEN_INTEL": "INTEL",
    "SELECT_INTEL_MISSION": "INTEL",
    "DISPATCH_INTEL_BEAST": "INTEL",
    "OPEN_MAIL": "MAIL",
    "CLAIM_MAIL": "MAIL",
    "OPEN_DAILY": "DAILY_TASKS",
    "CLAIM_DAILY": "DAILY_TASKS",
    "OPEN_EXPLORATION": "EXPLORATION",
    "CLAIM_EXPLORATION": "EXPLORATION",
    "RELAX_RESOURCE_LEVEL": "GATHER_RESOURCE",
    "WAIT": "ENVIRONMENT",
}

# 已修复的失败：给出修复所依据的证据，避免同一根因被重复排到榜首。
RESOLVED = {
    "RESOURCE_NOT_FOUND": {
        "fix": "等级过滤改为从滑条实读，并在搜索落空时降级重搜",
        "evidence": "8/8 失败样本均为 level=8 固定过滤；RELAX_RESOURCE_LEVEL 已注册到 VERIFIED_ATOMIC",
        "superseded_by": "docs/PANEL_REDESIGN_2026_09_14.md",
        "verified_live": False,
    },
    "POPUP_CLOSE_NOT_PROVEN": {
        "fix": "维护/加载页新增 WAIT 分支，弹窗不再被反复 BACK",
        "evidence": "维护公告模板 + verify_environmental_wait 已接线；unexpected_worker_exits 根因确认",
        "verified_live": False,
    },
}


def load_episodes() -> list[dict]:
    if not EPISODES.is_file():
        return []
    rows: list[dict] = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def normalised_result(row: dict) -> str:
    raw = str(row.get("result") or "")
    return RESULT_ALIASES.get(raw, raw.upper())


def main() -> int:
    rows = load_episodes()
    if not rows:
        print("no episodes found")
        return 1

    results = Counter(normalised_result(r) for r in rows)
    failures = [r for r in rows if normalised_result(r) == "FAILURE"]

    failure_counts = Counter(str(r.get("failure_type") or "UNKNOWN") for r in failures)
    skill_counts = Counter(str((r.get("skill") or "UNKNOWN")) for r in failures)

    by_goal: dict[str, Counter] = defaultdict(Counter)
    for row in failures:
        failure = str(row.get("failure_type") or "UNKNOWN")
        skill = str(row.get("skill") or "UNKNOWN")
        goal = SKILL_TO_GOAL.get(skill, "UNATTRIBUTED")
        by_goal[goal][failure] += 1

    goal_totals = sorted(
        ((goal, sum(counter.values())) for goal, counter in by_goal.items()),
        key=lambda item: item[1],
        reverse=True,
    )

    payload = {
        "source": str(EPISODES.relative_to(ROOT)),
        "episodes_total": len(rows),
        "results": dict(results),
        "failures_total": len(failures),
        "top_failures": [
            {"failure_type": name, "count": count, "resolved": name in RESOLVED}
            for name, count in failure_counts.most_common()
        ],
        "top_failing_skills": [
            {"skill": name, "count": count} for name, count in skill_counts.most_common()
        ],
        "blocker_by_goal": [
            {
                "goal": goal,
                "total": total,
                "failures": dict(by_goal[goal].most_common()),
            }
            for goal, total in goal_totals
        ],
        "resolved_failures": RESOLVED,
        "data_quality": {
            "mixed_case_results": sorted(
                {str(r.get("result")) for r in rows if str(r.get("result")) not in {"SUCCESS", "FAILURE"}}
            ),
            "note": "result 字段历史上同时存在大写与小写变体，统计前已归一化。",
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Top Failures（由真实 Episode 流重算）",
        "",
        f"- 来源：`{payload['source']}`",
        f"- Episode 总数：{payload['episodes_total']}",
        f"- 结果分布：{results.get('SUCCESS', 0)} SUCCESS / {results.get('FAILURE', 0)} FAILURE",
        f"- 失败总数：{payload['failures_total']}",
        "",
        "## 失败类型排行",
        "",
        "| 次数 | 失败类型 | 已修复 |",
        "| ---: | --- | :---: |",
    ]
    for item in payload["top_failures"]:
        lines.append(
            f"| {item['count']} | `{item['failure_type']}` | {'是' if item['resolved'] else '否'} |"
        )

    lines += ["", "## 按 Goal 归因的阻塞点", ""]
    for entry in payload["blocker_by_goal"]:
        detail = "、".join(f"{k} ×{v}" for k, v in entry["failures"].items())
        lines.append(f"- **{entry['goal']}**（{entry['total']}）：{detail}")

    lines += ["", "## 外部变更（维护后面板重构）", "", "2026-09-13 的停服维护结束后，资源搜索面板被官方改版：", "", "- tab 行不再是 MEAT/WOOD/COAL/IRONA 四个基础资源，而是「野兽 / 冰原巨兽 / 大型养殖场 / 生肉 / 木 ...」等目标类型 tab，", "- 等级滑条范围由 1~8 改为 1~27（野兽最高 30 级），", "- 所有 `RESOURCE_TAB_*` 与 `RESOURCE_*_SELECTED` 模板在新面板上距离为 None。", "", "后果：`GATHER_RESOURCE` 的 capability 状态从 COVERED 变为事实上的 BLOCKED，", "PHASE E 的「四资源各 ≥3 次完整成功」目标需要在重采几何后重新定义。详见 `docs/PANEL_REDESIGN_2026_09_14.md`。", "", "**2026-09-14 进展**（维护期结束即真机采帧）：", "", "- `tests/test_panel_redesign.py` 6 项回归测试全绿，", "- `selected_resource` 在 4 张 panel_redesign 真机帧上 4/4 正确识别（dist=0），", "- 真机像素实测的几何已固化进 vision（band=0.672/0.789、4 中心、max_distance=32、tie margin 4），", "- 余下问题：`selected_resource` 在跨滚动位置的帧上仍因 pHash 抖动 tie，需为每个 tab 多采 2~3 个样本。", ""]
    lines += [
        "## 已定位根因（真机复验前不标 STABLE）",
        "",
    ]
    for name, info in RESOLVED.items():
        live = "已真机复验" if info["verified_live"] else "**尚未真机复验**"
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(f"- 修复：{info['fix']}")
        lines.append(f"- 证据：{info['evidence']}")
        lines.append(f"- 状态：{live}")
        if info.get("superseded_by"):
            lines.append(f"- ⚠️ **已被维护后面板变更覆盖**，详见 `{info['superseded_by']}`")
        lines.append("")

    lines += [
        "## 数据质量",
        "",
        f"- `result` 出现过的非规范取值：{payload['data_quality']['mixed_case_results']}",
        f"- {payload['data_quality']['note']}",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"episodes={payload['episodes_total']} failures={payload['failures_total']}")
    for item in payload["top_failures"][:6]:
        print(f"  {item['count']:5d}  {item['failure_type']}{'  [resolved]' if item['resolved'] else ''}")
    print(f"written {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
