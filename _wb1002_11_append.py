"""Append this round's root-cause order to the one queue (contract: no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-10-BEAST-TAB-BRACKET-LOCK")

new = dict(template)
new.update({
    "status": "READY",
    "task_id": "WB-1002-11-FAILURE-ATTRIBUTION",
    "priority": "P0",
    "objective": (
        "让「这一步为什么没找到控件」在账本里可回答：把既有但无人读的识别失败原因写进 episode，"
        "使最大的一类失败从不可分类变成可分类"
    ),
    "timebox_minutes": 90,
    "why_now": (
        "2026-10-02 全天 1586 步 / 92 失败，其中 SEMANTIC_TARGET_NOT_VERIFIED 47 条（51%，最大一类），"
        "全部 after_screenshot 为空（动作根本没到设备）、executor_backend 为空、observed_change=UNKNOWN，"
        "而**没有一条**带任何原因。项目一直是在源码注释里手工回答「为什么 miss」，不是用数据回答。"
        "写入方早就存在：executor_router.last_recognition_error 有完整词表"
        "（MAA_OCR:NO_TEXT / STRUCTURE:NO_ANCHOR / LIST_DYNAMIC:NO_ROWS / TARGET_FALLBACK_REFUSED），"
        "但读取方只有四个手写 tools/device_*.py 诊断脚本，生产写入路径完全不读它。"
        "另有一层：runtime._unknown_navigation_target 的每个守卫都只 return None，不说明是哪一个。"
    ),
    "current_evidence": (
        "episodes.jsonl 2026-10-02：47 条 SEMANTIC_TARGET_NOT_VERIFIED，"
        "executor_backend 全为 ''、after_screenshot 全为空、recognition_error 字段尚不存在。"
        "VERIFIED_ATOMIC 静态扫描：140 个验证器里 18 个只返回 2 参 VerificationResult、完全没有 evidence，"
        "而这 18 个正好覆盖当日其余高频失败（SUBMIT_GIANT_BEAST_SEARCH 17、训练营一族 9、"
        "VERIFY_GATHERING、COLLECT_MY_REWARDS_ROW）。"
    ),
    "root_cause_or_hypothesis": (
        "attribution 断在两处：(1) 执行器路由已算出原因，但没人把它写进 episode；"
        "(2) 解析器自己的守卫拒绝时只回 None。两处都是「生产者存在、消费者缺失」的接线缺口，不是缺功能。"
    ),
    "files_to_inspect": [
        "winter_agent_v2/executor_router.py last_recognition_error 的全部写入点",
        "winter_agent_v2/executor.py TAP_SEMANTIC / SWIPE 的解析失败分支",
        "winter_agent_v2/runtime.py _unknown_navigation_target / 两处 resolve 闭包 / _record_episode",
        "winter_agent_v2/learning.py Episode 字段",
        "learning/episodes.jsonl 当日失败行",
    ],
    "files_allowed_to_modify": [
        "winter_agent_v2/runtime.py",
        "winter_agent_v2/learning.py",
        "tests/test_recognition_error_attribution.py",
    ],
    "implementation_hint": (
        "纯新增字段，不改任何判定与返回值：Episode 加 recognition_error（默认 ''），"
        "runtime 在两处 resolve 闭包里记录拒绝码（词表 UNKNOWN_NAV:* + RESOLVER:LOCATOR_MISSED），"
        "每步开始时重置以免串味；优先取 router 的 last_recognition_error（它说的是「试了哪种识别」），"
        "没有才用 resolver 的拒绝码（它说的是「哪个守卫没让问」）。两处都必须证明是 recorder 而非 decision。"
    ),
    "test_plan": "tests/test_recognition_error_attribution.py：8 个守卫拒绝码 + recorder 性质（返回值不变）+ Episode 字段与 asdict 序列化 + 优先级。先红后绿；A/B 用显式 SHA 逐字节还原证明 HEAD 上既没有记录也没有字段。",
    "replay_plan": "把 47 条失败里每种 skill 取一条，用当日归档帧过生产入口，确认得到的码随失败原因而不同、且不是同一个常量。",
    "live_plan": "部署后读下一批新 episode：recognition_error 必须出现在真实失败行上，且同一个 failure_type 下出现多个不同取值（否则等于没分类）。",
    "verifier": "新 episode 的 recognition_error 非空且取值分布 >1；同一批 episode 的 result/verifier_ok 与改动前同类步骤一致（判定未被改变）。",
    "before_metric": {
        "episodes_2026_10_02": 1586,
        "failed": 92,
        "semantic_target_not_verified": 47,
        "failed_rows_with_any_stated_reason": 0,
        "verifiers_returning_no_evidence": 18,
    },
    "target_metric": {
        "failed_rows_naming_their_reason": 47,
        "distinct_reasons_on_the_same_failure_type": 2,
        "verdicts_changed_by_this_work": 0,
    },
    "acceptance": [
        "字段是新增的，判定、返回值、控制流一律不变（用 A/B 证明）。",
        "码不是常量：同一 failure_type 下必须出现多个不同取值。",
        "既有红测试的归属用显式 SHA 的 A/B 说明，不静默改基线。",
    ],
    "stop_condition": "90 分钟；或发现要归因就必须改变某个判定（那属于另一单）。",
    "fallback_action": "若只有部分层能给出原因，就只写能确定的那部分并明确标注空白，不编造原因。",
    "dependencies": ["WB-1002-01-HANDOFF-FACTS"],
    "files_scope": [
        "winter_agent_v2/runtime.py",
        "winter_agent_v2/learning.py",
        "tests/test_recognition_error_attribution.py",
    ],
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": (
        "这是 2026-10-02 凌晨 SEMANTIC_TARGET_DIAGNOSIS 文档 §E 排在第一位的待办（「让失败可归因」），"
        "至今未做；且它覆盖当日 51% 的失败，没有任何既有工单的射程包含它。"
        "按工单契约追加到同一队列，不建第二队列。"
    ),
})

if any(o["task_id"] == new["task_id"] for o in orders):
    raise SystemExit("order already present; refusing to append twice")

orders.append(new)
payload["orders"] = orders
payload["updated_at"] = "2026-10-02T07:45:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round appended WB-1002-11 (failure attribution): 47 of the day's 92 "
    "failures were unclassifiable, and both layers that knew the answer already existed."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("appended:", new["task_id"], "| orders now:", len(orders))
