"""PHASE F —— GATHER_RESOURCE 语义目标失败归因。

`SEMANTIC_TARGET_NOT_VERIFIED`（104 次，全部失败中的 43%）是最大单一失败，
其中 174 次 GATHER_RESOURCE 归因里它占 73 次。本工具把该失败拆到
(action.target, state_before 特征) 粒度，回答"到底是哪一步的语义目标丢了"。

只读 learning/episodes.jsonl，不推测。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
OUT_JSON = ROOT / "knowledge/analysis/semantic_target_failures.json"
OUT_MD = ROOT / "docs/SEMANTIC_TARGET_FAILURES.md"

# 阈值裕度实测（720x1280，dataset/raw 顶层 MAP 帧）
MARGIN_NOTES = {
    "BTN_OPEN_RESOURCE_SEARCH": {
        "threshold": 12,
        "observed": {"min": 0, "median": 6, "max": 12, "samples": 51},
        "risk": "最大值已顶到阈值；ROI 内含地图动态指示箭头，pHash 随动画相位漂移，无裕度。",
    },
    "BTN_RESOURCE_SEARCH_SUBMIT": {
        "threshold": 6,
        "observed": None,
        "risk": "未单独标定；如需放宽应先按 ROI 实测分布决定，不得直接套用其它语义的阈值。",
    },
}


def load_episodes() -> list[dict]:
    if not EPISODES.is_file():
        return []
    rows = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def normalised_result(row: dict) -> str:
    return {"success": "SUCCESS", "failure": "FAILURE"}.get(
        str(row.get("result") or ""), str(row.get("result") or "").upper()
    )


def main() -> int:
    rows = load_episodes()
    failures = [
        r
        for r in rows
        if normalised_result(r) == "FAILURE"
        and r.get("failure_type") == "SEMANTIC_TARGET_NOT_VERIFIED"
    ]

    by_target: Counter = Counter()
    detail: dict[str, Counter] = defaultdict(Counter)
    for row in failures:
        target = str((row.get("action") or {}).get("target") or "NO_ACTION")
        by_target[target] += 1
        before = row.get("state_before") or {}
        detail[target][
            "search_open=%s,selected=%s,level=%s"
            % (
                before.get("resource_search_open"),
                before.get("resource_selected"),
                before.get("resource_level"),
            )
        ] += 1

    payload = {
        "source": str(EPISODES.relative_to(ROOT)),
        "failure_type": "SEMANTIC_TARGET_NOT_VERIFIED",
        "total": len(failures),
        "by_action_target": [
            {"target": name, "count": count, "contexts": dict(detail[name].most_common())}
            for name, count in by_target.most_common()
        ],
        "template_margins": MARGIN_NOTES,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# SEMANTIC_TARGET_NOT_VERIFIED 归因（PHASE F）",
        "",
        f"- 来源：`{payload['source']}`",
        f"- 该失败总数：**{payload['total']}**（全部失败 241 次中的 43%）",
        "",
        "## 按失效的动作目标拆分",
        "",
        "| 次数 | action.target | 典型前置状态 |",
        "| ---: | --- | --- |",
    ]
    for entry in payload["by_action_target"][:12]:
        top = next(iter(entry["contexts"].items()), ("-", 0))
        lines.append(f"| {entry['count']} | `{entry['target']}` | {top[0]} ×{top[1]} |")

    lines += ["", "## 阈值裕度实测", ""]
    for name, info in MARGIN_NOTES.items():
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(f"- 当前阈值：{info['threshold']}")
        if info["observed"]:
            o = info["observed"]
            lines.append(
                f"- 实测分布（{o['samples']} 帧）：min {o['min']} / median {o['median']} / max {o['max']}"
            )
        lines.append(f"- 风险：{info['risk']}")
        lines.append("")

    lines += [
        "## 结论",
        "",
        "1. `SELECT_RESOURCE` 的 `RESOURCE_DYNAMIC` 分支在「面板已打开但选中态识别为 None」时",
        "   无法确认目标，需真机复现以定位点击坐标与回读几何的偏差。",
        "2. `SEARCH_RESOURCE` 的 `BTN_OPEN_RESOURCE_SEARCH` 阈值裕度为零（实测最大 12 = 阈值 12），",
        "   属于真实鲁棒性风险，而非当前失败主因。",
        "3. 两者都**尚未真机复验**，因此不得标记为已修复。",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"semantic-target failures={len(failures)}")
    for entry in payload["by_action_target"][:6]:
        print(f"  {entry['count']:4d}  {entry['target']}")
    print(f"written {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
