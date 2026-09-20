"""MAA migration harness — measure a semantic on MAA vs the legacy matcher.

Why this exists (operator directive 2026-09-14, "MAA 强制生产接入"):

Migrating a button to MAA must not be a rewrite of an unproven template.  The
project has already paid for that mistake twice — ``BTN_HERO_FIGHT`` was
registered 103 px too high and self-matched at distance 0, which "proved" a wrong
coordinate through three live runs.

So every migrated semantic goes through this harness first, and the harness
reports the three things that actually decide the question:

``positive hit rate``
    Does MAA still find the control on frames from *other* runs?  A template
    matched against the frame it was cropped from is a tautology; frames from
    different runs of the same screen are the real test.

``negative false-positive rate``
    Does it also fire on screens where the control is absent?  A matcher that
    hits everything has a 100% positive rate and no value.  The negatives
    include the *hard* ones — the same screen with the button gone.

``latency``
    MAA template match cost per frame, so the routing decision has a number.

It also writes an annotated frame per case with the recognised box drawn on it,
because a box on a picture is the only thing that has ever caught a mis-crop here.

Writes ``learning/maa_migration/<stamp>.json`` and
``dataset/evidence/maa_migration/<stamp>/<semantic>.png``.

Run inside the project venv (needs PIL/numpy/opencv and maa):

    E:/无尽冬日智能体/.venv/Scripts/python.exe tools/maa_migrate.py nodes
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
import numpy as np  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.maa_executor import MaaExecutorAdapter  # noqa: E402
from winter_agent_v2.matchers import match_ccoeff  # noqa: E402

MUMU_ADB = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe")
SERIAL = "127.0.0.1:7555"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
T = ROOT / "dataset/truth_audit"
RAW = ROOT / "dataset/raw"


@dataclass
class Case:
    """One semantic under migration, with an auditable frame corpus."""

    semantic: str
    skill: str
    positives: list[Path]
    negatives: list[Path]
    threshold: float = 0.7
    # ``expect_norm`` is the coordinate the project already established by hand.
    # MAA must reproduce it; a match that scores well in the wrong place is worse
    # than no match, because the click would land somewhere else.
    expect_norm: tuple[float, float] | None = None
    expect_tolerance_px: int = 24


# ---------------------------------------------------------------------------
# Corpora.  Positives are frames from *different* runs of the same screen.
# Negatives are different screens, and include the same screen with the control
# gone (the hard case) wherever such a frame exists.
# ---------------------------------------------------------------------------
CASES: list[Case] = [
    Case(
        semantic="BTN_HERO_FIGHT",
        skill="INTEL_HERO_DISPATCH",
        threshold=0.6,
        expect_norm=(527.5 / 720.0, 1201.0 / 1280.0),
        expect_tolerance_px=25,
        positives=[
            T / "hero_fight_final_20260914/00_before.png",
            T / "hero_fight_seq_20260914/03_squad.png",
            T / "hero_fight_seq_20260914/04_autofill.png",
            T / "hero_fight_seq_20260914/05_fight.png",
            T / "hero_fight_seq_20260914/scan_base.png",
            T / "fight_why_20260914/14_squad.png",
            T / "hero_fight_manual_20260914/01_before.png",
            # Re-labelled 2026-09-14 after looking at them: both are the squad-setup
            # page with the 战斗 button visible. They had been guessed as negatives
            # and the harness reported them as false positives.
            T / "fight_why_20260914/00_state.png",
            T / "fight_why_20260914/15_toast_1.5s.png",
        ],
        negatives=[
            T / "fight_why_20260914/10_map.png",
            T / "fight_why_20260914/11_board.png",
            T / "fight_why_20260914/12_card.png",
            T / "fight_why_20260914/13_camp.png",
            T / "hero_fight_final_20260914/01_after_2.5s.png",
            T / "hero_fight_final_20260914/02_dismissed.png",
            T / "hero_fight_final_20260914/04_back.png",
            T / "hero_fight_seq_20260914/01_card.png",
        ],
    ),
    Case(
        semantic="BTN_HERO_CAMP_FIGHT",
        skill="INTEL_HERO_START_MARCH",
        threshold=0.6,
        positives=[
            T / "fight_why_20260914/13_camp.png",
            T / "hero_fight_seq_20260914/02_camp.png",
        ],
        negatives=[
            T / "hero_fight_seq_20260914/03_squad.png",
            T / "fight_why_20260914/10_map.png",
            T / "fight_why_20260914/12_card.png",
            T / "hero_fight_final_20260914/00_before.png",
        ],
    ),
    Case(
        semantic="BTN_OPEN_HOME",
        skill="OPEN_HOME",
        threshold=0.7,
        positives=[
            T / "fight_why_20260914/10_map.png",
            T / "hero_fight_final_20260914/04_back.png",
        ],
        negatives=[
            T / "hero_fight_seq_20260914/03_squad.png",
            T / "fight_why_20260914/11_board.png",
            T / "fight_why_20260914/00_state.png",
            # Looked at it: 20_now.png is the squad-setup page, not the world map,
            # so 回城 is genuinely absent.  MAA's "miss" here was a correct
            # rejection of a mislabelled positive (the same frame is a battle
            # button positive elsewhere, which is how it got mislabelled).
            T / "fight_why_20260914/20_now.png",
        ],
    ),
    Case(
        semantic="PAGE_MAP",
        skill="OPEN_MAP",
        threshold=0.8,
        positives=[
            RAW / "live_back_safe_home.png",
            RAW / "live_daily_hero_recruit_verified.png",
            RAW / "live_daily_hero_recruit_navigation.png",
            RAW / "live_attempt8_idle.png",
        ],
        negatives=[
            T / "fight_why_20260914/10_map.png",
            T / "hero_fight_seq_20260914/03_squad.png",
        ],
    ),
    Case(
        # OPEN_MARCH_PAGE: the historical MARCH_PAGE_NOT_OPEN family.  Positives are
        # three independent live runs of the resource-detail dialog; the hard
        # negatives are the march pages that FOLLOW it, where 采集 must be gone.
        semantic="BTN_GATHER",
        skill="START_GATHER",
        threshold=0.7,
        positives=[
            RAW / "live_resource_attempt6.png",
            RAW / "live_resource_attempt7.png",
            RAW / "live_attempt8_resource.png",
        ],
        negatives=[
            RAW / "live_march_selection.png",
            RAW / "live_beast_march_selection.png",
            T / "fight_why_20260914/10_map.png",
            T / "hero_fight_seq_20260914/03_squad.png",
            T / "fight_why_20260914/11_board.png",
        ],
    ),
    Case(
        semantic="BTN_CLOSE",
        skill="CLOSE_POPUP",
        threshold=0.7,
        positives=[
            RAW / "control_panel/runtime/step_001_before.png",
        ],
        negatives=[
            T / "fight_why_20260914/10_map.png",
            T / "hero_fight_seq_20260914/03_squad.png",
        ],
    ),
    Case(
        semantic="BTN_OPEN_INTEL_WILD_HUD",
        skill="OPEN_INTEL",
        threshold=0.7,
        positives=[
            RAW / "live_intel_wild_entry_v2/wild_fresh_before.png",
        ],
        negatives=[
            T / "hero_fight_seq_20260914/03_squad.png",
            T / "fight_why_20260914/11_board.png",
        ],
    ),
]


def load_templates() -> dict[str, list[dict]]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_semantic: dict[str, list[dict]] = {}
    for row in payload.get("records", []):
        by_semantic.setdefault(str(row.get("semantic", "")), []).append(row)
    return by_semantic


def template_for(rows: list[dict]) -> dict | None:
    """Pick the manifest record to migrate, preferring one already reviewed.

    Returning the *record* (not just its path) matters: the ROI column and the
    template must come from the same record, otherwise the legacy comparison
    measures a different crop than the template it claims to test.
    """
    for row in rows:
        if str(row.get("matcher", "")) == "ccoeff":
            return row
    # A semantic can hold both a ``legacy_*`` record (cropped from an older client
    # layout) and a live one.  Selecting the legacy candidate made PAGE_MAP score
    # 0/2 against current frames, which reads as "MAA cannot find the map button"
    # when the real problem is a stale candidate.
    for row in rows:
        text = f"{row.get('template_path', '')} {row.get('parent_screenshot', '')}".lower()
        if "legacy" not in text:
            return row
    for row in rows:
        if str(row.get("source", "")).startswith("LIVE"):
            return row
    return rows[0] if rows else None


def legacy_distance(frame: Path, row: dict) -> int | None:
    roi = row.get("roi_norm")
    if not roi:
        return None
    with Image.open(frame) as image:
        width, height = image.size
        bounds = (
            round(roi["x_norm"] * width), round(roi["y_norm"] * height),
            round((roi["x_norm"] + roi["w_norm"]) * width),
            round((roi["y_norm"] + roi["h_norm"]) * height),
        )
        with Image.open(ROOT / row["template_path"]) as template:
            return hamming(phash(image.crop(bounds)), phash(template))


@dataclass
class CaseReport:
    semantic: str
    skill: str
    template: str = ""
    threshold: float = 0.0
    maa_positive_hits: int = 0
    maa_positive_total: int = 0
    maa_negative_hits: int = 0
    maa_negative_total: int = 0
    ccoeff_positive: list[float | None] = field(default_factory=list)
    ccoeff_negative: list[float | None] = field(default_factory=list)
    phash_positive: list[int | None] = field(default_factory=list)
    phash_negative: list[int | None] = field(default_factory=list)
    maa_latency_ms: list[float] = field(default_factory=list)
    centre_errors_px: list[float] = field(default_factory=list)
    false_positive_frames: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)
    # A hit on a hand-labelled negative is a CLAIM, not a proven false positive.
    # Two negatives in this corpus turned out to be squad-page frames that really
    # do show the battle button, so counting them against the matcher would have
    # been slander.  Each one gets an annotated frame and a review flag instead.
    unverified_negative_hits: list[dict] = field(default_factory=list)
    rois_equal_the_box: bool = False

    def to_dict(self) -> dict:
        pos = self.maa_positive_hits / self.maa_positive_total if self.maa_positive_total else None
        neg = self.maa_negative_hits / self.maa_negative_total if self.maa_negative_total else None
        ccoeff_pos = [v for v in self.ccoeff_positive if v is not None]
        ccoeff_neg = [v for v in self.ccoeff_negative if v is not None]
        phash_pos = [v for v in self.phash_positive if v is not None]
        phash_neg = [v for v in self.phash_negative if v is not None]
        return {
            "semantic": self.semantic, "skill": self.skill, "template": self.template,
            "threshold": self.threshold,
            "maa": {
                "positive_hits": self.maa_positive_hits,
                "positive_total": self.maa_positive_total,
                "positive_rate": round(pos, 4) if pos is not None else None,
                "negative_hits": self.maa_negative_hits,
                "negative_total": self.maa_negative_total,
                "false_positive_rate": round(neg, 4) if neg is not None else None,
                "latency_ms_mean": round(statistics.fmean(self.maa_latency_ms), 2) if self.maa_latency_ms else None,
                "latency_ms_max": round(max(self.maa_latency_ms), 2) if self.maa_latency_ms else None,
                "misses": self.misses,
                "false_positive_frames": self.false_positive_frames,
                "frames": self.frames,
            },
            "centre_error_px": {
                "values": [round(v, 1) for v in self.centre_errors_px],
                "max": round(max(self.centre_errors_px), 1) if self.centre_errors_px else None,
            } if self.centre_errors_px else None,
            "legacy_ccoeff": {
                "positive_min": round(min(ccoeff_pos), 4) if ccoeff_pos else None,
                "negative_max": round(max(ccoeff_neg), 4) if ccoeff_neg else None,
                "gap": round(min(ccoeff_pos) - max(ccoeff_neg), 4) if ccoeff_pos and ccoeff_neg else None,
            },
            "legacy_phash": {
                "positive_max_distance": max(phash_pos) if phash_pos else None,
                "negative_min_distance": min(phash_neg) if phash_neg else None,
                "gap": (min(phash_neg) - max(phash_pos)) if phash_pos and phash_neg else None,
            },
            "legacy_comparison_valid": not self.rois_equal_the_box,
            "legacy_comparison_note": (
                "FIXED-POSITION TEST ONLY: this record's roi_norm is the button box, so the "
                "legacy matcher is asked 'does the known box contain the button?' and cannot "
                "be asked 'can it find the button anywhere'. It scores 1.0 by construction on "
                "positives; its negative column (low scores on other screens) is still real. "
                "The MAA column searches the full frame, so it also tests localisation - "
                "which is what the 0.5 px centre-error figure is measuring."
            ) if self.rois_equal_the_box else "",
            "unverified_negative_hits": self.unverified_negative_hits,
            # Promotion gate.  This rule exists because it was broken: a
            # ONE-positive-frame corpus (BTN_OPEN_INTEL_WILD_HUD) was promoted and
            # regressed production on the very first live frame - MAA located the
            # control at exactly the right box but correlated 0.448 against the
            # template, below the 0.7 default, so the action was refused and the
            # run stopped.  A single frame cannot reveal that a control animates.
            "corpus_sufficient": self.maa_positive_total >= 3 and self.maa_negative_total >= 3,
            "corpus_rule": (
                ">=3 independent live positives AND >=3 negatives are required before a "
                "semantic may be promoted to a MAA recognition node."
            ),
        }


def run_case(case: Case, adapter: MaaExecutorAdapter, rows: list[dict], out_dir: Path) -> CaseReport:
    report = CaseReport(case.semantic, case.skill, threshold=case.threshold)
    row = template_for(rows)
    template_path = ROOT / str(row["template_path"]) if row else None
    if row is None or template_path is None or not template_path.is_file():
        report.misses.append(f"NO_TEMPLATE:{template_path}")
        return report
    report.template = str(template_path.relative_to(ROOT))
    with Image.open(template_path) as template_image:
        template_size = template_image.size
    roi_norm = row.get("roi_norm") or {}
    roi_px = (
        (round(roi_norm["w_norm"] * 720), round(roi_norm["h_norm"] * 1280)) if roi_norm else None
    )
    # When the manifest ROI is the button box itself, the legacy matcher is handed
    # the answer: it crops exactly the region the template came from, so positives
    # and negatives both score 1.0 / distance 0 and the "gap" is meaningless.
    # Flag it instead of publishing a fake comparison.
    report.rois_equal_the_box = bool(
        roi_px is not None
        and abs(roi_px[0] - template_size[0]) <= 8
        and abs(roi_px[1] - template_size[1]) <= 8
    )
    image_arg = {case.semantic: template_path}

    def measure(frame: Path, expect_hit: bool) -> None:
        if not frame.is_file():
            report.misses.append(f"MISSING_FRAME:{frame.relative_to(ROOT)}")
            return
        # Score the corpus frame itself.  When this was ``None`` the adapter fell
        # back to a live screencap, so every frame in a case scored identically
        # and the harness "disproved" a matcher that was in fact correct.  The
        # frame is always read from disk and asserted below.
        with Image.open(frame) as image:
            width, height = image.size
            array = np.array(image.convert("RGB"))
        if array is None or getattr(array, "size", 0) == 0:
            report.misses.append(f"FRAME_UNREADABLE:{frame.relative_to(ROOT)}")
            return
        outcome = adapter.match_template(
            array, template=case.semantic, semantic=case.semantic,
            threshold=case.threshold, images=image_arg,
        )
        report.frames.append({
            "frame": str(frame.relative_to(ROOT)),
            "expected": "present" if expect_hit else "absent",
            "hit": outcome.hit, "box": list(outcome.box) if outcome.box else None,
            "score": outcome.score, "error": outcome.error,
            "latency_ms": round(outcome.latency_ms, 1),
        })
        report.maa_latency_ms.append(outcome.latency_ms)
        if expect_hit:
            report.maa_positive_total += 1
            if outcome.hit:
                report.maa_positive_hits += 1
                centre = outcome.center()
                if centre and case.expect_norm:
                    expected = (case.expect_norm[0] * width, case.expect_norm[1] * height)
                    report.centre_errors_px.append(
                        ((centre[0] - expected[0]) ** 2 + (centre[1] - expected[1]) ** 2) ** 0.5
                    )
            else:
                report.misses.append(str(frame.relative_to(ROOT)))
            report.ccoeff_positive.append(
                (lambda m: round(m.score, 3) if m else None)(match_ccoeff(frame, template_path, row.get("roi_norm")))
            )
            report.phash_positive.append(legacy_distance(frame, row))
        else:
            report.maa_negative_total += 1
            if outcome.hit:
                report.maa_negative_hits += 1
                report.false_positive_frames.append(str(frame.relative_to(ROOT)))
                shot = out_dir / f"negative_hit_{case.semantic}__{frame.stem}.png"
                adapter.save_annotated(array, outcome.box, shot,
                                       label=f"{case.semantic} {outcome.score}", color=(255, 140, 0))
                report.unverified_negative_hits.append({
                    "frame": str(frame.relative_to(ROOT)),
                    "score": outcome.score,
                    "box": list(outcome.box) if outcome.box else None,
                    "annotated": str(shot.relative_to(ROOT)),
                    "review": "PENDING - confirm the control is really absent before calling it a false positive",
                })
            report.ccoeff_negative.append(
                (lambda m: round(m.score, 3) if m else None)(match_ccoeff(frame, template_path, row.get("roi_norm")))
            )
            report.phash_negative.append(legacy_distance(frame, row))

    for frame in case.positives:
        measure(frame, True)
    for frame in case.negatives:
        measure(frame, False)

    # Annotated evidence for the first positive that hit, so a reviewer can see
    # the box without re-running anything.
    for frame in case.positives:
        if not frame.is_file():
            continue
        with Image.open(frame) as image:
            array = np.array(image.convert("RGB"))
        outcome = adapter.match_template(array, template=case.semantic, semantic=case.semantic,
                                        threshold=case.threshold, images=image_arg)
        if outcome.hit:
            adapter.save_annotated(array, outcome.box, out_dir / f"{case.semantic}.png",
                                   label=f"{case.semantic} {outcome.score}")
            break
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["nodes"])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = ROOT / "dataset/evidence/maa_migration" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir = ROOT / "learning/maa_migration"
    report_dir.mkdir(parents=True, exist_ok=True)

    adapter = MaaExecutorAdapter(
        adb_path=MUMU_ADB, serial=SERIAL, production=False,
        template_dir=ROOT / "dataset/candidate/templates",
        log_dir=ROOT / "learning/maa_logs",
    )
    ok, reason = adapter.ensure_ready()
    print(f"MAA backend: ok={ok} reason={reason or '-'}")
    print(f"screencap baseline: {adapter.frame().shape if adapter.frame() is not None else None}")

    templates = load_templates()
    results: dict[str, dict] = {}
    for case in CASES:
        rows = templates.get(case.semantic)
        if not rows:
            results[case.semantic] = {"error": "NOT_IN_MANIFEST"}
            continue
        report = run_case(case, adapter, rows, out_dir)
        results[case.semantic] = report.to_dict()
        data = results[case.semantic]
        maa = data.get("maa", {})
        print(
            f"\n=== {case.semantic} ({case.skill}) ==="
            f"\n  template      : {data.get('template')}"
            f"\n  MAA positives : {maa.get('positive_hits')}/{maa.get('positive_total')}"
            f"  negatives hit {maa.get('negative_hits')}/{maa.get('negative_total')}"
            f"\n  MAA latency   : mean {maa.get('latency_ms_mean')} ms  max {maa.get('latency_ms_max')} ms"
            f"\n  centre error  : {data.get('centre_error_px')}"
            f"\n  legacy ccoeff : {data.get('legacy_ccoeff')}"
            f"\n  legacy phash  : {data.get('legacy_phash')}"
        )
        if maa.get("false_positive_frames"):
            print(f"  NEGATIVE HITS (review required, annotated frames written): {maa['false_positive_frames']}")
        if not data.get("corpus_sufficient", False):
            print(f"  PROMOTION BLOCKED: corpus too thin "
                  f"({maa.get('positive_hits')}/{maa.get('positive_total')} positives, "
                  f"{maa.get('negative_hits')}/{maa.get('negative_total')} negatives). "
                  f"Needs >=3 independent live positives and >=3 negatives.")
        if not data.get("legacy_comparison_valid", True):
            print("  legacy columns INVALID: this ROI equals the box, so the legacy matcher "
                  "sees the answer (distance 0 / score 1.0 on positives and negatives alike)")
        if maa.get("misses"):
            print(f"  MISSES: {maa['misses']}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": "MAA",
        "adapter_ready": ok,
        "unavailable_reason": reason,
        "stats": adapter.stats(),
        "cases": results,
    }
    out = args.out or (report_dir / f"{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nreport  -> {out.relative_to(ROOT)}")
    print(f"annotated -> {out_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
