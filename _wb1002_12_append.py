"""Append this round's order and the next one it sized (contract: one queue, no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-11-FAILURE-ATTRIBUTION")
existing = {o["task_id"] for o in orders}

this_round = dict(template)
this_round.update({
    "status": "READY",
    "task_id": "WB-1002-12-CAMP-FIRST-TAP",
    "priority": "P1",
    "objective": "判定当日第三高失败簇（训练营动作栏 6 条）是不是缺陷，并给出可复用的判据而不是再挪一次坐标",
    "timebox_minutes": 75,
    "why_now": "FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN 6 条是当日 AVOID_STAMINA_WASTE/巨兽搜索之后最大的成簇失败；"
                "camp_ring 自己的历史显示该坐标已被两轮改动并回退过，需要数据而不是单帧来定论。",
    "current_evidence": "12 条 TAP_FOCUSED_TRAINING_CAMP_*（6F/6S）；camp_ring 的 docstring 声称「按当前帧环测量身体目标」，"
                        "而代码最后是 tap_x=ring_x / tap_y=ring_y。",
    "root_cause_or_hypothesis": "假设是坐标缺陷；需用失败/成功两组的真实坐标与后续结果检验。",
    "files_to_inspect": ["winter_agent_v2/camp_ring.py", "winter_agent_v2/verifier.py 1719/1724",
                         "winter_agent_v2/runtime.py 9686-9717", "winter_agent_v2/escalation_queue.py 1180-1244",
                         "learning/episodes.jsonl 当日训练营行"],
    "files_allowed_to_modify": ["winter_agent_v2/camp_ring.py 的文档契约", "tests/ 本单 targeted"],
    "implementation_hint": "先证伪再动手：三组假设（未跟踪模块是否影响发布树、6 条失败是否缺陷、升级是否误报）都必须用真实数据判。",
    "test_plan": "营地取点相关 8 个测试文件点名运行；既有红用显式 SHA 的 A/B 归属。",
    "replay_plan": "把生产取点器画在失败帧上目视复核（本项目自己的规矩），并逐候选打印它的门限判定。",
    "live_plan": "无需真机：本单结论来自归档帧与账本。",
    "verifier": "三组假设各自的证伪证据可复现；文档契约与实现一致。",
    "before_metric": {"camp_action_bar_failures": 6, "camp_steps_total": 12,
                      "documented_vs_implemented_mismatch": 1, "untracked_module_in_package": 1},
    "target_metric": {"defects_confirmed": 0, "defects_falsified_with_evidence": 3,
                      "docstring_matches_behaviour": 1},
    "acceptance": ["结论必须有可复现证据，不接受「看起来像」。",
                   "不得在单帧证据上移动坐标（该模块已因两次如此改动回退）。"],
    "stop_condition": "75 分钟；或任一假设被证实为真缺陷（那就要另开修复）。",
    "fallback_action": "若无法判定，写清还缺哪一条测量并保持现状。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "第三大成簇需要定论，且上一单新加的 recognition_error 正好把「非导航类 miss」框了出来。",
})

next_round = dict(template)
next_round.update({
    "status": "READY",
    "task_id": "WB-1002-13-LOCATOR-ATTRIBUTION",
    "priority": "P0",
    "objective": "把「注册定位器为什么没命中」也写成账本事实：让非导航类 miss（当日 18 条）可分类",
    "timebox_minutes": 90,
    "why_now": "WB-1002-11 落地后，非导航类 miss 只得到 NOT_A_NAVIGATION_ACTION：真实但浅一层。"
                "当日 53 条 SEMANTIC_TARGET_NOT_VERIFIED 中 31 条是导航类（已有具体码）、22 条是"
                "SELECT_RESOURCE 10 / SELECT_BEAST_TARGET_MAMMOTH 8 / TRY_ORDINARY_CONTROL 3 / SEARCH_RESOURCE 1，"
                "后者正是「决策层说目标可见、解析层却在同一帧找不到」的老分裂。",
    "current_evidence": "episodes 2026-10-02：SELECT_BEAST_TARGET_MAMMOTH 的 decision_reason 是 "
                        "verified_visible_mammoth_target 却 SEMANTIC_TARGET_NOT_VERIFIED；SELECT_RESOURCE 10 条同理。",
    "root_cause_or_hypothesis": "runtime._resolve_semantic_target（4437 起）的每个分支都不记录「哪个分支返回了 None」，"
                                "所以「定位器没命中」无法再往下分。",
    "files_to_inspect": ["winter_agent_v2/runtime.py _resolve_semantic_target 全部分支",
                         "winter_agent_v2/vision.py 各 reader", "learning/episodes.jsonl 上述 22 条"],
    "files_allowed_to_modify": ["winter_agent_v2/runtime.py", "tests/ 本单 targeted"],
    "implementation_hint": "沿用 WB-1002-11 已验证的 recorder 模式：只记录、不改判定；码沿用 DOMAIN:DETAIL。",
    "test_plan": "先红后绿；每个分支一条拒绝码，并断言返回值不变。",
    "replay_plan": "对 22 条失败各取一帧过生产入口，确认码随原因而不同且非常量。",
    "live_plan": "部署后读新 episode：同一 failure_type 下出现多个不同码。",
    "verifier": "非导航类 miss 的 recognition_error 不再是单一常量，且判定/返回值未变。",
    "before_metric": {"non_navigation_misses": 22, "distinct_codes_for_them": 1},
    "target_metric": {"distinct_codes_for_them": ">1", "verdicts_changed": 0},
    "acceptance": ["纯新增；用 A/B 证明判定未变。", "码非常量。"],
    "stop_condition": "90 分钟；或发现必须先改判定才能归因。",
    "fallback_action": "只写能确定的层，空白处明确标注。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "WB-1002-11 明确留下的下一层，且已量化到条数与技能。",
})

for order in (this_round, next_round):
    if order["task_id"] in existing:
        raise SystemExit(f"{order['task_id']} already present; refusing to append twice")
    orders.append(order)

payload["orders"] = orders
payload["updated_at"] = "2026-10-02T08:30:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round: closed the third-largest cluster as a designed interaction "
    "(WB-1002-12) and appended the layer WB-1002-11 exposed as next (WB-1002-13)."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("orders now:", len(orders), "->", [o["task_id"] for o in orders[-2:]])
