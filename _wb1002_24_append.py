"""Append WB-1002-24 (this round) and WB-1002-25/26 (what it sized) to the same queue."""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

BASE = {
    "required_tool": [".venv/Scripts/python.exe", "git", "tools/cq.py", "pytest", "现有 Runtime / MAA"],
    "recommended_tool": "优先现有 GoalLibrary / goal_utility / capability_bootstrap；仅对明确根因做小改动。",
    "preferred_backend": "MAA current-frame semantic execution；ADB 为既有 fallback",
    "fallback_backend": "现有 deterministic / L1 learned step；不绕过租约",
    "do_not_touch": [
        "第二 Scheduler / Executor / WorldState / Session Engine",
        "历史 Episode / Executor Ledger；不得篡改或虚构成功",
        "真钱支付与不可逆操作",
        "git add . / reset --hard / clean -fd / checkout . / restore .",
        "不得为让测试变绿而降低 UNKNOWN 数量、把 UNKNOWN 改成 BLOCKED、删除 Goal 或硬编码假 Skill",
    ],
    "files_scope": "最小改动；先红测试后修",
    "activation_rule": "按优先级领取",
}

THIS_ROUND = {
    **BASE,
    "status": "READY",
    "task_id": "WB-1002-24-SCHEDULED-ROWS-ARE-ROUTABLE",
    "priority": "P0",
    "objective": (
        "让日历产出的活动行（`SCHEDULED_*`）真的能进调度器：它们既有 route 缺失、也没声明 `required_observation`，"
        "因此被定价 `-inf` 且永不产生观察；同时关闭镜像缺陷——3 个有票却无 route 的目标会被选中后落进 brain 的默认分支。"
    ),
    "timebox_minutes": 150,
    "why_now": (
        "面板上 32 个目标里 23 个 UNKNOWN、`priority: None`、贡献能力待发现；这 20 行是模拟器覆盖与活动低保的直接来源，"
        "且它们是唯一'已发现、已定价、却无法被读取'的一族。"
    ),
    "current_evidence": (
        "learning/goal_state.json 2026-10-02 20:15：32 目标，23 UNKNOWN、available_skills=[]、priority=None；"
        "runtime_snapshot.capability_discovery：20 个 SCHEDULED_* 全部 MISSING_NAVIGATION / route_exists=False；"
        "coverage audit：BOARD_ONLY_STATUS=18，全部 chooser_base=-inf，reason=OFF_BOARD_NOTHING_DECLARED；"
        "同时 ALLIANCE_TIMED_EVENTS / USE_FREE_ARENA_ATTEMPTS / LABYRINTH_DAILY 有票(50.0)但 route_exists=False。"
    ),
    "root_cause_or_hypothesis": (
        "route_for 对 `SCHEDULED_{event_id}` 没有答案（id 按发现事件生成，表装不下），而行的证据里已声明 "
        "registered_goal_ids 全是 EVENT；它们还用散文写着 AWAITING_LIVE_CLIENT_READING / CALENDAR_PREVIEW_ONLY，"
        "却没把'要读什么'写进 observation_ticket 唯一会读的 required_observation。另一半：capability_gate 不检查"
        "'是否有技能'，所以有票无 route 的目标能通过 _selectable，而 _sync_brain_goal 会把 brain.current_goal 设成 None。"
    ),
    "files_to_inspect": [
        "winter_agent_v2/goal_library.py",
        "winter_agent_v2/goal_utility.py",
        "winter_agent_v2/runtime.py",
        "winter_agent_v2/capability_bootstrap.py",
        "winter_agent_v2/capability_gate.py",
        "tools/invariant_review.py",
    ],
    "test_plan": "先红后绿：家族 route、带日历的页面枚举、观察声明、选择边界的具名拒绝、两张表名字一致。",
    "replay_plan": "用 tools/full_auto_coverage_audit.py 与 tools/invariant_review.py 取前后数字。",
    "live_plan": "repin 后观察 capability_discovery 是否从 MISSING_NAVIGATION 变 MISSING_OBSERVATION、是否出现安全入口。",
    "verifier": "活动行的当前帧入口观察必须经 _resolve_semantic_target 解析后才可点",
    "before_metric": "KNOWN_EXECUTABLE_GOALS 16 / BOARD_ONLY_STATUS 18 / OFF_BOARD_NOTHING_DECLARED 18",
    "target_metric": "KNOWN_EXECUTABLE_GOALS 33 / BOARD_ONLY_STATUS 1 / OFF_BOARD_NOTHING_DECLARED 1",
    "acceptance": "20 行有 route 且声明了要读什么；3 个无 route 的目标留在板上但不得被执行；不变式全绿；真机观测或明确记录未观测。",
    "stop_condition": "route 与声明落地、选择边界具名拒绝、门全绿、repin 完成。",
    "fallback_action": "若真机窗口内没有活动行步骤，结论写'未观测'并列出可判信号。",
    "dependencies": [],
    "appended_by": "autonomous-development-loop",
    "appended_reason": "面板 23 个 UNKNOWN 的直接成因，且不属于任何既有工单。",
}

NEXT = {
    **BASE,
    "status": "READY",
    "task_id": "WB-1002-25-CALENDAR-ROW-OBSERVATION-LIVE",
    "priority": "P0",
    "objective": (
        "让活动行的**观察那一跳真的发生**：定价半边已由 WB-1002-24 证明，但 `SCHEDULED_*` 从未产生过一次观察步骤。"
        "需要证明 UNKNOWN → 调度器选中 → 生成有界入口候选 → Executor → MAA → Verifier →（成功则为 Candidate Step，"
        "失败则留下 Failure/Recovery/Cooldown 且可重试）。"
    ),
    "timebox_minutes": 180,
    "why_now": (
        "进入候选只是必要条件。生产侧目前 0 次 SCHEDULED_* 步骤，所以整条链的后半段一次都没被观测过；"
        "而它依赖日历页已打开（入口标签才会出现在当前帧）。"
    ),
    "current_evidence": (
        "WB-1002-24 部署后 capability_discovery 应显示 SCHEDULED_* 的 route_exists=True；"
        "runtime.py 的步骤构造对 SCHEDULED_ 有专门分支（用事件 name/aliases 匹配当前帧元素），"
        "但入口需要 DISCOVER_EVENT_CALENDAR 先打开日历页。"
    ),
    "root_cause_or_hypothesis": "未知，需测量：可能是日历未打开导致当前帧没有入口标签，也可能是候选被 _selectable 之后的关卡拒掉。",
    "files_to_inspect": [
        "winter_agent_v2/runtime.py",
        "winter_agent_v2/capability_bootstrap.py",
        "winter_agent_v2/goal_library.py",
        "tests/test_bootstrap_safe_entry_boundary.py",
    ],
    "test_plan": "为'日历页在屏时活动行产生有界入口候选'写红测试；用真实帧复现。",
    "replay_plan": "在已归档的日历页帧上跑生产观测与步骤构造。",
    "live_plan": "repin 后观察是否出现 goal_id 以 SCHEDULED_ 开头的 episode，以及其 verifier 结果。",
    "verifier": "该步骤自己的验证器；失败必须留下可重试的 cooldown 记录",
    "before_metric": "SCHEDULED_* 步骤数 = 0",
    "target_metric": "至少一次 SCHEDULED_* 步骤进入 Executor 并留下 Verifier 结果",
    "acceptance": "真机上出现该步骤；成功形成 Candidate Step，或失败留下 failure/recovery/cooldown 且日后可重试。",
    "stop_condition": "拿到一次真实尝试与它的验证结果。",
    "fallback_action": "若窗口内日历页从未打开，记录该前提并把它作为下一单的阻塞条件。",
    "dependencies": ["WB-1002-24-SCHEDULED-ROWS-ARE-ROUTABLE"],
    "appended_by": "autonomous-development-loop",
    "appended_reason": "定价修好后仍未观测到后半段链路。",
}

NEXT2 = {
    **BASE,
    "status": "READY",
    "task_id": "WB-1002-26-DISCOVERY-DECLARATION-DRIFT",
    "priority": "P1",
    "objective": (
        "修正 `tests/test_goal_discovery_audit.py::test_the_missing_set_is_the_declared_one` 的漂移："
        "它声明的 missing 集合是 3 个，而实测是 5 个（ALLIANCE_MOBILIZATION_ICEFIELD_BEAST / CLAIM_FREE_REWARDS / "
        "OBSERVE_FISHING_STATE / TRAVEL_SUPPLY / USE_NORMAL_FISHING_BAIT），且声明的 3 个实测已可发现。"
    ),
    "timebox_minutes": 90,
    "why_now": (
        "该测试的用途正是'定义与产物对不上时立刻失败'，而它自己也已过期——一条过期的不变式等价于没有不变式，"
        "且它是 WB-1002-24 之外唯一与 UNKNOWN 覆盖率直接相关的红。"
    ),
    "current_evidence": (
        "2026-10-02 实测（A/B，HEAD 与改动后同一结果）：defined=20 discoverable=34，"
        "missing={'ALLIANCE_MOBILIZATION_ICEFIELD_BEAST','CLAIM_FREE_REWARDS','OBSERVE_FISHING_STATE','TRAVEL_SUPPLY',"
        "'USE_NORMAL_FISHING_BAIT'}，与被声明的 3 个不相交。"
        "注意 OBSERVE_FISHING_STATE 在生产板上是 READY 且有 READ_FISHING_STATE，说明至少一个'缺失'是审计探测集的问题而非产品缺失。"
    ),
    "root_cause_or_hypothesis": "声明的 KNOWN_MISSING 从未随引擎变化更新；同时审计的探测集可能覆盖不到那几个目标的分支。",
    "files_to_inspect": [
        "tests/test_goal_discovery_audit.py",
        "tools/goal_discovery_audit.py",
        "winter_agent_v2/goal_library.py",
    ],
    "test_plan": "先判定每个'缺失'是审计探测不足还是产品真的没有分支，再据实更新声明或补探测；不得为了让测试变绿而删名字。",
    "replay_plan": "对每个名字指出它由哪个 WorldState 字段/分支产出，或指出确实没有分支。",
    "live_plan": "用 learning/goal_state.json 的生产目标集合交叉核对。",
    "verifier": "声明的 missing 集合与实测一致，且每个名字带原因",
    "before_metric": "declared=3 measured=5，交集为 0",
    "target_metric": "declared == measured",
    "acceptance": "测试绿且每个名字都有原因；区分'审计探测不足'与'产品确实缺失'。",
    "stop_condition": "声明与实测一致。",
    "fallback_action": "若某个名字无法判定，写明未判定而不是猜测。",
    "dependencies": [],
    "appended_by": "autonomous-development-loop",
    "appended_reason": "本轮 A/B 归属为既有红，且与 UNKNOWN 覆盖率直接相关。",
}


def main() -> int:
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    existing = {o["task_id"] for o in payload["orders"]}
    for order in (THIS_ROUND, NEXT, NEXT2):
        if order["task_id"] in existing:
            raise SystemExit(f"{order['task_id']} already queued; refusing to append twice")
        payload["orders"].append(order)
    payload["updated_at"] = "2026-10-02T12:45:00Z"
    payload["update_reason"] = (
        "WB-1002-24：20 个日历活动行既无 route 又没声明要读什么，被定价 -inf 永不产生观察；"
        "同时 3 个有票无 route 的目标会被选中后落进 brain 默认分支。已按行自身证据补 route 与观察声明，"
        "并把'无 route 不得执行'放到选择边界（票价上的门被 invariant_review 当场否证）。"
        "另开 WB-1002-25（观察那一跳从未发生过）与 WB-1002-26（发现声明的漂移）。"
    )
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("orders now:", len(payload["orders"]))
    print("appended:", THIS_ROUND["task_id"], NEXT["task_id"], NEXT2["task_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
