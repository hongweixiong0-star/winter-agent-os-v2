"""WB-0BA gate: reason classification, targeted tests, wiring, post-fix episodes."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = r"E:\dongri-mumu-bot\.venv\Scripts\python.exe"
sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime_snapshot import NON_FATAL_STOPS, is_fatal_stop  # noqa: E402


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> None:
    print("=== 1. reason classification ===")
    for reason in (
        "intel_no_untried_pins",
        "dispatch_unaffordable_for_stamina",
        "MARCH_COUNT_NOT_READ",
        "SKILL_NOT_ENABLED_FOR_LIVE_LOOP",
    ):
        print(
            "   %-36s in_NON_FATAL=%-6s is_fatal_stop=%s"
            % (reason, reason in NON_FATAL_STOPS, is_fatal_stop(reason))
        )

    print()
    print("=== 2. targeted tests (WB-0BA test_plan) ===")
    rc, out = run(
        [
            PY,
            "-m",
            "pytest",
            "tests/test_intel_pin_exhaustion.py",
            "tests/test_stamina_supply_clock.py",
            "tests/test_live_runtime.py",
            "-q",
            "--tb=short",
            "-p",
            "no:cacheprovider",
        ]
    )
    print("   exit=%s" % rc)
    print("\n".join("   " + ln for ln in out.splitlines()[-18:]))

    print()
    print("=== 3. wiring ===")
    rc, out = run([PY, "-u", "tools/check_wiring.py"])
    print("   exit=%s" % rc)
    for ln in out.splitlines():
        if ln.startswith(("MISS", "problems")):
            print("   " + ln)

    print()
    print("=== 4. every episode with a pin/vision failure, by date ===")
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    from collections import Counter

    c = Counter()
    for r in rows:
        ft = r.get("failure_type")
        if ft in ("SEMANTIC_TARGET_NOT_VERIFIED",) or r.get("skill") == "SELECT_INTEL_PIN":
            c[((r.get("recorded_at") or "")[:19], r.get("skill"), str(r.get("result")), ft)] += 1
    for k, v in sorted(c.items()):
        print("   %s | %-22s | %-8s | %-38s | x%d" % (k[0], k[1], k[2], k[3], v))

    print()
    print("=== 5. evidence/intel_pins_*.json (last 8) ===")
    for p in sorted((ROOT / "evidence").glob("intel_pins_*.json"))[-8:]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("   %-44s UNREADABLE %s" % (p.name, exc))
            continue
        print(
            "   %-44s stop=%-28s disp=%s claims=%s cycles=%s"
            % (
                p.name,
                d.get("stop_reason"),
                d.get("dispatches"),
                d.get("claims"),
                d.get("navigation_cycles"),
            )
        )


if __name__ == "__main__":
    main()
