"""Answer the questions the AUTO could not work out for itself.

    python tools/unknown_advisor.py --list
    python tools/unknown_advisor.py --show <request_id>
    python tools/unknown_advisor.py --answer <request_id> --json '{"unknown_type": "CONTROL", ...}'
    python tools/unknown_advisor.py --answer <request_id> --answer-file answer.json

Why a tool and not a client
---------------------------
The runtime side (``winter_agent_v2/unknown_advisor.py``) writes a question to
``learning/unknown_requests/`` and reads an answer if one is there; it has no client and cannot
wait, and that is deliberate -- the project's standing rule is that a model is an optional
provider, never a runtime dependency (operator section 7, pinned by
``tests/test_qwen_decoupling.py``).

This tool is the other half, and it is where a reasoner is allowed to live: a WorkBuddy session, an
operator reading the questions, or a local model driven by a script.  Whatever answers, it answers
by *calling this*, so an answer is always validated by the same ``parse_advice`` the runtime uses --
a malformed answer, an invented skill, a point outside the frame or a mention of money is refused
here rather than at 3am in the field.

What an answer may say (directive §三, all of it required)
----------------------------------------------------------
    unknown_type          PAGE | CONTROL | RESULT
    candidate_semantics   ["候选页面或控件语义", ...]
    proposed_action       a skill id this registry already has (usually TRY_ORDINARY_CONTROL)
    expected_result       what should be observable afterwards
    uncertainty           how sure the reasoner is, in its own words -- kept verbatim

Optional: ``target_point`` (``[x, y]`` or ``{"x_norm","y_norm"}``), ``target_bbox``,
``alternative_actions``, ``note``.

The runtime will use ``target_point`` only if this frame's own OCR read text there, so a point
picked off the picture is fine and a made-up one is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import unknown_advisor  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

EXAMPLE = {
    "unknown_type": "CONTROL",
    "candidate_semantics": ["REWARD_PANEL", "领取按钮"],
    "proposed_action": "TRY_ORDINARY_CONTROL",
    "expected_result": "the reward is claimed and the panel closes",
    "uncertainty": "high: the panel is clearly a reward panel, the button is the largest control",
    "target_point": [0.50, 0.72],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="answer the AUTO's UNKNOWN questions")
    parser.add_argument("--list", action="store_true", help="questions with no answer yet")
    parser.add_argument("--show", metavar="REQUEST_ID", help="the full question, as JSON")
    parser.add_argument("--answer", metavar="REQUEST_ID", help="write an answer for this question")
    parser.add_argument("--json", default="", help="the answer, as a JSON object")
    parser.add_argument("--answer-file", default="", help="the answer, from a file")
    parser.add_argument("--root", default="", help="request directory (default: the project's)")
    parser.add_argument("--example", action="store_true", help="print an answer template and exit")
    args = parser.parse_args()

    if args.example:
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=1))
        return 0

    advisor = unknown_advisor.UnknownAdvisor(root=args.root or None)

    if args.list:
        pending = advisor.pending()
        print(f"requests : {advisor.root.as_posix()}")
        print(f"pending  : {len(pending)}")
        for request in pending:
            print()
            print(f"  id       : {request.request_id}")
            print(f"  screen   : {request.page_key}  (page model read it as {request.page_label})")
            print(f"  question : {request.question}")
            print(f"  goal     : {request.goal}")
            print(f"  frame    : {request.frame_path}")
            print(f"  asked    : {request.created_at}")
            print(f"  next     : python tools/unknown_advisor.py --show {request.request_id}")
        if not pending:
            print("nothing to answer -- every question the AUTO asked has an answer, or none has been asked")
        return 0

    if args.show:
        request = advisor.read_request(args.show)
        if request is None:
            print(f"no such request: {args.show}")
            return 2
        print(json.dumps(request.as_row(), ensure_ascii=False, indent=1))
        return 0

    if args.answer:
        if bool(args.json) == bool(args.answer_file):
            print("give exactly one of --json / --answer-file (see --example)")
            return 2
        raw = args.json or Path(args.answer_file).read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"the answer is not JSON: {exc}")
            return 2
        if advisor.read_request(args.answer) is None:
            print(f"no such request: {args.answer}")
            return 2
        # Validated here with the real registry, so what lands on disk is an answer the runtime can
        # actually use: an unknown skill id, a point outside the frame or a mention of money is
        # refused now, with a reason, instead of silently failing a live step later.
        try:
            advice = unknown_advisor.parse_advice(
                payload, request_id=args.answer, registry=v2_registry()
            )
        except unknown_advisor.AdviceRejected as exc:
            print(f"refused: {exc}")
            return 2
        answers = advisor.root / unknown_advisor.ANSWERS_DIR
        answers.mkdir(parents=True, exist_ok=True)
        (answers / f"{args.answer}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"answered : {args.answer}")
        print(f"file     : {(answers / f'{args.answer}.json').as_posix()}")
        print(f"used     : {advice.proposed_action} -> {advice.expected_result}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
