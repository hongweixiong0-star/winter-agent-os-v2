"""Drive the intel pin map: tap every mission pin and let the real loop work it.

Live finding 2026-09-14 17:24 (operator correction): the intel page is a map
of mission pins - dozens of them - not the single mission card the vision
layer was built around.  The card only appears AFTER tapping a pin, which is
why every earlier probe reported available_count=0 while the operator could
see a full board.

Flow per pin:
1. detect pins on the live intel page (colour blobs, white-icon verified)
2. tap the next pin - ORANGE (completed/claimable) first, then top to bottom
3. whatever opens, hand control to tools/run_live.py --goal INTEL: the real
   loop observes the card and runs the already-verified chain (select ->
   view target -> start march -> dispatch, or claim, or close)
4. re-detect the remaining pins and repeat

The harness never taps paid controls and stops honestly: no pins left, no
detectable response to a tap (counted as skipped), stamina below one beast
march, or the pin budget exhausted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_LIVE = ROOT / "tools" / "run_live.py"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

PIN_BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 30
RUN_LIVE_TIMEOUT = 420
STAMINA_FLOOR = 10

# A pin counts as worked when a *verified* step of one of these ran.  It used
# to be beast dispatch + reward claim only, so a Hero Journey fight or a Rescue
# Survivors start that really happened still made `productive` False, which
# blacklisted a good pin and, worse, hid the success from the summary.  The
# verified-step list is the authority, not the mission type.
PRODUCTIVE_SKILLS = (
    "DISPATCH_INTEL_BEAST",
    "INTEL_CLAIM_REWARDS",
    "EXECUTE_INTEL_RESCUE_SURVIVORS",
    "INTEL_HERO_DISPATCH",
)


def observe() -> tuple[dict, Path]:
    """One observation of the live client through the production stack."""
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    hybrid = HybridVision(
        template,
        OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
    )
    shot = ROOT / "dataset/raw/control_panel/probe" / f"pins_{STAMP}.png"
    device.screenshot(shot)
    state = hybrid.observe(shot)
    return {
        "page": state.page.value,
        "popup": state.popup,
        "intel": state.intel,
        "stamina": (state.stamina or {}).get("current"),
    }, shot


def run_live_cycle(tag: str) -> dict:
    capture = f"dataset/raw/control_panel/runtime_auto/intel_pins_{STAMP}_{tag}"
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-u", str(RUN_LIVE), "--goal", "INTEL", "--max-actions", "14",
         "--no-stamina-check",
         "--serial", "127.0.0.1:7555", "--capture-dir", capture],
        capture_output=True, text=True, errors="replace", cwd=str(ROOT), timeout=RUN_LIVE_TIMEOUT,
    )
    payload = {}
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
    steps = payload.get("steps") or []
    dispatches = sum(
        1 for s in steps
        if str((s.get("decision") or {}).get("skill")) == "DISPATCH_INTEL_BEAST"
        and (s.get("verification") or {}).get("ok") is True
    )
    claims = sum(
        1 for s in steps
        if str((s.get("decision") or {}).get("skill")) == "INTEL_CLAIM_REWARDS"
        and (s.get("verification") or {}).get("ok") is True
    )
    productive_steps = [
        str((s.get("decision") or {}).get("skill"))
        for s in steps
        if str((s.get("decision") or {}).get("skill")) in PRODUCTIVE_SKILLS
        and (s.get("verification") or {}).get("ok") is True
    ]
    stamina = None
    for s in steps:
        for key in ("after", "before"):
            value = ((s.get(key) or {}).get("stamina") or {}).get("current")
            if isinstance(value, int):
                stamina = value
    return {
        "exit_code": proc.returncode,
        "stop_reason": payload.get("stop_reason"),
        "steps": len(steps),
        "dispatches": dispatches,
        "claims": claims,
        "productive_steps": productive_steps,
        "stamina_after": stamina,
        "elapsed_s": round(time.monotonic() - started, 1),
        "capture_dir": capture,
    }


def intel_stamina(shot: Path) -> int | None:
    """Stamina from the intel page's top-right barrel (conf 1.0 live).

    The map HUD gauge misreads under overlays (live: 295 read as 28 and 275
    as 2), which once stopped this loop on a false stamina floor.  On the
    intel page the value sits alone in the header and OCR reads it exactly.
    """
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    result = ocr.recognize(shot, {"x_norm": 0.78, "y_norm": 0.015, "w_norm": 0.16, "h_norm": 0.04})
    for token in result.tokens:
        text = token.text.strip()
        if token.confidence >= 0.9 and text.isdigit():
            return int(text)
    return None


def hero_teams_full_refusal(device, ocr, squad_shot: Path) -> str | None:
    """Tap 战斗 once and read the transient toast.

    Live 2026-09-14 (CORRECTED): the original refusal this probe was built for
    (「出战队伍已满。」) came from tapping a hero PORTRAIT slot, because the
    BTN_HERO_FIGHT template had been cropped 103 px too high; tapping a slot in
    a full squad is refused with that toast.  The real fix was re-measuring the
    button (see the manifest provenance), and the fight then worked at once
    (victory + rewards).  This probe stays as a generic refusal catcher for any
    future silent rejection; its finding must never be read as a claim about
    the account's battle-team capacity.
    """
    import json as _json
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend, HybridVision
    from winter_agent_v2.vision import SemanticWorldVision

    config = _json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    hybrid = HybridVision(template, OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))))
    state = hybrid.observe(squad_shot)
    if state.page.value != "MARCH":
        return None
    match = template.semantic.find(squad_shot, "BTN_HERO_FIGHT")
    if match is None or match.center_norm is None:
        return None
    width, height = device.status().resolution
    device.tap(round(match.center_norm[0] * width), round(match.center_norm[1] * height))
    time.sleep(0.4)
    toast = ROOT / "dataset/raw/control_panel/probe" / "fight_refusal_toast.png"
    device.screenshot(toast)
    result = ocr.recognize(toast)
    for token in result.tokens:
        text = token.text.strip()
        if "出战队伍已满" in text or "队伍已满" in text:
            return text
    return None


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.intel_pins import intel_pin_centers
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    intel_ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    width, height = device.status().resolution

    results: list[dict] = []
    processed = 0
    skipped = 0
    nav_cycles = 0
    MAX_NAV_CYCLES = 3
    # Pins stay on the board after their mission is consumed (claimed / marching),
    # so a tap that produces nothing blacklists that spot for this session; the
    # hourly automation re-runs from a cold start and will retry it later.
    dead_spots: list[tuple[str, int, int]] = []

    def is_dead(pin) -> bool:
        return any(
            color == pin.color and (x - pin.x) ** 2 + (y - pin.y) ** 2 <= 40 ** 2
            for color, x, y in dead_spots
        )

    print(f"intel pin loop start {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
          f"pin_budget={PIN_BUDGET}", flush=True)
    try:
        while processed + skipped < PIN_BUDGET:
            state, shot = observe()
            stamina = intel_stamina(shot) if state["page"] == "INTEL" else state.get("stamina")
            pins = [p for p in intel_pin_centers(shot) if not is_dead(p)]
            if state["page"] != "INTEL":
                # navigate: back out, then open intel through the real loop.
                # Uncapped this once spun forever: a page the loop could not
                # resolve kept failing the nav run and the budget never moved.
                nav_cycles += 1
                if nav_cycles > MAX_NAV_CYCLES:
                    print(f"STOP: {MAX_NAV_CYCLES} navigation cycles failed to reach the intel page", flush=True)
                    break
                run = run_live_cycle(f"nav_{processed+skipped:02d}")
                results.append({"pin": None, "note": "navigation cycle", **run})
                continue
            if not pins:
                print("no actionable pins left on the intel board", flush=True)
                break
            # ORANGE (claimable) first - the operator's expiry concern
            pins.sort(key=lambda p: (0 if p.color == "ORANGE" else 1, p.y, p.x))
            pin = pins[0]
            tap_x, tap_y = round(pin.x / width, 4), round(pin.y / height, 4)
            print(f"pin {processed+skipped}: {pin.color} at ({pin.x},{pin.y}) -> tap", flush=True)
            device.tap(pin.x, pin.y)
            time.sleep(2.5)
            after, _ = observe()
            opened_card = after["popup"] is not None or after["page"] in ("POPUP", "BEAST")
            if not opened_card:
                skipped += 1
                dead_spots.append((pin.color, pin.x, pin.y))
                results.append({"pin": pin.color, "tap": [tap_x, tap_y], "note": "no card opened, blacklisted"})
                print("  no card opened -> blacklist spot", flush=True)
                time.sleep(1.5)
                continue
            run = run_live_cycle(f"pin_{processed+skipped:02d}")
            nav_cycles = 0
            # Any verified productive step counts, not just a beast dispatch:
            # a Hero Journey fight or a Rescue Survivors start is real work.
            productive = bool(run.get("productive_steps"))
            refusal = None
            if not productive:
                dead_spots.append((pin.color, pin.x, pin.y))
                # The hero-journey fight refuses silently except for a ~1 s
                # toast; probe for it so a capacity block is not recorded as
                # an unexplained failure.
                after_state, after_shot = observe()
                if after_state["page"] == "MARCH":
                    refusal = hero_teams_full_refusal(device, intel_ocr, after_shot)
                    if refusal:
                        print(f"  REFUSED: {refusal}", flush=True)
            entry = {"pin": pin.color, "tap": [tap_x, tap_y], "card_opened": opened_card,
                     "productive": productive, "refusal": refusal, **run}
            results.append(entry)
            print("  " + json.dumps(entry, ensure_ascii=False), flush=True)
            if refusal:
                print(f"STOP: hero battle teams are full ({refusal}); the account's concurrent "
                      "hero deployments are occupied by outstanding marches", flush=True)
                break
            processed += 1
            if isinstance(run.get("stamina_after"), int):
                stamina = run["stamina_after"]
            if isinstance(stamina, int) and stamina < STAMINA_FLOOR:
                print(f"STOP: stamina {stamina} below {STAMINA_FLOOR}", flush=True)
                break
            time.sleep(2.0)
    except subprocess.TimeoutExpired:
        print("STOP: a cycle exceeded the timeout", flush=True)
    except KeyboardInterrupt:
        print("STOP: interrupted", flush=True)

    total_dispatch = sum(r.get("dispatches", 0) for r in results)
    total_claims = sum(r.get("claims", 0) for r in results)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pins_processed": processed,
        "pins_skipped": skipped,
        "dispatches": total_dispatch,
        "claims": total_claims,
        "per_pin": results,
    }
    print("\n=== INTEL PINS SUMMARY ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    out = ROOT / "evidence" / f"intel_pins_{STAMP}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
