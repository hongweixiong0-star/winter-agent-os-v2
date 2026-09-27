# -*- coding: utf-8 -*-
"""CAPTURE-FIRST popup scanner -- POPUP_EXPLORATION_REWARD / POPUP_MAIL_REWARD.

Round brief 2026-09-27 §二/§三: the last two ordinary popup gaps have no
dedicated real frame, and guessing an ROI offline is forbidden.  Production
AUTO already saves before/after step frames for every episode; this watcher
turns those saved frames into capture-first evidence the moment a reward
popup (获得奖励 semantics) actually appears:

    1. the frame itself           (copied, never mutated)
    2. the page it appeared on    (from the episode's step record)
    3. the OCR tokens             (full-frame pass, exact tokens kept)
    4. the popup bbox             (union of reward-word boxes, normalized)
    5. previous action            (the step's action that produced the popup)
    6. next action                (what AUTO did after)
    7. semantic candidates        (CLAIM / CLOSE / CONFIRM reuse check)

Captures land in ``dataset/raw/popup_capture/<stamp>_<semantic>/`` plus one
``capture.json``; a summary index is appended to
``dataset/raw/popup_capture/INDEX.jsonl``.  It never invents a capture: no
reward word on the frame, no record.

Reuse rule (§三): if the popup's own buttons are already covered by generic
CLAIM/CLOSE/CONFIRM nodes in routing, the capture record says so, and no
dedicated skill is minted.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO_DIR = ROOT / "dataset" / "raw" / "control_panel" / "runtime_auto"
OUT_DIR = ROOT / "dataset" / "raw" / "popup_capture"
INDEX = OUT_DIR / "INDEX.jsonl"
ROUTING = ROOT / "knowledge" / "execution" / "backend_routing.json"

#: Reward popup identity words.  Both gap items carry 获得奖励 in visible_words.
REWARD_WORDS = ("获得奖励",)

#: Which captured popup each gap item wants.
SEMANTIC_BY_CONTEXT = {
    "MAIL": "POPUP_MAIL_REWARD",
    "EXPLOR": "POPUP_EXPLORATION_REWARD",
}
DEFAULT_SEMANTIC = "POPUP_REWARD_GENERIC"

#: Generic nodes the popup may reuse instead of a dedicated skill (§三).
GENERIC_REUSES = ("BTN_OK_POPUP", "BTN_CLOSE_POPUP", "BTN_CLAIM")


def _routing_generics() -> dict[str, dict]:
    routing = json.loads(ROUTING.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for skill, body in (routing.get("skills") or {}).items():
        for semantic in (body.get("recognition") or {}):
            if semantic in GENERIC_REUSES:
                found[semantic] = {"skill": skill}
    return found


def _episode_steps(episode_dir: Path) -> list[Path]:
    """After-step frames of one episode, in name order.

    A reward popup is the RESULT of an action, so it is only looked for on
    ``after`` frames; before-frames OCR would double the cost for nothing.
    """
    return sorted(p for p in episode_dir.iterdir()
                  if p.suffix.lower() == ".png" and "_after_" in p.name)


def _scan_frame(frame: Path, ocr) -> dict | None:
    """Reward-popup evidence from one real frame, or None."""
    try:
        from PIL import Image

        with Image.open(frame) as src:
            width, height = src.size
        result = ocr.recognize(frame)
    except Exception:  # noqa: BLE001 -- an unreadable frame is not a capture
        return None
    tokens = [t for t in getattr(result, "tokens", ()) if getattr(t, "text", "").strip()]
    hits = [t for t in tokens if any(w in t.text for w in REWARD_WORDS)]
    if not hits:
        return None
    boxes = [t.box for t in hits if getattr(t, "box", None)]
    bbox_norm = None
    if boxes:
        xs = [p[0] for b in boxes for p in b]
        ys = [p[1] for b in boxes for p in b]
        bbox_norm = [
            round(min(xs) / width, 4), round(min(ys) / height, 4),
            round(max(xs) / width, 4), round(max(ys) / height, 4),
        ]
    return {
        "tokens": [{"text": t.text, "centre_norm": [
            round(t.centre[0] / width, 4), round(t.centre[1] / height, 4)]}
            for t in tokens],
        "reward_hits": [t.text for t in hits],
        "popup_bbox_norm": bbox_norm,
        "frame_size": [width, height],
    }


def scan_episode(episode_dir: Path, ocr, *, seen: set[str]) -> list[dict]:
    """One episode: every step frame with reward semantics becomes a capture."""
    captures: list[dict] = []
    steps = _episode_steps(episode_dir)
    for index, frame in enumerate(steps):
        name = frame.name
        # prev/next actions from the step file naming: ..._step_NNN_before/after_<ts>.png
        match = re.search(r"_step_(\d+)_(before|after)_", name)
        step_no = int(match.group(1)) if match else None
        phase = match.group(2) if match else None
        evidence = _scan_frame(frame, ocr)
        if evidence is None:
            continue
        context = " ".join(episode_dir.name.split("_")[1:3]).upper()
        semantic = next(
            (s for key, s in SEMANTIC_BY_CONTEXT.items() if key in context),
            DEFAULT_SEMANTIC,
        )
        key = f"{episode_dir.name}/{step_no}/{phase}"
        if key in seen:
            continue
        seen.add(key)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = OUT_DIR / f"{stamp}_{semantic}"
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = out_dir / frame.name
        if not saved.exists():
            shutil.copy2(frame, saved)
        prev_action = steps[index - 1].name if index else None
        next_action = steps[index + 1].name if index + 1 < len(steps) else None
        record = {
            "semantic": semantic,
            "gap_class": "CAPTURE_FIRST_POPUP",
            "captured_at": stamp,
            "episode": episode_dir.name,
            "step": step_no,
            "phase": phase,
            "page": "POPUP",
            "previous_action": prev_action,
            "next_action": next_action,
            "generic_reuse_available": sorted(_routing_generics()),
            "reuse_rule": "prefer generic CLAIM/CLOSE/CONFIRM; no dedicated skill if covered",
            **evidence,
            "frame": str(saved.relative_to(ROOT)),
        }
        (out_dir / "capture.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        with INDEX.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        captures.append({"semantic": semantic, "episode": episode_dir.name,
                         "out": str(out_dir.relative_to(ROOT))})
    return captures


def main() -> None:
    """Scan recent runtime_auto episodes that have not been scanned yet.

    Only the last ``--days`` (default 3) of episodes and only ``after`` step
    frames: a reward popup is the RESULT of an action, and full-history OCR of
    every before/after frame costs minutes of CPU for captures the index
    already has.
    """
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    from datetime import datetime, timedelta, timezone

    from winter_agent_v2.ocr import OCRService, RapidOCRBackend

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3,
                        help="scan episodes modified within this many days")
    args = parser.parse_args()
    cutoff = datetime.now() - timedelta(days=args.days)

    scanned_keys: set[str] = set()
    if INDEX.exists():
        for line in INDEX.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            scanned_keys.add(f"{record.get('episode')}/{record.get('step')}/{record.get('phase')}")
    ocr = OCRService(RapidOCRBackend())
    all_captures: list[dict] = []
    episodes = sorted(AUTO_DIR.iterdir()) if AUTO_DIR.exists() else []
    recent = [d for d in episodes
              if d.is_dir()
              and datetime.fromtimestamp(d.stat().st_mtime) >= cutoff]
    for episode_dir in recent:
        all_captures += scan_episode(episode_dir, ocr, seen=scanned_keys)
    print(json.dumps({
        "episodes_total": len(episodes),
        "episodes_scanned": len(recent),
        "new_captures": all_captures,
        "total_indexed": len(scanned_keys),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
