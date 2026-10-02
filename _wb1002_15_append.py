"""Append this round's order and the two it sized (contract: one queue, no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-14-CITY-HUD-ENTRY-GUARD")
existing = {o["task_id"] for o in orders}

this_round = dict(template)
this_round.update({
    "status": "READY",
    "task_id": "WB-1002-15-MAA-NODE-ATTRIBUTION",
    "priority": "P0",
    "objective": "把 MAA 节点路径的拒绝也具名：让「有识别节点却没命中」的导航 miss 不再返回空原因，"
                 "且模板未命中要带上真实分数与门限",
    "timebox_minutes": 90,
    "why_now": "WB-1002-11/13 的归因记录器**只覆盖 ADB 路径**；当日 31 条带该字段的 "
                "SEMANTIC_TARGET_NOT_VERIFIED 里，12 条理由为空的恰好全是「有 MAA 节点」的技能，"
                "19 条带码的全是无节点技能（退回 adb_resolver ⇒ 走到已有记录器）。空与不空的分界就是这一处。",
    "current_evidence": "空原因 12 条 = OPEN_HOME 6 / OPEN_BUILDING_UPGRADE 4 / "
                        "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT 2，四条节点经 dispatch_hint 全部判为 TEMPLATE；"
                        "对照 SELECT_RESOURCE 15 / SELECT_BEAST_TARGET_MAMMOTH 3 / TRY_ORDINARY_CONTROL 1 全部带码。",
    "root_cause_or_hypothesis": "executor_router.maa_resolver 三处 return None 不写 last_recognition_error"
                                "（默认的模板路径、frame is None、LIST_DYNAMIC 的 fallback 分支）；"
                                "且 build_router:257 把 MAA resolver 绑成 lambda，从不经过 runtime 的 resolve。",
    "files_to_inspect": ["winter_agent_v2/executor_router.py 227-260 与 378-620",
                         "winter_agent_v2/maa_executor.py match_template（分数与 error 已算好）",
                         "tests/test_rally_list_dynamic_node.py（既有的 last_recognition_error 约定）"],
    "files_allowed_to_modify": ["winter_agent_v2/executor_router.py", "tests/ 本单 targeted"],
    "implementation_hint": "纯记录：只写 last_recognition_error，不改返回值与判定。码沿用 DOMAIN:DETAIL；"
                           "模板路径必须带 score 与 gate（「离门限多近」是调阈值还是换模板的唯一判据）。",
    "test_plan": "先红后绿；每条静默分支一个码；并断言「解析成功即清空」与「判定不变」。",
    "replay_plan": "无法在不抢设备的前提下取到 MAA 的真实分数（建第二个 tasker 会与 AUTO 争 ADB），"
                   "故真实取值由部署后的账本给出；部署前只做静态确认（四条节点均为 TEMPLATE 分派）。",
    "live_plan": "部署后读新 episode：出现 MAA_TEMPLATE:*:score=*:gate=* 这类码，且无节点技能的失败不再空原因。",
    "verifier": "节点类技能的 miss 不再空原因；A/B 证明判定与返回值未变。",
    "before_metric": {"empty_reason_node_bearing_misses": 12,
                      "named_reason_nodeless_misses": 19,
                      "silent_return_none_sites": 3},
    "target_metric": {"empty_reason_node_bearing_misses": 0, "verdicts_changed": 0,
                      "template_miss_carries_score": 1},
    "acceptance": ["纯新增；显式 SHA 的 A/B 证明判定未变。",
                   "模板路径的码带真实分数与门限。",
                   "既有约定（回退解析成功时保留主策略理由）不被破坏。"],
    "stop_condition": "90 分钟；或发现必须先改判定才能归因。",
    "fallback_action": "只覆盖能确定的静默分支，其余明确标注未覆盖。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "WB-1002-14 顺手量出的同一家族下一层，已精确到文件行号与条数。",
})

next_one = dict(template)
next_one.update({
    "status": "READY",
    "task_id": "WB-1002-16-GATHER-FORMATION-ROLE-SCOPE",
    "priority": "P0",
    "objective": "让采集出兵真的发出去：让 DISPATCH_MARCH 的编队满足「当前角色域」判据，"
                 "或在拒绝时说清是三个子条件里的哪一个没满足",
    "timebox_minutes": 90,
    "why_now": "采集流程在最新版本上首次端到端跑通（SEARCH→SELECT→SUBMIT→START_GATHER 全 SUCCESS），"
                "却停在最后一跳：DISPATCH_MARCH 的验证器判 DISPATCH_NOT_PROVEN。"
                "而它前两步是两次 CLEAR_GATHER_HEROES 都没把编队修好 —— 重建编队的动作执行了，但没有生效。",
    "current_evidence": "2026-10-02T09:24:28Z，rev 3ce3ef3，DISPATCH_MARCH / FAILURE / DISPATCH_NOT_PROVEN，"
                        "recognition_error 为空（不是识别问题）；verifier_evidence："
                        "gather_formation_policy=STALE_OR_ROLE_UNSCOPED_FORMATION、"
                        "gather_formation_policy_ok=false、gather_formation_is_current_role_scoped=false、"
                        "wood_march_page=true。前两步 09:24:03 / 09:24:06 均为 CLEAR_GATHER_HEROES SUCCESS。",
    "root_cause_or_hypothesis": "CLEAR_GATHER_HEROES 的清空动作与验证器读到的「角色域编队」不是同一件事："
                                "前者可能只清空了一次/一部分，或验证器读的字段来自未刷新的帧；"
                                "也可能 role_scope 的判定口径与清空动作的口径不一致。",
    "files_to_inspect": ["winter_agent_v2/skills.py CLEAR_GATHER_HEROES",
                         "winter_agent_v2/verifier.py 采集编队/角色域相关验证器",
                         "winter_agent_v2/vision.py / ocr.py 中 gather formation 的读者",
                         "learning/episodes.jsonl 该步骤的完整行与其前后两帧"],
    "files_allowed_to_modify": ["winter_agent_v2/verifier.py", "winter_agent_v2/skills.py",
                                "winter_agent_v2/vision.py", "tests/ 本单 targeted"],
    "implementation_hint": "先配对/先读帧：把两条 CLEAR_GATHER_HEROES 的 before/after 与 DISPATCH 的 before 三帧画出来对比，"
                           "确认清空是否真的落到屏幕上。本项目规矩：点击与状态都画出来看。",
    "test_plan": "先红后绿；三个子条件各自一条断言（policy 当前 / role_scoped 为真 / 清空真的改变了读取）。",
    "replay_plan": "用该步骤前后三帧过生产编队读取器，逐帧打印三个子条件的取值。",
    "live_plan": "部署后读新 episode：DISPATCH_MARCH 出现 SUCCESS，或失败时 verifier_evidence 明确指向未满足的那一个子条件。",
    "verifier": "采集全程（含 DISPATCH_MARCH）在真机上 SUCCESS；或失败被精确归因到三个子条件之一。",
    "before_metric": {"dispatch_march_successes": 0, "clear_gather_heroes_steps_before_it": 2,
                      "distinct_sub_conditions_in_evidence": 3},
    "target_metric": {"dispatch_march_successes": ">=1",
                      "unattributed_dispatch_failures": 0},
    "acceptance": ["真实主动出击而非无关动作；有 after 帧与验证器证据。",
                   "若仍失败，必须能说出是哪个子条件（不接受笼统的 NOT_PROVEN）。"],
    "stop_condition": "90 分钟；或发现编队判据本身需要政策决定（那要写清并交回）。",
    "fallback_action": "只把三个子条件变成可区分的证据，不改判据，并写明还缺哪一条测量。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "最新版本上唯一那次失败，且是刚跑通的流程的最后一跳。",
})

next_two = dict(template)
next_two.update({
    "status": "READY",
    "task_id": "WB-1002-17-ROUTING-PROMOTION-INTEGRITY",
    "priority": "P1",
    "objective": "让路由表自己的声明与自己的证据一致：DISPATCH_MARCH 是 27 个 autogen 节点里"
                 "唯一排 P0 的，而它自带的 validation_report 写着 corpus_sufficient: false",
    "timebox_minutes": 60,
    "why_now": "这是仓库里一条**长期存在的红**（test_executor_router::"
               "test_autogen_nodes_are_wired_but_never_promoted），已多轮被归因为既有；"
               "而它说的是一件产品事：一个自动生成的模板正排在最高迁移优先级上，"
               "而生成它的那份报告说语料不足。",
    "current_evidence": "knowledge/execution/backend_routing.json → skills.DISPATCH_MARCH："
                        "recognition.BTN_DISPATCH 为 OCR 节点（expected 出征，roi [440,1120,260,120]），"
                        "promoted=false 但 migration_priority=P0；"
                        "evidence.validation_report = {positives: 1, negatives: 4, positive_hits: 1, "
                        "negative_hits: 0, corpus_sufficient: false}；"
                        "对照全部 autogen 节点的优先级分布 {'P3': 23, 'P1': 4, 'P2': 3, 'P0': 1}。"
                        "该红在 HEAD（executor_router.py md5 abb18679dff6a068423cc1317b1add64）上同样红。",
    "root_cause_or_hypothesis": "P0 是「已晋升」的优先级（test_promoted_skills_route_to_maa_with_adb_fallback "
                                "断言 promoted ⇒ P0），而这条既想享受 P0 的调度优先、又把 promoted 记为 false；"
                                "两种可能：① 优先字打错，应为 P1/P3；② 它其实已被有依据地晋升，"
                                "则 promoted 与 validation_report 都该更新为实测证据。",
    "files_to_inspect": ["knowledge/execution/backend_routing.json（DISPATCH_MARCH 条目）",
                         "learning/ocr_batch1_validation_20260926.json（它引用的验证存档）",
                         "tools/maa_migrate.py 的晋升规则与 corpus_rule",
                         "tests/test_executor_router.py:90-100"],
    "files_allowed_to_modify": ["knowledge/execution/backend_routing.json", "tests/ 本单 targeted"],
    "implementation_hint": "不许为了让测试变绿而改断言。要么按语料规则把它降级，"
                           "要么补齐 >=3 正例 / >=3 反例并记录帧路径后把 promoted 置真。",
    "test_plan": "断言「声明与证据一致」本身：promoted 为假 ⇒ 优先级不得为 P0；"
                 "语料不足 ⇒ 不得进入最高迁移优先级。",
    "replay_plan": "用 tools/maa_migrate.py 的离线评分路径重跑该节点的正反例，取真实分数。",
    "live_plan": "无需真机：本单是知识资产与声明的一致性。",
    "verifier": "该节点在优先级与证据上自洽；长期那条红要么修好、要么按契约显式改口径并写明理由。",
    "before_metric": {"autogen_nodes_at_P0": 1, "corpus_sufficient": False,
                      "positives": 1, "negatives": 4, "standing_red": 1},
    "target_metric": {"autogen_nodes_at_P0": 0, "declaration_matches_corpus": 1},
    "acceptance": ["不接受改断言换绿。",
                   "若判为「其实已可晋升」，必须给出 >=3 正例与 >=3 反例的帧路径与分数。"],
    "stop_condition": "60 分钟；或发现晋升口径本身需要操作者决定。",
    "fallback_action": "只把它降级到与语料相符的优先级，并把「为何曾经是 P0」记进条目。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "归因既有红时量出的知识资产不一致，且是长期红的主题。",
})

for order in (next_one, next_two):
    if order["task_id"] in existing:
        raise SystemExit(f"{order['task_id']} already present; refusing to append twice")
    orders.append(order)

payload["orders"] = orders
payload["updated_at"] = "2026-10-02T09:40:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round: closed the MAA-node attribution layer (WB-1002-15) and appended the "
    "two it exposed -- the gather march's last hop (WB-1002-16) and the routing table's standing "
    "declaration/evidence inconsistency (WB-1002-17)."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("orders now:", len(orders), "->", [o["task_id"] for o in orders[-3:]])
