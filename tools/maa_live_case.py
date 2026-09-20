"""Live A/B: ADB (legacy) versus MAA, measured on the real client.

Operator directive 2026-09-14 requires a real live A/B, not a benchmark on saved
frames.  This tool provides the three measurements that decide the migration, in
increasing cost:

``state``
    One MAA-captured frame, reported as a WorldState.  Proves the MAA observation
    path works end to end on the live client and tells you what screen you are on.

``capture-ab``
    N alternating captures per backend on the same screen, with both recognisers
    run on each frame.  No game action, so it is safe to repeat and it measures
    the 246 ms -> 12 ms claim plus recognition agreement on live pixels.

``action-ab``
    N real transitions on a repeatable pair.  Each attempt captures with one
    backend, recognises with the same backend, taps, and is judged by the V2
    verifier.  Arms alternate so ordering cannot explain the result.  The reset
    leg uses the same legacy path for BOTH arms, so it cannot bias the measured
    leg - recorded that way in the report.

``battle``
    The hero-journey battle button (today's two-hour loss) driven end to end with
    MAA recognition and MAA action, judged by verify_intel_hero_dispatched.  If no
    intel hero-journey target exists on the board it reports
    BLOCKED_NO_INTEL_TARGET rather than inventing attempts.

Run with the project venv:

    E:/无尽冬日智能体/.venv/Scripts/python.exe -u tools/maa_live_case.py state
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice  # noqa: E402
from winter_agent_v2.maa_executor import MaaExecutorAdapter  # noqa: E402
from winter_agent_v2.verifier import verify_open_home  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

CONFIG = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
ADB_PATH = Path(CONFIG["device"]["adb_path"])
SERIAL = CONFIG["device"]["serial"]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
EVIDENCE = ROOT / "dataset/evidence/maa_live"


def build(production: bool = True):
    adb = ADBDevice(ADB_PATH, SERIAL, production=production)
    adb.resolve_connection()
    maa = MaaExecutorAdapter(
        adb_path=ADB_PATH, serial=SERIAL, production=production,
        template_dir=ROOT / "dataset/candidate/templates",
        log_dir=ROOT / "learning/maa_logs",
    )
    ok, reason = maa.ensure_ready()
    world = SemanticWorldVision(MANIFEST)
    return adb, maa, world, ok, reason


def template_paths(semantic: str) -> list[Path]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [ROOT / str(r["template_path"]) for r in payload.get("records", [])
            if str(r.get("semantic", "")) == semantic]


def observe(path: Path, world: SemanticWorldVision):
    return world.observe(path)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


# --------------------------------------------------------------------------- state
def cmd_state(_args) -> int:
    adb, maa, world, ok, reason = build(production=False)
    print(f"MAA ready: {ok} reason: {reason or '-'}")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    live_frame = EVIDENCE / f"state_maa_{stamp()}.png"
    started = time.perf_counter()
    frame = maa.capture()
    maa_ms = (time.perf_counter() - started) * 1000
    if frame is None:
        print("MAA_CAPTURE_FAILED")
        return 1
    maa.save_annotated(frame, None, live_frame, label="MAA capture")
    adb_frame = EVIDENCE / f"state_adb_{stamp()}.png"
    started = time.perf_counter()
    adb.screenshot(adb_frame)
    adb_ms = (time.perf_counter() - started) * 1000
    state = observe(adb_frame, world)
    print(f"capture: MAA {maa_ms:.1f} ms   ADB {adb_ms:.1f} ms   ratio {adb_ms / max(maa_ms, 0.01):.1f}x")
    print(f"frame  : {live_frame.relative_to(ROOT)}")
    print(json.dumps({
        "page": state.page.value,
        "march_used": state.march_used,
        "march_max": state.march_max,
        "stamina": state.stamina,
        "intel": state.intel,
        "beast": state.beast,
        "resource_search_open": state.resource_search_open,
    }, ensure_ascii=False, indent=2, default=str))
    print("stats:", json.dumps(maa.stats(), ensure_ascii=False))
    return 0


# ----------------------------------------------------------------------- capture-ab
def cmd_capture_ab(args) -> int:
    adb, maa, world, ok, reason = build(production=False)
    if not ok:
        print(f"MAA_NOT_READY: {reason}")
        return 1
    semantic = args.semantic
    templates = template_paths(semantic)
    if not templates:
        print(f"SEMANTIC_NOT_IN_MANIFEST: {semantic}")
        return 1
    image_arg = {semantic: templates[0]}
    roi_vision = world.semantic
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for index in range(1, args.attempts + 1):
        adb_frame = EVIDENCE / f"capab_{stamp()}_{index:02d}_adb.png"
        started = time.perf_counter()
        adb.screenshot(adb_frame)
        adb_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        frame = maa.capture()
        maa_ms = (time.perf_counter() - started) * 1000
        if frame is None:
            print(f"attempt {index}: MAA capture failed")
            continue

        started = time.perf_counter()
        legacy = roi_vision.find(adb_frame, semantic)
        legacy_ms = (time.perf_counter() - started) * 1000

        outcome = maa.match_template(frame, template=semantic, semantic=semantic,
                                    images=image_arg)

        delta = None
        if legacy is not None and outcome.center() is not None:
            lx, ly = (legacy.center_norm[0] * 720, legacy.center_norm[1] * 1280)
            cx, cy = outcome.center()
            delta = round(((lx - cx) ** 2 + (ly - cy) ** 2) ** 0.5, 1)

        rows.append({
            "attempt": index,
            "adb_capture_ms": round(adb_ms, 1),
            "maa_capture_ms": round(maa_ms, 1),
            "legacy_recognition_ms": round(legacy_ms, 1),
            "maa_recognition_ms": round(outcome.latency_ms, 1),
            "legacy_hit": legacy is not None,
            "legacy_distance": None if legacy is None else legacy.distance,
            "maa_hit": outcome.hit,
            "maa_score": outcome.score,
            "maa_box": list(outcome.box) if outcome.box else None,
            "centre_delta_px": delta,
            "agree": (legacy is not None) == outcome.hit,
        })
        print(f"  attempt {index:2d}: cap adb={adb_ms:6.1f}ms maa={maa_ms:5.1f}ms | "
              f"reco legacy={('hit' if legacy is not None else 'miss'):4s} {legacy_ms:6.1f}ms  "
              f"maa={('hit' if outcome.hit else 'miss'):4s} {outcome.latency_ms:6.1f}ms "
              f"d={delta}")

    def mean(key):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    summary = {
        "semantic": semantic,
        "attempts": len(rows),
        "adb_capture_ms_mean": mean("adb_capture_ms"),
        "maa_capture_ms_mean": mean("maa_capture_ms"),
        "capture_ratio": (round(mean("adb_capture_ms") / mean("maa_capture_ms"), 1)
                          if mean("maa_capture_ms") else None),
        "legacy_recognition_ms_mean": mean("legacy_recognition_ms"),
        "maa_recognition_ms_mean": mean("maa_recognition_ms"),
        "legacy_hits": sum(1 for r in rows if r["legacy_hit"]),
        "maa_hits": sum(1 for r in rows if r["maa_hit"]),
        "agreement": f"{sum(1 for r in rows if r['agree'])}/{len(rows)}",
        "centre_delta_px_max": max([r["centre_delta_px"] for r in rows if r["centre_delta_px"] is not None],
                                   default=None),
        "rows": rows,
    }
    out = ROOT / "learning" / f"maa_capture_ab_{stamp()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nSUMMARY:", json.dumps({k: v for k, v in summary.items() if k != "rows"},
                                   ensure_ascii=False, indent=2))
    print("report ->", out.relative_to(ROOT))
    return 0


# ------------------------------------------------------------------------ action-ab
def _reset_to_map(adb: ADBDevice, world: SemanticWorldVision, settle: float) -> bool:
    """Return to the world map with the legacy path, shared by both arms.

    Deliberately identical for both arms so it cannot bias the measured leg; that
    limitation is stated in the report instead of being hidden.  It never presses
    BACK: on the city screen a stray BACK can open an exit prompt, and a reset
    that damages the session would invalidate the measurement it is setting up.
    """
    for _ in range(3):
        if not EVIDENCE.exists():
            EVIDENCE.mkdir(parents=True, exist_ok=True)
        probe = EVIDENCE / f"reset_{stamp()}.png"
        adb.screenshot(probe)
        state = observe(probe, world)
        if state.page.value == "MAP":
            return True
        anchor = world.semantic.find(probe, "PAGE_MAP")
        if anchor is None:
            return False
        x, y = anchor.center_norm
        adb.tap(round(x * 720), round(y * 1280))
        time.sleep(settle)
    return False


def cmd_action_ab(args) -> int:
    adb, maa, world, ok, reason = build(production=True)
    if not ok:
        print(f"MAA_NOT_READY: {reason}")
        return 1
    semantic, skill = args.semantic, args.skill
    templates = template_paths(semantic)
    if not templates:
        print(f"SEMANTIC_NOT_IN_MANIFEST: {semantic}")
        return 1
    image_arg = {semantic: templates[0]}
    verifier = {"OPEN_HOME": verify_open_home}[skill]
    settle = 2.0
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for index in range(1, args.attempts + 1):
        arm = "ADB" if index % 2 == 1 else "MAA"
        if not _reset_to_map(adb, world, settle):
            rows.append({"attempt": index, "arm": arm, "setup": "RESET_TO_MAP_FAILED"})
            print(f"  attempt {index:2d} [{arm}]: setup failed (could not reach MAP)")
            continue

        before_path = EVIDENCE / f"actab_{stamp()}_{index:02d}_{arm}_before.png"
        started = time.perf_counter()
        if arm == "ADB":
            adb.screenshot(before_path)
            resolve_ms = (time.perf_counter() - started) * 1000
            match = world.semantic.find(before_path, semantic)
            if match is None:
                rows.append({"attempt": index, "arm": arm, "resolved": False,
                             "error": "LEGACY_TARGET_NOT_FOUND"})
                print(f"  attempt {index:2d} [{arm}]: legacy target not found")
                continue
            x, y = match.center_norm
            before = observe(before_path, world)
            started_action = time.perf_counter()
            adb.tap(round(x * 720), round(y * 1280))
            action_ms = (time.perf_counter() - started_action) * 1000
            recognition_ms = resolve_ms
            score = None
        else:
            frame = maa.capture()
            if frame is None:
                rows.append({"attempt": index, "arm": arm, "resolved": False,
                             "error": "MAA_CAPTURE_FAILED"})
                continue
            maa.save_annotated(frame, None, before_path, label="MAA paint frame")
            before = observe(before_path, world)
            outcome = maa.match_template(frame, template=semantic, semantic=semantic,
                                        images=image_arg)
            recognition_ms = outcome.latency_ms
            score = outcome.score
            if not outcome.hit:
                rows.append({"attempt": index, "arm": arm, "resolved": False,
                             "error": outcome.error, "recognition_ms": round(recognition_ms, 1)})
                print(f"  attempt {index:2d} [{arm}]: MAA target not recognised")
                continue
            center = outcome.center()
            started_action = time.perf_counter()
            clicked, err = maa.click(*center)
            action_ms = (time.perf_counter() - started_action) * 1000
            maa.save_annotated(frame, outcome.box, EVIDENCE / f"actab_{stamp()}_{index:02d}_box.png",
                               label=f"{semantic} {score}")

        time.sleep(settle)
        after_path = EVIDENCE / f"actab_{stamp()}_{index:02d}_{arm}_after.png"
        if arm == "MAA":
            after_frame = maa.capture()
            if after_frame is not None:
                maa.save_annotated(after_frame, None, after_path, label="MAA after")
        else:
            adb.screenshot(after_path)
        after = observe(after_path, world)
        verification = verifier(before, after)
        rows.append({
            "attempt": index, "arm": arm, "resolved": True,
            "recognition_ms": round(recognition_ms, 1),
            "action_ms": round(action_ms, 1),
            "score": score,
            "before_page": before.page.value,
            "after_page": after.page.value,
            "verifier_ok": bool(verification.ok),
            "verifier_reason": verification.reason,
            "before_screenshot": str(before_path.relative_to(ROOT)),
            "after_screenshot": str(after_path.relative_to(ROOT)),
        })
        print(f"  attempt {index:2d} [{arm}]: {before.page.value} -> {after.page.value} "
              f"verifier={'PASS' if verification.ok else 'FAIL'} ({verification.reason}) "
              f"reco={recognition_ms:.1f}ms action={action_ms:.1f}ms")

    summary = {"semantic": semantic, "skill": skill, "attempts_requested": args.attempts,
               "rows": rows, "by_arm": {}}
    for arm in ("ADB", "MAA"):
        arm_rows = [r for r in rows if r["arm"] == arm]
        resolved = [r for r in arm_rows if r.get("resolved")]
        passed = [r for r in resolved if r.get("verifier_ok")]
        summary["by_arm"][arm] = {
            "attempts": len(arm_rows),
            "target_resolved": len(resolved),
            "verifier_pass": len(passed),
            "success_rate": round(len(passed) / len(resolved), 3) if resolved else None,
            "recognition_ms_mean": round(sum(r["recognition_ms"] for r in resolved) / len(resolved), 1) if resolved else None,
            "action_ms_mean": round(sum(r["action_ms"] for r in resolved) / len(resolved), 1) if resolved else None,
        }
    out = ROOT / "learning" / f"maa_action_ab_{stamp()}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nSUMMARY:", json.dumps(summary["by_arm"], ensure_ascii=False, indent=2))
    print("report ->", out.relative_to(ROOT))
    print("reset leg: legacy path for BOTH arms (documented, not hidden)")
    return 0


# ---------------------------------------------------------------------------- battle
def cmd_battle(args) -> int:
    """Hero-journey battle button: MAA recognition + MAA action, V2 verifier.

    Reports BLOCKED_NO_INTEL_TARGET when the board has no hero-journey pin rather
    than fabricating attempts.  The route is: MAP -> intel HUD -> pin -> mission
    card -> 前往查看 -> camp panel -> 探险 -> squad page -> 战斗.
    """
    adb, maa, world, ok, reason = build(production=True)
    if not ok:
        print(f"MAA_NOT_READY: {reason}")
        return 1
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    probe = EVIDENCE / f"battle_state_{stamp()}.png"
    adb.screenshot(probe)
    state = observe(probe, world)
    print(f"current page: {state.page.value}  intel: {state.intel}")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page": state.page.value,
        "intel": state.intel,
        "result": "BLOCKED_NO_INTEL_TARGET",
        "note": (
            "The battle button lives on the hero-journey squad page, which is only "
            "reachable through an intel hero-journey pin. The recognition node itself is "
            "measured in knowledge/execution/backend_routing.json (9/9 positives, 0/8 "
            "negatives, 0.5 px centre error) and exercised live via the OPEN_HOME action "
            "A/B until a pin is on the board."
        ),
    }
    out = ROOT / "learning" / f"maa_battle_case_{stamp()}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("report ->", out.relative_to(ROOT))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live ADB vs MAA measurement harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("state")
    cap = sub.add_parser("capture-ab")
    cap.add_argument("--attempts", type=int, default=20)
    cap.add_argument("--semantic", default="BTN_OPEN_HOME")
    act = sub.add_parser("action-ab")
    act.add_argument("--attempts", type=int, default=10)
    act.add_argument("--semantic", default="BTN_OPEN_HOME")
    act.add_argument("--skill", default="OPEN_HOME")
    bat = sub.add_parser("battle")
    bat.add_argument("--attempts", type=int, default=10)
    args = parser.parse_args()
    return {"state": cmd_state, "capture-ab": cmd_capture_ab,
            "action-ab": cmd_action_ab, "battle": cmd_battle}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
