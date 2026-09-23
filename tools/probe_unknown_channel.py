"""Where the AI-help channel actually stands, read-only and from the record.

Answers the operator's question "along the existing chain, where is the first real break?" with
the artefacts rather than with an opinion.  Three groups of facts, each from its own file:

* **the questions** -- one row per request: screen, goal at ask time, when, and whether the screen
  has ever been seen again since (the page record's ``last_seen_at`` vs the request's ``created_at``).
  A request whose screen was never revisited cannot be adopted by any amount of later answering.
* **the answers** -- one row per answered request, with the answer's own grounding basis, and how
  long after the question the answer landed.
* **the channel** -- every dispatch-ledger event, so "the channel is automatic" is checkable, and
  the count of episodes that ever carried ``ai_advice`` (the consumption site's own evidence).

No device, no writes, no network.

Usage:
    python tools/probe_unknown_channel.py
    python tools/probe_unknown_channel.py --out dataset/truth_audit/<dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUESTS = ROOT / "learning/unknown_requests"
ANSWERS = REQUESTS / "answers"
DISPATCH = ROOT / "learning/unknown_dispatch.jsonl"
PAGES = ROOT / "knowledge/perception/pages/INDEX.json"
EPISODES = ROOT / "learning/episodes.jsonl"


def _moment(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _minutes(a: str, b: str) -> float | None:
    first, second = _moment(a), _moment(b)
    if first is None or second is None:
        return None
    return round((second - first).total_seconds() / 60.0, 1)


def _stamp(value: str) -> str:
    return str(value or "")[5:19]


def _pages() -> dict[str, dict]:
    try:
        payload = json.loads(PAGES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(row.get("page_key") or ""): row for row in (payload.get("pages") or [])}


def _requests() -> list[dict]:
    out: list[dict] = []
    for path in sorted(REQUESTS.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            out.append(payload)
    out.sort(key=lambda row: str(row.get("created_at") or ""))
    return out


def _answer(request_id: str) -> dict | None:
    path = ANSWERS / f"{request_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _dispatch_rows() -> list[dict]:
    try:
        lines = DISPATCH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _consumption() -> dict:
    """How many episodes carry an advice, and what the ones that do look like.

    ``ai_advice`` is the field the resolver fills when an answer was actually reached on a live
    frame -- so a corpus-wide zero is the proof that the consumption site has never run with an
    answer present, and is not an inference from the absence of a tap.
    """
    total = 0
    with_advice = 0
    unknown_page = 0
    latest = ""
    try:
        handle = EPISODES.open(encoding="utf-8")
    except OSError:
        return {"episodes": 0, "with_advice": 0, "unknown_page_steps": 0, "latest": ""}
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            total += 1
            if '"ai_advice"' in line and '"ai_advice": []' not in line and '"ai_advice": {}' not in line:
                with_advice += 1
            if '"page": "UNKNOWN"' in line:
                unknown_page += 1
            latest = line[:400]
    return {
        "episodes": total,
        "with_advice": with_advice,
        "unknown_page_steps": unknown_page,
        "latest": latest,
    }


def _unknown_page_frames(after: str) -> list[tuple[str, str]]:
    """``(recorded_at, frame)`` for every step that stood on an UNKNOWN page after ``after``.

    The corpus is the only place that can answer "did the answered screen come back", because the
    page record's ``last_seen_at`` is written on ``stage`` and on ``record_attempt`` -- a revisit
    that resolved nothing updates neither, so an unchanged ``last_seen_at`` is **not** evidence of
    absence.  Reading the frames' own titles is.
    """
    out: list[tuple[str, str]] = []
    try:
        handle = EPISODES.open(encoding="utf-8")
    except OSError:
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line or '"page": "UNKNOWN"' not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = str(row.get("recorded_at") or "")
            if stamp <= after:
                continue
            frame = str(row.get("before_screenshot") or "")
            if frame:
                out.append((stamp, frame))
    out.sort()
    return out


def _revisits(requests: list[dict]) -> None:
    """For each answered question, what the UNKNOWN frames after it actually read as a title."""
    answered = [row for row in requests if _answer(str(row.get("request_id") or ""))]
    if not answered:
        print("no answered request -- nothing to look for")
        return
    for row in answered:
        path = ANSWERS / f"{row['request_id']}.json"
        landed = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        wanted = str(row.get("page_key") or "").split("::", 1)[-1]
        frames = _unknown_page_frames(landed)
        print(f"--- {row['request_id']}: answer landed {_stamp(landed)}; "
              f"{len(frames)} UNKNOWN-page steps after it")
        if not frames:
            print("    (the run never stood on an UNKNOWN page again)")
            continue
        from winter_agent_v2 import page_knowledge
        from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend, read_frame_size

        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
        matches = 0
        for stamp, frame in frames:
            frame_path = Path(frame)
            if not frame_path.is_file():
                print(f"    {_stamp(stamp)}  (frame gone)")
                continue
            title = ""
            try:
                size = read_frame_size(frame_path)
                info = page_knowledge.read_title_candidate(frame_path, ocr, size) if size else None
                title = str((info or {}).get("text") or "")
            except (OSError, ValueError):
                pass
            hit = "  <== the asked screen" if title and title == wanted else ""
            if hit:
                matches += 1
            print(f"    {_stamp(stamp)}  reads title {title!r}{hit}")
        print(f"    => the screen the question was about came back {matches} time(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--revisits", action="store_true",
                        help="also OCR every UNKNOWN-page frame recorded after each answer")
    args = parser.parse_args()

    pages = _pages()
    requests = _requests()
    rows = _dispatch_rows()
    consumed = _consumption()

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requests": [],
        "dispatch": {"events": len(rows), "by_event": {}},
        "consumption": {k: v for k, v in consumed.items() if k != "latest"},
    }
    by_event: dict[str, int] = {}
    for row in rows:
        key = str(row.get("event") or "")
        by_event[key] = by_event.get(key, 0) + 1
    report["dispatch"]["by_event"] = by_event

    print("=== the questions, and whether their screen ever came back ===")
    print(f"{'request':<34} {'screen':<24} {'goal':<10} {'asked':<16} {'seen again':<26}")
    for request in requests:
        key = str(request.get("page_key") or "")
        page = pages.get(key) or {}
        answer = _answer(str(request.get("request_id") or ""))
        seen = _stamp(str(page.get("last_seen_at") or ""))
        asked = _moment(str(request.get("created_at")))
        revisited = ""
        if page:
            revisited = seen + (
                "  (never)" if str(page.get("last_seen_at")) == str(page.get("created_at")) else ""
            )
        row = {
            "request_id": str(request.get("request_id") or ""),
            "page_key": key,
            "goal": str(request.get("goal") or ""),
            "asked_at": str(request.get("created_at") or ""),
            "frame": str(request.get("frame_path") or ""),
            "answered": answer is not None,
            "screen_created_at": str(page.get("created_at") or ""),
            "screen_last_seen_at": str(page.get("last_seen_at") or ""),
            "screen_ever_revisited": bool(
                page and str(page.get("last_seen_at")) != str(page.get("created_at"))
            ),
            "screen_attempts": page.get("attempt_count"),
        }
        if answer is not None:
            row["answer"] = {
                "proposed_action": answer.get("proposed_action"),
                "grounding_basis": answer.get("grounding_basis"),
                "action_level": answer.get("action_level"),
                "target_anchor": answer.get("target_anchor"),
            }
            path = ANSWERS / f"{row['request_id']}.json"
            landed = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            row["answer_landed_at"] = landed
            row["answer_minutes_after_question"] = _minutes(row["asked_at"], landed)
        report["requests"].append(row)
        print(
            f"{row['request_id'][:33]:<34} {key[:23]:<24} {row['goal'][:9]:<10} "
            f"{_stamp(row['asked_at']):<16} {revisited:<26}"
        )

    print()
    print("=== the answers that exist ===")
    answered = [row for row in report["requests"] if row.get("answer")]
    if not answered:
        print("  (none)")
    for row in answered:
        print(f"  {row['request_id']}")
        print(f"     action  : {row['answer']['proposed_action']}")
        print(f"     basis   : {row['answer']['grounding_basis']}")
        print(f"     anchor  : {json.dumps(row['answer']['target_anchor'], ensure_ascii=False)}")
        print(f"     landed  : {_stamp(row.get('answer_landed_at'))} "
              f"({row.get('answer_minutes_after_question')} min after the question)")
        print(f"     screen revisited since: {row['screen_ever_revisited']}")

    print()
    print("=== the channel's own ledger ===")
    for key, count in sorted(by_event.items(), key=lambda item: -item[1]):
        print(f"  {count:>4}  {key}")
    print()
    print("=== has the consumption site ever run with an answer? ===")
    print(f"  episodes                       : {consumed['episodes']}")
    print(f"  episodes whose step carries an AI advice : {consumed['with_advice']}")
    print(f"  steps that stood on an UNKNOWN screen    : {consumed['unknown_page_steps']}")
    if consumed["latest"]:
        print(f"  latest episode line (first 200 chars)    : {consumed['latest'][:200]}")

    if args.revisits:
        print()
        print("=== did the screen behind each answer ever come back? ===")
        _revisits(requests)

    if args.out:
        answers_dir = args.out
        answers_dir.mkdir(parents=True, exist_ok=True)
        (answers_dir / "channel.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print()
        print("wrote", answers_dir / "channel.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
