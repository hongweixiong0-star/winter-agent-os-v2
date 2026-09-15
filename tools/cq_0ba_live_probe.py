"""WB-0BA live probe: read the acceptance evidence, then report the live client state.

Read-only apart from `adb devices` / a single screenshot for the page probe.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADB = r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe"
PY = r"E:\dongri-mumu-bot\.venv\Scripts\python.exe"


def main() -> None:
    print("=== gather_acceptance evidence (the runs that produced the 12:43 episodes) ===")
    for p in sorted((ROOT / "evidence").glob("gather_acceptance_*.json")):
        print("-" * 70)
        print(p.name)
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("   UNREADABLE", exc)
            continue
        for k in ("stop_reason", "runs", "exit_code", "started_at", "finished_at"):
            if k in d:
                print("   %-14s %s" % (k, json.dumps(d[k], ensure_ascii=False)[:200]))
        for run in d.get("runs") or []:
            print(
                "   run: exit=%s steps=%s elapsed=%s stop=%s"
                % (
                    run.get("exit_code"),
                    len(run.get("steps") or []),
                    run.get("elapsed_s"),
                    run.get("stop_reason"),
                )
            )
            for st in (run.get("steps") or [])[:14]:
                dec = st.get("decision") or {}
                ex = st.get("execution") or {}
                ver = st.get("verification") or {}
                print(
                    "      %-3s %-24s exec=%-5s ver=%-5s/%s"
                    % (
                        st.get("index"),
                        dec.get("skill"),
                        bool(ex.get("executed")),
                        ver.get("ok"),
                        ver.get("reason"),
                    )
                )

    print()
    print("=== adb devices ===")
    try:
        p = subprocess.run(
            [ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
        print(p.stdout.strip() or "(no output)")
        if p.stderr.strip():
            print("stderr:", p.stderr.strip()[:300])
    except Exception as exc:  # noqa: BLE001
        print("adb failed:", exc)

    print()
    print("=== live page probe (production vision) ===")
    p = subprocess.run(
        [PY, "-u", "tools/probe_live_page.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    print((p.stdout or "")[-2000:])
    if p.stderr.strip():
        print("stderr:", p.stderr.strip()[-600:])


if __name__ == "__main__":
    sys.exit(main())
