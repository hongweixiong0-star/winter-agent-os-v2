"""Append WB-1002-22 (this round) and WB-1002-23 (what it found) to the same queue."""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

BASE = {
    "required_tool": [".venv/Scripts/python.exe", "git", "tools/cq.py", "pytest", "现有 Runtime / MAA"],
    "recommended_tool": "优先现有 Runtime、MAA、Verifier 与 RoutingTable；仅对明确根因做小改动。",
    "preferred_backend": "MAA current-frame semantic execution；ADB 为既有 fallback",
    "fallback_backend": "现有 deterministic / L1 learned step；不绕过租约",
    "do_not_touch": [
        "第二 Scheduler / Executor / WorldState / Session Engine",
        "历史 Episode / Executor Ledger；不得篡改或虚构成功",
        "真钱支付与不可逆操作",
        "git add . / reset --hard / clean -fd / checkout . / restore . / blind stash pop",
    ],
    "files_scope": "最小改动；先红测试后修",
    "activation_rule": "按优先级领取",
}

THIS_ROUND = {
    **BASE,
    "status": "READY",
    "task_id": "WB-1002-22-BUILDING-UPGRADE-ROUTE",
    "priority": "P0",
    "objective": (
        "让 `OPEN_BUILDING_UPGRADE` 的**已存在且已通过测试**的帧内解析器真正被路由到。当日 10 次尝试 0 次成功，"
        "而运行时解析器能在同一帧上读出 `升级` 标签 (0.4993, 0.7188)。"
    ),
    "timebox_minutes": 120,
    "why_now": (
        "它是当日第三大簇（10/145），是唯一一个 0 成功的技能，且阻碍 `KEEP_BUILDING_PRODUCTIVE` 这一核心目标；"
        "上一轮的修复已在树里、已绿、却从未被执行——这是'修好了但路由不到'的典型。"
    ),
    "current_evidence": (
        "episodes.jsonl 2026-10-02：OPEN_BUILDING_UPGRADE 10 次，0 成功，全部 SEMANTIC_TARGET_NOT_VERIFIED，"
        "带 MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75，duration 0.171 s，after_screenshot 为空；"
        "同一步 state_before.building.upgrade_tap_norm=[0.4993,0.7188] 且 decision_reason="
        "selected_building_upgrade_control_precedes_generic_panel_entry。"
    ),
    "root_cause_or_hypothesis": (
        "路由文件声明 preferred=MAA + autogen TEMPLATE 节点（validation=PENDING_RECORD），而 execute() 先试 preferred；"
        "maa_resolver 命中失败时返回 None 且不回落（有意为之，避免盲点）。节点 ROI x335..483 y288..432 不含 y≈920 的控件，"
        "窗口里是雪地——是几何错位而非阈值问题。"
    ),
    "files_to_inspect": [
        "knowledge/execution/backend_routing.json",
        "winter_agent_v2/executor_router.py",
        "winter_agent_v2/pipeline_autogen.py",
        "tests/test_building_upgrade_entry_target.py",
        "tests/test_recognition_backend_declaration.py",
    ],
    "test_plan": "先红后绿：路由/解析器组合、router 先跑 ADB、退休形状、not_migrated 记录、autogen 声明跟随路由。",
    "replay_plan": "在 20261002_184532_133866_step_003_before 上跑生产观测并核对 upgrade_tap_norm。",
    "live_plan": "repin 后 8 分钟窗口观察该技能是否再次出现并成功。",
    "verifier": "OPEN_BUILDING_UPGRADE 的 BUILDING_UPGRADE_PANEL_OPENED",
    "before_metric": "10 attempts / 0 successes / 0.5146 vs gate 0.7",
    "target_metric": "该技能在路线改动后不再以模板理由失败",
    "acceptance": "路由不再首选那个从未作答的节点；real resolver 可达；真机观测或明确记录未观测。",
    "stop_condition": "节点退休、路由可达、测试与门全绿、repin 完成。",
    "fallback_action": "若真机窗口内未出现该技能，结论写'未观测'并列出可判信号。",
    "dependencies": [],
    "appended_by": "autonomous-development-loop",
    "appended_reason": "当日第三大簇且 0 成功，且不在任何既有工单射程内。",
}

NEXT = {
    **BASE,
    "status": "READY",
    "task_id": "WB-1002-23-DEV-TREE-SILENT-REVERT",
    "priority": "P0",
    "objective": (
        "查清**工作树为何在数秒内被还原成 HEAD**，并消除它：本轮两次观察到已提交文件回到 HEAD（一次仅编辑后数秒），"
        "一个未跟踪测试文件在一次读取中不存在、下一次又在；这已实际毁掉两处编辑与生产自己写入的一个 autogen 条目。"
    ),
    "time_minutes": 120,
    "timebox_minutes": 120,
    "why_now": (
        "它损坏的是开发环本身：任何'看文件确认改动生效'的验证都不可信，未提交的工作会被静默丢弃。"
        "本轮因此改为从内存 blob 构造提交（hash-object + 临时索引 + commit-tree），并把这作为纪律写下来；但机制未查明。"
    ),
    "current_evidence": (
        "① 19:0x 与 19:1x 两次：`git diff --stat` 刚显示改动存在，几十秒后同一路径已是 HEAD 字节（md5 cf316ba5d8c68e250940f4510a7c7471 / "
        "d9f9ffc3480cbb80dfb93d9947bb723a），且两文件同时发生，其中一个（winter_agent_v2/）不在 junction 之下；"
        "② tests/test_unvalidated_node_keeps_adb.py 在一次读取中缺失、下一次存在；"
        "③ 生产自己写入的 autogen 条目 OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN 在我一次按 HEAD 字节回写后被抹掉，此后未再出现。"
        "已排除：pin 工作树与 dev 在 knowledge/config/learning/dataset 上是 junction（同 inode，已用 samefile 证实），"
        "但 winter_agent_v2/tests/tools 不是；launch_pinned_production.py 只校验不回写；repin_production.py 的 checkout 排除四个数据目录；"
        "runtime 的 RoutingTable.save() 与 PipelineAutoGen.wire() 都是新鲜加载后写回，不会丢键。"
    ),
    "root_cause_or_hypothesis": "未确定。候选：某个周期性进程对 dev 树做 checkout/clean；或宿主沙箱对工作区做快照回滚。",
    "files_to_inspect": [
        "tools/launch_pinned_production.py",
        "tools/repin_production.py",
        "winter_agent_v2/control_plane_reload.py",
        "learning/control_panel/desktop_startup.log",
    ],
    "files_allowed_to_modify": ["tools/ 下的诊断脚本；查明后最小修复"],
    "implementation_hint": (
        "先测：起一个只读监视器记录 (path, mtime, md5, size) 与被写入时间，覆盖 knowledge/ + winter_agent_v2/ 的代表文件，"
        "持续 10 分钟；出现漂移时抓当时的进程快照（psutil，用项目 venv）与文件锁持有者。不要先改任何东西。"
    ),
    "test_plan": "测量优先：先拿到'谁在何时写了什么'，再谈修。",
    "replay_plan": "把监视器输出与 learning/control_panel/desktop_startup.log、PRODUCTION_LAUNCH.log 的时间对齐。",
    "live_plan": "同一监视器在 AUTO 运行中与停止时各跑一段，用有无差异区分'生产进程'与'宿主/其他进程'。",
    "verifier": "漂移事件带可归因的写入者（PID + cmdline）",
    "before_metric": "未测：本轮的两次漂移都是偶然观察",
    "target_metric": "10 分钟内 0 次未归因漂移",
    "acceptance": "给出写入者身份或证明在 AUTO 停止时消失；并把'验证必须读 git show HEAD:'写成纪律。",
    "stop_condition": "写入者被点名或漂移不再出现且有解释。",
    "fallback_action": "若确实无法归因，则把'所有交付物从内存构造提交'固化为流程，并记录该限制。",
    "dependencies": [],
    "appended_by": "autonomous-development-loop",
    "appended_reason": "本轮直接损失了两处编辑与一个生产写入的条目；这是开发环的 Tier-0 风险。",
}


def main() -> int:
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    existing = {o["task_id"] for o in payload["orders"]}
    for order in (THIS_ROUND, NEXT):
        if order["task_id"] in existing:
            raise SystemExit(f"{order['task_id']} already queued; refusing to append twice")
        payload["orders"].append(order)
    payload["updated_at"] = "2026-10-02T11:30:00Z"
    payload["update_reason"] = (
        "WB-1002-22: OPEN_BUILDING_UPGRADE 的节点 0 成 10 且从未验证，路由却首选它；已按文件自身先例退休并让帧内解析器可达。"
        "WB-1002-23: 本轮两次观察到工作树被静默还原成 HEAD，损坏开发环，列为 P0。"
    )
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("orders now:", len(payload["orders"]))
    print("appended:", THIS_ROUND["task_id"], NEXT["task_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
