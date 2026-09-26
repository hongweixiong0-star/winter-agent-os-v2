"""Harvest recognition nodes for every control the client is currently showing.

Run:
    python tools/autogen_harvest.py --visit home:621,1240 --visit heroes:151,1240 [--apply]

Two phases, because wiring an unvalidated node is worse than not wiring one:

**Phase 1 — observe.** Takes the development lease, then for each ``--visit``
navigates (optional tap) and captures one frame. Nothing is tapped that the
operator did not name on the command line.

**Phase 2 — derive, validate, and only then wire.** For every semantic the
dictionary declares and the registry can execute, the label is looked up in each
frame's OCR tokens. A hit becomes a candidate node; the candidate is then matched
against every frame captured in this pass — its own page as positives, the other
pages as negatives. Only a node that hits all of its positives and none of the
negatives is written to ``backend_routing.json``. Everything else is reported and
left on disk, because ``maa_resolver`` does *not* fall back to ADB when a node
misses: a bad node does not merely fail to help, it actively breaks a control
that V2 recognition was already finding.

Ownership matters as much as validity. ``RoutingTable`` is keyed by skill id and
the router looks up ``recognition_node(skill_id, semantic)``, so a node filed
under the wrong skill is unreachable. Every semantic is therefore filed under
*each* skill whose ``Action`` targets it, read from the live registry.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice  # noqa: E402
from winter_agent_v2.device_lease import DeviceLease  # noqa: E402
from winter_agent_v2.executor_router import RoutingTable  # noqa: E402
from winter_agent_v2.pipeline_autogen import (  # noqa: E402
    GenerationRequest,
    PipelineAutoGen,
    normalize_box,
)
from winter_agent_v2.skills import v2_registry  # noqa: E402

ADB = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe")
SERIAL = "127.0.0.1:7555"
SEMANTIC_DICT = ROOT / "knowledge" / "ui" / "semantic_dictionary.json"
FRAMES = ROOT / "dataset" / "raw" / "autogen"


def declared_labels() -> list[tuple[str, str, list[str]]]:
    payload = json.loads(SEMANTIC_DICT.read_text(encoding="utf-8"))
    out: list[tuple[str, str, list[str]]] = []
    seen: set[tuple[str, str]] = set()
    for record in payload.get("records") or ():
        if not (isinstance(record, dict) and record.get("id")):
            continue
        # A page/popup title can carry the same text as an action, but clicking
        # its OCR box is not an action. Only explicit interactive UI records may
        # become click nodes.
        if str(record.get("type", "")).upper() not in {
            "BUTTON", "TAB", "ROW", "ROW_CONTROL", "INTERACTIVE_CONTROL",
            "NAVIGATION", "CONTROL", "CARD",
        }:
            continue
        semantic = str(record["id"])
        # The ``cn`` field is a display name ("领取挂机收益") that no OCR token ever
        # contains -- the client draws the words separately, which is exactly why the
        # dictionary also carries an ``ocr`` word list. Locating by the compound name
        # is why the first pass scanned 45 executable semantics and hit none. Each
        # declared word is its own chance to find the control; the compound name is
        # the fallback for records that never split their words.
        words = [str(w) for w in (record.get("ocr") or []) if str(w).strip()]
        cn = str(record.get("cn") or "")
        if cn and cn not in words:
            words.append(cn)
        pages = [str(p).upper() for p in (record.get("pages") or [])]
        for word in words:
            key = (semantic, word)
            if key not in seen:
                seen.add(key)
                out.append((semantic, word, pages))
    return out


def owning_skills() -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for skill in v2_registry().all():
        target = str(skill.action.target or "")
        if target:
            owners.setdefault(target, []).append(skill.id)
    return owners


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--visit", action="append", default=[],
                    help="page_name[:x,y] — navigate (optional) then capture")
    ap.add_argument("--frame", action="append", default=[],
                    help="page_name:path — use an archived real frame without taking the device lease")
    ap.add_argument("--back-before", type=int, default=2, metavar="N",
                    help="press BACK this many times before each visit, so a previous "
                         "visit's full-screen page cannot swallow the next tap")
    ap.add_argument("--expand", type=int, default=22)
    ap.add_argument("--want", default="template", choices=("auto", "ocr", "template"))
    ap.add_argument("--min-score", type=float, default=0.90,
                    help="minimum OCR confidence for a label to count as present")
    ap.add_argument("--apply", action="store_true",
                    help="write nodes that pass validation (default: report only)")
    args = ap.parse_args()
    if not args.visit and not args.frame:
        args.visit = ["current"]
    if args.visit and args.frame:
        ap.error("--visit and --frame cannot be combined")

    lease = None
    device = None
    if args.visit:
        lease = DeviceLease()
        record, reason = lease.request(
            capability_id="PIPELINE_AUTOGEN", trace_id="WORKBUDDY_AUTOGEN_HARVEST",
            reason=f"harvest+validate recognition nodes across {len(args.visit)} page(s)",
        )
        if record is None:
            print(f"[BLOCKED] lease unavailable: {reason}")
            return 2
        print(f"lease {record.lease_id} until {record.expires_at}")
        device = ADBDevice(ADB, SERIAL, production=True)
        status = device.status()
        print(f"device: connected={status.connected} resolution={status.resolution}")
        if not status.connected:
            lease.release(result="failed", reason="device not connected")
            return 3

    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        gen = PipelineAutoGen(device=device)
        frames: dict[str, Path] = {}
        token_cache: dict[str, list] = {}

        # ---------------------------------------------------------- phase 1
        sources = [(item.partition(":")[0], item.partition(":")[2], True)
                   for item in args.frame] if args.frame else [
                       (item.partition(":")[0], item.partition(":")[2], False)
                       for item in args.visit]
        for index, (page, coord, archived) in enumerate(sources):
            if archived:
                path = Path(coord).resolve()
                if not path.is_file():
                    raise FileNotFoundError(path)
                frames[page] = path
                token_cache[page] = gen.tokens_for(path)
                print(f"[frame] {page:20} -> {path.name}  tokens={len(token_cache[page])}")
                continue
            # A full-screen page (hero training, an event) hides the bottom nav, so
            # the next visit's coordinate would land on that page's own UI and go
            # somewhere unplanned. Backing out first keeps every visit starting from
            # a page whose nav is where the operator's coordinates assume it is.
            for _ in range(args.back_before if index else 0):
                device.press_back()
                time.sleep(1.2)
            if coord:
                x, _, y = coord.partition(",")
                device.tap(int(x), int(y))
                time.sleep(2.5)
            path = FRAMES / f"{stamp}_{page}.png"
            saved = device.screenshot(path)
            frames[page] = Path(saved)
            token_cache[page] = gen.tokens_for(Path(saved))
            print(f"[frame] {page:20} -> {saved.name}  tokens={len(token_cache[page])}")

        # ---------------------------------------------------------- phase 2
        labels = declared_labels()
        owners = owning_skills()
        table = RoutingTable.load()

        # Validation needs the real MAA matcher: a node is only as good as the
        # backend that will run it. Built from config/v2.json like every other
        # consumer; if MAA is off or down, nodes are still generated and reported,
        # but nothing is wired -- wiring against a matcher that is not there would
        # be grading homework without a teacher.
        from winter_agent_v2.executor_router import build_maa_adapter

        config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        adapter = build_maa_adapter(config, production=True)
        if adapter is None:
            print("[WARN] MAA disabled by config; nodes will be generated but NOT wired")
            args.apply = False
        else:
            ok, why = adapter.ensure_ready()
            print(f"maa adapter: ready={ok} reason={why}")
            if not ok:
                print("[WARN] MAA not ready; nodes will be generated but NOT wired")
                args.apply = False

        def has_node(skill_id: str, semantic: str) -> bool:
            return table.recognition_node(skill_id, semantic) is not None

        results: list[dict[str, object]] = []
        wired = rejected = absent = 0
        for semantic, cn, declared_pages in labels:
            skill_ids = owners.get(semantic, [])
            if not skill_ids:
                continue
            if all(has_node(s, semantic) for s in skill_ids):
                continue
            # Where is this control actually visible?
            hits = []
            for page, tokens in token_cache.items():
                located = gen.locate_in_tokens(tokens, cn)
                # Substring OCR hits are useful for discovery but unsafe for
                # clicking: 出征 inside 本次出征胜券在握 is descriptive text.
                if located and located[1] >= args.min_score and located[2].strip() == cn.strip():
                    hits.append((page, located))
            if not hits:
                absent += 1
                continue

            page, (box, score, observed) = hits[0]
            # Page membership: the dictionary declares which pages a control lives on,
            # and the visit name is the page this frame claims to be. A generic word
            # ("领取") is owned by several semantics on several pages -- without this
            # check the exploration page's claim button was filed as the alliance-gift
            # claim, because both say 领取 and both validate against a text-absent
            # negative. A record with no declared pages keeps the old behaviour.
            if declared_pages and str(page).upper() not in declared_pages:
                continue
            positives = [frames[p] for p, _ in hits]
            # A negative is a frame where the label's own text is absent — not merely
            # "another page". Bottom-nav and top-bar controls persist across pages, so
            # using other pages as negatives would reject every persistent control:
            # its template would legitimately hit there too. Text-absence is the
            # criterion that matches what the node is actually claiming.
            negatives = [frames[p] for p in frames
                         if not (gen.locate_in_tokens(token_cache[p], cn)
                                 and gen.locate_in_tokens(token_cache[p], cn)[1] >= args.min_score
                                 and gen.locate_in_tokens(token_cache[p], cn)[2].strip() == cn.strip())]

            for skill_id in skill_ids:
                if has_node(skill_id, semantic):
                    continue
                node = gen.generate(
                    GenerationRequest(semantic=semantic, cn_text=cn, skill_id=skill_id,
                                      expand=args.expand, want=args.want),
                    frame=frames[page],
                )
                if node is None:
                    continue
                node.evidence.update({
                    "harvest_page": page, "harvest_score": round(score, 4),
                    "observed_text": observed, "observed_box": box,
                    "positive_frames": [str(p) for p in positives],
                    "negative_frames": [str(p) for p in negatives],
                    "negative_rule": "frames whose OCR does not show the label text",
                })
                report = gen.validate(node, positives=positives, negatives=negatives,
                                      adapter=adapter)
                node.evidence["validation_report"] = report
                # Wiring needs a frame that does NOT show the label: without one, a
                # pass whose every frame contains the word (a bottom-nav label, 系统消息,
                # any persistent text) validates trivially and files a node under the
                # wrong page's context -- measured live: mail-tab nodes were "validated"
                # 3/3 against three frames of the kingdom map, because 联盟 is drawn in
                # its navigation bar. No negative context, no wiring.
                context_ok = len(negatives) >= 1
                ok = (
                    report["positive_hits"] == report["positives"]
                    and report["negative_hits"] == 0
                    and report["positives"] >= 1
                    and context_ok
                )
                verdict = "WIRED" if ok else (
                    "REJECTED_NO_NEGATIVE_CONTEXT" if not context_ok else "REJECTED_VALIDATION")
                if ok and args.apply:
                    _wired, verdict = gen.wire(node, note="harvested+validated")
                if ok:
                    wired += 1
                else:
                    rejected += 1
                results.append({
                    "semantic": semantic, "skill_id": skill_id, "kind": node.kind,
                    "page": page, "score": round(score, 4), "box": box,
                    "positive_hits": report["positive_hits"], "positives": report["positives"],
                    "negative_hits": report["negative_hits"], "negatives": report["negatives"],
                    "verdict": verdict, "template": str(node.template_path or ""),
                })

        print()
        print(f"labels scanned        : {len(labels)}")
        print(f"executable semantics  : {len([1 for s, _, _ in labels if s in owners])}")
        print(f"not on any frame      : {absent}")
        print(f"nodes wired           : {wired}   (apply={args.apply})")
        print(f"rejected by validation: {rejected}")
        for row in results:
            print(f"  {row['verdict']:20} {row['skill_id'][:24]:24} {row['semantic'][:24]:24}"
                  f" p={row['positive_hits']}/{row['positives']} n={row['negative_hits']}/{row['negatives']}"
                  f" score={row['score']}")

        manifest = FRAMES / f"{stamp}_harvest_manifest.json"
        manifest.write_text(json.dumps({"frames": {k: str(v) for k, v in frames.items()},
                                        "rows": results}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        print(f"\nmanifest -> {manifest}")
        if lease is not None:
            lease.release(result="ok", reason="harvest complete")
        return 0
    except Exception as exc:  # noqa: BLE001
        if lease is not None:
            lease.release(result="failed", reason=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
