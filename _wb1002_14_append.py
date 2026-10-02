"""Append this round's order and the next one it sized (contract: one queue, no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-13-LOCATOR-ATTRIBUTION")
existing = {o["task_id"] for o in orders}

this_round = dict(template)
this_round.update({
    "status": "READY",
    "task_id": "WB-1002-14-CITY-HUD-ENTRY-GUARD",
    "priority": "P1",
    "objective": "修掉 11 条「某目标需要城镇 HUD」分支里缺守卫的两条（FISHING / BUILDING），"
                 "并把这条路线的家族判据从手写清单改成从 brain 自身发现",
    "timebox_minutes": 75,
    "why_now": "当日 OPEN_HOME 从地图被发 69 次、失败 10 次，且这 10 次是「目标根本没画在帧上」却仍被点击的唯一成簇原因；"
                "同族 11 条分支里另外 9 条早就有守卫，缺的正是后加的两条。",
    "current_evidence": "2026-10-02 账本：OPEN_HOME 成功 59/59 的 state_before 都是 resource_search_open=False，"
                        "失败 10/10 都是 True（完全分离，无重叠）；10 条分属 FISHING 8（fishing_entry_requires_city_hud，"
                        "0 成功）与 BUILDING 2（building_goal_requires_home）；其中 8 条的下一步就是一次 BACK/SUCCESS，"
                        "再下一步 OPEN_HOME/SUCCESS。",
    "root_cause_or_hypothesis": "BTN_OPEN_HOME 是模板节点（source_template=dataset/candidate/templates/"
                                "btn_open_home__live_attempt8_idle__3.png），而野兽搜索面板画在地图 HUD 之上并盖住回城门，"
                                "所以目标确实不在帧上。缺的不是识别而是决策守卫。",
    "files_to_inspect": ["winter_agent_v2/brain.py 852-856（FISHING）", "winter_agent_v2/brain.py 1737-1738（BUILDING）",
                         "winter_agent_v2/brain.py 1102-1105（已有的守卫形状）",
                         "tests/test_route_goal_requires_home.py"],
    "files_allowed_to_modify": ["winter_agent_v2/brain.py", "tests/test_route_goal_requires_home.py"],
    "implementation_hint": "不发明新机制：照抄同文件里已有的 9 条守卫（BACK + close_resource_search_* 命名族）。"
                           "并顺手修正该测试文件里两条已滞后于 cc5894d（2026-09-27）收窄的断言，把收窄本身钉住。",
    "test_plan": "先红后绿；并新增一条从 brain 自身发现家族的不变式测试，使第 12 条分支无法漏掉守卫。",
    "replay_plan": "_wb1002_14_real_steps.py：把 10 条失败步骤各自的 state_before 重建后问新 brain。",
    "live_plan": "部署后读新 episode：fishing_entry_requires_city_hud 不再出现在失败里，"
                 "而 close_resource_search_for_fishing_goal / _building_goal 开始出现。",
    "verifier": "同上；且判定/坐标来源未变（只换决策，不换取点）。",
    "before_metric": {"open_home_failures": 10, "open_home_successes": 59,
                      "guarded_branches": 9, "unguarded_branches": 2,
                      "stale_assertions_in_the_guard_test": 2},
    "target_metric": {"replayed_steps_now_answering_BACK": "10/10",
                      "unguarded_branches": 0, "family_discovered_by_test": 1},
    "acceptance": ["10 条真实步骤在各自的帧上不再返回 OPEN_HOME。",
                   "A/B 反向证明：HEAD 字节上仍 10/10 是 OPEN_HOME。",
                   "家族不变式由测试发现而非人工枚举。"],
    "stop_condition": "75 分钟；或发现 BACK 不是正确恢复（那要先解释为何 8 条真机就是这样恢复的）。",
    "fallback_action": "若某条 route 的 BACK 语义不同，只为有证据的那条加守卫并写清差异。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "当日第四大成簇（SEMANTIC_TARGET_NOT_VERIFIED 里 OPEN_HOME 10 条），且根因是守卫家族漏了两条而非缺能力。",
})

next_round = dict(template)
next_round.update({
    "status": "READY",
    "task_id": "WB-1002-15-MAA-NODE-ATTRIBUTION",
    "priority": "P0",
    "objective": "把 MAA 节点路径的拒绝也具名：让「有识别节点却没命中」的导航 miss 不再返回空原因",
    "timebox_minutes": 90,
    "why_now": "WB-1002-11/13 给 ADB 路径做了归因，但 MAA 路径从来没做。当日带该字段的版本上，"
                "28 条 SEMANTIC_TARGET_NOT_VERIFIED 里 11 条原因为空，且恰好全是「有 MAA 节点」的技能——"
                "没有节点的技能会退回 adb_resolver，所以它们确实记录了。空与不空的分界就是这一处。",
    "current_evidence": "episodes 2026-10-02：空原因的 11 条 = OPEN_HOME 6 / OPEN_BUILDING_UPGRADE 3 / "
                        "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT 2，三条全部 pref=MAA 且带 recognition 节点"
                        "（backend_routing.json）；对照 SELECT_RESOURCE（declared=LEGACY、无节点）的 13 条全部"
                        "带 UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION。",
    "root_cause_or_hypothesis": "executor_router.maa_resolver 有多条 return None 不写 last_recognition_error："
                                "① 模板路径 607-618 的 return outcome.center_norm()（默认路径，最常走）；"
                                "② frame is None；③ LIST_DYNAMIC 的 fallback 分支 580 行。"
                                "而 MAA 执行器的 resolver 是 build_router:257 的 lambda，从不经过 runtime 的 resolve，"
                                "所以 ADB 侧的记录器在这条路径上完全不生效。",
    "files_to_inspect": ["winter_agent_v2/executor_router.py 227-260（build_router 的 resolver 绑定）",
                         "winter_agent_v2/executor_router.py 378-618（maa_resolver 全部分支）",
                         "winter_agent_v2/maa_executor.py RecognitionOutcome 的 score/error 字段",
                         "learning/episodes.jsonl 上述 11 条"],
    "files_allowed_to_modify": ["winter_agent_v2/executor_router.py", "tests/ 本单 targeted"],
    "implementation_hint": "沿用已验证的 recorder 模式：只记录、不改判定。MAA_TEMPLATE:<score> 这类码要把分数带上——"
                           "「离门限多近」是下一步该调阈值还是该换模板的唯一判据。",
    "test_plan": "先红后绿；每条静默分支一个码，并断言返回值与判定不变。",
    "replay_plan": "对 11 条各取一帧过生产入口，确认码随原因而不同，且模板路径带出真实分数。",
    "live_plan": "部署后读新 episode：同一 failure_type 下不再有「导航类却空原因」的行。",
    "verifier": "导航类 miss 的 recognition_error 不再为空；判定与返回值未变（A/B 证明）。",
    "before_metric": {"empty_reason_navigation_misses": 11, "silent_return_none_sites": 3},
    "target_metric": {"empty_reason_navigation_misses": 0, "verdicts_changed": 0},
    "acceptance": ["纯新增；A/B 证明判定未变。", "模板路径的码带真实分数。"],
    "stop_condition": "90 分钟；或发现必须先改判定才能归因。",
    "fallback_action": "只覆盖能确定的静默分支，其余明确标注未覆盖。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "本单顺手量出的同一家族下一层，已精确到文件行号与条数。",
})

for order in (this_round, next_round):
    if order["task_id"] in existing:
        raise SystemExit(f"{order['task_id']} already present; refusing to append twice")
    orders.append(order)

payload["orders"] = orders
payload["updated_at"] = "2026-10-02T09:20:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round: closed the OPEN_HOME entry-guard family (WB-1002-14) and appended "
    "the MAA-node attribution layer it exposed (WB-1002-15)."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("orders now:", len(orders), "->", [o["task_id"] for o in orders[-2:]])
