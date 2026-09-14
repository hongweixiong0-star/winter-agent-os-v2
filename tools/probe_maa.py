"""Probe: what MAA / MaaFramework capability actually exists on this machine?

Read-only reconnaissance. No network install. Prints a JSON verdict.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPORT: dict = {"probe": "maa_availability", "python": sys.executable}


def _safe(fn, label):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        REPORT.setdefault("errors", {})[label] = f"{type(exc).__name__}: {exc}"
        return None


# ---------------------------------------------------------------- 1. PATH binaries
def which_all(names):
    out = {}
    for n in names:
        p = shutil.which(n)
        if p:
            out[n] = p
    return out


REPORT["which"] = _safe(
    lambda: which_all(
        [
            "maa", "MaaPiCli", "MaaDebugger", "maadbg",
            "MaaAgentClient", "MaaAgentServer",
            "adb", "python", "node", "npm", "git",
        ]
    ),
    "which",
)

# ---------------------------------------------------------------- 2. known install roots
CANDIDATE_ROOTS = [
    r"C:\Program Files\MaaAssistantArknights",
    r"C:\Program Files (x86)\MaaAssistantArknights",
    r"D:\Program Files\MaaAssistantArknights",
    r"C:\MAA",
    r"D:\MAA",
    r"E:\MAA",
    r"E:\MaaFramework",
    r"D:\MaaFramework",
    r"C:\MaaFramework",
    os.path.expanduser(r"~\MaaAssistantArknights"),
    os.path.expanduser(r"~\AppData\Local\MaaAssistantArknights"),
    os.path.expanduser(r"~\AppData\Roaming\MaaAssistantArknights"),
    r"E:\无尽冬日智能体\.maa",
    r"E:\无尽冬日智能体\tools\maa",
]
found_roots = {}
for root in CANDIDATE_ROOTS:
    if os.path.isdir(root):
        try:
            entries = os.listdir(root)[:40]
        except Exception:
            entries = ["<unreadable>"]
        found_roots[root] = entries
REPORT["candidate_roots_existing"] = found_roots


# ---------------------------------------------------------------- 3. hunt for MaaCore / MaaFramework dll/so
def hunt_libs():
    hits = []
    roots = [
        r"C:\Program Files",
        r"D:\Program Files",
        "E:\\",
        os.path.expanduser("~"),
    ]
    patterns = ["MaaCore.dll", "libMaaFramework*", "MaaFramework.dll", "MaaToolkit*"]
    for r in roots:
        if not os.path.isdir(r):
            continue
        for pat in patterns:
            for depth in ("", "*", "*/*", "*/*/*"):
                g = os.path.join(r, depth, pat) if depth else os.path.join(r, pat)
                for p in glob.glob(g):
                    if len(hits) < 60:
                        hits.append(p)
    return hits


REPORT["native_libs"] = _safe(hunt_libs, "hunt_libs")

# ---------------------------------------------------------------- 4. python bindings
PY_MODULES = ["maa", "maafw", "MaaFw", "maa_framework", "asst", "MaaAgentClient"]
REPORT["python_modules"] = {
    m: bool(importlib.util.find_spec(m)) for m in PY_MODULES
}

# ---------------------------------------------------------------- 5. pip list (project venv + current)
def pip_list(py):
    try:
        r = subprocess.run(
            [py, "-m", "pip", "list", "--format=freeze"],
            capture_output=True, text=True, timeout=120,
        )
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        interesting = [
            l for l in lines
            if any(k in l.lower() for k in ("maa", "opencv", "rapidocr", "onnx", "pillow", "numpy"))
        ]
        return {"total": len(lines), "interesting": interesting, "stderr_tail": r.stderr[-400:]}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


REPORT["pip_current"] = pip_list(sys.executable)
PROJECT_VENV = r"E:\dongri-mumu-bot\.venv\Scripts\python.exe"
if os.path.exists(PROJECT_VENV):
    REPORT["pip_project_venv"] = pip_list(PROJECT_VENV)
else:
    REPORT["pip_project_venv"] = {"error": "project venv missing"}

# ---------------------------------------------------------------- 6. npm global / node bindings
def npm_global():
    npm = shutil.which("npm")
    if not npm:
        return {"error": "npm not on PATH"}
    try:
        r = subprocess.run([npm, "ls", "-g", "--depth=0"], capture_output=True, text=True, timeout=180, shell=True)
        return {"stdout": r.stdout[-1500:], "stderr": r.stderr[-400:]}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


REPORT["npm_global"] = _safe(npm_global, "npm_global")

# ---------------------------------------------------------------- 7. project-side existing executors
proj = Path(r"E:\无尽冬日智能体")
REPORT["project_executor_files"] = sorted(
    str(p.relative_to(proj))
    for p in proj.glob("winter_agent_v2/*.py")
) if proj.is_dir() else []

grep_hits = []
for p in proj.rglob("*.py"):
    if ".venv" in p.parts or "__pycache__" in p.parts:
        continue
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    low = txt.lower()
    if "maa" in low or "maaframework" in low or "maatouch" in low:
        grep_hits.append(str(p.relative_to(proj)))
REPORT["project_files_mentioning_maa"] = grep_hits

# ---------------------------------------------------------------- 8. adb / device
def adb_state():
    adb = None
    for cand in [
        r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe",
        shutil.which("adb"),
    ]:
        if cand and os.path.exists(cand):
            adb = cand
            break
    if not adb:
        return {"error": "adb not found"}
    try:
        r = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, timeout=30)
        return {"adb": adb, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except Exception as exc:  # noqa: BLE001
        return {"adb": adb, "error": f"{type(exc).__name__}: {exc}"}


REPORT["adb"] = _safe(adb_state, "adb_state")

print(json.dumps(REPORT, indent=2, ensure_ascii=False))
