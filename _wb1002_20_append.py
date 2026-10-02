"""Append this round's order and the one it sized (contract: one queue, no second queue)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

payload = json.loads(QUEUE.read_text(encoding="utf-8"))
orders = payload["orders"]
template = next(o for o in orders if o["task_id"] == "WB-1002-16-GATHER-FORMATION-ROLE-SCOPE")
existing = {o["task_id"] for o in orders}

this_round = dict(template)
this_round.update({
    "status": "READY",
    "task_id": "WB-1002-20-RESOURCE-TAB-LABEL-FALLBACK",
    "priority": "P0",
    "objective": "让材料页签用**它自己标签读出来的位置**作为点击点：几何层解析不出来时回退到 OCR 标签中心",
    "timebox_minutes": 75,
    "why_now": "部署版本 76a5e90 上**全部 4 条失败**都是 SELECT_RESOURCE（0.11-0.14 s、无 after 帧、从未到设备），"
                "而它们自己的 state_before 显示：目标 MEAT **就在 `resource_tab_kinds` 里**"
                "（('BEAST','GIANT_BEAST','MEAT','WOOD')），而 `resource_tab_offset` / `anchored_tab_kind` / "
                "`resource_selected_tab` 三项全 None。**身份层知道页签在哪，几何层什么都解析不出**，"
                "解析器只有一行 `resource_cell_center_norm` ⇒ 有身份、没有点。",
    "current_evidence": "2026-10-02 帧 20261002_182040_468682 / 20261002_182322_031915 四帧："
                        "生产观测读到四个页签中心（生肉 (0.6896,0.7394) 等，OCR 置信 0.95-1.00）；"
                        "`ocr.py:5716-5719` 只留 `resource_beast_tab_norm` / `resource_giant_beast_tab_norm`，"
                        "**材料页签的中心被丢弃**，只剩名字进 `kinds`；"
                        "而 `runtime.py:5032` / `:4985` 早就把这两条标签中心**当作点击点**（2026-09-21 起）。",
    "root_cause_or_hypothesis": "不是一个需要发明的新机制，而是项目自己为「最先需要的那两个页签」选定的模式，"
                                "没有接到其余页签上：`read_resource_tab_labels` 返回 kind→中心，"
                                "消费者只有两条被保留下来。",
    "files_to_inspect": ["winter_agent_v2/ocr.py read_resource_tab_labels 与其在观测里的赋值",
                         "winter_agent_v2/models.py resource_beast_tab_norm / resource_tab_kinds",
                         "winter_agent_v2/runtime.py RESOURCE_DYNAMIC 与 BEAST_SEARCH_TAB 两个解析器",
                         "20261002_182040_468682 等四帧"],
    "files_allowed_to_modify": ["winter_agent_v2/models.py", "winter_agent_v2/ocr.py",
                                "winter_agent_v2/runtime.py", "tests/ 本单 targeted"],
    "implementation_hint": "几何优先、标签兜底——照 BEAST_SEARCH_TAB 的既有顺序；"
                           "把三处重复的取值范围校验收进一个助手（`_tab_label_centre`）。"
                           "**不要**给标签加位置校准：它是客户端自己画的字，读到的就是它画的地方。",
    "test_plan": "先红后绿；观测层保留读到的每个中心、解析器几何优先/标签兜底、越界与缺页拒绝、两条既有页签不回归。",
    "replay_plan": "_wb1002_20_replay.py：四条真实失败帧 帧→生产观测→解析器，并把解出的点画在条带上目视。",
    "live_plan": "部署后读 episode：SELECT_RESOURCE 不再成对失败；成功行的 after 帧存在。",
    "verifier": "目标页签在屏上时必须能解析出一个点，且该点落在页签上（画出来看）。",
    "before_metric": {"select_resource_failures_on_76a5e90": 4, "select_resource_successes": 0,
                      "frames_resolving_a_point": 0, "tab_centres_kept": 2},
    "target_metric": {"frames_resolving_a_point": "4/4", "tab_centres_kept": 7,
                      "geometry_precedence_preserved": 1},
    "acceptance": ["四条真实帧各自解析出目标页签的点，并画在帧上核对落在该页签内。",
                   "A/B 反向证明：HEAD 上同样红。",
                   "不改变几何优先的既有顺序。"],
    "stop_condition": "75 分钟；或发现标签中心与页签命中区不一致（那就要另开一次带语料的校准）。",
    "fallback_action": "只保留中心并让它可测，不改解析器；把接线留给下一轮。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "当前部署版本上全部 4 条失败，且修法是项目自己既有的模式。",
})

next_one = dict(template)
next_one.update({
    "status": "READY",
    "task_id": "WB-1002-21-STRIP-BRACKET-CHAIN-DEAD",
    "priority": "P1",
    "objective": "查清页签条带的几何层为何**什么都解析不出**：`resource_tab_offset` / `anchored_tab_kind` / "
                 "`selected_resource` 在每条测得帧上都是 None",
    "timebox_minutes": 90,
    "why_now": "WB-1002-20 用 OCR 标签把**点击**这一端接上了，但几何层仍然是死的，而它承载的是**另一个问题**："
                "`resource_selected_tab`（白括号锚在哪个页签）来自这条链，而 brain 用它当门"
                "（brain.py:2667「The gate is resource_selected_tab, not resource_beast_tab_norm」）。"
                "一条什么都解析不出的链，等于那个门永远拿到 None。",
    "current_evidence": "2026-10-02：四条 SELECT_RESOURCE 失败帧上 `resource_tab_offset`=None、"
                        "`anchored_tab_kind`=None、`selected_resource`=None，而同一帧 OCR 读到四个页签"
                        "（置信 0.95-1.00）。更早一轮（WB-1002-13）在 20 条失败帧上量到同样三项全 None。"
                        "即**几何层从未在这些画面上成功过**，不是偶发。",
    "root_cause_or_hypothesis": "白括号描边/条带偏移的检测条件在这些画面上不成立（阈值、条带 y 或 ROI），"
                                "或者该分支的入口条件先失败；需要逐帧打印它内部的中间量才能定位。",
    "files_to_inspect": ["winter_agent_v2/vision.py selected_resource / anchored_tab_kind / resource_tab_offset 的实现",
                         "winter_agent_v2/ocr.py 里白括号/条带的读取与阈值",
                         "winter_agent_v2/brain.py:2660-2680 对 resource_selected_tab 的用法",
                         "上述帧与更多同形态帧（>=10 帧）"],
    "files_allowed_to_modify": ["winter_agent_v2/vision.py", "winter_agent_v2/ocr.py", "tests/ 本单 targeted"],
    "implementation_hint": "先当**测量**做：把该分支的每个中间量逐帧打印，判定是阈值问题还是入口问题。"
                           "**不要只看一帧就动阈值**（camp 坐标因此改过两轮并回退）。",
    "test_plan": "先红后绿；断言在语料帧上三项至少有一项解析出来，且假阳性（解析到错的页签）为 0。",
    "replay_plan": "在 >=10 帧语料上给出真/伪分离度（解析出的 vs 邻近页签）。",
    "live_plan": "部署后读 episode：`resource_selected_tab` 不再是常量 None。",
    "verifier": "该链在真实帧上至少解析出一项，且不与 OCR 标签读到的身份矛盾。",
    "before_metric": {"fields_resolving_nothing": 3, "frames_measured": "4 + 20 早前"},
    "target_metric": {"fields_resolving_something": ">=1", "contradictions_with_ocr": 0},
    "acceptance": ["先用多帧测量判定原因，再考虑改阈值。",
                   "若判为「几何层不再需要」（OCR 标签已足够），必须写清 `selected_resource_tab` 由谁提供替代。"],
    "stop_condition": "90 分钟；或发现需要语料收集（那就先开那一单）。",
    "fallback_action": "只把中间量变成可观测的证据，不改判定，并写明还缺哪一条测量。",
    "appended_by": "WorkBuddy autonomous development, 2026-10-02",
    "appended_reason": "WB-1002-20 接上了点击端，几何层这一端仍死，且它承载 brain 的一个门。",
})

for order in (this_round, next_one):
    if order["task_id"] in existing:
        raise SystemExit(f"{order['task_id']} already present; refusing to append twice")
    orders.append(order)

payload["orders"] = orders
payload["updated_at"] = "2026-10-02T10:40:00+00:00"
payload["update_reason"] = (
    "WorkBuddy autonomous round: closed the material tabs' missing tap point (WB-1002-20) and "
    "appended the dead geometry branch it exposed (WB-1002-21)."
)
QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("orders now:", len(orders), "->", [o["task_id"] for o in orders[-2:]])
