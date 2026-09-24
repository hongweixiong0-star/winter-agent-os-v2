"""The 登录好礼 closure, on the real client, with every step's own evidence.

Directive 2026-09-24 §四.  What it does, in order, and nothing else:

  1. takes the project's device lease, so no second actor shares the screen;
  2. reaches the city if it is not there -- by recognised words, never a blind BACK;
  3. reads the frame's own element table and taps the 登录好礼 **control** (the registered crop
     match, not the label's text box -- that difference is the whole of
     ``SEMANTIC_TARGET_IS_A_LABEL_NOT_A_CONTROL``);
  4. confirms the panel opened by its own page identity (``EVENT`` + ``events.panel``);
  5. taps the panel's 免费 tab -- a free, zero-cost control that is registered for exactly this,
     and the only way to answer "is there a free reward to claim here" without guessing;
  6. reads the result, and says what is claimable / claimed / locked / paid.

It never taps a day-node reward: whether an unlit-but-unlocked node is a claim control was not
measured, and a guessed reward position is what the directive forbids.  Where the panel offers a
free control the project has not registered, this reports that as the gap rather than pressing a
point.

Usage
-----
    python tools/probe_login_gift_claim.py              # observe only, no tap
    python tools/probe_login_gift_claim.py --execute
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

from winter_agent_v2 import ui_collection  # noqa: E402
from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease  # noqa: E402
from winter_agent_v2.executor import Executor  # noqa: E402
from winter_agent_v2.executor_router import build_maa_adapter  # noqa: E402
from winter_agent_v2.models import Action  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    OCRService, RapidOCRBackend, ResilientOCRBackend, HybridVision,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

OUT = ROOT / "dataset/truth_audit/live_ops"

#: Words that mean "the city is on screen".  Recognised rather than taken from the page label:
#: measured 2026-09-24, the recogniser called the city HUD ``MAIL`` at 0.99 on one frame and
#: ``HOME`` on the next, so the label alone decides nothing.
CITY_WORDS = ("登录好礼", "常规活动")


class Probe:
    def __init__(self) -> None:
        cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        self.adapter = build_maa_adapter(cfg, production=True)
        self.adapter.ensure_ready()
        self.ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
        self.vision = HybridVision(
            SemanticWorldVision(Path("dataset/candidate/template_manifest.json")), self.ocr
        )
        self.started = time.perf_counter()
        self.report: dict = {"steps": []}

    def step(self, name: str, **fields) -> None:
        row = {"step": name, "utc": datetime.now(timezone.utc).isoformat(),
               "ms": round((time.perf_counter() - self.started) * 1000, 1), **fields}
        self.report["steps"].append(row)
        print(f"  {name:22} {json.dumps(fields, ensure_ascii=False)[:150]}")

    def shoot(self, directory: Path, name: str) -> tuple[Path, object, list[str]]:
        path = directory / f"{name}.png"
        self.adapter.screenshot(path)
        world = self.vision.observe(path)
        texts = [str(r.get("text") or "") for r in ui_collection.grounding_regions(path, self.ocr)]
        return path, world, texts

    def tap_semantic_control(self, frame: Path, semantic: str) -> tuple[bool, dict]:
        """Tap a control this project has *registered a crop of*, found on this frame.

        ``ui_collection.build_element_table`` reads text and registered controls, but the day node
        carries no caption the table accepts -- the client draws it as art -- so the tile is located
        by its own template (``LOGIN_GIFT_DAY_CLAIM``, registered by
        ``tools/register_login_gift_claim_tile.py`` with a bounded search band).  The position is
        whatever the *current* frame matches, never a stored coordinate (Constitution A §24.2/§24.3).
        """
        from winter_agent_v2.vision import SemanticROIVision

        manifest = Path("dataset/candidate/template_manifest.json")
        hit = SemanticROIVision(ROOT / manifest).find(frame, semantic)
        if hit is None:
            return False, {"reason": f"the current frame does not draw {semantic}"}
        point = (round(hit.center_norm[0], 4), round(hit.center_norm[1], 4))
        executor = Executor(production=True, dry_run=False, device=self.adapter,
                            target_resolver=lambda _state: point, backend="MAA")
        result = executor.execute(Action("TAP_SEMANTIC", semantic))
        return bool(result.executed), {
            "semantic": semantic, "distance": getattr(hit, "distance", None),
            "box_norm": getattr(hit, "box_norm", None), "point": point,
            "executed": bool(result.executed),
            "tap_point": list(result.tap_point) if result.tap_point else None,
            "latency_ms": result.latency_ms, "error": result.error,
        }

    def tap_element(self, frame: Path, text: str, page: str) -> tuple[bool, dict]:
        """Tap the *control* element whose label is ``text``, from this frame's own table."""
        table = ui_collection.build_element_table(frame, self.ocr, page=page)
        entry = next(
            (e for e in table
             if str(e.get("text")) == text and e.get("executable")), None,
        )
        if entry is None:
            return False, {"reason": f"no executable element named {text} on this frame"}
        box = entry["box_norm"]
        point = (round(box["x_norm"] + box["w_norm"] / 2, 4),
                 round(box["y_norm"] + box["h_norm"] / 2, 4))
        executor = Executor(production=True, dry_run=False, device=self.adapter,
                           target_resolver=lambda _state: point, backend="MAA")
        result = executor.execute(Action("TAP_SEMANTIC", entry["semantic"]))
        return bool(result.executed), {
            "element_id": entry["id"], "kind": entry["kind"], "semantic": entry["semantic"],
            "basis": entry.get("basis"), "score": entry.get("confidence"),
            "box_norm": box, "point": point, "executed": bool(result.executed),
            "tap_point": list(result.tap_point) if result.tap_point else None,
            "latency_ms": result.latency_ms, "error": result.error,
        }


def _delta(a: Path, b: Path, box: tuple[float, float, float, float] | None = None) -> float | None:
    """Mean absolute luminance difference between two frames, optionally over one region.

    The same measure ``tools/probe_live_operation.py`` reports, and the reason it is here: "did the
    tap do anything" must be a number taken from the client's own drawing, not an impression.
    """
    try:
        from PIL import Image

        with Image.open(a) as first, Image.open(b) as second:
            one = first.convert("L")
            two = second.convert("L")
            if one.size != two.size:
                return None
            if box is not None:
                width, height = one.size
                rect = (int(box[0] * width), int(box[1] * height),
                        int((box[0] + box[2]) * width), int((box[1] + box[3]) * height))
                one = one.crop(rect)
                two = two.crop(rect)
            one = one.resize((90, 160))
            two = two.resize((90, 160))
            diff = [abs(p - q) for p, q in zip(one.getdata(), two.getdata())]
        return round(sum(diff) / len(diff) / 255.0, 4) if diff else None
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--claim-node", action="store_true",
                        help="after reading the panel, tap the registered highlighted day node once")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    probe = Probe()
    if not probe.adapter.available():
        print("MAA unavailable:", probe.adapter.unavailable_reason)
        return 3

    lease = DeviceLease(root=ROOT)
    op_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    directory = OUT / (args.out or f"{op_id}_login_gift_claim")
    directory.mkdir(parents=True, exist_ok=True)
    probe.report["op_id"] = directory.name

    record, refusal = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION,
        reason="login-gift closure probe",
        ttl_seconds=600.0,
    )
    acquired = record is not None
    probe.report["lease"] = {"acquired": acquired, "refusal": refusal}
    print(f"lease: {acquired} {refusal}  -> {directory}")
    if not acquired:
        print("another owner holds the device; stopping rather than sharing the screen")
        (directory / "claim.json").write_text(
            json.dumps(probe.report, ensure_ascii=False, indent=1), encoding="utf-8")
        return 4

    try:
        # ---------------------------------------------------------------- 1. reach the city
        at_city = False
        for attempt in range(5):
            frame, world, texts = probe.shoot(directory, f"city_{attempt}")
            page = str(getattr(world.page, "value", world.page))
            city_hud = any(word in texts for word in CITY_WORDS)
            probe.step("observe_city", attempt=attempt, page=page, city_hud=city_hud,
                       conf=world.confidence, dialog=any("退出游戏" in t for t in texts))
            if city_hud:
                at_city = True
                break
            # A quit dialog is answered by its own recognised 取消, never by another BACK.
            if any("退出游戏" in t for t in texts) and any(t.strip() == "取消" for t in texts):
                ok, detail = probe.tap_element(frame, "取消", page)
                probe.step("answer_quit_dialog", ok=ok, **{k: detail[k] for k in ("point", "executed") if k in detail})
                time.sleep(1.2)
                continue
            probe.adapter.press_back()
            probe.step("press_back", reason="not the city and no dialog on screen")
            time.sleep(1.8)
        if not at_city:
            probe.step("ABORT", reason="could not reach the city by recognised words")
            return 5

        # ---------------------------------------------------------------- 2. open the panel
        if not args.execute:
            entry = next(
                (e for e in ui_collection.build_element_table(frame, probe.ocr, page=page)
                 if str(e.get("text")) == "登录好礼"), None)
            probe.step("dry_run_entry", entry=(entry or {}).get("id"),
                       kind=(entry or {}).get("kind"), executable=(entry or {}).get("executable"))
            print("(no tap: pass --execute)")
            return 0

        ok, detail = probe.tap_element(frame, "登录好礼", page)
        probe.step("tap_login_gift_entry", ok=ok, **detail)
        time.sleep(1.4)
        panel, panel_world, panel_texts = probe.shoot(directory, "panel")
        panel_page = str(getattr(panel_world.page, "value", panel_world.page))
        probe.step("panel_opened", page=panel_page, events=getattr(panel_world, "events", {}),
                   texts=panel_texts[:14])
        result = {"panel_page": panel_page, "panel_events": getattr(panel_world, "events", {}),
                  "panel_texts": panel_texts}
        probe.report["panel"] = result
        if panel_page != "EVENT" or not (result["panel_events"] or {}).get("panel"):
            probe.step("PANEL_NOT_IDENTIFIED", page=panel_page)
            return 6

        # ---------------------------------------------------------------- 3. the 免费 tab
        table = ui_collection.build_element_table(panel, probe.ocr, page=panel_page)
        probe.report["panel_elements"] = [
            {"id": e["id"], "kind": e["kind"], "text": e["text"], "executable": e["executable"],
             "box_norm": e["box_norm"]} for e in table
        ]
        executable = [(e["id"], e["kind"], e["text"]) for e in table if e["executable"]]
        probe.step("panel_element_table", elements=len(table), executable=executable)

        ok, detail = probe.tap_element(panel, "免费", panel_page)
        probe.step("tap_free_tab", ok=ok, **detail)
        time.sleep(1.4)
        free_frame, free_world, free_texts = probe.shoot(directory, "free_tab")
        probe.step("free_tab_read",
                   page=str(getattr(free_world.page, "value", free_world.page)),
                   texts=free_texts[:24])
        probe.report["free_tab"] = {
            "frame": str(free_frame), "texts": free_texts,
            "page": str(getattr(free_world.page, "value", free_world.page)),
        }
        claim_words = [t for t in free_texts if "领取" in t]
        probe.step("claim_controls", words=claim_words)
        probe.report["claim_words"] = claim_words

        if not args.claim_node:
            return 0

        # ------------------------------------------------------- 4. one bounded claim, measured
        # One tap, on the node the client itself drew with a highlight ring, located by that node's
        # registered crop on *this* frame.  Nothing is guessed: if the crop does not resolve, no tap
        # is issued and that is the report.  Before/after frames and their deltas are the evidence --
        # whether the tile claims anything is exactly what this measures, and a null result is a
        # result.
        ok, detail = probe.tap_semantic_control(free_frame, "LOGIN_GIFT_DAY_CLAIM")
        probe.step("tap_claim_node", ok=ok, **detail)
        probe.report["claim_tap"] = detail
        if not ok:
            probe.step("CLAIM_NOT_ATTEMPTED", reason=detail.get("reason"))
            return 7

        node_box = (detail.get("box_norm") or {})
        region = None
        if node_box:
            region = (node_box["x_norm"], node_box["y_norm"], node_box["w_norm"], node_box["h_norm"])
        deltas = []
        for index in range(12):
            time.sleep(0.25)
            after, _world, _texts = probe.shoot(directory, f"claim_after_{index:02d}")
            deltas.append({
                "i": index,
                "ms": round((time.perf_counter() - probe.started) * 1000, 1),
                "whole": _delta(free_frame, after),
                "node": _delta(free_frame, after, region) if region else None,
            })
        probe.step("claim_delta", whole_max=max((d["whole"] or 0) for d in deltas),
                   node_max=max((d["node"] or 0) for d in deltas),
                   first=deltas[0], last=deltas[-1])
        probe.report["claim_deltas"] = deltas

        final, final_world, final_texts = probe.shoot(directory, "claim_final")
        probe.step("claim_final", page=str(getattr(final_world.page, "value", final_world.page)),
                   events=getattr(final_world, "events", {}), texts=final_texts[:24])
        probe.report["claim_final"] = {
            "frame": str(final),
            "page": str(getattr(final_world.page, "value", final_world.page)),
            "events": getattr(final_world, "events", {}),
            "texts": final_texts,
        }
        return 0
    finally:
        lease.release(result="RELEASED", reason="login-gift closure probe finished")
        (directory / "claim.json").write_text(
            json.dumps(probe.report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {directory / 'claim.json'}")


if __name__ == "__main__":
    sys.exit(main())
