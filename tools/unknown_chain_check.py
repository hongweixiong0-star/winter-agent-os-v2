"""Replay the UNKNOWN channel end-to-end on the questions the AUTO really asked.

    python tools/unknown_chain_check.py                 every request on file
    python tools/unknown_chain_check.py --request <id>  one of them
    python tools/unknown_chain_check.py --request <id> --answer-file a.json
                                                        convert a candidate answer, writing nothing

What this is for
----------------
Directive 2026-09-22 ("UNKNOWN AI 求助通道补齐") §六: 先用已有真实 UNKNOWN 截图进行隔离测试，验证
请求、自动作答、候选动作和执行参数的完整转换 -- and explicitly *not* by re-running INTEL hoping an
unknown screen turns up.  So this takes the requests already on disk (with their real frames), and
prints every step of the conversion with the value that step produced:

    the question          id, screen, goal, the frame, and when it was asked
    the evidence          the regions this frame measures (text / template / anchored), with bases
    the answer            whether one is on file, and what the runtime's own parser makes of it
    the candidate action  which of the three shapes it is, and the element it names
    the grounding         which of the frame's regions justifies the point, and on what basis
    the risk decision     whether that candidate may be pressed, and why not when it may not
    the execution         the pixel coordinate the MAA tap would use, or the reason there is none

It is read-only: nothing is tapped, no job is submitted, and no file is written.  A question with no
answer yet prints the point in the chain where it is waiting, which is the honest result -- the
runtime is not blocked by it either, and the next matching step picks the answer up if one arrives.

``--answer-file`` exists so a candidate answer can be put through exactly this conversion *without*
writing it into the live queue: an answer handed to the running AUTO is a real action on a real
screen, and checking one should not be the same act as publishing it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import (  # noqa: E402
    page_knowledge,
    ui_collection,
    unknown_advisor,
)
from winter_agent_v2.skills import v2_registry  # noqa: E402

FRAME_WIDTH = 720
FRAME_HEIGHT = 1280


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _risk(advice, region) -> str:
    identity = " ".join(
        [
            str((region or {}).get("text") or ""),
            str(advice.target_semantics or ""),
            str(advice.grounding_ref or ""),
        ]
    ).lower()
    for word in unknown_advisor.REFUSED_WORDS:
        if word.lower() in identity:
            return f"refused: the candidate itself is {word!r}"
    return "allowed (the candidate is not a purchase, a spend or an irreversible action)"


def _regions_for(request, ocr):
    regions = ui_collection.grounding_regions(request.frame_path, ocr)
    templates = ui_collection.template_entries_from_candidates(
        ui_collection.UiCandidateStore().all(), page=request.page_label
    )
    if templates:
        regions = regions + ui_collection.template_regions(request.frame_path, templates)
    return regions


def _one(request, ocr, advisor, *, answer_file: str = "") -> bool:
    print("=" * 78)
    print(f"question  : {request.request_id}")
    print(f"screen    : {request.page_key}   (page model read it as {request.page_label})")
    print(f"goal      : {request.goal or '(none)'}   state: {request.situation or '(unstated)'}")
    print(f"frame     : {request.frame_path}")
    print(f"digest    : {request.frame_digest}   asked: {request.created_at}")
    if not Path(request.frame_path).exists():
        print("!! the frame this question is about is gone: it cannot be replayed, only re-asked")
        return False
    regions = _regions_for(request, ocr)
    bases: dict[str, int] = {}
    for region in regions:
        bases[str(region.get("basis"))] = bases.get(str(region.get("basis")), 0) + 1
    print(f"evidence  : {len(regions)} region(s) measured on this frame -- {bases}")

    answers = advisor.root / unknown_advisor.ANSWERS_DIR
    answer_path = answers / f"{request.request_id}.json"
    if answer_file:
        answer_path = Path(answer_file)
    if not answer_path.exists():
        rejected = answers / f"{request.request_id}.rejected.json"
        if rejected.exists():
            reason = (answers / f"{request.request_id}.rejected.reason").read_text(
                encoding="utf-8"
            ) if (answers / f"{request.request_id}.rejected.reason").exists() else ""
            print(f"answer    : REFUSED by the runtime's parser -- {reason}")
            return False
        print("answer    : none yet (the question is waiting; the AUTO is not blocked by it)")
        print("            next: python tools/unknown_ai_worker.py --state")
        return False

    payload = json.loads(answer_path.read_text(encoding="utf-8"))
    print(f"answer    : {answer_path.as_posix()}")
    try:
        advice = unknown_advisor.parse_advice(
            payload, request_id=request.request_id, registry=v2_registry()
        )
    except unknown_advisor.AdviceRejected as exc:
        print(f"            REFUSED by the runtime's parser -- {exc}")
        return False
    print(f"            kind={advice.action_kind}  action={advice.proposed_action!r}  "
          f"target={advice.target_semantics or advice.candidate_semantics}")

    anchored = None
    pool = list(regions)
    if advice.target_anchor:
        anchored = ui_collection.anchored_region(advice.target_anchor, pool)
        if anchored is not None:
            pool = [anchored] + pool
            print(f"            anchor {str(advice.target_anchor.get('text'))!r} is on this frame "
                  f"-> {anchored['box_norm']}")
        else:
            print(f"            anchor {str(advice.target_anchor.get('text'))!r} is NOT on this frame")
    points = []
    if anchored:
        box = anchored["box_norm"]
        points.append((box["x_norm"] + box["w_norm"] / 2, box["y_norm"] + box["h_norm"] / 2))
    region = unknown_advisor.grounded_region(advice, pool, points=points)
    if region is None:
        print("grounding : NONE -- the answer's point is over nothing this frame measured")
        print("            => no tap is issued (this is the rule, not a failure of the run)")
        return False
    point = region["point"]
    print(f"grounding : basis={region.get('basis')}  text={str(region.get('text') or '(none)')!r}")
    print(f"            region={region.get('box_norm')}  point=({point[0]:.4f}, {point[1]:.4f})")
    decision = _risk(advice, region)
    print(f"risk      : {decision}")
    if decision.startswith("refused"):
        return False
    x_px, y_px = round(point[0] * FRAME_WIDTH), round(point[1] * FRAME_HEIGHT)
    print(f"execution : MAA tap at ({x_px}, {y_px}) px on a {FRAME_WIDTH}x{FRAME_HEIGHT} frame")
    print("            expected: " + (advice.expected_result or "(unstated)"))
    print("            (isolated check: nothing was tapped)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="replay the UNKNOWN channel on real questions")
    parser.add_argument("--request", default="", help="one request id (default: all on file)")
    parser.add_argument("--root", default="", help="request directory (default: the project's)")
    parser.add_argument(
        "--answer-file",
        default="",
        help="convert this candidate answer instead of the one on file (writes nothing)",
    )
    args = parser.parse_args()

    advisor = unknown_advisor.UnknownAdvisor(root=args.root or None)
    ocr = _ocr()
    if args.request:
        request = advisor.read_request(args.request)
        if request is None:
            print(f"no such request: {args.request}")
            return 2
        requests = [request]
    else:
        requests = advisor.pending() + [
            advisor.read_request(path.stem)
            for path in sorted(advisor.root.glob("*.json"))
            if (advisor.root / unknown_advisor.ANSWERS_DIR / path.name).exists()
        ]
        requests = [item for item in requests if item is not None]

    print(f"requests  : {advisor.root.as_posix()}  ({len(requests)} on file)")
    if args.answer_file and not args.request:
        print("--answer-file needs --request: an answer is about one question")
        return 2
    complete = 0
    for request in requests:
        if _one(request, ocr, advisor, answer_file=args.answer_file):
            complete += 1
    print("=" * 78)
    print(
        f"{complete} of {len(requests)} question(s) convert all the way to a tap coordinate. "
        "The rest are waiting on an answer, or on a frame that justifies one."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
