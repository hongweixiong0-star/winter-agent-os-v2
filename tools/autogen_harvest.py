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
        # Page/popup titles are not actions. ROW/ROW_CONTROL labels are also
        # excluded: on the quick panel the actual control is the arrow to the
        # right, and clicking the row label does not enter the task.
        if str(record.get("type", "")).upper() not in {
            "BUTTON", "TAB", "INTERACTIVE_CONTROL",
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
    # The gap queue is the other declared source: it names every skill-target
    # semantic that still lacks a node and the words the client prints there.
    # Measured 2026-09-26, the dictionary declares none of the 81 gap semantics,
    # so a dictionary-only scan never sees the harvest's actual work list.
    from winter_agent_v2.pipeline_autogen import DEFAULT_GAP_QUEUE_PATH

    try:
        gap_payload = json.loads(DEFAULT_GAP_QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        gap_payload = {}
    for item in gap_payload.get("queue") or ():
        if not isinstance(item, dict) or not item.get("semantic"):
            continue
        if str(item.get("record_type", "")).upper() not in {"BUTTON", "TAB", "CONTROL"}:
            continue
        semantic = str(item["semantic"])
        pages = [str(p).upper() for p in (item.get("pages") or [])]
        for word in item.get("visible_words") or ():
            text = str(word).strip()
            if not text or not any("\u4e00" <= ch <= "\u9fff" for ch in text):
                continue
            key = (semantic, text)
            if key not in seen:
                seen.add(key)
                out.append((semantic, text, pages))
    return out


def _field(token: object, name: str):
    """Read a field from either an OCRToken dataclass or a plain dict."""
    if isinstance(token, dict):
        return token.get(name)
    return getattr(token, name, None)


def _template_hit(adapter, root: Path, routing: dict, frame: Path) -> bool:
    """Does the template node find its control on this frame? Real matcher only."""
    try:
        import numpy as np
        from PIL import Image
        with Image.open(frame) as im:
            image = np.asarray(im.convert("RGB"))
        src = Path(str(routing.get("source_template", "")))
        if not src.is_absolute():
            src = root / src
        out = adapter.find(
            image, str(routing.get("template", "")),
            template=str(routing.get("template", "")),
            roi=tuple(routing.get("roi", ())) or None,
            threshold=routing.get("threshold", 0.7),
            images={str(routing.get("template", "")): src} if src.is_file() else None,
        )
        return bool(out.hit)
    except Exception:  # noqa: BLE001
        return False


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
                    help="page_name[#sample]:path — use archived real frames without taking the device lease")
    ap.add_argument("--back-before", type=int, default=2, metavar="N",
                    help="press BACK this many times before each visit, so a previous "
                         "visit's full-screen page cannot swallow the next tap")
    ap.add_argument("--expand", type=int, default=22)
    ap.add_argument("--want", default="template", choices=("auto", "ocr", "template"))
    ap.add_argument("--min-score", type=float, default=0.90,
                    help="minimum OCR confidence for a label to count as present")
    ap.add_argument("--template-roi", action="append", default=[],
                    help="SEMANTIC=x,y,w[h] — crop a TEMPLATE-method gap control from its "
                         "page frame at this rect and validate the template node")
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
        validated = wired = rejected = absent = 0
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
            if declared_pages and str(page).partition("#")[0].upper() not in declared_pages:
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
                verdict = "VALIDATED_CANDIDATE" if ok else (
                    "REJECTED_NO_NEGATIVE_CONTEXT" if not context_ok else "REJECTED_VALIDATION")
                if ok:
                    validated += 1
                if ok and args.apply:
                    _wired, verdict = gen.wire(node, note="harvested+validated")
                    if _wired:
                        wired += 1
                if not ok:
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
        print(f"validated candidates  : {validated}")
        print(f"nodes wired           : {wired}   (apply={args.apply})")
        print(f"rejected by validation: {rejected}")
        for row in results:
            print(f"  {row['verdict']:20} {row['skill_id'][:24]:24} {row['semantic'][:24]:24}"
                  f" p={row['positive_hits']}/{row['positives']} n={row['negative_hits']}/{row['negatives']}"
                  f" score={row['score']}")

        # ---------------------------------------------------------- method paths
        # Gap entries without CJK visible_words are classified (real UI features)
        # into OCR / TEMPLATE / COLOR / STRUCTURE / LIST_DYNAMIC and take the
        # generation path their type allows — no invented Chinese labels.
        method_rows: list[dict[str, object]] = []
        gap_payload = json.loads(
            (ROOT / "knowledge" / "execution" / "pipeline_gap_queue.json").read_text(encoding="utf-8"))
        rect_overrides: dict[str, tuple[int, int, int, int]] = {}
        for spec in args.template_roi:
            name, _, rect = spec.partition("=")
            parts = [int(v) for v in rect.replace(":", ",").split(",")]
            while len(parts) < 4:
                parts.append(0)
            rect_overrides[name.strip()] = tuple(parts[:4])  # type: ignore[assignment]
        for item in gap_payload.get("queue") or ():
            if not isinstance(item, dict):
                continue
            semantic = str(item.get("semantic", ""))
            method = str((item.get("recognition") or {}).get("method", "")).upper()
            skill_ids = owners.get(semantic, [])
            if not method or not skill_ids or all(has_node(s, semantic) for s in skill_ids):
                continue
            pages = [str(p).upper() for p in item.get("pages") or []]
            page_frames = [frames[p] for p in frames
                           if not pages or str(p).partition("#")[0].upper() in pages]
            if not page_frames:
                method_rows.append({"semantic": semantic, "method": method, "verdict": "NO_FRAME_FOR_PAGE"})
                continue

            if method == "OCR":
                # The control prints text we have not recorded. Read the live
                # frame's CJK tokens and file them as observed_words — real
                # readings, attachable to the queue, never invented labels.
                from winter_agent_v2.pipeline_autogen import gap_recognition_method  # noqa: F401
                tokens = gen.tokens_for(page_frames[0])
                seen_cjk = []
                for token in tokens:
                    text = str(_field(token, "text") or "").strip()
                    if text and any("\u4e00" <= ch <= "\u9fff" for ch in text) and text not in seen_cjk:
                        seen_cjk.append(text)
                method_rows.append({"semantic": semantic, "method": method,
                                    "verdict": "OCR_DISCOVERY", "observed_cjk_tokens": seen_cjk[:40]})
                continue

            if method == "TEMPLATE":
                rect = rect_overrides.get(semantic)
                if rect is None:
                    method_rows.append({"semantic": semantic, "method": method,
                                        "verdict": "NEEDS_TEMPLATE_RECT"})
                    continue
                from winter_agent_v2.pipeline_autogen import build_routing_template_node
                from winter_agent_v2.pipeline_autogen import (TEMPLATE_ROI_EXPAND,
                                                              compute_roi)
                import hashlib
                frame = page_frames[0]
                from PIL import Image
                digest = hashlib.sha1(f"{semantic}|{rect}".encode()).hexdigest()[:8]
                tpl_dir = ROOT / "dataset" / "candidate" / "autogen"
                tpl_dir.mkdir(parents=True, exist_ok=True)
                tpl = tpl_dir / f"{semantic.lower()}__rect_{digest}.png"
                with Image.open(frame) as im:
                    im.convert("RGB").crop(rect).save(tpl, "PNG")
                rel = tpl.resolve().relative_to(ROOT.resolve()).as_posix()
                # crop stays exact; the SEARCH roi gets the same drift margin
                # every other TEMPLATE path uses (measured 30px live drift).
                # rect_overrides are PIL boxes (x1,y1,x2,y2) for cropping;
                # compute_roi wants x,y,w,h — convert explicitly.
                from PIL import Image
                screen = Image.open(frame).size  # (w, h)
                bx, by, bx2, by2 = rect
                search_roi = compute_roi((bx, by, bx2 - bx, by2 - by),
                                         TEMPLATE_ROI_EXPAND,
                                         screen=(screen[0], screen[1]))
                for skill_id in skill_ids:
                    if has_node(skill_id, semantic):
                        continue
                    routing = build_routing_template_node(semantic, rel, roi=list(search_roi))
                    # Validation: the template must hit its own page frame and
                    # miss every other captured frame (icon sprites are page-bound).
                    positives, negatives = page_frames, [f for p, f in frames.items()
                                                         if f not in page_frames]
                    hit_pos = sum(1 for f in positives if _template_hit(adapter, ROOT, routing, f))
                    hit_neg = sum(1 for f in negatives if _template_hit(adapter, ROOT, routing, f))
                    ok = positives and hit_pos == len(positives) and hit_neg == 0 and negatives
                    verdict = "VALIDATED_CANDIDATE" if ok else "REJECTED_VALIDATION"
                    if ok and args.apply:
                        from winter_agent_v2.pipeline_autogen import GeneratedNode
                        node = GeneratedNode(semantic=semantic, skill_id=skill_id, kind="TEMPLATE",
                                             routing_node=routing,
                                             pipeline_node={"recognition": "TemplateMatch",
                                                            "template": [semantic], "roi": list(search_roi),
                                                            "threshold": [0.7]},
                                             template_path=tpl, frame=frame)
                        node.evidence = {"source": "harvest rect template", "rect": list(rect),
                                         "frame": str(frame), "validation": "PENDING_RECORD"}
                        _ok, verdict = gen.wire(node, note="harvest rect template")
                        if _ok:
                            wired += 1
                            validated += 1
                        method_rows.append({"semantic": semantic, "method": method,
                                            "skill_id": skill_id, "verdict": verdict})
                        continue
                    method_rows.append({"semantic": semantic, "method": method,
                                        "skill_id": skill_id, "verdict": verdict,
                                        "positive_hits": hit_pos, "positives": len(positives),
                                        "negative_hits": hit_neg, "negatives": len(negatives)})
                continue

            # COLOR / STRUCTURE / LIST_DYNAMIC: candidate-only until their
            # adapters exist — reported, never wired.
            method_rows.append({"semantic": semantic, "method": method,
                                "verdict": "CANDIDATE_ONLY_NO_ADAPTER"})

        print()
        print(f"method-path rows      : {len(method_rows)}")
        for row in method_rows:
            print(f"  [{row.get('method', '?'):12}] {row.get('semantic', '?')[:34]:34} {row.get('verdict')}")
        for page, tokens in token_cache.items():
            cjk = sorted({str(_field(t, 'text') or '').strip() for t in tokens
                          if _field(t, 'text') and any('\u4e00' <= ch <= '\u9fff' for ch in str(_field(t, 'text')))})
            print(f"[page-tokens] {page}: {len(cjk)} cjk tokens")

        manifest = FRAMES / f"{stamp}_harvest_manifest.json"
        manifest.write_text(json.dumps({"frames": {k: str(v) for k, v in frames.items()},
                                        "rows": results, "method_rows": method_rows},
                                       ensure_ascii=False, indent=2),
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
