# -*- coding: utf-8 -*-
"""Observe the 情报 (Intel / Lighthouse) board on the real client -- read-only, nothing spent.

Why this exists
---------------
``CLEAR_INTEL`` is 已发现 on the console and its blocker names exactly one capability::

    {"goal_id": "CLEAR_INTEL", "capability": "READ_INTEL_LIST", "state": "DEFERRED",
     "reason": "3 consecutive production episodes passed their verifier and advanced no part
                of this goal",
     "source": "NO_GOAL_PROGRESS", "failure_signature": "READ_INTEL_LIST|NO_GOAL_PROGRESS|OPEN_MAP",
     "streak": 3, "last_skill": "OPEN_MAP"}

Two halves of that sentence are already explained from the code, and this tool is what tests
the explanation on the real client:

  * **"passed their verifier"** -- ``verifier.verify_intel_list_read`` only asks whether the
    list was *read* (``after.intel["list_read"] is True``) and whether a status word is one of
    four. It never asks how many were on the board.
  * **"advanced no part of this goal"** -- ``CLEAR_INTEL``'s meter is ``untried_pins``
    (``goal_library.py:2594-2614``). ``runtime.py:8994`` stamps it only on a frame where
    ``page is INTEL and not intel["mission_type"]``. When it is absent the meter is ``None``
    and the goal falls back to its constant ``distance`` of 1.0, so ``1.0 < 1.0`` is False on
    every step.

So the thing to measure is narrow and concrete: **on a real intel board, what number does the
production reading claim, and what does the pin detector count on the same frame?**

What it does, in order (each step is proven before the next is attempted)
-----------------------------------------------------------------------
1. lease the device as the development owner and wait for AUTO to actually yield it;
2. navigate to the board, proving each page with the **production observer**
   (``HybridVision.observe``) rather than with a remembered coordinate: the wild HUD's
   lighthouse entry is ``BTN_OPEN_INTEL_WILD_HUD``, and the fallback is ``BTN_OPEN_HOME``;
3. on the board, dump the frame's own OCR tokens, the production reading, and
   ``intel_pin_centers`` -- the very function ``runtime.py:8994`` calls to stamp
   ``untried_pins``;
4. print the comparison the hypothesis turns on: ``available_count`` as claimed, against the
   number of pins the board actually draws;
5. leave the board and prove it.

It touches nothing else: **no pin is tapped, no mission is dispatched, no reward is claimed,
no stamina is spent.** Dispatching costs stamina irreversibly and claiming is
``CLAIM_INTEL_REWARD``'s job, so both are deliberately out of scope. The only controls this
tool may press are the entry and the way home.

Usage
-----
    python tools/observe_intel_panel.py             # full pass, evidence written
    python tools/observe_intel_panel.py --no-lease  # observe only, take no lease
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = "dataset/candidate/template_manifest.json"

#: The three controls this tool is allowed to press. Named here so the allow-list is auditable
#: at a glance -- anything not on it (a pin, 一键领取, 前往查看) is never tapped.
#:
#: The bottom-right control is ONE button with two readings, which is why the manifest holds it
#: twice: on the map it is 城镇 (``BTN_OPEN_HOME``) and in the city it is 野外 (``PAGE_MAP``,
#: whose own parent screenshot is ``legacy_home.png``). Measured on the live city frame at
#: ``dataset/evidence/intel_panel_observe_20261005T081115/n0_look.png``: ``PAGE_MAP`` matches it
#: at distance 0 with centre (665, 1221), and nothing else in the list matches at all.
ENTRY_SEMANTICS = ("BTN_OPEN_INTEL_WILD_HUD",)   # the lighthouse entry on the wilderness HUD
WILDERNESS_SEMANTICS = ("PAGE_MAP",)             # city, bottom-right 野外 -> the map
HOME_SEMANTICS = ("BTN_OPEN_HOME",)              # map, bottom-right 城镇 -> the city

#: Wording the intel board draws. Used only to *report* what the frame says.
INTEL_WORDS = ("情报", "下次刷新", "体力", "领取", "一键领取", "前往查看", "查看")


def _shot(ad, out: Path, tag: str, log) -> tuple[np.ndarray, Path]:
    frame = None
    for _ in range(3):
        frame = ad.capture()
        if frame is not None:
            break
        time.sleep(0.4)
    if frame is None:
        raise RuntimeError("SCREENCAP_FAILED")
    image = np.asarray(frame)
    path = out / f"{tag}.png"
    from PIL import Image

    Image.fromarray(image).save(path)
    log(f"   frame {tag} -> {path.name}")
    return image, path


def _tokens(path: Path) -> list[dict]:
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    with Image.open(path) as source:
        return list(read_all(source.convert("RGB")))


def _tap_semantic(frame_path: Path, semantics: tuple[str, ...], *, max_distance: int, log
                  ) -> tuple[tuple[int, int], str] | tuple[None, None]:
    """Locate one reviewed UI element on this frame and return its pixel centre.

    Template lookup against the reviewed manifest, so the tap position is a *measurement on
    this frame* rather than a remembered coordinate. Returns ``(None, None)`` when none of the
    named elements is on the frame -- and the caller must then not tap at all.
    """
    from winter_agent_v2.vision import SemanticROIVision

    vision = SemanticROIVision(ROOT / MANIFEST, max_distance=max_distance)
    for semantic in semantics:
        found = vision.find(frame_path, semantic)
        if found is None:
            continue
        centre = getattr(found, "center_norm", None)
        if callable(centre):
            centre = centre()
        if not centre:
            continue
        from PIL import Image

        with Image.open(frame_path) as source:
            width, height = source.size
        return (int(centre[0] * width), int(centre[1] * height)), semantic
    return None, None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-lease", action="store_true", help="observe without leasing")
    parser.add_argument("--max-distance", type=int, default=8)
    parser.add_argument("--attempts", type=int, default=8, help="navigation attempts")
    parser.add_argument("--keep-open", action="store_true", help="leave the board up")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = ROOT / "dataset" / "evidence" / f"intel_panel_observe_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    log_file = (out / "run.log").open("w", encoding="utf-8")

    def log(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))

    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.shop_visit import wait_for_the_device

    lease = None
    lease_id = ""
    if not args.no_lease:
        lease = DeviceLease(ROOT)
        rec, why = lease.acquire(
            owner=OWNER_DEVELOPMENT_VALIDATION,
            capability_id="READ_INTEL_LIST",
            # Short on purpose: a lease that outlives a crash keeps AUTO standing down for its
            # whole TTL. Measured once on the daily tool: a 3000 s TTL plus a release that
            # raised left the device held for the full 50 minutes.
            ttl_seconds=600,
            reason="READ_INTEL_LIST first live observation of the 情报 board",
        )
        if rec is None:
            log(json.dumps({"refused": why}, ensure_ascii=False))
            return 2
        lease_id = str(getattr(rec, "lease_id", "") or "")
        log(f"lease {lease_id or '(no id)'} acquired; expires {getattr(rec, 'expires_at', None)}")

    try:
        # A lease is a request, not a handover: AUTO keeps acting until its next safe point.
        wait_for_the_device(ROOT, log=log)
        ad = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"],
            serial=cfg["device"]["serial"],
            production=True,
            template_dir=ROOT / "dataset/candidate/templates",
            log_dir=ROOT / "learning/maa_logs",
        )
        ok, reason = ad.ensure_ready()
        if not ok:
            log(reason)
            return 3

        # Build the production observer once: it is how every page claim below is made.
        from winter_agent_v2.ocr import (
            HybridVision,
            OCRService,
            RapidOCRBackend,
            ResilientOCRBackend,
        )
        from winter_agent_v2.vision import SemanticWorldVision

        ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
        hybrid = HybridVision(
            SemanticWorldVision(ROOT / MANIFEST, max_distance=args.max_distance), ocr
        )

        # ---- 1. reach the intel board ----------------------------------------------------
        log("[1] reach the 情报 board (proved with the production observer, not a coordinate)")
        board_path: Path | None = None
        last_page = "?"
        for attempt in range(args.attempts):
            _img, path = _shot(ad, out, f"n{attempt}_look", log)
            state = hybrid.observe(path)
            last_page = str(getattr(state.page, "value", state.page))
            # The popup identity travels with the page: "page = POPUP" alone is what made the
            # first run (and the daily tool's second run) look like a navigation failure when
            # the screen was actually the client's own 无网络 modal. A failure has to say what
            # it was looking at.
            log(f"   attempt {attempt}: production page = {last_page} "
                f"popup={getattr(state, 'popup', None)!r} (conf {state.confidence})")
            if last_page == "INTEL":
                board_path = path
                break
            # The board's own entry first -- it lives on the wilderness HUD and, measured on the
            # live city frame, does not match there at all. From the city the bottom-right
            # control is what goes to the wilderness; from the map, 城镇 comes back. Nothing
            # else is ever pressed: a blind tap is exactly what the project forbids, so when
            # none of these is on the frame we press back and look again.
            xy, semantic = _tap_semantic(path, ENTRY_SEMANTICS, max_distance=args.max_distance, log=log)
            if xy is None and last_page == "HOME":
                xy, semantic = _tap_semantic(path, WILDERNESS_SEMANTICS,
                                             max_distance=args.max_distance, log=log)
            if xy is None and last_page == "MAP":
                xy, semantic = _tap_semantic(path, HOME_SEMANTICS,
                                             max_distance=args.max_distance, log=log)
            if xy is None:
                log(f"   none of {ENTRY_SEMANTICS + WILDERNESS_SEMANTICS + HOME_SEMANTICS}"
                    f" is on this frame -- one back")
                ad.press_back()
                time.sleep(1.2)
                continue
            log(f"   {semantic} centre -> {xy}")
            log(f"   click -> {ad.click(int(xy[0]), int(xy[1]))}")
            time.sleep(1.6)

        if board_path is None:
            log(f"!! could not reach the 情报 board; last page seen was {last_page}."
                " Stopping without tapping anything on the board.")
            log(f"   last frame: {out / f'n{args.attempts - 1}_look.png'}")
            return 4

        # ---- 2. what the board draws -----------------------------------------------------
        log("\n[2] the board's own wording (text @ pixel centre, normalised)")
        from PIL import Image

        with Image.open(board_path) as source:
            width, height = source.size
        board_toks = _tokens(board_path)
        log(f"   frame size {width}x{height}, {len(board_toks)} tokens")
        for t in sorted(board_toks, key=lambda t: (t["centre"][1], t["centre"][0])):
            text = str(t["text"]).strip()
            if not text:
                continue
            x, y = t["centre"]
            log(f"     ({x:>4},{y:>4})  ({x / width:.4f},{y / height:.4f})  {text!r}")
        seen = [w for w in INTEL_WORDS if any(w in str(t["text"]) for t in board_toks)]
        log(f"   intel wording present: {seen}")

        # ---- 3. the production reading for this same frame -------------------------------
        log("\n[3] production reading (HybridVision.observe -- the entry point the runtime uses)")
        state = hybrid.observe(board_path)
        intel = dict(state.intel or {})
        log(f"   page       : {getattr(state.page, 'value', state.page)}")
        log(f"   confidence : {state.confidence}")
        log(f"   intel keys : {sorted(intel.keys())}")
        for key in ("status", "list_read", "pins", "detected_pins", "untried_pins",
                    "available_count", "claimable_count", "mission_type", "mission_level",
                    "stamina", "refresh"):
            if key in intel:
                log(f"     {key:18s} = {intel[key]!r}")

        # ---- 4. the number the board actually draws --------------------------------------
        log("\n[4] the pin detector -- what runtime.py:8994 calls to stamp untried_pins")
        from winter_agent_v2.intel_pins import intel_pin_centers

        pins = intel_pin_centers(board_path)
        log(f"   intel_pin_centers -> {len(pins)} pin(s)")
        for p in pins:
            log(f"     ({p.x:>4},{p.y:>4})")

        # ---- 5. the comparison the hypothesis turns on -----------------------------------
        claimed = intel.get("available_count")
        detected = len(pins)
        log("\n[5] reading vs board")
        log(f"   reading claims available_count = {claimed!r}")
        log(f"   the board draws                  {detected} pin(s)")
        if not isinstance(claimed, int):
            verdict = "READING_CARRIES_NO_COUNT"
        elif claimed == detected:
            verdict = "AGREE"
        elif claimed < detected:
            verdict = "UNDERSTATED"
        else:
            verdict = "OVERSTATED"
        log(f"   verdict: {verdict}")
        # The meter the goal needs. Present == CLEAR_INTEL can report progress; absent == it
        # cannot, no matter how correct the reading looks to the verifier.
        log(f"   meter for CLEAR_INTEL (untried_pins) present in this reading: "
            f"{'untried_pins' in intel}")
        log(f"   note: runtime stamps it only when page is INTEL AND no mission_type is set;"
            f" this frame has mission_type={intel.get('mission_type')!r}")

        (out / "production_reading.json").write_text(
            json.dumps({
                "page": getattr(state.page, "value", state.page),
                "confidence": state.confidence,
                "intel": intel,
                "pins_detected": [{"x": p.x, "y": p.y} for p in pins],
                "pins_detected_count": detected,
                "available_count_claimed": claimed,
                "verdict": verdict,
                "untried_pins_present": "untried_pins" in intel,
                "source_frame": board_path.name,
            }, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )

        # ---- 6. leave the board ----------------------------------------------------------
        if not args.keep_open:
            log("\n[6] leave the board")
            for attempt in range(4):
                ad.press_back()
                time.sleep(1.2)
                _img, path = _shot(ad, out, f"b{attempt}_back", log)
                page = str(getattr(hybrid.observe(path).page, "value", "?"))
                log(f"   attempt {attempt}: page now {page}")
                if page in {"MAP", "HOME"}:
                    break
        else:
            log("\n[6] --keep-open: board left up")

        log(f"\nEVIDENCE: {out}")
        return 0
    finally:
        if lease is not None:
            # ``release`` takes ``result`` as a REQUIRED keyword-only argument. The daily tool's
            # first version omitted it, the TypeError was swallowed by a bare ``except``, and the
            # device stayed leased for AUTO's whole stand-down window while the run looked clean.
            try:
                released = lease.release(
                    result="OBSERVED",
                    reason="READ_INTEL_LIST read-only observation finished",
                    expect_lease_id=lease_id,
                )
                log(f"lease release -> {released}")
            except Exception as exc:  # noqa: BLE001 - a failed release must not mask the result
                log(f"!! lease release FAILED: {type(exc).__name__}: {exc!r}"
                    " -- the device stays leased until it expires; release it by hand")
        log_file.close()


if __name__ == "__main__":
    sys.exit(main())
