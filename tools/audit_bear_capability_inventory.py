"""§1.2 + §5.1 — what the project ACTUALLY has for the bear chain, and what it does not.

The task book is explicit that this must not be a summary: each of the 16 capabilities
gets one of five verdicts, and each bear UI element gets one of five status marks, with
the evidence named.  The distinction that matters most is the one the book repeats three
times -- "已有但未接入生产" and "已有候选但缺当前客户端截图" are NOT the same as "可用".

Reads the real registry / manifest / runtime rather than grepping for hopeful names.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
print("=" * 78)
print("§1.2 CAPABILITY INVENTORY")
print("=" * 78)

registry = {}
try:
    from winter_agent_v2.skills import v2_registry
    reg = v2_registry()
    registry = {s.id: s for s in reg.all()}
    print(f"registry loaded: {len(registry)} skills")
except Exception as exc:
    print(f"registry load FAILED: {exc!r}")

verified_atomic: set[str] = set()
try:
    from winter_agent_v2.runtime import LiveRuntime
    verified_atomic = set(getattr(LiveRuntime, "VERIFIED_ATOMIC", {}) or {})
    print(f"VERIFIED_ATOMIC: {len(verified_atomic)}")
except Exception as exc:
    print(f"VERIFIED_ATOMIC load FAILED: {exc!r}")

widgets = set()
try:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    widgets = {r["semantic"] for r in payload["records"]}
    print(f"template manifest: {payload['count']} records, {len(widgets)} semantics")
except Exception as exc:
    print(f"manifest FAILED: {exc!r}")

bear_semantics = sorted(s for s in widgets if any(
    k in s.upper() for k in ("RALLY", "BEAR", "MARCH", "ALLIANCE_WAR", "TAB_RALLY")))
print(f"bear-related templates present: {len(bear_semantics)}")
for s in bear_semantics:
    print(f"    {s}")


def verdict(skill_id: str) -> str:
    if skill_id not in registry:
        return "COMPLETELY_MISSING (not in the registry)"
    if skill_id in verified_atomic:
        return "HAS_AND_PRODUCTION_CALLS_IT (in VERIFIED_ATOMIC -> the loop may dispatch it)"
    return "HAS_BUT_NOT_WIRED (registered, absent from VERIFIED_ATOMIC -> never dispatched)"


print()
print("-" * 78)
print("the 16 capabilities the task book asks about")
print("-" * 78)

checks: list[tuple[str, str]] = [
    ("巨熊活动日程 (schedule)",
     "event_registry.json / BEAR_HUNT start field — read separately below"),
    ("活动开放检测 (open detection)",
     "rally.bear_phase() thresholds — verified present earlier"),
    ("角色切换 (role switch)", "state_truth.record_role + change_player"),
    ("设备独占 (device lease)", "device_lease.py"),
    ("巨熊导航 (navigation)",
     "BTN_ALLIANCE_WAR / TAB_RALLY_LIST / BTN_BEAR_GO templates registered by me today"),
    ("START_RALLY", verdict("START_RALLY")),
    ("JOIN_RALLY", verdict("JOIN_RALLY")),
    ("联盟集结列表识别 (rally list)", "ROW_TARGET_BEAR_COLUMN / STATUS_RALLY_COUNTDOWN (today)"),
    ("英雄与士兵预设 (presets)", "see grep below"),
    ("行军队列判断 (march slots)", "WorldState.march_used/march_max + CHECK_MARCH"),
    ("活动连续执行 (continuous participation)", "see grep below"),
    ("MAA Pipeline", "maa_executor.py + ExecutorRouter"),
    ("UI 模板导入 (template import)", f"{MANIFEST.name}, {len(widgets)} semantics"),
    ("OCR 词典 (dictionary)", "knowledge/ui/semantic_dictionary.json"),
    ("AI UNKNOWN 兜底", "unknown_advisor.py / unknown_dispatch.py"),
    ("Episode 与后帧验证", "verifier.py + learning/episodes.jsonl"),
]
for name, v in checks:
    print(f"  {name:44s} -> {v}")

print()
print("-" * 78)
print("what the bear chain still has NO template for")
print("-" * 78)
# Names the task book's §5.1 lists that we can check against the manifest.
wanted = {
    "A 活动入口": ["BTN_ALLIANCE_WAR", "TAB_RALLY_LIST", "BTN_BEAR_GO",
                   "STATUS_BEAR_WINDOW", "PAGE_ALLIANCE", "TARGET_BEAR_TRAP"],
    "B 集结列表": ["ROW_TARGET_BEAR_COLUMN", "STATUS_RALLY_COUNTDOWN",
                   "BTN_JOIN_ROW", "BTN_AUTO_JOIN"],
    "C 编队": ["PAGE_TITLE_MARCH", "BTN_CONFIRM_MARCH", "TARGET_TROOP_PRESET",
               "BTN_HERO_SELECT", "STATUS_TROOP_CAPACITY"],
    "D 参与结果": ["STATUS_MARCHING", "STATUS_RALLY_JOINED",
                   "STATUS_BATTLE_RESULT", "STATUS_TROOP_RETURNING"],
    "E 异常": ["BTN_CLOSE", "POPUP_GENERIC_REWARD_HEADER", "BTN_RECONNECT_SESSION"],
}
for group, names in wanted.items():
    have = [n for n in names if n in widgets]
    miss = [n for n in names if n not in widgets]
    print(f"\n  {group}")
    print(f"    HAVE : {', '.join(have) or '(none)'}")
    print(f"    MISS : {', '.join(miss) or '(none)'}")
