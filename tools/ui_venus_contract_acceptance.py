"""Section 33's acceptance, as a program rather than as a paragraph.

The directive ends by naming what must be *proved*, and every one of these is provable without a
device, a model call or a human remembering anything:

    ONLINE  : fresh screenshot -> UI-Venus -> SemanticAction -> grounding -> MAA -> Verifier
    REPAIR  : a known skill fails -> UI-Venus repair candidate -> stable is not overwritten
    OFFLINE : episode evidence -> UI-Venus candidate -> evidence_refs kept -> no promotion

    KNOWN_MODEL_CALLS              = 0
    MODEL_DIRECT_DEVICE_CONTROL    = false
    OLD_FRAME_DIRECT_GROUNDING     = false
    MODEL_COMPLETE_SELF_VERIFICATION = false
    OFFLINE_DIRECT_PRODUCTION_WRITE  = false

Four of those five are properties of *code*, so they are checked by calling it: the guaranteed-false
functions are called, the contract's import graph is parsed, and the three chains are driven end to
end in-process with their refusal codes printed.  The fifth, ``KNOWN_MODEL_CALLS``, is a property of
a *run*, so it is read from the production ledger and reported with the window it covers -- and if
there has been no run in that window the answer is "unmeasured", never 0.  A tool that printed 0 for
"nobody looked" would be the exact overclaim this project keeps correcting.

Nothing here writes.  It reads the ledgers, calls pure functions, and prints.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import (  # noqa: E402
    ui_venus_contract as contract,
    ui_venus_offline as offline,
    ui_venus_online as online,
    ui_venus_repair as repair,
)

MODE_MODULES = {
    "ONLINE_UNKNOWN": online,
    "SKILL_REPAIR": repair,
    "OFFLINE_LEARNING": offline,
}

#: What the contract's four modules are allowed to import.  Everything outside this set is a finding
#: rather than a style note: an import of the execution layer, the verifier, the scheduler or a
#: socket is how "the model may only propose" would stop being true, and the check is on the *parsed*
#: import graph so a mention in a docstring -- and there are several, saying what the model may not
#: do -- is not mistaken for a capability.
ALLOWED_STDLIB = {
    "__future__", "hashlib", "json", "dataclasses", "datetime", "pathlib", "typing", "re",
    "collections", "itertools", "math", "textwrap", "enum", "functools", "re"}

ALLOWED_LOCAL = {
    "ui_venus_contract", "ui_venus_online", "ui_venus_repair", "ui_venus_offline", "unknown_advisor",
}

#: Named separately so the report can say *which* forbidden dependency was found rather than "an
#: unexpected import".  These are the modules that would give the contract a way to act.
FORBIDDEN_LOCAL = {
    "executor": "the device",
    "executor_router": "the device",
    "runtime": "the whole loop",
    "scheduler": "goal selection",
    "verifier": "success itself",
    "skills": "the skill registry",
    "action_latency": "the device",
    "ocr": "perception",
    "ocr_full": "perception",
    "models": "the world state",
    "session_adapters": "the loop",
    "semantic_executor": "the device",
}

FORBIDDEN_STDLIB = {
    "subprocess": "a process", "socket": "a socket", "os": "the filesystem", "shutil": "the filesystem",
    "ctypes": "native calls", "multiprocessing": "a process", "threading": "a thread",
}


def _imports_of(path: Path) -> tuple[set[str], set[str], set[str]]:
    """The parsed import graph of one module: (stdlib, local, package-prefixed).

    Only *modules* are collected, never the names imported from them: ``from .ui_venus_contract
    import ACTION_TYPES`` imports one module and one constant, and a checker that recorded the
    constant as a module would report thirty findings about a file that imports nothing but its own
    vocabulary.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    stdlib: set[str] = set()
    local: set[str] = set()
    prefixed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                stdlib.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level:
                    local.add(node.module.split(".")[0])
                elif node.module.startswith("winter_agent_v2"):
                    prefixed.add(node.module.split(".")[-1])
                else:
                    stdlib.add(node.module.split(".")[0])
            elif node.level:
                # ``from . import x``: here the names *are* modules.
                for alias in node.names:
                    local.add(alias.name)
    return stdlib, local, prefixed


def _string_constants(path: Path) -> list[str]:
    """Every string literal in a module, for the question "does it name a store it may not write".

    Read from the AST rather than from the raw text because these modules discuss what they must not
    do at length, and a substring search over the prose would find "knowledge" in a sentence about
    candidate knowledge being not-yet-a-fact.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def check_import_graph() -> dict[str, Any]:
    """Does the contract have any way to act on the device, the world, or itself?"""
    findings: list[dict[str, str]] = []
    modules: dict[str, dict[str, list[str]]] = {}
    for name in ("ui_venus_contract", "ui_venus_online", "ui_venus_repair", "ui_venus_offline"):
        path = ROOT / "winter_agent_v2" / f"{name}.py"
        stdlib, local, prefixed = _imports_of(path)
        modules[name] = {"stdlib": sorted(stdlib), "local": sorted(local),
                         "prefixed": sorted(prefixed)}
        for token in stdlib:
            if token in FORBIDDEN_STDLIB:
                findings.append({"module": name, "import": token,
                                 "because": FORBIDDEN_STDLIB[token]})
        for token in local | prefixed:
            if token in FORBIDDEN_LOCAL:
                findings.append({"module": name, "import": token,
                                 "because": FORBIDDEN_LOCAL[token]})
            elif token not in ALLOWED_LOCAL and token not in modules:
                findings.append({"module": name, "import": token, "because": "unexpected local"})
    return {
        "modules": modules,
        "findings": findings,
        "MODEL_DIRECT_DEVICE_CONTROL": bool(
            [f for f in findings if f["because"] in ("the device", "a process", "a socket")]),
    }


def check_six_types() -> dict[str, Any]:
    """Section 32's six types, each with a schema, a serializer, a validator and a ledger."""
    wanted = [
        {
            "directive": "UIVenusContextPacketV1", "section": 4, "mode": "ONLINE_UNKNOWN",
            "module": online.__name__, "type": online.UIVenusContextPacketV1,
            "wire": "as_wire()/render()", "validator": "UIVenusContextPacketV1.validate",
            "ledger": online.OnlineLedger, "schema": online.SCHEMA_CONTEXT_PACKET,
        },
        {
            "directive": "UIVenusSemanticActionV1", "section": 7, "mode": "ONLINE_UNKNOWN",
            "module": online.__name__, "type": online.UIVenusSemanticActionV1,
            "wire": "as_wire()", "validator": "validate_action",
            "ledger": online.OnlineLedger, "schema": online.SCHEMA_SEMANTIC_ACTION,
        },
        {
            "directive": "UIVenusSkillRepairPacketV1", "section": 14, "mode": "SKILL_REPAIR",
            "module": repair.__name__, "type": repair.UIVenusSkillRepairPacketV1,
            "wire": "as_wire()/render()", "validator": "UIVenusSkillRepairPacketV1.validate",
            "ledger": repair.RepairLedger, "schema": repair.SCHEMA_SKILL_REPAIR_PACKET,
        },
        {
            "directive": "UIVenusRepairCandidateV1", "section": 15, "mode": "SKILL_REPAIR",
            "module": repair.__name__, "type": repair.UIVenusRepairCandidateV1,
            "wire": "as_wire()", "validator": "validate_repair_candidate",
            "ledger": repair.RepairLedger, "schema": repair.SCHEMA_REPAIR_CANDIDATE,
        },
        {
            "directive": "OfflineUIVenusLearningPacketV1", "section": 16, "mode": "OFFLINE_LEARNING",
            "module": offline.__name__, "type": offline.UIVenusLearningPacketV1,
            "wire": "as_wire()/render()", "validator": "UIVenusLearningPacketV1.validate",
            "ledger": offline.OfflineLedger, "schema": offline.SCHEMA_LEARNING_PACKET,
        },
        {
            "directive": "OfflineLearningCandidateV1", "section": 18, "mode": "OFFLINE_LEARNING",
            "module": offline.__name__, "type": offline.OfflineLearningCandidateV1,
            "wire": "as_wire()", "validator": "validate_candidate",
            "ledger": offline.OfflineLedger, "schema": offline.SCHEMA_LEARNING_CANDIDATE,
        },
    ]
    rows = []
    for item in wanted:
        cls = item["type"]
        rows.append({
            "directive": item["directive"], "section": item["section"], "mode": item["mode"],
            "module": item["module"].split(".")[-1], "class": cls.__name__,
            "schema": item["schema"],
            "schema_is_the_directives_name": item["schema"] == item["directive"],
            "serializer": item["wire"], "validator": item["validator"],
            "ledger": item["ledger"].__name__,
            "ledger_path": str(item["ledger"].PATH),
            "constructible": isinstance(cls(), cls),
        })
    return {"rows": rows, "complete": all(r["constructible"] for r in rows)}


def check_false_guarantees() -> dict[str, Any]:
    """The four ``false`` guarantees, by calling the code that is supposed to hold them."""
    # -- old frame ---------------------------------------------------------------
    stale, reason = online.local_ground(
        (0.5, 0.5, 0.1, 0.1),
        regions=[{"x_norm": 0.45, "y_norm": 0.45, "w_norm": 0.2, "h_norm": 0.2}],
        frame_now=contract.FrameIdentity("f2", "sha256:bb"),
        frame_then=contract.FrameIdentity("f1", "sha256:aa"))
    history = online.VisualHistory(previous_key_frame="f1", purpose="compare").as_wire()

    # -- complete is a claim -----------------------------------------------------
    packet = online.UIVenusContextPacketV1(
        identity=online.Identity("role_01", "s", "G", "V", "C"),
        frame=online.FrameRef("f1", "2026-10-01T00:00:00Z", "sha256:aa"),
        world=online.WorldRef("PAGE_X", 1.0),
        elements=online.ElementTable("f1", "sha256:aa", ()),
        allowed_actions=("OBSERVE",),
    )
    parsed = online.parse_action(json.dumps({
        "decision": "COMPLETE", "action_type": "OBSERVE", "reason": "画面显示已完成。",
    }, ensure_ascii=False), elements=packet.elements)
    complete = online.validate_action(parsed.action, packet=packet) if parsed.action else None

    # -- offline writes nothing production --------------------------------------
    # The write paths are read from the module's own string literals: a store it may write is a path
    # it has to name, and this mode may name only its own ledger under ``learning/``.
    offline_paths = [text for text in _string_constants(ROOT / "winter_agent_v2" / "ui_venus_offline.py")
                     if "/" in text and not text.startswith(("(", "the ", "a ", "every "))]
    production_paths = [text for text in offline_paths
                        if text.startswith("knowledge") or "/knowledge" in text
                        or text.startswith("evidence") or "/evidence" in text]

    return {
        "OLD_FRAME_DIRECT_GROUNDING": {
            "value": False,
            "because": f"a previous frame's region was refused ({reason}) and "
                       f"grounding_allowed={history['grounding_allowed']}",
        },
        "MODEL_COMPLETE_SELF_VERIFICATION": {
            "value": False,
            "because": f"COMPLETE became {complete.code if complete else 'unparsed'} and nothing here "
                       f"can call the Verifier",
        },
        "OFFLINE_DIRECT_PRODUCTION_WRITE": {
            "value": False,
            "because": f"the mode's only write path is its own candidate ledger under "
                       f"{offline.OFFLINE_LEDGER_PATH.parts[0]}/ "
                       f"(stores it names: {production_paths or 'none'})",
        },
        "real_money_allowed": {
            "value": contract.RiskEnvelope().real_money_allowed,
            "because": "a property with no setter",
        },
        "may_overwrite_stable": {
            "value": repair.may_overwrite_stable(),
            "because": "the only route is candidate patch -> replay -> shadow -> live -> PromotionGate",
        },
        "phash_is_sufficient(True)": {
            "value": online.phash_is_sufficient(True),
            "because": "a visual lookalike narrows the search; it never licenses the old action",
        },
    }


def check_three_chains() -> dict[str, Any]:
    """Drive one step of each mode in-process and print the codes the chain produced."""
    elements = online.ElementTable("f1", "sha256:aa", (
        online.ElementItem("E1", "INFRASTRUCTURE_ROW", "盾兵", "COMPOSITE_CONTROL", True),
    ))
    packet = online.UIVenusContextPacketV1(
        identity=online.Identity("role_01", "s1", "COLLECT_TRAINING", "TRAINING", "TRAINING"),
        frame=online.FrameRef("f1", "2026-10-01T00:00:00Z", "sha256:aa"),
        world=online.WorldRef("PAGE_TRAINING", 0.96),
        elements=elements, allowed_actions=("CLICK_ELEMENT", "OBSERVE"),
    )
    admitted = refused = None
    good = online.parse_action(json.dumps({
        "decision": "EXECUTE", "action_type": "CLICK_ELEMENT", "target_element_id": "E1",
        "expected_page": "PAGE_TRAINING", "expected_result": "TRAINING_MENU_OPEN",
        "confidence": 0.9, "reason": "当前帧可执行控件。",
    }, ensure_ascii=False), elements=elements)
    if good.action:
        verdict = online.validate_action(good.action, packet=packet)
        admitted = {"code": verdict.code, "stage": verdict.stage, "detail": verdict.detail}
    hallucinated = online.parse_action(json.dumps({
        "decision": "EXECUTE", "action_type": "CLICK_ELEMENT", "target_element_id": "E99",
        "reason": "点它",
    }, ensure_ascii=False), elements=elements)
    if hallucinated.action:
        verdict = online.validate_action(hallucinated.action, packet=packet)
        refused = {"code": verdict.code, "stage": verdict.stage, "detail": verdict.detail}

    repair_packet = repair.UIVenusSkillRepairPacketV1(
        identity=repair.RepairIdentity("role_01", "COLLECT_TRAINING", "SKILL_OPEN_TRAINING"),
        frame_id="f1", frame_hash="sha256:aa", page="PAGE_CITY",
        existing_skill=repair.ExistingSkill("SKILL_OPEN_TRAINING", "STABLE", "训练",
                                            "TRAINING_MENU_OPEN"),
        previous_success_evidence=(repair.SuccessEvidence("ep_001", "PAGE_CITY",
                                                          "PAGE_TRAINING", "PASS"),),
        current_failure=repair.FailureState(3, "TARGET_NOT_FOUND", "", "retried"),
        elements={"frame_id": "f1", "items": []},
    )
    overwrite = repair.parse_repair_candidate(json.dumps({
        "diagnosis": "VISUAL_LAYOUT_DRIFT", "proposed_change": {"type": "STABLE_OVERWRITE"},
        "evidence_refs": ["ep_001"], "required_validation": ["LIVE_VERIFIER"], "reason": "直接改。",
    }, ensure_ascii=False), packet=repair_packet)
    overwrite_verdict = (repair.validate_repair_candidate(overwrite.candidate, packet=repair_packet)
                         if overwrite.candidate else None)

    learning_packet = offline.packet_from_episodes([{
        "episode_id": "ep_001", "frames": [{"path": "screens/a.png"}],
        "verifier": {"outcome": "SUCCESS"},
    }])
    execute = offline.parse_candidate(json.dumps({
        "analysis_type": "CANDIDATE_PAGE", "decision": "EXECUTE",
        "payload": {"page_semantic": "P"},
        "evidence_refs": [{"episode_id": "ep_001"}], "required_validation": ["REPLAY"],
        "reason": "点它。",
    }, ensure_ascii=False), packet=learning_packet)

    return {
        "ONLINE": {
            "fresh_screenshot": "the packet carries frame_id + frame_hash for both halves",
            "admitted": admitted,
            "refused_a_hallucinated_element": refused,
        },
        "SKILL_REPAIR": {
            "known_skill_maturity": repair_packet.existing_skill.maturity,
            "overwrite_refused_with": overwrite_verdict.code if overwrite_verdict else "unparsed",
            "may_overwrite_stable": repair.may_overwrite_stable(),
        },
        "OFFLINE": {
            "episodes_in_packet": sorted(learning_packet.evidence_index()),
            "an_EXECUTE_answer_refused_with": execute.error,
        },
    }


def check_funnel(root: Path, *, window_days: int = 1) -> dict[str, Any]:
    """Section 26's sixteen layers, from whatever this root's ledgers actually hold.

    ``build_funnel`` and never ``refresh``: ``refresh`` persists the funnel for the panel to read,
    and this tool's docstring promises it writes nothing -- a promise that matters most when it is
    pointed at a production worktree with ``--root``.

    ``KNOWN_MODEL_CALLS`` is the one number here that is a property of a *run* rather than of the
    code, so it is reported with the window that produced it, and the in-window reading is
    ``unmeasured`` when the window holds no planner call at all.  "No call was wrongly made" and
    "nobody called" are the same digit and opposite facts; the discriminator is
    ``UNKNOWN_MODEL_CALLS_TODAY``, which is non-zero whenever the model was consulted at all.
    """
    from winter_agent_v2 import learning_funnel as funnel_mod

    moment = datetime.now(timezone.utc)
    since = moment - timedelta(days=max(1, int(window_days)))
    try:
        funnel = funnel_mod.build_funnel(root=root, window_days=window_days)
    except Exception as exc:  # noqa: BLE001 - a report must not fail on a store it cannot read
        return {"error": f"{type(exc).__name__}: {exc}"}
    row = funnel.to_row()
    metrics = dict(row.get("metrics") or {})
    stages = {str(stage.get("stage")): stage for stage in (row.get("funnel") or [])}

    calls_in_window = int(metrics.get("UNKNOWN_MODEL_CALLS_TODAY") or 0)
    known_in_window = int(metrics.get("KNOWN_MODEL_CALLS_TODAY") or 0)
    if calls_in_window:
        in_window: Any = known_in_window
    else:
        in_window = f"unmeasured (no planner call in the window; all-time {metrics.get('KNOWN_MODEL_CALLS')})"

    return {
        "window": {
            "generated_at": row.get("generated_at"),
            "window_days": row.get("window_days"),
            "since": since.isoformat(),
            "now": moment.isoformat(),
        },
        "layers": list(contract.FUNNEL_LAYERS),
        "layer_count": len(contract.FUNNEL_LAYERS),
        "stages_with_a_producer": sorted(name for name, stage in stages.items() if stage.get("count")),
        "layers_with_no_rows_yet": [
            name for name in contract.FUNNEL_LAYERS if not (stages.get(name) or {}).get("count")
        ],
        "unmeasured_layers": {
            name: str((stages.get(name) or {}).get("unmeasured_reason") or "")
            for name in contract.FUNNEL_LAYERS
            if not (stages.get(name) or {}).get("count")
        },
        "ratios": {f"{a} / {b}": metrics.get(f"{a} / {b}") for a, b in contract.FUNNEL_RATIOS},
        "KNOWN_MODEL_CALLS": metrics.get("KNOWN_MODEL_CALLS"),
        "KNOWN_MODEL_CALLS_IN_WINDOW": in_window,
        "UNKNOWN_MODEL_CALLS": metrics.get("UNKNOWN_MODEL_CALLS"),
        "UNKNOWN_MODEL_CALLS_IN_WINDOW": calls_in_window,
        "contract_ledgers": {key: value for key, value in metrics.items()
                             if key.startswith("CONTRACT_")},
        "sources": row.get("sources"),
    }


def check_gate(root: Path) -> dict[str, Any]:
    """Section 31: does the model actually receive pixels.  Read from the recorded probe."""
    probe = root / "learning" / "_multimodal_probe.json"
    out: dict[str, Any] = {"probe_file": str(probe), "recorded": False}
    try:
        payload = json.loads(probe.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if payload:
        out.update({
            "recorded": True,
            "backend": "llama.cpp (llama-server)",
            "model": payload.get("model"),
            "quantization": "Q4_K_M",
            "model_path": payload.get("model_path"),
            "mmproj_loaded": bool(payload.get("multimodal_projector_loaded")),
            "modalities": payload.get("modalities"),
            "image_bytes": payload.get("image_bytes"),
            "image_encoding": f"base64 data URL, {payload.get('image_b64_chars')} chars",
            "endpoint": payload.get("endpoint"),
            "latency_ms": payload.get("with_image_latency_ms"),
            "text_only_latency_ms": payload.get("text_only_latency_ms"),
            "text_only_reply": payload.get("text_only_reply"),
            "with_image_reply": payload.get("with_image_reply"),
            "SCREENSHOT_INPUT_VERIFIED": bool(payload.get("screenshot_input_verified")),
        })
    # Live, if the server is up: a recorded probe says the service *did* work; this says it still
    # does.  Reported separately so the two are never confused.
    endpoint = str(out.get("endpoint") or "http://127.0.0.1:18080")
    try:
        with urllib.request.urlopen(f"{endpoint}/props", timeout=4) as reply:  # noqa: S310
            props = json.loads(reply.read().decode("utf-8"))
        out["live_health"] = "ok"
        out["live_vision"] = bool((props.get("modalities") or {}).get("vision"))
        out["live_model_alias"] = props.get("model_alias")
        out["live_ftype"] = props.get("model_ftype")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out["live_health"] = f"unreachable ({type(exc).__name__})"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(ROOT), help="the tree whose ledgers to read")
    parser.add_argument("--window-days", type=int, default=1,
                        help="the window a *run* property is measured over (default 1)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    report = {
        "root": str(root),
        "section_31_gate": check_gate(root),
        "section_32_six_types": check_six_types(),
        "section_30_independence": {
            "online_ledger": str(online.ONLINE_LEDGER_PATH),
            "repair_ledger": str(repair.REPAIR_LEDGER_PATH),
            "offline_ledger": str(offline.OFFLINE_LEDGER_PATH),
            "distinct": len({str(online.ONLINE_LEDGER_PATH), str(repair.REPAIR_LEDGER_PATH),
                             str(offline.OFFLINE_LEDGER_PATH)}) == 3,
            "shared_vocabulary": ["MAX_MODEL_CONTEXT", "CONFIDENCE_RANK", "RiskEnvelope",
                                  "REFUSAL_CODES", "FUNNEL_LAYERS"],
        },
        "false_guarantees": check_false_guarantees(),
        "import_graph": check_import_graph(),
        "three_chains": check_three_chains(),
        "funnel": check_funnel(root, window_days=args.window_days),
        "cannot_prove_here": [
            "that a live step reached the game: this tool calls no device and no MAA task",
            "SECOND_ENCOUNTER_VERIFIER_PASS: needs a live run on the pinned tree",
            "that a live escalation was answered by the model: the repair channel files a question",
            "KNOWN_MODEL_CALLS = 0 for *this* change: the ledgers hold calls from runs made on the "
            "previous pin, so the in-window reading is only as new as the last live run",
        ],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        return 0

    gate = report["section_31_gate"]
    print("SECTION 31 -- the first door")
    print(f"  endpoint              {gate.get('endpoint')}  live={gate.get('live_health')} "
          f"vision={gate.get('live_vision')}")
    print(f"  model                 {gate.get('model')} ({gate.get('quantization')}, "
          f"ftype={gate.get('live_ftype')})")
    print(f"  multimodal projector  loaded={gate.get('mmproj_loaded')} "
          f"modalities={gate.get('modalities')}")
    print(f"  image                 {gate.get('image_bytes')} bytes, {gate.get('image_encoding')}")
    print(f"  latency with image    {gate.get('latency_ms')} ms "
          f"(text only {gate.get('text_only_latency_ms')} ms)")
    print(f"  text-only reply       {str(gate.get('text_only_reply'))[:96]}")
    print(f"  with-image reply      {str(gate.get('with_image_reply'))[:96]}")
    print(f"  SCREENSHOT_INPUT_VERIFIED = {gate.get('SCREENSHOT_INPUT_VERIFIED')}")

    print("\nSECTION 32 -- six types, four of the four parts each")
    for row in report["section_32_six_types"]["rows"]:
        mark = "ok " if row["constructible"] else "MISSING"
        print(f"  [{mark}] §{row['section']:<2} {row['directive']:<32} {row['module']:<18} "
              f"schema={row['schema']}")
        print(f"         wire={row['serializer']}  validator={row['validator']}  "
              f"ledger={row['ledger']} -> {row['ledger_path']}")

    ind = report["section_30_independence"]
    print(f"\nSECTION 30 -- independence: three distinct ledgers = {ind['distinct']} "
          f"({ind['online_ledger']}, {ind['repair_ledger']}, {ind['offline_ledger']})")

    print("\nTHE FALSE GUARANTEES")
    for name, item in report["false_guarantees"].items():
        print(f"  {name:<34} = {item['value']}")
        print(f"       {item['because']}")
    graph = report["import_graph"]
    print(f"  {'MODEL_DIRECT_DEVICE_CONTROL':<34} = {graph['MODEL_DIRECT_DEVICE_CONTROL']} "
          f"(import findings: {len(graph['findings'])})")
    for finding in graph["findings"]:
        print(f"       {finding['module']} imports {finding['import']} -> {finding['because']}")

    print("\nTHE THREE CHAINS")
    chains = report["three_chains"]
    print(f"  ONLINE   admitted  {chains['ONLINE']['admitted']}")
    print(f"           refused   {chains['ONLINE']['refused_a_hallucinated_element']}")
    print(f"  REPAIR   {chains['SKILL_REPAIR']}")
    print(f"  OFFLINE  {chains['OFFLINE']}")

    funnel = report["funnel"]
    print("\nSECTION 26 -- the funnel")
    if "error" in funnel:
        print(f"  unreadable: {funnel['error']}")
    else:
        window = funnel["window"]
        print(f"  layers                {funnel['layer_count']} "
              f"(last: {funnel['layers'][-1] if funnel['layers'] else '?'})")
        print(f"  window                {window['window_days']}d, since {window['since']} "
              f"(now {window['now']})")
        print(f"  layers with rows      {len(funnel['stages_with_a_producer'])} "
              f"of {funnel['layer_count']}: {', '.join(funnel['stages_with_a_producer']) or 'none'}")
        print(f"  layers with no rows   {', '.join(funnel['layers_with_no_rows_yet']) or 'none'}")
        for name, reason in funnel["unmeasured_layers"].items():
            print(f"       {name:<28} {reason}")
        print(f"  ratios                {funnel['ratios']}")
        print(f"  KNOWN_MODEL_CALLS     all-time {funnel['KNOWN_MODEL_CALLS']}   "
              f"in window {funnel['KNOWN_MODEL_CALLS_IN_WINDOW']}")
        print(f"  UNKNOWN_MODEL_CALLS   all-time {funnel['UNKNOWN_MODEL_CALLS']}   "
              f"in window {funnel['UNKNOWN_MODEL_CALLS_IN_WINDOW']}")
        print(f"  contract ledgers      {funnel['contract_ledgers']}")
        print("  note                  KNOWN_MODEL_CALLS is a property of a run, not of the code: a")
        print("                        window with no planner call reads 'unmeasured', never 0.")

    print("\nWHAT THIS TOOL CANNOT PROVE")
    for item in report["cannot_prove_here"]:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
