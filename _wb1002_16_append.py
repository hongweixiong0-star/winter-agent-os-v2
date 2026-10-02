"""Append the two orders this round sized (contract: one queue, no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-15-MAA-NODE-ATTRIBUTION")
existing = {o["task_id"] for o in orders}

resource_reader = dict(template)
resource_reader.update({
    "status": "READY",
    "task_id": "WB-1002-18-GATHER-RESOURCE-READ-FROM-FRAME",
    "priority": "P1",
    "objective": "给采集路径一个**帧上的**资源事实：读编队页头部的资源标签（生肉/木材/煤炭/铁矿），"
                 "让 formation.resource_source 能变成 PAGE、验证器的资源子句重新成为真检查",
    "timebox_minutes": 90,
    "why_now": "WB-1002-16 把这条子句从'永远为假'改成'页没说就不拦'，但系统**至今没有任何资源帧验证**："
                "编队页头部的四个词没有任何声明的读取记录，而 verify_march_page_open 里那条 "
                "after.resource_target == before.resource_target 两边都是被运行时覆盖后的计划值。"
                "工具已就位：resource_source/resource_observed 两个字段就是为这次交接留的开关——"
                "读取器到位后 resource_source 变 PAGE，验证器无需其它改动即恢复拦截能力。",
    "current_evidence": "实测 2026-10-02（WB-1002-16）：生产观测在 4 张真实编队页帧上给出 page=MARCH 而 "
                        "resource_target=None（修复前是硬编码的 WOOD 占位）；帧上页头可见 生肉；"
                        "knowledge/ui/semantic_dictionary.json 里 '生肉/木材/煤炭/铁矿' 四个词**均未声明**；"
                        "vision.py 另有一处 MAP 页发明 resource_target=\"WOOD\"（L2625 附近）未处理。",
    "root_cause_or_hypothesis": "缺的不是能力而是知识资产：四个资源词没有声明记录，所以读者无从读取；"
                                "按本项目规矩，新 ROI 必须由语料而不是单帧标定。",
    "files_to_inspect": ["knowledge/ui/semantic_dictionary.json", "winter_agent_v2/vision.py 的 MARCH 页读取",
                         "winter_agent_v2/runtime.py _annotate_gather_formation / _stamp_gather_formation_resource",
                         "winter_agent_v2/verifier.py verify_wood_dispatch_from_march 的资源子句",
                         "已归档的编队页帧（先收集不少于 10 帧、覆盖四种资源与两种分辨率）"],
    "files_allowed_to_modify": ["knowledge/ui/semantic_dictionary.json", "winter_agent_v2/vision.py",
                                "winter_agent_v2/runtime.py", "tests/ 本单 targeted"],
    "implementation_hint": "先收语料再标 ROI：至少 10 帧、覆盖四种资源。读取成功时写 "
                           "resource_source=\"PAGE\" 且 resource_observed=读到的值；读不到时保持 NONE。"
                           "**不要**用单帧挪 ROI（camp 坐标已因此改过两轮并回退）。",
    "test_plan": "先红后绿；断言四种资源各自能读到、读不到时不猜、以及 verifier 在 PAGE 与计划不一致时恢复拒绝。",
    "replay_plan": "在语料帧上逐一打印读取值与 ROI，并给出真/伪分离度（真标签 vs 邻近文字）。",
    "live_plan": "部署后读 episode：出现 resource_source=\"PAGE\"，且资源子句不再是 NOT_STATED_BY_PAGE。",
    "verifier": "编队页的资源由帧读出且可复核；page 说的与计划不一致时 dispatch 被拒。",
    "before_metric": {"resource_words_declared": 0, "frames_with_a_frame_resource_read": 0,
                      "invented_resource_sites_remaining": 1},
    "target_metric": {"resource_words_declared": 4, "resource_source_PAGE_on_real_frames": ">=1",
                      "invented_resource_sites_remaining": 0},
    "acceptance": ["新读取器必须在 >=10 帧语料上验证，不接受单帧校准。",
                   "resource_source 的三种取值（PAGE/PLANNED/NONE）真实可区分。"],
    "stop_condition": "90 分钟；或语料不足以支撑 ROI 标定（那就先把语料收集变成单独一单）。",
    "fallback_action": "只声明资源词与 ROI，不接线；把接线留给下一轮。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "WB-1002-16 保留了这个缺口并专门留了开关字段，且已量化到 0 条声明记录。",
})

after_side = dict(template)
after_side.update({
    "status": "READY",
    "task_id": "WB-1002-19-DISPATCH-AFTER-PROOF",
    "priority": "P0",
    "objective": "让出征的 after 侧证据属于**这一掌**：现在它接受任何一条行军，所以一个没发生的出征也可能被记成 OK",
    "timebox_minutes": 75,
    "why_now": "WB-1002-16 的重放暴露了另一半风险：after 侧条件是 page=MAP + 存在 MARCHING/GATHERING + "
                "march_used>=1，而 march_used 是**全局计数**、不区分哪一次出行。于是只要屏幕上本来就有别的行军，"
                "即使这次点击什么都没发出去，验证器也会判 OK。**这与本轮修的假阴性正好相反——是假阳性。**",
    "current_evidence": "2026-10-02T09:24:28 的 DISPATCH_MARCH 行：before 为 MAP/MARCH 页 marches=[] "
                        "march_used=None，after 为 page=MAP marches=['MARCHING'] march_used=1；"
                        "验证器在新资源子句下对这两个状态判 ok=True，而它无法区分这条行军是本次点击造成的、"
                        "还是本来就在（该 episode 后段 step19 显示同一行军已转入 GATHERING）。",
    "root_cause_or_hypothesis": "after 侧只用了全局量（march_used 计数、marches 集合），没有一个属于本次点击的标识；"
                                "每个行军没有 id/起点/资源，所以'多了一条'无法归因到这一掌。",
    "files_to_inspect": ["winter_agent_v2/verifier.py verify_wood_dispatch_from_march 的 after 侧",
                         "winter_agent_v2/models.py MarchState 与 marches 的表示",
                         "winter_agent_v2/vision.py 的 MAP 页行军读取（是否有可分辨的出行标识）",
                         "learning/episodes.jsonl 全部 DISPATCH_MARCH / START_GATHER 行"],
    "files_allowed_to_modify": ["winter_agent_v2/verifier.py", "winter_agent_v2/vision.py", "tests/ 本单 targeted"],
    "implementation_hint": "先量'能不能分辨'：若帧上无法区分两次行军，就**不要装出能分辨**——"
                           "正确的做法是把该子条件降级为'未证明属于本掌'并在证据里写明，"
                           "或改用可归因的量（例如本步的出击前后 march 集合差 + 目标资源）。",
    "test_plan": "先红后绿；断言'本来就有别的行军'时不再被判 OK，或明确记录为不可归因。",
    "replay_plan": "用该 episode 的第 16 步与第 19 步两帧，对比'本次出征前后'与'无关行军'的可区分性。",
    "live_plan": "部署后读新 episode：DISPATCH_MARCH 的 OK 行必须带可归因证据。",
    "verifier": "出征成功要么有属于本次点击的证据，要么明确标为不可归因——不接受'屏幕上有行军'当证明。",
    "before_metric": {"after_side_attributable": False, "global_quantities_used": 2},
    "target_metric": {"after_side_attributable": True,
                      "unattributable_ok_verdicts": 0},
    "acceptance": ["不许把'屏幕上有行军'当成本次出征的证明。",
                   "若确实不可分辨，必须写明并降级判定，而不是保持现状。"],
    "stop_condition": "75 分钟；或发现需要新的帧读取能力（那就先开那个读取器的单）。",
    "fallback_action": "只把不可归因写成证据字段，不改判定，并写明还缺什么。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "本轮修的是假阴性，同一验证器的假阳性是它的镜像，且已在真实行上量化。",
})

for order in (resource_reader, after_side):
    if order["task_id"] in existing:
        raise SystemExit(f"{order['task_id']} already present; refusing to append twice")
    orders.append(order)

payload["orders"] = orders
payload["updated_at"] = "2026-10-02T10:10:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round: closed the gather dispatch's false negative (WB-1002-16) and "
    "appended its two mirrors -- the missing frame-level resource read (WB-1002-18) and the "
    "after-side that accepts any march (WB-1002-19)."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("orders now:", len(orders), "->", [o["task_id"] for o in orders[-2:]])
