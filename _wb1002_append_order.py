"""Append this round's root-cause order to the one queue (contract: no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-06-GIANT-RALLY-VERIFIER")

new = dict(template)
new.update({
    "required_tool": template["required_tool"],
    "recommended_tool": template["recommended_tool"],
    "preferred_backend": template["preferred_backend"],
    "fallback_backend": template["fallback_backend"],
    "do_not_touch": template["do_not_touch"],
    "status": "READY",
    "task_id": "WB-1002-10-BEAST-TAB-BRACKET-LOCK",
    "priority": "P1",
    "objective": (
        "让「选择框标的是哪个页签」的读取不再因自身的宽松容差而返回 None，"
        "使普通野兽搜索的切页签动作能被真实识别与验证"
    ),
    "timebox_minutes": 75,
    "why_now": (
        "2026-10-02 全天 80 条 FAILURE 中 AVOID_STAMINA_WASTE 占 43 条、位居第一；"
        "其中 OPEN_BEAST_SEARCH_TAB 失败 16 条（BEAST_SEARCH_TAB_NOT_PROVEN 8 + "
        "SEMANTIC_TARGET_NOT_VERIFIED 8），并且每次失败后都会走 ONLINE_UNKNOWN_NAVIGATION "
        "去问 UI-Venus，而该画面唯一诚实的答案是 REPLAN —— 同一身份在 7 小时内被重复问了 9 次，"
        "4 次纯超时。不是点击错，是读取错。"
    ),
    "current_evidence": (
        "episode 20261002_123127_711948 step_004：点击后客户端的选择框已明显从 冰原巨兽 移到 野兽"
        "（after_refresh_2 帧），state_after.resource_selected_tab 却是 null，"
        "verifier_evidence.after_selected = null ⇒ BEAST_SEARCH_TAB_NOT_PROVEN。"
        "同批 40 帧（ledger 记 resource_search_open=true）实测：真括号对中心到自身标签 0.0000/0.0003/0.0010；"
        "最接近的伪括号对到任意标签 0.0212（15.3 px），分离 15.3 倍。旧容差 0.03 两者都收，"
        "函数在两种 kind 同时命中时拒绝猜，于是回答 None。"
    ),
    "root_cause_or_hypothesis": (
        "winter_agent_v2/ocr.py:3780 selected_tab_from_live_labels 的标签容差 0.03 宽于真实几何："
        "括号画在页签正中，真对中心距标签约 1 px，而页签带滚动/多图标帧会产生间距 134.5 px 的伪描边对，"
        "其中心恰好落在 15 px 外的相邻标签上。两 kind 同时命中 ⇒ 唯一性判据失败 ⇒ None。"
    ),
    "files_to_inspect": [
        "winter_agent_v2/ocr.py selected_tab_from_live_labels / read_resource_tab_labels",
        "winter_agent_v2/vision.py _bracket_strokes / anchored_tab_kind / selected_resource",
        "winter_agent_v2/verifier.py verify_beast_search_tab_selected",
        "winter_agent_v2/brain.py 的 beast 搜索分支",
        "learning/episodes.jsonl 中 OPEN_BEAST_SEARCH_TAB / SUBMIT_GIANT_BEAST_SEARCH 行",
        "learning/ui_venus_online.jsonl 的 AVOID_STAMINA_WASTE|MAP|BEAST_SEARCH_TAB|MAP 记录",
    ],
    "files_allowed_to_modify": [
        "winter_agent_v2/ocr.py 的页签读取容差与其注释",
        "tests/test_resource_tab_bracket_lock.py",
        "本单 targeted regression tests",
    ],
    "implementation_hint": (
        "只收紧容差，不改变唯一性判据：容差收紧后接受的集合是原集合的子集，"
        "于是函数只可能把某个答案变成 None、或把 None 变成同一个答案，永远不可能把一个页签改判成另一个。"
        "0.005 取在实测间隙的几何中点（高于最差真值 4.8 倍、低于最优伪值 4.2 倍）。"
    ),
    "test_plan": "tests/test_resource_tab_bracket_lock.py：先红（4 中 2 红，第 2 条红时旧代码把 15 px 外的伪对判成 SNOW_MONSTER）后绿；相邻 test_stamina_sink_routing / test_resource_tab_anchor / test_semantic_roi_vision 不回归。",
    "replay_plan": "对失败的那一集归档帧跑生产入口 HybridVision.observe：after 帧由 None 变 BEAST，before 帧仍 GIANT_BEAST；再用真实 verifier verify_beast_search_tab_selected 判定同一对 before/after。",
    "live_plan": "部署后由 AUTO 自己在下一个 AVOID_STAMINA_WASTE 野兽搜索步上验收；判据是 OPEN_BEAST_SEARCH_TAB 的 BEAST_SEARCH_TAB_NOT_PROVEN 不再出现（SUCCESS 或该步消失均可），不需要为它单独占设备。",
    "verifier": "verify_beast_search_tab_selected 在真实归档帧上由 ok=False/BEAST_SEARCH_TAB_NOT_PROVEN 变为 ok=True/OK。",
    "before_metric": {
        "open_beast_search_tab_failures_2026_10_02": 16,
        "beast_search_tab_not_proven": 8,
        "semantic_target_not_verified_on_that_skill": 8,
        "frames_reading_None_against_a_real_bracket_of_40": 17,
        "venus_calls_on_the_same_unknown_identity_in_7h": 9,
        "venus_call_timeouts_on_that_identity": 4,
    },
    "target_metric": {
        "open_beast_search_tab_failures_dropping_to": 0,
        "verifier_ok_on_the_archived_failing_frame": 1,
        "frames_losing_a_verdict": 0,
    },
    "acceptance": [
        "同一批真实帧上没有任何一帧从「已有页签」变成 None（只允许 None → 页签）。",
        "生产入口而不是我重写的辅助函数给出结论。",
        "check_wiring problems=0；既有红测试的归属用显式 SHA 的 A/B 说明。",
    ],
    "stop_condition": "75 分钟；或发现收紧容差会拿走任何一帧的真实判定（即单调性假设被证伪）。",
    "fallback_action": "若无法在真实帧上证明单调性，则不改常量，只记录证据并把该缺口写回队列。",
    "dependencies": ["WB-1002-01-HANDOFF-FACTS"],
    "files_scope": [
        "winter_agent_v2/ocr.py",
        "tests/test_resource_tab_bracket_lock.py",
    ],
    "activation_rule": template["activation_rule"],
    "evidence_context": template["evidence_context"],
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": (
        "AVOID_STAMINA_WASTE 是当日第一失败目标，而该簇的根因不在任何既有工单的射程内："
        "既有工单分别覆盖日历/竞技场/科研/建筑/稳定性/Venus 服务，没有一条覆盖「页签选择框读取」。"
        "按工单契约「新增自主根因工单追加到同一队列」追加，不建第二队列。"
    ),
})

if any(o["task_id"] == new["task_id"] for o in orders):
    raise SystemExit("order already present; refusing to append twice")

orders.append(new)
payload["orders"] = orders
payload["updated_at"] = "2026-10-02T07:15:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round appended WB-1002-10 (beast tab bracket lock): the day's "
    "top failure cluster's real root cause was outside every existing order's scope."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("appended:", new["task_id"], "| orders now:", len(orders))
