"""Automatic UI-element collection: turn the failures the AUTO already has into knowledge.

Why this exists (operator directive 2026-09-22, "自动 UI 元素采集、验证与模板入库")

The project's UI knowledge grows by hand: someone reads a live frame, measures a control,
writes a tool, registers a template.  Meanwhile the AUTO itself keeps meeting controls it
cannot locate -- ``SEMANTIC_TARGET_NOT_VERIFIED`` is the largest failure class in the episode
stream, and every one of those steps *had the frame on disk*.  This module is the missing
wire between the two: the evidence the AUTO already paid for becomes candidate records, and a
candidate that a real step proves becomes a template the next cycle can use.

What it is and is not
---------------------
It is a **state file plus pure helpers**, the same shape as ``observation_store``,
``control_experience`` and ``stamina_supply``.  It does not observe, does not decide, does not
click, and owns no device: it is handed the frames, the page, the semantic and the verifier's
own verdict by the runtime, and it writes files.  There is no second Brain, no second
Scheduler, no second Executor, no second template store -- the template it writes goes into
``dataset/candidate/template_manifest.json``, the one manifest the one vision layer reads.

Three facts it refuses to blur
------------------------------
* ``recognition_method`` says where a position came from (OCR / template / ledger / AI), and
  ``verification_status`` says what a real step proved.  An OCR guess never becomes a
  live-verified effect by being written down.
* A crop is not an element.  ``stage`` writes the crop and the context image, and the record
  is ``DISCOVERED`` until a real step exercises it.
* Ingesting needs the step's **own verifier** to have passed.  A page that changed is not a
  task that succeeded (clicking 训练 and getting a count dialog is not troops training), which
  is why ``expected_effect``/``observed_effect``/``verification_status`` are three fields and
  not one.

Statuses (operator directive §七)
---------------------------------
    DISCOVERED  a region was proposed from a real frame; never exercised
    CANDIDATE   located and given a candidate semantic; no verified effect yet
    VERIFIED    a step using it passed its verifier and the frame really changed
    FAILED      exercised and the declared effect did not hold (per expectation, not forever)

``FAILED`` is recorded per attempt and never deletes the record: one unresponsive tap is not
a disproof of a control (operator §七).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image

#: Where candidates live.  ``knowledge/perception/candidates`` is the operator's own path, and
#: it is deliberately outside ``dataset/raw`` -- the retention pass prunes that tree, and a
#: candidate that gets pruned before it is verified is a candidate nobody ever sees again.
CANDIDATE_ROOT = Path("knowledge/perception/candidates")
INDEX_NAME = "INDEX.json"

#: The one manifest the one vision layer reads (``tools/run_live.py`` hands it to
#: ``SemanticWorldVision``).  Writing here is what makes a new template live: each AUTO cycle
#: is a fresh subprocess that re-reads this file, so no code change and no restart is needed.
TEMPLATE_MANIFEST = Path("dataset/candidate/template_manifest.json")
TEMPLATE_DIR = Path("dataset/candidate/auto_collected")

STATUS_DISCOVERED = "DISCOVERED"
STATUS_CANDIDATE = "CANDIDATE"
STATUS_VERIFIED = "VERIFIED"
STATUS_FAILED = "FAILED"
STATUSES: tuple[str, ...] = (STATUS_DISCOVERED, STATUS_CANDIDATE, STATUS_VERIFIED, STATUS_FAILED)

#: Template manifest statuses this module must never overwrite (operator §八.4/§八.5).
#: ``STABLE`` templates are not a thing in this repository's manifest today (every record is
#: ``CANDIDATE``); the guard exists so that the day one appears, an automatic collector cannot
#: quietly replace it.
PROTECTED_TEMPLATE_STATUSES = frozenset({"VERIFIED", "STABLE", "LIVE_VERIFIED"})

#: Recognition provenance (operator §五, "标注来源必须可追溯").  Kept as the layer names this
#: project already uses so a reader can follow one field from the record back to the code.
METHOD_OCR_WORD = "OCR_WORD"
METHOD_TEMPLATE = "TEMPLATE_MATCH"
METHOD_LEDGER = "EXPERIENCE_LEDGER"
METHOD_ACTION_RESULT = "ACTION_RESULT"

#: How far a control's box is taken to extend beyond the word the client printed on it.  A word
#: box is the *text*, not the button, and a template cut to the text alone would match on any
#: other text of the same length -- so the element crop is padded to a control-sized box.  This
#: is the one heuristic in the file and it is labelled as such in every record it produces.
ELEMENT_PAD_NORM = (0.055, 0.028)      # (x, y) of the frame, per side
CONTEXT_PAD_NORM = (0.11, 0.075)       # the same control with its surrounding UI

#: A countdown or a ratio inside a crop is what makes a template unstable (operator §八.2).
DYNAMIC_TEXT = re.compile(r"\d{1,2}:\d{2}:\d{2}|\d{1,4}\s*/\s*\d{1,4}|^\d{1,4}%$")

#: Storage bound (operator §九).  DISCOVERED/FAILED records are pruned oldest-first past this;
#: VERIFIED records are never pruned by this module, and neither is any record a template in
#: the manifest was cut from.
MAX_CANDIDATES = 400

#: A candidate whose region is not at least this large in either axis is a strip (a border, an
#: edge artefact) rather than a control, and is refused at stage time.
MIN_ELEMENT_SIDE_PX = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_box(box: Mapping[str, float] | Sequence[float] | None) -> dict[str, float] | None:
    """``{x_norm,y_norm,w_norm,h_norm}`` from either mapping or ``(x,y,w,h)``, or ``None``."""
    if box is None:
        return None
    if isinstance(box, Mapping):
        try:
            return {
                "x_norm": float(box["x_norm"]),
                "y_norm": float(box["y_norm"]),
                "w_norm": float(box["w_norm"]),
                "h_norm": float(box["h_norm"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(box, Sequence) and len(box) == 4:
        try:
            return {
                "x_norm": float(box[0]),
                "y_norm": float(box[1]),
                "w_norm": float(box[2]),
                "h_norm": float(box[3]),
            }
        except (TypeError, ValueError):
            return None
    return None


def element_box(
    anchor: Mapping[str, float] | Sequence[float],
    *,
    pad: tuple[float, float] = ELEMENT_PAD_NORM,
    frame: tuple[int, int] | None = None,
) -> dict[str, float] | None:
    """The element box around an anchor, clipped to the frame, or ``None``.

    The anchor is what the client drew -- an OCR word box, or a point turned into a zero-size
    box by the caller.  ``pad`` grows it to a control-sized region.  Clipping is not cosmetic:
    a control at the frame's edge (a back arrow, a corner close) would otherwise produce a crop
    that runs off the image, and PIL silently pads such a crop with black, which then matches
    nothing.
    """
    box = _norm_box(anchor)
    if box is None:
        return None
    x = box["x_norm"] - pad[0]
    y = box["y_norm"] - pad[1]
    w = box["w_norm"] + 2 * pad[0]
    h = box["h_norm"] + 2 * pad[1]
    x = max(0.0, x)
    y = max(0.0, y)
    w = min(w, 1.0 - x)
    h = min(h, 1.0 - y)
    if w <= 0.0 or h <= 0.0:
        return None
    if frame:
        width, height = int(frame[0]), int(frame[1])
        if min(w * width, h * height) < MIN_ELEMENT_SIDE_PX:
            return None
    return {"x_norm": round(x, 4), "y_norm": round(y, 4), "w_norm": round(w, 4), "h_norm": round(h, 4)}


def box_to_pixels(box: Mapping[str, float], frame: tuple[int, int]) -> tuple[int, int, int, int]:
    """``(left, top, right, bottom)`` in the frame's own pixels."""
    width, height = int(frame[0]), int(frame[1])
    left = round(float(box["x_norm"]) * width)
    top = round(float(box["y_norm"]) * height)
    right = round((float(box["x_norm"]) + float(box["w_norm"])) * width)
    bottom = round((float(box["y_norm"]) + float(box["h_norm"])) * height)
    return left, top, right, bottom


def carries_dynamic_text(texts: Iterable[str]) -> bool:
    """Whether any of these strings is a countdown/ratio -- i.e. a template that would rot."""
    for text in texts:
        value = str(text or "").strip()
        if value and DYNAMIC_TEXT.search(value):
            return True
    return False


def candidate_id(page: str, semantic: str, digest: str) -> str:
    """A candidate's identity: page + semantic + a visual digest of the element crop.

    The page is part of it and that is load-bearing (operator §四/§九): the same-looking icon on
    two pages is two different controls, and an id that merged them would make the second page's
    evidence silently answer for the first.
    """
    material = f"{page}|{semantic}|{digest}".encode("utf-8")
    stem = re.sub(r"[^a-z0-9]+", "_", f"{page}_{semantic}".lower()).strip("_")[:48]
    return f"{stem}__{hashlib.sha256(material).hexdigest()[:10]}"


def phash_digest(image: Image.Image, *, size: int = 8) -> str:
    """A perceptual digest of a crop, for dedupe only.

    Deliberately the same idea as ``image_hash.phash`` (downscale, compare to the mean) but
    returned as a hex string: a candidate's identity must be stable across processes, and the
    integer hamming distance the matcher uses is a *comparison*, not an identity.
    """
    small = image.convert("L").resize((size, size), Image.LANCZOS)
    pixels = list(small.tobytes())
    mean = sum(pixels) / len(pixels)
    bits = "".join("1" if value > mean else "0" for value in pixels)
    return f"{int(bits, 2):0{size * size // 4}x}"


@dataclass
class Candidate:
    """One element's record.  Field names follow the operator's §五 list."""

    candidate_id: str
    semantic_id: str
    page: str
    goal: str = ""
    source_frame: str = ""
    source_episode: str = ""
    image_path: str = ""
    context_image_path: str = ""
    bbox: dict[str, float] = field(default_factory=dict)
    frame_size: tuple[int, int] | None = None
    ocr_text: str = ""
    ocr_confidence: float | None = None
    visual_match: str = ""
    recognition_method: str = ""
    semantic_candidates: tuple[str, ...] = ()
    expected_effect: str = ""
    observed_effect: str = ""
    verification_status: str = STATUS_DISCOVERED
    confidence: float = 0.0
    attempt_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    created_at: str = ""
    last_seen_at: str = ""
    template_version: str = ""
    notes: str = ""

    def as_metadata(self) -> dict[str, Any]:
        """The ``metadata.yaml`` payload: the operator's fields, nothing invented."""
        payload = asdict(self)
        payload["bbox_frame_size"] = payload.pop("frame_size")
        return payload


class UiCandidateStore:
    """The candidate directory and its index, as a state file plus pure helpers."""

    def __init__(self, root: Path | str | None = None, *, manifest: Path | str | None = None) -> None:
        self.root = Path(root) if root else CANDIDATE_ROOT
        self.manifest = Path(manifest) if manifest else TEMPLATE_MANIFEST
        self.index_path = self.root / INDEX_NAME
        self._records: dict[str, Candidate] = self._load()

    # ---------------------------------------------------------------- reading / writing

    def _load(self) -> dict[str, Candidate]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[str, Candidate] = {}
        for row in payload.get("candidates") or ():
            if not isinstance(row, Mapping):
                continue
            try:
                data = dict(row)
                data["semantic_candidates"] = tuple(data.get("semantic_candidates") or ())
                size = data.get("frame_size")
                data["frame_size"] = tuple(size) if size else None
                candidate = Candidate(**{k: v for k, v in data.items() if k in Candidate.__dataclass_fields__})
            except (TypeError, ValueError):
                continue
            out[candidate.candidate_id] = candidate
        return out

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "written_at": _now(),
            "count": len(self._records),
            "counts_by_status": self.counts(),
            "candidates": [asdict(record) for record in self._records.values()],
        }
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for record in self._records.values():
            counts[record.verification_status] = counts.get(record.verification_status, 0) + 1
        return counts

    def all(self) -> list[Candidate]:
        return list(self._records.values())

    def get(self, key: str) -> Candidate | None:
        return self._records.get(key)

    def find(self, page: str, semantic: str) -> list[Candidate]:
        return [
            record
            for record in self._records.values()
            if record.page == page and record.semantic_id == semantic
        ]

    # ---------------------------------------------------------------- collecting

    def stage(
        self,
        *,
        frame_path: Path | str,
        page: str,
        semantic: str,
        box_norm: Mapping[str, float] | Sequence[float],
        goal: str = "",
        episode: str = "",
        ocr_text: str = "",
        ocr_confidence: float | None = None,
        recognition_method: str = METHOD_OCR_WORD,
        semantic_candidates: Sequence[str] = (),
        expected_effect: str = "",
        notes: str = "",
        context_pad: tuple[float, float] = CONTEXT_PAD_NORM,
    ) -> Candidate | None:
        """Write one candidate's two crops and metadata; return it, or ``None`` if refused.

        Refusals are all of the same kind -- the frame cannot honestly support the record:
        an unreadable frame, a box that is not on it, or a box too small to be a control.
        Everything else is written, including records that may turn out to be wrong: a
        candidate is a hypothesis with a picture attached, and the status says so.
        """
        frame_path = Path(frame_path)
        box = _norm_box(box_norm)
        if box is None:
            return None
        try:
            with Image.open(frame_path) as source:
                width, height = source.size
                element_px = box_to_pixels(box, (width, height))
                context = element_box(
                    box,
                    pad=(context_pad[0] + ELEMENT_PAD_NORM[0], context_pad[1] + ELEMENT_PAD_NORM[1]),
                )
                if context is None:
                    return None
                context_px = box_to_pixels(context, (width, height))
                element = source.crop(element_px).convert("RGB")
                surroundings = source.crop(context_px).convert("RGB")
        except (OSError, ValueError):
            return None
        if min(element.size) < MIN_ELEMENT_SIDE_PX:
            return None

        digest = phash_digest(element)
        key = candidate_id(page, semantic, digest)
        existing = self._records.get(key)
        directory = self.root / key
        directory.mkdir(parents=True, exist_ok=True)
        element_path = directory / "element.png"
        context_path = directory / "context.png"
        # The same element seen again is the same candidate: the crops already on disk are the
        # evidence for this exact digest, so re-writing them would only cost I/O (and would
        # make "when was this picture taken" unanswerable, which is what `source_frame` is for).
        if not (existing and existing.image_path and Path(existing.image_path).exists()):
            element.save(element_path)
            surroundings.save(context_path)

        record = existing or Candidate(candidate_id=key, semantic_id=semantic, page=page)
        record.image_path = str(element_path.as_posix())
        record.context_image_path = str(context_path.as_posix())
        record.bbox = box
        record.frame_size = (width, height)
        record.source_frame = str(frame_path.as_posix())
        record.source_episode = episode or record.source_episode
        record.goal = goal or record.goal
        record.ocr_text = ocr_text or record.ocr_text
        record.ocr_confidence = ocr_confidence if ocr_confidence is not None else record.ocr_confidence
        record.recognition_method = recognition_method or record.recognition_method
        record.semantic_candidates = tuple(
            dict.fromkeys(tuple(record.semantic_candidates) + tuple(semantic_candidates))
        )
        record.expected_effect = expected_effect or record.expected_effect
        if notes:
            record.notes = notes
        record.confidence = round(float(ocr_confidence or record.confidence or 0.0), 4)
        record.created_at = record.created_at or _now()
        record.last_seen_at = _now()
        if record.verification_status not in (STATUS_VERIFIED, STATUS_FAILED):
            record.verification_status = STATUS_CANDIDATE if semantic else STATUS_DISCOVERED
        # Kept as a sibling of the crops rather than only in the index: the record has to be
        # readable as a file, the way every other candidate in this repository is.
        metadata = self.root / key / "metadata.yaml"
        try:
            import yaml

            metadata.write_text(
                yaml.safe_dump(record.as_metadata(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 - a missing metadata file must not fail a run
            pass
        self._records[key] = record
        return record

    def stage_unlocated(
        self,
        *,
        page: str,
        semantic: str,
        goal: str = "",
        episode: str = "",
        source_frame: str = "",
        expected_effect: str = "",
        notes: str = "",
    ) -> Candidate:
        """Record a named control the machine could NOT locate on this frame, without a crop.

        This is the most common real case and the one an all-or-nothing collector would throw
        away: the route asked for a control by name, nothing (template, ledger, printed word)
        could turn the name into a pixel, and the step died with
        ``SEMANTIC_TARGET_NOT_VERIFIED``.  There is no box to crop -- inventing one would be
        exactly the "裁剪出图片就算有效" mistake -- but there IS a fact worth keeping: on this
        page, this named control was on screen and unlocatable.  The record carries the frame so
        a later pass can find the box with better tools, and the count is what tells the
        development pipeline which controls are actually costing the AUTO steps.
        """
        key = candidate_id(page, semantic, "unlocated")
        record = self._records.get(key)
        if record is None:
            record = Candidate(
                candidate_id=key,
                semantic_id=semantic,
                page=page,
                created_at=_now(),
                verification_status=STATUS_DISCOVERED,
                recognition_method="UNLOCATED",
            )
        record.goal = goal or record.goal
        record.source_episode = episode or record.source_episode
        record.source_frame = source_frame or record.source_frame
        record.expected_effect = expected_effect or record.expected_effect
        record.failure_count += 1
        record.last_seen_at = _now()
        record.notes = notes or (
            "named control could not be located on this frame (no template, no ledger entry, "
            "no printed word); no crop is stored because no region was measured"
        )
        self._records[key] = record
        return record

    def record_attempt(
        self,
        *,
        page: str,
        semantic: str,
        verified: bool,
        observed_effect: str = "",
        expected_effect: str = "",
    ) -> list[Candidate]:
        """Fold one real step's outcome into every candidate for that (page, semantic).

        ``verified`` is the *step's own verifier* verdict, which is what makes this honest: a
        page that changed is not a task that succeeded, and only a passed verifier may promote a
        candidate to ``VERIFIED``.  A failure does not demote a VERIFIED record -- different
        page states produce different outcomes (operator §七) -- it is counted.
        """
        touched: list[Candidate] = []
        for record in self.find(page, semantic):
            if record.verification_status == STATUS_DISCOVERED:
                record.verification_status = STATUS_CANDIDATE
            record.attempt_count += 1
            record.last_seen_at = _now()
            if expected_effect:
                record.expected_effect = expected_effect
            record.observed_effect = observed_effect or record.observed_effect
            if verified:
                record.success_count += 1
                record.verification_status = STATUS_VERIFIED
                record.confidence = max(record.confidence, 0.9)
            else:
                record.failure_count += 1
                if record.verification_status != STATUS_VERIFIED:
                    record.verification_status = STATUS_FAILED
            touched.append(record)
        return touched

    # ---------------------------------------------------------------- ingestion

    def ingest(self, record: Candidate, *, ocr_text: str = "") -> tuple[bool, str]:
        """Write this candidate into the one template manifest, or refuse with a reason.

        Five conditions, straight from the operator's §八, and each one is a refusal with a
        name rather than a silent skip::

            not verified            -> "NOT_VERIFIED"
            dynamic content in crop -> "DYNAMIC_REGION"
            no page / no semantic   -> "SEMANTIC_UNKNOWN"
            template already there  -> "ALREADY_REGISTERED"
            a protected record for the same semantic -> "CONFLICT_WITH_VERIFIED"

        A *variant* -- the same semantic, a new picture -- is written as its own record with its
        own id, which is what the manifest's existing multi-record-per-semantic shape is for
        (``find`` weighs every record for a semantic).  Nothing here ever rewrites a record.
        """
        if record.verification_status != STATUS_VERIFIED:
            return False, "NOT_VERIFIED"
        if not record.page or not record.semantic_id:
            return False, "SEMANTIC_UNKNOWN"
        if carries_dynamic_text([ocr_text, record.ocr_text]):
            return False, "DYNAMIC_REGION"
        try:
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "MANIFEST_UNREADABLE"
        records = payload.get("records")
        if not isinstance(records, list):
            return False, "MANIFEST_UNREADABLE"

        template_id = f"auto__{record.candidate_id}"
        for row in records:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("template_id") or "") == template_id:
                return False, "ALREADY_REGISTERED"
            if str(row.get("semantic") or "") != record.semantic_id:
                continue
            status = str(row.get("status") or "").upper()
            if status in PROTECTED_TEMPLATE_STATUSES:
                # The existing record is the reviewed, protected one: keep it and say so, do
                # not overwrite it and do not lose the evidence either (it stays a candidate).
                return False, "CONFLICT_WITH_VERIFIED"

        frame_size = record.frame_size or (720, 1280)
        try:
            with Image.open(record.image_path) as element:
                width, height = element.size
                TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
                template_path = TEMPLATE_DIR / f"{template_id}.png"
                element.convert("RGB").save(template_path)
        except (OSError, ValueError):
            return False, "CROP_UNREADABLE"

        records.append({
            "semantic": record.semantic_id,
            "template_path": template_path.as_posix(),
            "roi_norm": dict(record.bbox),
            "source": record.source_frame,
            "provenance": "LIVE_CLIENT",
            "reviewed_from": "AUTO_COLLECTION",
            "confidence": round(max(record.confidence, 0.5), 4),
            "status": "VERIFIED",
            "template_id": template_id,
            "parent_screenshot": record.source_frame,
            "width": int(width),
            "height": int(height),
            "note": (
                "Collected automatically from a live frame: this element's declared effect was "
                f"proven by the step's own verifier on page {record.page} "
                f"(observed {record.observed_effect or 'CHANGE'}; frame "
                f"{frame_size[0]}x{frame_size[1]}). Landed by {record.recognition_method}."
            ),
        })
        payload["records"] = records
        payload["count"] = len(records)
        payload["generated_at"] = _now()
        self.manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        record.template_version = template_id
        record.verification_status = STATUS_VERIFIED
        return True, "INGESTED"

    # ---------------------------------------------------------------- retention

    def prune(self, *, limit: int = MAX_CANDIDATES) -> list[str]:
        """Drop the oldest unproven records past the cap; never a VERIFIED one.

        Operator §九: storage is bounded, and "development must not roll back what the AUTO
        learned" -- so this deletes candidate *records*, and the crops they own, for everything
        that is still only a hypothesis.  Order is by value of the hypothesis, not by age alone:
        a ``FAILED`` record has already been exercised and did not hold, so it goes before a
        ``DISCOVERED`` one that has never been tried, and a ``CANDIDATE`` with attempts behind it
        outlives both.  Within a status, oldest ``last_seen_at`` first.
        """
        if len(self._records) <= limit:
            return []
        rank = {STATUS_FAILED: 0, STATUS_DISCOVERED: 1, STATUS_CANDIDATE: 2}
        prunable = [
            record
            for record in self._records.values()
            if record.verification_status != STATUS_VERIFIED
        ]
        prunable.sort(
            key=lambda item: (
                rank.get(item.verification_status, 3),
                item.last_seen_at or item.created_at or "",
            )
        )
        dropped: list[str] = []
        for record in prunable:
            if len(self._records) - len(dropped) <= limit:
                break
            dropped.append(record.candidate_id)
            directory = self.root / record.candidate_id
            for name in ("element.png", "context.png", "metadata.yaml"):
                try:
                    (directory / name).unlink()
                except OSError:
                    pass
            try:
                directory.rmdir()
            except OSError:
                pass
        for key in dropped:
            self._records.pop(key, None)
        return dropped
