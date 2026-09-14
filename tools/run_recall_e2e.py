"""End-to-end live verification of the recall path.

The operator directive of 2026-09-14 is: when a better use for a march slot
appears, recall a gathering march.  That is a two-skill sequence through the
live loop (SELECT_MARCH_TO_RECALL then RECALL_MARCH), and it only triggers when
``idle_marches == 0``.

With the shipped ``reserve_for_stamina = 2`` a gather sweep stops at two idle
slots (verified live: ``reserved_march_for_stamina``), so the queue cannot be
filled by gathering alone.  This harness therefore relaxes the reserve to 0 for
the duration of the experiment, fills the queue, and drives the recall through
the real loop.

The relax is written to a *separate* config file and passed to the runners via
``WINTER_AGENT_CONFIG``.  An earlier version edited ``config/v2.json`` in place,
which silently broke any test running at the same time (the suite reads the
tracked config directly).  The tracked config is now never touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONFIG = ROOT / "config/v2.json"
EXPERIMENT_CONFIG = ROOT / "learning/experiments/v2_recall_experiment.json"
PYTHON = sys.executable


def run(command: list[str], label: str, env: dict[str, str] | None = None) -> str:
    print(f"\n=== {label}: {' '.join(str(part) for part in command[:6])} ...", flush=True)
    result = subprocess.run(
        command, capture_output=True, text=True, cwd=str(ROOT), errors="replace", env=env
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(output[-2500:], flush=True)
    print(f"=== {label} exit={result.returncode}", flush=True)
    return output


def observe_state() -> dict:
    script = (
        "import json,sys;from pathlib import Path;"
        f"sys.path.insert(0,{str(ROOT)!r});"
        "from winter_agent_v2.device import ADBDevice;"
        "from winter_agent_v2.ocr import HybridVision,OCRService,RapidOCRBackend,ResilientOCRBackend;"
        "from winter_agent_v2.vision import SemanticWorldVision;"
        "cfg=json.loads(Path('config/v2.json').read_text(encoding='utf-8'));"
        "d=ADBDevice(Path(cfg['device']['adb_path']),cfg['device']['serial'],production=True);"
        "d.resolve_connection();"
        "t=SemanticWorldVision(Path('dataset/candidate/template_manifest.json'));"
        "hv=HybridVision(t,OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg['ocr']['module_path'])))));"
        "f=Path('dataset/raw/control_panel/probe/recall_e2e_state.png');"
        "d.screenshot(f);s=hv.observe(f);"
        "print(json.dumps({'page':s.page.value,'popup':s.popup,"
        "'stamina':(s.stamina or {}).get('current'),'used':s.march_used,'max':s.march_max,"
        "'idle':s.idle_marches,'marches':[m.value for m in s.marches]},ensure_ascii=False))"
    )
    result = subprocess.run([PYTHON, "-c", script], capture_output=True, text=True, cwd=str(ROOT), errors="replace")
    for line in reversed((result.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {"error": (result.stdout or "") + (result.stderr or "")}


def main() -> int:
    original = json.loads(CONFIG.read_text(encoding="utf-8"))
    reserve = int(original["march_policy"]["reserve_for_stamina"])
    relaxed = json.loads(json.dumps(original))
    relaxed["march_policy"]["reserve_for_stamina"] = 0
    relaxed["march_policy"]["_experiment"] = "reserve relaxed by tools/run_recall_e2e.py"
    EXPERIMENT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EXPERIMENT_CONFIG.write_text(json.dumps(relaxed, ensure_ascii=False, indent=2), encoding="utf-8")
    env = {**os.environ, "WINTER_AGENT_CONFIG": str(EXPERIMENT_CONFIG)}
    print(f"experiment config: reserve_for_stamina {reserve} -> 0 (tracked config untouched)")
    try:
        print("state before:", observe_state(), flush=True)
        run([PYTHON, "-u", "tools/run_gather_acceptance.py", "--runs", "3",
             "--serial", "127.0.0.1:7555"], "fill the queue with gathering", env)
        state = observe_state()
        print("state after filling:", state, flush=True)
        if state.get("idle") != 0:
            print("\nRESULT: the queue did not reach 0 idle, so the recall trigger cannot fire.")
            print("NOTE: run this when the account really has six marches out.")
            return 1
        log = run([PYTHON, "-u", "tools/run_live.py", "--goal", "BEAST_HUNT", "--max-actions", "8",
                   "--serial", "127.0.0.1:7555",
                   "--capture-dir", "dataset/raw/control_panel/runtime_auto/recall_e2e"],
                  "recall via the live loop", env)
        (ROOT / "evidence").mkdir(exist_ok=True)
        (ROOT / "evidence" / f"recall_e2e_{time.strftime('%Y%m%d_%H%M%S')}.log").write_text(log, encoding="utf-8")
        payload = next((json.loads(line) for line in reversed(log.splitlines())
                        if line.strip().startswith("{") and '"steps"' in line), {"steps": []})
        skills = [step.get("decision", {}).get("skill") for step in payload["steps"]]
        verified = [bool((step.get("verification") or {}).get("ok")) for step in payload["steps"]]
        print("\nskills dispatched:", skills)
        print("verifier results :", verified)
        print("stop_reason      :", payload.get("stop_reason"))
        recalled = "RECALL_MARCH" in skills and all(verified)
        print("RESULT:", "recall verified end to end" if recalled else "recall NOT verified end to end")
        return 0 if recalled else 1
    finally:
        EXPERIMENT_CONFIG.unlink(missing_ok=True)
        print(f"tracked config untouched (reserve_for_stamina still {reserve})")
        print("state at the end:", observe_state())


if __name__ == "__main__":
    raise SystemExit(main())
