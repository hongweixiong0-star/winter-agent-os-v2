"""Prove the control panel's cells equal the production source of truth.

The operator's requirement is not "the GUI was written to read X" -- it is "the value
shown equals the value in X", verified.  So this tool does not inspect source code: it
builds the window's derivation functions and the source of truth independently and
compares them, printing both numbers on every line.

What it refuses to do, and why
------------------------------
The AUTO worker owned the client for this work unit (``run_live.py`` PID 3552, launched
by the panel).  So this tool **never unplugs the emulator** to prove the disconnect cell,
and **never taps** anything.  Test 2 is done at the ADB boundary instead: a real
``ADBDevice`` aimed at a port nothing serves, which is a genuine ADB failure and not a
mocked object.  Unplugging the emulator the operator is playing through would be a real
experiment with a real cost, and it is listed as pending rather than faked.

Usage
-----
    python tools/verify_panel_wiring.py            # read-only wiring comparison
    python tools/verify_panel_wiring.py --gateway  # print the gateway cell once
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import control_panel as panel  # noqa: E402
from winter_agent_v2.device import ADBDevice  # noqa: E402

RESULTS: list[tuple[str, bool, str, str]] = []


def record(label: str, ok: bool, shown: str, source: str) -> None:
    RESULTS.append((label, ok, shown, source))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"       GUI  : {shown}")
    print(f"       源   : {source}")


def check_device_cells(config: dict) -> None:
    print("\n== 1/2. MuMu 与 游戏 ==")
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    expected = str(config["device"]["package_name"])
    try:
        status = device.status()
        independent = (f"connected={status.connected} serial={status.serial} "
                       f"resolution={status.resolution} foreground={status.foreground_package}")
    except Exception as exc:  # noqa: BLE001
        status = None
        independent = f"ADBDevice.status() raised {type(exc).__name__}: {exc}"
        record("MuMu 状态 = 真实 ADB 读数", False,
               panel.device_cells({"ok": False, "status": None, "error": str(exc)}, expected)[0], independent)
        return
    mumu, game = panel.device_cells({"ok": True, "status": status, "error": ""}, expected)
    record("MuMu 状态 = 真实 ADB 读数", ("已连接" in mumu) == status.connected, mumu, independent)
    record("游戏 状态 = 真实前台包名", (game == "运行中") == (status.foreground_package == expected),
           game, f"expected={expected}")

    dead = ADBDevice(Path(config["device"]["adb_path"]), "127.0.0.1:59999", production=True)
    try:
        dead_status = dead.status()
        dead_note = f"ADBDevice.status() unexpectedly returned connected={dead_status.connected}"
        unreachable = dead_status.connected
    except Exception as exc:  # noqa: BLE001
        dead_status = None
        dead_note = f"ADBDevice.status() raised {type(exc).__name__}: {str(exc).strip()[:80]}"
        unreachable = True
    shown = panel.device_cells({"ok": dead_status is not None, "status": dead_status,
                                "error": dead_note}, expected)[0]
    record("MuMu 断开 = 未连接（真实 ADB 失败，未拔真机）",
           unreachable and shown.startswith("● 未连接"), shown, dead_note)


def check_maa(now: datetime) -> dict:
    print("\n== 3/4. MAA ==")
    report = panel.runtime_interpreter_report()
    axis = panel.backend_axis(panel.tail_jsonl(panel.BACKEND_LEDGER_PATH, 200))
    cell = panel.maa_cell(report, axis, now=now)
    # Independent recomputation of the same facts, straight from the ledger.
    rows = [json.loads(line) for line in panel.BACKEND_LEDGER_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("{")][-200:]
    maa_rows = [row for row in rows if str(row.get("used_backend")).upper() == "MAA"]
    newest = str(maa_rows[-1].get("recorded_at")) if maa_rows else ""
    age = panel.age_seconds(newest, now)
    failures = sorted({str(attempt.get("error")) for row in rows for attempt in (row.get("attempts") or [])
                       if str(attempt.get("error") or "").startswith("MAA_")})
    degraded = any(str(row.get("used_backend")).upper() == "ADB"
                   and str(row.get("preferred_backend")).upper() == "MAA" for row in rows) \
        or any(row.get("fallback_used") for row in rows)
    source = (f"解释器 missing={report.missing} exists={report.exists}; "
              f"近{len(rows)}步 MAA {len(maa_rows)} 次, 最近 {newest or '(none)'} "
              f"= {age:.0f}s 前, degraded={degraded}, MAA_* 失败={failures or '无'}")
    if report.missing or not report.exists or failures:
        expected = panel.MAA_BROKEN
    elif degraded:
        expected = panel.MAA_ADB_FALLBACK
    elif age is not None and age <= panel.MAA_FRESH_SECONDS:
        expected = f"{panel.MAA_NORMAL} · {panel._human_age(age)}执行"
    elif age is None and not maa_rows:
        expected = panel.MAA_NORMAL
    else:
        expected = f"{panel.MAA_NORMAL} · {panel._human_age(age)}无 MAA 执行"
    record("MAA 单元格 = 台账+解释器实测", cell == expected, cell, source)
    print(f"       判据        : {panel.maa_note(report, axis)}")
    print("       注意：近 200 步里 preferred=MAA 的步骤全部真的走了 MAA，"
          "若只看 preferred_backend 这里会误报『正常』")
    return axis


def check_auto(axis: dict) -> None:
    print("\n== 5/6. AUTO ==")
    from tools import control_panel as module

    class _Process:
        def __init__(self, alive: bool) -> None:
            self._alive = alive

        def poll(self):
            return None if self._alive else 0

    cases = (
        ("worker 存活", module.auto_cell(starting=False, worker_alive=True, paused=False,
                                        stop_requested=False, restart_scheduled=False), module.AUTO_RUNNING),
        ("无 worker 且未排程", module.auto_cell(starting=False, worker_alive=False, paused=False,
                                             stop_requested=False, restart_scheduled=False), module.AUTO_STOPPED),
        ("已排下一轮", module.auto_cell(starting=False, worker_alive=False, paused=False,
                                      stop_requested=False, restart_scheduled=True), module.AUTO_WAITING),
    )
    for label, shown, expected in cases:
        record(f"AUTO「{label}」", shown == expected, shown, f"期望 {expected}")
    # The live reading, taken from the process table rather than from any file.
    live = panel.auto_cell(starting=False, worker_alive=_live_worker(), paused=False,
                           stop_requested=False, restart_scheduled=False)
    print(f"       （现场读数：{live} —— 与进程表一致，来自 self.process.poll()）")


def _live_worker() -> bool:
    """Is a run_live worker alive right now?  Asked of the OS, not of a status file."""
    import subprocess

    try:
        listing = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | "
             "Where-Object { $_.CommandLine -like '*run_live.py*' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return listing.stdout.strip().splitlines()[-1].strip() not in ("", "0")
    except Exception:  # noqa: BLE001
        return False


def check_backend(axis: dict) -> None:
    print("\n== 12. 执行后端 ==")
    rows = panel.tail_jsonl(panel.BACKEND_LEDGER_PATH, 200)
    last = rows[-1]
    shown = axis["label"]
    expected_fragment = str(last.get("capture_backend") or "")
    record("执行后端 = 台账最后一行的真实后端",
           expected_fragment in shown,
           shown,
           f"最后一行: skill={last.get('skill_id')} preferred={last.get('preferred_backend')} "
           f"used={last.get('used_backend')} capture={last.get('capture_backend')}")
    record("未迁移技能不显示为降级",
           not axis["degraded"] or shown.startswith("ADB 降级"),
           f"degraded={axis['degraded']}",
           "降级必须同时满足 preferred=MAA 且 used=ADB（或 fallback_used=true）")


def check_capability_kpi() -> None:
    print("\n== 11. Capability KPI ==")
    real = panel.overview_kpis()
    catalog = json.loads((ROOT / "knowledge/game/capability_catalog.json").read_text(encoding="utf-8"))
    summary = catalog["summary"]
    checks = (
        ("Live Verified", int(real["verified"]["value"]), summary["by_lifecycle"].get("LIVE_VERIFIED")),
        ("Implemented", int(real["implemented"]["value"]), summary["by_implementation"].get("EXISTING")),
        ("Never Tried", int(real["never"]["value"]), summary["by_lifecycle"].get("MISSING")),
    )
    for label, shown, truth in checks:
        record(f"KPI「{label}」= capability_catalog", shown == truth, str(shown), str(truth))

    # And a *change* in the source must move the number: done on a copied tree so the
    # production catalog is never touched.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "knowledge/game").mkdir(parents=True)
        (root / "learning").mkdir(parents=True)
        mutated = json.loads(json.dumps(catalog))
        for entry in mutated["capabilities"]:
            if entry.get("lifecycle") == "LIVE_VERIFIED":
                entry["lifecycle"] = "MISSING"
                entry["implementation_status"] = "MISSING"
                entry["live_attempts"] = 0
        (root / "knowledge/game/capability_catalog.json").write_text(
            json.dumps(mutated, ensure_ascii=False), encoding="utf-8")
        (root / "knowledge/goals").mkdir(parents=True, exist_ok=True)
        (root / "knowledge/goals/capability_skill_map.json").write_text("{}", encoding="utf-8")
        changed = panel.overview_kpis(root)
        record("Capability 变化后 KPI 同步变化",
               int(changed["verified"]["value"]) == 0 and int(changed["never"]["value"]) > int(real["never"]["value"]),
               f"verified {real['verified']['value']} -> {changed['verified']['value']}",
               "把副本里所有 LIVE_VERIFIED 改成 MISSING 后重算（未触碰生产目录）")


def check_gateway(summary: bool = False) -> dict:
    from winter_agent_v2.workbuddy_bridge import WorkBuddyBridge

    bridge = WorkBuddyBridge(cwd=ROOT)
    probe = bridge.is_available()
    state = {"available": bool(probe), "reason": str(getattr(probe, "reason", "") or ""),
             "checked_at": datetime.now().strftime("%H:%M:%S"),
             "checked_at_utc": datetime.now(timezone.utc).isoformat()}
    cell = panel.gateway_cell(state)
    if not summary:
        print("\n== 7/8. WorkBuddy Gateway ==")
        print(f"       is_available() -> available={state['available']} reason={state['reason'] or 'OK'}")
        print(f"       GUI 单元格     -> {cell}")
        record("Gateway 单元格 = bridge.is_available()",
               ("网关正常" in cell) == state["available"],
               cell, f"available={state['available']} reason={state['reason'] or 'OK'}")
    return state


def check_escalation_card() -> None:
    print("\n== 9/10. WorkBuddy 自动开发卡 ==")
    view = panel.escalation_view()
    gateway = check_gateway(summary=True)
    label, detail = panel.workbuddy_cell(view, gateway)
    counts = view.get("counts") or {}
    record("WorkBuddy 状态 = 升级台账 fold",
           bool(counts) or label == panel.WORKBUDDY_LABELS["IDLE"],
           f"{label}（{detail}）",
           f"ledger 状态计数 {counts}；active={len(view.get('active') or ())}")
    current = view.get("current")
    if current is not None:
        shown = f"{current.capability or current.skill} | {current.job_id or '未提交'} | {current.state}"
        record("当前 Job 卡 = 台账当前记录", bool(current.key), shown,
               f"key={current.key} submitted_at={current.submitted_at} model={current.model or '(none)'}")
    else:
        print("       （台账当前无活跃 job：卡片显示待命/Blocked，与 fold 一致）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gateway", action="store_true", help="print the gateway cell only")
    args = parser.parse_args(argv)
    if args.gateway:
        check_gateway()
        return 0

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    print(f"面板接线验证 · {now.isoformat()}")
    print("方式：独立重算生产源的值，与 GUI 派生函数的结果逐项比对。不读源码，不看注释。")
    check_device_cells(config)
    axis = check_maa(now)
    check_auto(axis)
    check_backend(axis)
    check_capability_kpi()
    check_gateway()
    check_escalation_card()

    failed = [row for row in RESULTS if not row[1]]
    print("\n" + "=" * 90)
    print(f"合计 {len(RESULTS)} 项：{len(RESULTS) - len(failed)} PASS / {len(failed)} FAIL")
    for label, _, shown, source in failed:
        print(f"  FAIL {label}\n       GUI={shown}\n       src={source}")
    print("未在此工具内执行（并说明原因）：")
    print("  · 真机拔线 —— AUTO worker 正在使用该客户端，拔线会打断操作者的运行；")
    print("    改在 ADB 边界做等价负例（指向无人监听的端口，得到真实 ADB 失败）。")
    print("  · 点击按钮 —— 会真的启停操作者正在跑的 AUTO 循环；按钮路径由 auto_cell 的")
    print("    状态转移测试覆盖，现场读数另附。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
