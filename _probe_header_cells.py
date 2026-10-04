"""What the three fold-able top-bar cells read on the REAL data root, right now.

Written before the code, because the tiering is only worth building if the three cells are
"健康时" in production today: if all three read 未确认, hiding them hides nothing and the honest
report is "the declaration is right and its effect is zero today" rather than a claimed win.

Uses the window's *own* probes, and the window's own reading path, so the words printed here are
the words the operator would see -- not a re-derivation that could agree with me and not with it.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.state_truth import health_of  # noqa: E402


def load_panel():
    spec = importlib.util.spec_from_file_location("cp_header_probe",
                                                  ROOT / "tools" / "control_panel.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


panel = load_panel()


def show(label: str, value: object) -> str:
    if value is None:
        print(f"  {label:<10} -> 报告里没有这个来源（None）-> 按判据会显示为 未确认")
        return "unknown"
    word, colour = health_of(value)  # type: ignore[arg-type]
    print(f"  {label:<10} -> {word:<4} ({colour:<7}) value={getattr(value, 'value', None)!r}"
          f"  status={getattr(value, 'status', None)}")
    return colour


def main() -> int:
    probes = panel.PanelProbes(ROOT, device=None)
    # ``truth()`` returns the *last* audit from the probe thread, so a probe that was never
    # started answers "no report" and would have let this script report 未确认 for all three
    # cells while measuring only its own failure to run.  Start it and wait for the first pass.
    probes.start()
    deadline = time.monotonic() + 90
    probe: dict = {}
    while time.monotonic() < deadline:
        probe = probes.truth()
        if probe.get("report") is not None:
            break
        time.sleep(1.0)
    try:
        report = probe.get("report")
        print(f"审计 report: {'可用' if report is not None else '不可用'}"
              f"  ok={probe.get('ok')}  reason={probe.get('reason')!r}"
              f"  （等了 {90 - max(0, int(deadline - time.monotonic()))} 秒）")
        colours = {}
        for source, label in (("gateway_health", "WorkBuddy"), ("bootstrap", "预载")):
            value = report.by_name(source) if report is not None else None
            colours[label] = show(label, value)
        try:
            colours["本地模型"] = show("本地模型", probes.local_model_truth())
        except Exception as exc:  # noqa: BLE001
            print(f"  本地模型       -> 探测失败 {type(exc).__name__}: {exc}")
            colours["本地模型"] = "unknown"

        healthy = {"good", "work", "idle"}
        print()
        for label, colour in colours.items():
            verdict = "隐藏（健康）" if colour in healthy else "常驻（非健康，浮到 L1）"
            print(f"  {label:<10} {colour:<7} -> {verdict}")
    finally:
        probes.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
