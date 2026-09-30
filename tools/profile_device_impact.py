"""Measure what the local GUI model costs the *device* -- the field the directive calls
``MUMU_IMPACT`` and ``MAA_CAPTURE_IMPACT``.

Why this tool exists
--------------------
The 32K directive's priority order is explicit and puts the model last::

    长期稳定 > MuMu/MAA 正常 > 32K 可用 > 推理速度 > 最大 GPU offload

and its VRAM section names the exact conditions under which offload must be *given up*: "如果
VRAM 接近占满 / MuMu 掉帧 / MAA capture 延迟 / CUDA OOM / Windows VRAM swapping → 减少 GPU
offload 层数，把部分模型放到系统内存".  Every one of those conditions is a statement about the
device, not about the model, and none of them is visible from VRAM and latency numbers alone.
So the deciding measurement is: *does the screen-capture path the runtime depends on stay
healthy while the model is resident and busy?*

``MAA_EmulatorExtras`` screencap is the right canary because it runs through the emulator's own
renderer: if MuMu is starved of GPU or is swapping, the capture time rises or the capture fails,
and that is the same call ``MaaExecutorAdapter.capture()`` makes for every evidence frame.  The
recorded production baseline is 12.1 ms (``config/v2.json`` -> ``executor.maa.observed``, measured
by ``tools/probe_maa_api2.py``); ADB ``exec-out screencap`` is the 246 ms fallback.

Three phases, one variable
--------------------------
For each candidate profile the tool measures the same capture loop three times so that the only
thing that changes is what the model is doing:

* ``no_server``  -- the model is stopped entirely.  This is the device's own floor.
* ``server_idle`` -- the model is resident and loaded, but no request is in flight.  The VRAM is
  already taken, so this isolates *occupancy* pressure.
* ``server_load`` -- real packets are answered in a background thread while captures continue.
  This isolates *compute* pressure, which is what actually competes with the emulator.

The verdict is deliberately asymmetric and conservative.  ``no_server`` is the reference; a
profile fails if the p95 capture regresses past ``--tolerance`` (default 1.5x), if any capture
returns ``None``, if a capture exceeds ``--hard-ms``, or if the launch log shows a CUDA
allocation failure.  A profile that fails is not "fast enough to keep"; per the directive it is
a profile whose offload must come down.

Only MAA capture feeds that verdict.  The ADB round-trip is collected as corroboration that the
emulator is alive and answering, but it is excluded from the decision because it times a
process spawn rather than the renderer, and it was measured swinging 24.5 -> 163.3 ms with no
load change -- noise far larger than any effect it could be asked to detect.

Usage::

    python tools/profile_device_impact.py --profiles 24:f16,16:q8_0
    python tools/profile_device_impact.py --profiles 24:f16 --load-seconds 90 --captures 40
"""

from __future__ import annotations

import argparse
import importlib
import json
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from winter_agent_v2 import local_gui_model, ui_planner  # noqa: E402

launcher = importlib.import_module("launch_gui_model_server")
benchmark = importlib.import_module("benchmark_gui_unknown")
profiler = importlib.import_module("profile_gui_model_context")

OUT_PATH = ROOT / "dataset" / "truth_audit" / "gui_model_context_profile" / "device_impact.json"

#: Production's own recorded screencap baseline (config/v2.json -> executor.maa.observed).
BASELINE_MAA_MS = 12.1
BASELINE_ADB_MS = 246.2


def _stats(samples: list[float]) -> dict:
    if not samples:
        return {"n": 0, "p50": None, "p95": None, "max": None, "mean": None}
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 2),
        "max": round(ordered[-1], 2),
        "mean": round(statistics.fmean(ordered), 2),
        "min": round(ordered[0], 2),
    }


def _make_adapter(config: dict):
    """The production MAA adapter, built exactly as the router builds it."""
    from winter_agent_v2.executor_router import build_maa_adapter

    return build_maa_adapter(config, production=True, project_root=ROOT)


def _capture_phase(adapter, count: int, *, duration_s: float = 0.0) -> dict:
    """Time MAA screencaps, the call every evidence frame depends on.

    A capture is only ~12 ms, so ``count`` alone would finish a 30-sample phase in under half a
    second -- too short a window to contain a single model call, and therefore unable to answer
    *"does inference starve the emulator"*.  When ``duration_s`` is given the loop keeps
    sampling for at least that long and returns however many samples fit, which is what makes
    the load phase overlap the calls it is supposed to be competing with.
    """
    samples: list[float] = []
    failures = 0
    deadline = time.monotonic() + duration_s if duration_s else None
    taken = 0
    while taken < count or (deadline is not None and time.monotonic() < deadline):
        started = time.perf_counter()
        frame = adapter.capture()
        elapsed = (time.perf_counter() - started) * 1000.0
        taken += 1
        if frame is None:
            failures += 1
        else:
            samples.append(elapsed)
    row = _stats(samples)
    row["failures"] = failures
    return row


def _adb_roundtrip(adb_path: str, serial: str, count: int) -> dict:
    """Emulator liveness independent of the renderer: an ADB round-trip per sample."""
    samples: list[float] = []
    for _ in range(count):
        started = time.perf_counter()
        try:
            subprocess.run([adb_path, "-s", serial, "shell", "echo", "ok"],
                           capture_output=True, timeout=20, check=False)
            samples.append((time.perf_counter() - started) * 1000.0)
        except (OSError, subprocess.SubprocessError):
            continue
    return _stats(samples)


def _load_thread(config: dict, profile, stop: threading.Event) -> tuple[threading.Thread, dict]:
    """Answer real packets in the background for as long as the capture phase runs.

    The packets are the same real ones the sweep uses, so the work in flight is production
    work; ``purpose`` is tagged so these calls can be excluded from the runtime's metrics.
    """
    client_config = dict(config)
    section = dict(client_config.get("local_planner") or {})
    section["context"] = profile.context
    client_config["local_planner"] = section
    client = local_gui_model.from_config(client_config, root=ROOT)
    state = {"calls": 0, "failures": 0, "latencies": []}
    cases = profiler._cases(6)

    def run() -> None:
        index = 0
        while not stop.is_set() and cases:
            request = cases[index % len(cases)]
            index += 1
            elements = ui_planner.elements_from_request(request)
            packet = profiler._packet_for(request, history=[], elements=elements)
            call = client.ask_json(
                system=ui_planner.SYSTEM_PROMPT, user=ui_planner.render_packet(packet),
                purpose="device_impact_load", element_count=len(elements),
                image_path=getattr(request, "frame_path", None), timeout_s=180.0)
            state["calls"] += 1
            if call.ok:
                state["latencies"].append(round(call.latency_ms, 1))
            else:
                state["failures"] += 1
            if stop.is_set():
                break

    if client is None:
        return threading.Thread(target=lambda: None), state
    thread = threading.Thread(target=run, daemon=True)
    return thread, state


def measure(config: dict, profiles: list[launcher.ServerProfile], *, captures: int,
            adb_samples: int, load_seconds: float, tolerance: float,
            hard_ms: float) -> dict:
    adb_path = str((config.get("device") or {}).get("adb_path") or "")
    serial = str((config.get("device") or {}).get("serial") or "")
    # All three phases sample for the same wall-clock window, so their p95s are comparable:
    # a 0.4 s burst and a 60 s soak do not estimate the same tail.
    probe_seconds = max(15.0, float(load_seconds))
    report: dict = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tolerance": tolerance,
        "hard_ms": hard_ms,
        "probe_seconds": probe_seconds,
        "baseline_recorded": {"maa_screencap_ms": BASELINE_MAA_MS, "adb_screencap_ms": BASELINE_ADB_MS},
        "profiles": [],
    }

    # ---- phase 0: the device with no model at all.  Every comparison is against this.
    launcher.stop()
    time.sleep(8.0)
    adapter = _make_adapter(config)
    ready = adapter is not None and adapter.ensure_ready()[0] if adapter else False
    report["maa_available"] = bool(ready)
    report["maa_backend"] = getattr(adapter, "capture_backend", "") if adapter else ""
    if not ready:
        report["error"] = f"MAA unavailable: {getattr(adapter, 'unavailable_reason', 'unknown')}"
        return report
    reference = _capture_phase(adapter, captures, duration_s=probe_seconds)
    reference_adb = _adb_roundtrip(adb_path, serial, adb_samples)
    report["no_server"] = {"maa_capture": reference, "adb_roundtrip": reference_adb,
                           "vram": profiler._vram(), "ram": profiler._ram()}
    print(f"[no_server]   maa p50={reference['p50']} p95={reference['p95']} "
          f"fail={reference['failures']}  adb p50={reference_adb['p50']}")

    for profile in profiles:
        row: dict = {"profile": profile.to_row()}
        launcher.stop()
        time.sleep(8.0)
        row["vram_before"] = profiler._vram()
        code = launcher.start(profile)
        row["launch_exit"] = code
        row["cuda_oom_at_launch"] = profiler._has_cuda_oom()
        if code != 0:
            row["verdict"] = "LAUNCH_FAILED"
            report["profiles"].append(row)
            print(f"[ngl {profile.gpu_layers}/{profile.kv_type}] LAUNCH FAILED ({code})")
            continue
        time.sleep(5.0)
        row["vram_idle"] = profiler._vram()
        row["ram_idle"] = profiler._ram()
        row["server_rss_idle_mib"] = profiler._server_rss_mib()

        # ---- phase 1: resident but idle.  Isolates the cost of occupancy.
        idle = _capture_phase(adapter, captures, duration_s=probe_seconds)
        idle_adb = _adb_roundtrip(adb_path, serial, adb_samples)
        row["server_idle"] = {"maa_capture": idle, "adb_roundtrip": idle_adb,
                              "vram": profiler._vram(), "ram": profiler._ram()}

        # ---- phase 2: busy.  Isolates the cost of compute, which is what starves the emulator.
        stop = threading.Event()
        thread, state = _load_thread(config, profile, stop)
        thread.start()
        time.sleep(3.0)
        load = _capture_phase(adapter, captures, duration_s=load_seconds)
        load_adb = _adb_roundtrip(adb_path, serial, adb_samples)
        peak_vram = profiler._vram()
        peak_ram = profiler._ram()
        stop.set()
        thread.join(timeout=240.0)
        row["server_load"] = {
            "maa_capture": load, "adb_roundtrip": load_adb,
            "vram": peak_vram, "ram": peak_ram,
            "model_calls": state["calls"], "model_call_failures": state["failures"],
            "model_latency_ms": _stats(state["latencies"]),
        }
        row["server_rss_peak_mib"] = profiler._server_rss_mib()
        row["cuda_oom"] = profiler._has_cuda_oom()

        # ---- the verdict, stated in the directive's own terms.
        #
        # Only MAA capture decides.  The ADB round-trip is recorded but deliberately excluded
        # from the verdict: it times a *process spawn* plus a shell echo, so it is bounded by
        # how fast Windows can start adb.exe, not by the emulator.  Measured here it swung
        # 24.5 -> 163.3 ms without any load change, i.e. a 3.7x "regression" that was pure
        # scheduling noise -- and a verdict built on it would have condemned a healthy profile.
        # It stays in the report as evidence that the emulator was alive and answering.
        reasons: list[str] = []
        worst = load if load["n"] else idle
        if load["failures"] or idle["failures"]:
            reasons.append(f"MAA_CAPTURE_FAILED idle={idle['failures']} load={load['failures']}")
        if reference["p95"] and worst["p95"]:
            ratio = worst["p95"] / reference["p95"]
            row["capture_p95_ratio_vs_no_server"] = round(ratio, 3)
            if ratio > tolerance:
                reasons.append(f"MAA_P95_REGRESSION x{ratio:.2f}")
        if worst["max"] and worst["max"] > hard_ms:
            reasons.append(f"MAA_CAPTURE_STALL {worst['max']:.0f}ms>{hard_ms:.0f}ms")
        if row["cuda_oom"] or row["cuda_oom_at_launch"]:
            reasons.append("CUDA_OOM")
        if reference_adb["p50"] and idle_adb["p50"]:
            row["adb_roundtrip_ratio_idle"] = round(idle_adb["p50"] / reference_adb["p50"], 3)
        row["reasons"] = reasons
        row["verdict"] = "OK" if not reasons else "DEVICE_IMPACT"
        # A profile is usable for production only if it leaves headroom on a 8188 MiB card too:
        # the directive's first priority is long-run stability, so free VRAM is reported, not judged.
        row["vram_free_mib"] = peak_vram.get("free_mib")
        report["profiles"].append(row)
        print(f"[ngl {profile.gpu_layers}/{profile.kv_type}] idle p50={idle['p50']} "
              f"load p50={load['p50']} p95={load['p95']} fail={load['failures']} "
              f"calls={state['calls']} free={peak_vram.get('free_mib')} -> {row['verdict']}")

    launcher.stop()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default="24:f16,16:q8_0",
                        help="comma-separated ngl:kv pairs, e.g. 24:f16,20:q8_0,16:q8_0")
    parser.add_argument("--captures", type=int, default=30, help="MAA screencaps per phase")
    parser.add_argument("--adb-samples", type=int, default=6)
    parser.add_argument("--load-seconds", type=float, default=60.0)
    parser.add_argument("--tolerance", type=float, default=1.5,
                        help="allowed p95 capture regression against the no-model phase")
    parser.add_argument("--hard-ms", type=float, default=250.0,
                        help="a single capture slower than this is a stall, not a sample")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    profiles = []
    for token in args.profiles.split(","):
        token = token.strip()
        if not token:
            continue
        layers, _, kv = token.partition(":")
        profiles.append(launcher.ServerProfile(gpu_layers=int(layers), kv_type=kv or launcher.KV_TYPE))
    if not profiles:
        print("no profiles given")
        return 2

    config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    report = measure(config, profiles, captures=args.captures, adb_samples=args.adb_samples,
                     load_seconds=args.load_seconds, tolerance=args.tolerance,
                     hard_ms=args.hard_ms)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
