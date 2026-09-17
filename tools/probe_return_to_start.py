"""Bounded probe: bring the client back to a page the route goals can start from.

Why: the client's resting page is the map, but a previous run can leave it on MAIL
or any other page, and a *named* route goal deliberately refuses to rescue itself
from an unrelated page (it would be acting on another goal's page).  So before
running `--goal TRAIN` the operator needs the client back on HOME or MAP.

What it does, once per iteration, with a hard cap:

    capture -> observe -> if page in {HOME, MAP}: stop
                              otherwise: press BACK

It never taps a semantic target and never touches a purchase surface: BACK is the
only action, which is why it is safe to run unattended.  Every frame and every
observed page is printed, so the caller sees the route the client took.

Usage
-----
    python tools/probe_return_to_start.py --max-back 3
    python tools/probe_return_to_start.py --serial 127.0.0.1:7555 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_ROOT = ROOT / "dataset/raw/control_panel/probe"
STARTABLE = {"HOME", "MAP"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="press BACK until the client is on HOME or MAP")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--max-back", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]),
                       args.serial or config["device"]["serial"], production=True)
    if args.serial is None:
        device.resolve_connection()
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_dir = OUT_ROOT / f"return_to_start_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    trace: list[dict] = []
    for index in range(args.max_back + 1):
        shot = run_dir / f"{stamp}_step_{index:03d}_before.png"
        device.screenshot(shot)
        state = vision.observe(shot)
        trace.append({"step": index, "page": state.page.value, "popup": state.popup,
                      "screenshot": str(shot)})
        if not args.json:
            print(f"step {index}: page={state.page.value} popup={state.popup}")
        if state.page.value in STARTABLE:
            break
        if index == args.max_back:
            break
        device.press_back()
        # No sleep helper here on purpose: the caller sees one BACK per unclear
        # page, and a page that needs two BACKs shows up as two iterations.
    else:
        pass

    result = {"trace": trace, "final_page": trace[-1]["page"] if trace else None,
              "startable": bool(trace) and trace[-1]["page"] in STARTABLE,
              "capture_dir": str(run_dir)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"final page : {result['final_page']}   startable={result['startable']}")
        print(f"frames     : {run_dir}")
    return 0 if result["startable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
