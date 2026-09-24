"""Ask the real local model for one structured action and print what came back.

This is the loop's first acceptance step and nothing more:

    STRUCTURED_OUTPUT_PASS   the model returned a plan that parses and validates
    + element id             it named an element this frame really produced
    + no geometry            it did not transport a coordinate

It is a **probe**, not a completion claim: it performs no device action and proves nothing
about MAA or about a goal.  See ``docs/LOCAL_PLANNER_ACCEPTANCE.md`` for the four levels and
which of them this one reaches.

Usage:
    python tools/probe_local_planner.py                     # built-in sample screen
    python tools/probe_local_planner.py --frame <png>       # a real frame's own OCR elements
    python tools/probe_local_planner.py --goal TRAIN_TROOPS --trials 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import local_qwen, ui_planner  # noqa: E402

#: A screen shape this project has real questions about: the client's own printed controls on
#: an unnamed page, with the goal that was standing when the question was filed.  Used only
#: when no ``--frame`` is given, so the probe runs without a device.
SAMPLE_ELEMENTS = [
    {"id": "E1", "text": "领取", "area": "middle"},
    {"id": "E2", "text": "挂机收益", "area": "top"},
    {"id": "E3", "text": "快速挂机", "area": "lower"},
    {"id": "E4", "text": "钻石", "area": "lower"},
    {"id": "E5", "text": "关闭", "area": "top"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", default="DAILY_ROUTINE")
    parser.add_argument("--page", default="UNKNOWN::挂机收益")
    parser.add_argument("--frame", default="", help="a real frame; its OCR becomes the element table")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    client = local_qwen.from_config(config, root=ROOT)
    if client is None:
        print("local_planner.enabled is false in the config -- nothing to probe")
        return 3
    ok, reason = client.available(force=True)
    print(f"model    : {client.model}")
    print(f"endpoint : {client.endpoint}")
    print(f"reachable: {ok} ({reason})")
    if not ok:
        return 2

    elements = SAMPLE_ELEMENTS
    world_state: dict[str, object] = {"page": "UNKNOWN", "confidence": 0.18}
    if args.frame:
        frame = Path(args.frame)
        if not frame.is_file():
            print(f"frame not found: {frame}")
            return 4
        from winter_agent_v2.ocr import RapidOCRBackend
        from winter_agent_v2 import ui_collection

        ocr = RapidOCRBackend(Path(config["ocr"]["module_path"]))
        regions = ui_collection.grounding_regions(frame, ocr)
        elements = [
            {"id": f"E{i + 1}", "text": str(r.get("text") or ""),
             "area": ui_planner._area_of(r.get("box_norm") or {})}
            for i, r in enumerate(regions) if str(r.get("text") or "").strip()
        ][:30]
        print(f"frame    : {frame} -> {len(elements)} element(s) from its own OCR")

    packet = ui_planner.build_packet(
        goal=args.goal, current_page=args.page, world_state=world_state,
        elements=elements, actions=ui_planner.OFFERED_ACTIONS,
        relevant_knowledge=[], last_action=None, last_result=None, remaining_steps=2,
    )
    print("packet   :")
    print(json.dumps(packet, ensure_ascii=False, indent=1))
    print("-" * 78)

    passed = 0
    for trial in range(max(1, args.trials)):
        call = client.ask_json(
            system=ui_planner.SYSTEM_PROMPT, user=ui_planner.render_packet(packet),
            purpose="probe", element_count=len(elements), timeout_s=args.timeout,
        )
        print(f"trial {trial + 1}: ok={call.ok} latency={call.latency_ms:.0f}ms "
              f"prompt={call.prompt_chars}c reply={len(call.text)}c")
        if not call.ok:
            print(f"  error: {call.error}")
            continue
        print("  raw  :", call.text[:400].replace("\n", " "))
        parsed = ui_planner.parse_plan(call.text, elements=elements)
        if not parsed.ok:
            print(f"  REFUSED: {parsed.error}")
            continue
        assert parsed.plan is not None
        plan = parsed.plan
        print(f"  PLAN : decision={plan.decision} action={plan.action_type} "
              f"element={plan.target_element_id} text={plan.target_text!r}")
        print(f"         expected_page={plan.expected_page!r} reason={plan.reason!r}")
        passed += 1
    print("-" * 78)
    print(f"STRUCTURED_OUTPUT_PASS: {passed}/{max(1, args.trials)}")
    return 0 if passed else 5


if __name__ == "__main__":
    raise SystemExit(main())
