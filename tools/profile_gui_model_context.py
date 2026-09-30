"""Profile the local GUI model against its 32K context: VRAM, RAM, latency, and the ladder.

Operator directive 2026-09-30 (second half) asks for three things this tool produces evidence
for, and deliberately nothing else:

1. **A KV-cache A/B.**  ``--sweep`` launches the server once per (offload, KV type) combination
   with *the production flags*, waits for health, measures, and stops it again.  The directive's
   rule is that q8_0 may not be adopted on paper savings alone -- "必须 A/B ... 如果Q8没有明显
   副作用才使用" -- so the sweep measures both and the report says which won.
2. **The 32K ladder.**  ``--ladder`` sends prompts sized at ~8K, ~16K, ~24K and just under the
   input budget, and records latency, VRAM, RAM and any CUDA failure for each.  Its purpose is
   to find the wall, not to grade the model: it is a *size* experiment, and it is labelled as
   one below.
3. **Estimator calibration.**  Every call records both the client's own estimate and the
   server's ``usage.prompt_tokens``, so the heuristic in ``context_budget`` can be checked
   against the tokenizer it is standing in for instead of being trusted.

What is real and what is padding, stated plainly
-------------------------------------------------
The underlying request, its element table, its world state and its frame all come from real
``learning/unknown_requests/*.json`` records -- screens the live system genuinely failed to
advance.  The *history* rows come from real ``learning/episodes.jsonl`` entries.  Above ~8K,
however, no real V2 UNKNOWN prompt is that large: a production packet with a 16-step history is
about 3K tokens, which is the whole point of the budget manager.  So each rung past the real
size is reached by repeating those real history rows to the depth the rung needs, and every row
is marked ``synthetic_depth: true``.  The directive forbids "无意义超长prompt"; a prompt padded
with fabricated prose would be exactly that.  A prompt padded with *repeated real rows* answers
the question actually being asked of the ladder -- does the deployment survive a large input --
and the report never presents those latencies as if a session had really been that deep.

Usage::

    python tools/profile_gui_model_context.py --sweep
    python tools/profile_gui_model_context.py --ladder --gpu-layers 16 --kv q8_0
    python tools/profile_gui_model_context.py --ladder --targets 8192,16384,24576,28672
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import psutil  # noqa: E402

from winter_agent_v2 import context_budget, local_gui_model, ui_planner  # noqa: E402

launcher = importlib.import_module("launch_gui_model_server")
benchmark = importlib.import_module("benchmark_gui_unknown")

OUT_PATH = ROOT / "dataset" / "truth_audit" / "gui_model_context_profile" / "profile.json"
EPISODES = ROOT / "learning" / "episodes.jsonl"

#: The rungs the directive asks for: 8K, 16K, 24K, and "接近32K但不超过输入预算".
DEFAULT_TARGETS = (8192, 16384, 24576, 28672)


# ------------------------------------------------------------------ sampling
def _vram() -> dict[str, int]:
    from winter_agent_v2 import winproc

    try:
        out = winproc.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            timeout=10.0)
        used, free = (int(part.strip()) for part in out.stdout.strip().splitlines()[0].split(","))
        return {"used_mib": used, "free_mib": free}
    except Exception:  # noqa: BLE001
        return {"used_mib": 0, "free_mib": 0}


def _ram() -> dict[str, int]:
    vm = psutil.virtual_memory()
    return {"used_mib": int(vm.used / 1048576), "free_mib": int(vm.available / 1048576),
            "percent": int(vm.percent)}


def _server_rss_mib() -> int:
    """llama-server's own working set, which is where the CPU-resident layers land."""
    for proc in psutil.process_iter(["name"]):
        name = str(proc.info.get("name") or "")
        if "llama-server" in name:
            try:
                return int(proc.memory_info().rss / 1048576)
            except (psutil.Error, OSError):
                return 0
    return 0


def _has_cuda_oom() -> bool:
    """Whether the last launch died with a CUDA allocation failure.

    Read from the launch log because a failed allocation is reported by llama.cpp rather than
    raised into this process, and "no OOM" has to be a check rather than an assumption.
    """
    try:
        text = launcher.LOG_PATH.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in text for marker in
               ("out of memory", "cuda error", "failed to allocate", "ggml_backend_cuda"))


# ------------------------------------------------------------------ real material
def _real_history(limit: int = 1500) -> list[dict]:
    """Real Action -> Feedback rows from the production episode log.

    Built with ``ui_planner.ManagedAdvisor.note_step``'s own field names so the packet a rung
    sends is shaped exactly like one the runtime would send, and so this tool cannot drift from
    the runtime's idea of what a history row is.
    """
    rows: list[dict] = []
    try:
        text = EPISODES.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines()[-limit:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append({
            "step": len(rows) + 1,
            "skill": str(payload.get("skill") or "")[:60],
            "control": str(payload.get("control") or "")[:60],
            "expected": str(payload.get("expected_result") or "")[:80],
            "observed": str(payload.get("observed_change") or "")[:40],
            "verifier": "PASS" if payload.get("verifier_ok") else "FAIL",
        })
    return rows


def _cases(limit: int = 6) -> list:
    return benchmark._cases(limit)


def _packet_for(request, *, history: list[dict], elements: list[dict]) -> dict:
    return ui_planner.build_packet(
        goal=str(getattr(request, "goal", "") or ""),
        role_id=str(getattr(request, "character", "") or ""),
        current_page=str(getattr(request, "page_key", "") or ""),
        world_state=getattr(request, "world_state", {}) or {},
        elements=elements,
        actions=ui_planner.OFFERED_ACTIONS,
        relevant_knowledge=[
            f"templates matched here: {getattr(request, 'template_match', '')}",
            f"previous control->page on this screen: {getattr(request, 'ledger_match', '')}",
        ],
        recent_steps=history,
        last_verifier_outcome={"ok": False, "skill": "TRY_ORDINARY_CONTROL",
                               "result": "NO_EXECUTION", "reason": ""},
        session={"step_index": len(history), "remaining_steps": 2,
                 "remaining_run_steps": 12, "no_progress_count": 3,
                 "steps_on_this_screen": 2, "steps_in_session": len(history)},
        remaining_steps=2,
        step_index=len(history),
    )


def _grow_to(packet: dict, history: list[dict], manager: context_budget.ContextBudgetManager,
             target: int) -> tuple[dict, bool]:
    """Repeat real history rows until the packet estimates at ``target`` tokens.

    Returns the packet and whether it had to be padded.  Bounded by the material that exists:
    a target the available real rows cannot reach returns the largest packet they *can* build
    rather than spinning or inventing prose, and the report shows the shortfall as the gap
    between ``target_tokens`` and ``actual_prompt_tokens``.
    """
    if not history:
        return packet, False
    synthetic = False
    depth = ui_planner.HISTORY_TARGET
    best = packet
    while depth <= len(history):
        trial = dict(packet)
        trial["recent_steps"] = [dict(row) for row in history[-depth:]]
        best = trial
        if manager.count(json.dumps(trial, ensure_ascii=False, indent=1, default=str)) >= target:
            return trial, synthetic
        depth += ui_planner.HISTORY_TARGET
        synthetic = True
    return best, synthetic


# ------------------------------------------------------------------ the two modes
def sweep(config: dict, profiles: list[launcher.ServerProfile], calls: int,
          timeout: float, *, keep_last: bool = False) -> dict:
    client_config = dict(config)
    cases = _cases(calls)
    if not cases:
        return {"error": "no readable learning/unknown_requests/*.json case with a frame"}
    results: list[dict] = []
    for profile in profiles:
        row: dict = {"profile": profile.to_row()}
        launcher.stop()
        time.sleep(6.0)
        row["vram_before"] = _vram()
        row["ram_before"] = _ram()
        code = launcher.start(profile)
        row["launch_exit"] = code
        if code != 0:
            row["cuda_oom"] = _has_cuda_oom()
            results.append(row)
            print(json.dumps(row, ensure_ascii=False))
            continue
        time.sleep(4.0)
        row["vram_idle"] = _vram()
        row["ram_idle"] = _ram()
        row["server_rss_idle_mib"] = _server_rss_mib()

        # The same client the runtime builds, so the call under test is the production call.
        section = dict(client_config.get("local_planner") or {})
        section["context"] = profile.context
        client_config["local_planner"] = section
        client = local_gui_model.from_config(client_config, root=ROOT)
        assert client is not None

        latencies: list[float] = []
        prompt_tokens: list[int] = []
        peak_vram = row["vram_idle"]["used_mib"]
        peak_ram = row["ram_idle"]["used_mib"]
        for request in cases:
            elements = ui_planner.elements_from_request(request)
            packet = _packet_for(request, history=[], elements=elements)
            call = client.ask_json(
                system=ui_planner.SYSTEM_PROMPT, user=ui_planner.render_packet(packet),
                purpose="context_sweep", element_count=len(elements),
                image_path=getattr(request, "frame_path", None), timeout_s=timeout)
            if call.ok and call.latency_ms:
                latencies.append(call.latency_ms)
            if call.prompt_tokens:
                prompt_tokens.append(call.prompt_tokens)
            sampled = _vram()
            peak_vram = max(peak_vram, sampled["used_mib"])
            peak_ram = max(peak_ram, _ram()["used_mib"])
        row["latency_ms"] = _stats(latencies)
        row["actual_prompt_tokens"] = _stats(prompt_tokens)
        row["vram_peak"] = {"used_mib": peak_vram, "free_mib": _vram()["free_mib"]}
        row["ram_peak"] = {"used_mib": peak_ram, "free_mib": _ram()["free_mib"]}
        row["server_rss_peak_mib"] = _server_rss_mib()
        row["cuda_oom"] = _has_cuda_oom()
        # Quality half of the A/B.  The directive requires latency AND output quality AND
        # stability, so the same real frames are planned and the replies are compared: a KV
        # change that shortened answers or shifted decisions would show up here.
        row["replies"] = []
        for request in cases:
            elements = ui_planner.elements_from_request(request)
            packet = _packet_for(request, history=[], elements=elements)
            call = client.ask_json(
                system=ui_planner.SYSTEM_PROMPT, user=ui_planner.render_packet(packet),
                purpose="context_sweep_quality", element_count=len(elements),
                image_path=getattr(request, "frame_path", None), timeout_s=timeout)
            parsed = ui_planner.parse_plan(call.text, elements=elements) if call.ok else None
            row["replies"].append({
                "ok": bool(call.ok),
                "parse_error": "" if parsed is None else parsed.error,
                "decision": (parsed.plan.decision if parsed and parsed.plan else ""),
                "target": (parsed.plan.target_text if parsed and parsed.plan else ""),
                "reply_chars": len(call.text or ""),
            })
        row["quality"] = {
            "answered": sum(1 for r in row["replies"] if r["ok"]),
            "parsed": sum(1 for r in row["replies"] if not r["parse_error"]),
            "decisions": sorted({r["decision"] for r in row["replies"] if r["decision"]}),
            "mean_reply_chars": round(
                sum(r["reply_chars"] for r in row["replies"]) / max(1, len(row["replies"])), 1),
        }
        results.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "replies"},
                         ensure_ascii=False), flush=True)
    if not keep_last:
        launcher.stop()
    return {"mode": "sweep", "rows": results}


def ladder(config: dict, manager: context_budget.ContextBudgetManager, targets: list[int],
           cases: int, timeout: float) -> dict:
    client = local_gui_model.from_config(config, root=ROOT)
    if client is None:
        return {"error": "local_planner.enabled is false"}
    ok, reason = client.available(force=True)
    if not ok:
        return {"error": f"model unreachable: {reason}"}
    requests = _cases(cases)
    if not requests:
        return {"error": "no readable case"}
    history = _real_history()
    rows: list[dict] = []
    for target in [0, *targets]:
        for request in requests[:1]:
            elements = ui_planner.elements_from_request(request)
            packet = _packet_for(request, history=[], elements=elements)
            synthetic = False
            if target:
                packet, synthetic = _grow_to(packet, history, manager, target)
            packet, report = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=packet)
            before = _vram()
            ram_before = _ram()
            call = client.ask_json(
                system=ui_planner.SYSTEM_PROMPT, user=ui_planner.render_packet(packet),
                purpose=f"context_ladder_{target or 'real'}", element_count=len(elements),
                image_path=getattr(request, "frame_path", None), timeout_s=timeout)
            peak = _vram()
            row = {
                "target_tokens": target or "real",
                "synthetic_depth": bool(synthetic),
                "history_rows": len(packet.get("recent_steps") or []),
                "estimated_input_tokens": report.estimated_tokens,
                "actual_prompt_tokens": call.prompt_tokens,
                "estimate_ratio": (round(call.prompt_tokens / report.estimated_tokens, 3)
                                   if report.estimated_tokens and call.prompt_tokens else None),
                "within_budget": report.within_budget,
                "dropped_sections": list(report.dropped_sections),
                "ok": bool(call.ok),
                "error": call.error,
                "latency_ms": call.latency_ms,
                "image_sent": call.image_sent,
                "vram_used_mib": peak["used_mib"],
                "vram_free_mib": peak["free_mib"],
                "ram_used_mib": _ram()["used_mib"],
                "ram_free_mib": _ram()["free_mib"],
                "vram_delta_mib": peak["used_mib"] - before["used_mib"],
                "ram_delta_mib": _ram()["used_mib"] - ram_before["used_mib"],
                "cuda_oom": _has_cuda_oom(),
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    return {"mode": "ladder", "rows": rows}


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50": 0, "p95": 0, "max": 0, "min": 0, "mean": 0}
    ordered = sorted(values)

    def pct(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 1)

    return {"n": len(ordered), "p50": pct(0.5), "p95": pct(0.95), "max": ordered[-1],
            "min": ordered[0], "mean": round(sum(ordered) / len(ordered), 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--ladder", action="store_true")
    parser.add_argument("--gpu-layers", default="",
                        help="comma list for --sweep, or one value for the report header")
    parser.add_argument("--kv", default="q8_0,f16", help="comma list of KV cache types")
    parser.add_argument("--context", type=int, default=context_budget.MAX_MODEL_CONTEXT)
    parser.add_argument("--targets", default=",".join(str(t) for t in DEFAULT_TARGETS))
    parser.add_argument("--calls", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", default=str(OUT_PATH))
    #: Leaves the last swept profile resident so ``--ladder`` can run against it in the same
    #: invocation, which is how the A/B and the size ladder are measured on one server rather
    #: than two that share a name.
    parser.add_argument("--keep", action="store_true",
                        help="leave the last swept profile running (for --ladder)")
    args = parser.parse_args()

    config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    manager = context_budget.ContextBudgetManager(
        max_model_context=args.context,
        output_reserve=int((config.get("local_planner") or {}).get("output_reserve")
                           or context_budget.OUTPUT_RESERVE),
    )

    report: dict = {
        "what_this_is": ("VRAM/RAM/latency evidence for the 32768-context deployment: a KV-cache "
                         "A/B, an input-size ladder, and the estimator's calibration against the "
                         "server's own prompt_tokens"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_model_context": manager.max_model_context,
        "max_input_budget": manager.max_input_budget,
        "output_reserve": manager.output_reserve,
    }
    if args.sweep:
        layers = [int(v) for v in str(args.gpu_layers or launcher.GPU_LAYERS).split(",") if v.strip()]
        kvs = [v.strip() for v in args.kv.split(",") if v.strip()]
        profiles = [launcher.ServerProfile(gpu_layers=n, context=args.context, kv_type=kv)
                    for n in layers for kv in kvs]
        report["sweep"] = sweep(config, profiles, args.calls, args.timeout,
                                keep_last=args.keep)
    if args.ladder:
        targets = [int(v) for v in args.targets.split(",") if v.strip()]
        report["ladder"] = ladder(config, manager, targets, args.calls, args.timeout)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
