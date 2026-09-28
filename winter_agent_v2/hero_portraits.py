"""Shared hero identity from a named portrait library.

Identity samples are public game art and are shared across roles. Ownership,
availability and march usage are deliberately left to role-scoped live state.
Only current-frame portrait crops can authorize a hero identity; class badges
and fixed historical selection-list positions never do.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "knowledge" / "heroes" / "portrait_library"
INDEX = LIBRARY / "index.json"

# Normalized PAGE_FORMATION card rectangles measured from live 720x1280
# formation captures. They are page geometry, scaled from the current frame;
# the portrait region excludes the mutable badge, level and star overlay.
HERO_CARD_RECTS = (
    (0.1292, 0.2422, 0.2139, 0.2109),
    (0.3917, 0.2422, 0.2139, 0.2109),
    (0.6542, 0.2422, 0.2139, 0.2109),
)
# The source roster and PAGE_FORMATION hero cards share the same 154x270
# card scale. The library stores the card-relative 120x130 core at
# x=20..140, y=28..158; keep that exact core here so matching compares the
# same face/hat pixels rather than rescaling a truncated crop.
PORTRAIT_CORE = (20 / 154, 28 / 270, 140 / 154, 158 / 270)
IDENTITY_MIN_SCORE = 0.82
IDENTITY_MIN_MARGIN = 0.12
PICKER_FACE_VARIANT = "HERO_PICKER_FACE_CORE"
PICKER_LIST_ROI = (0.09, 0.448, 0.91, 0.735)
PICKER_CARD_FACE_OFFSET = (10, 32)
PICKER_CARD_REFERENCE_SIZE = (117, 117)

_LIB_CACHE: tuple[str, int, dict[str, Any]] | None = None


def load_library(path: Path = INDEX) -> dict[str, Any]:
    global _LIB_CACHE
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {"samples": {}}
    cache_key = str(path.resolve())
    if _LIB_CACHE and _LIB_CACHE[0] == cache_key and _LIB_CACHE[1] == stamp:
        return _LIB_CACHE[2]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"samples": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), dict):
        payload = {"samples": {}}
    _LIB_CACHE = (cache_key, stamp, payload)
    return payload


def append_verified_sample(
    hero_id: str,
    display_name: str,
    portrait: Any,
    *,
    source_page: str,
    source_frame: str,
    source_bbox: tuple[int, int, int, int] | list[int],
    source_role: str,
    name_evidence: Mapping[str, Any],
    library_path: Path = INDEX,
    variant: str = "LIVE_OBSERVED",
) -> Path:
    """Append, never replace, a portrait sample after an explicit name binding.

    ``name_evidence`` must identify a detail/title frame or another explicit
    binding path. An unlabelled face alone is never enough to create a hero ID.
    """
    from datetime import datetime, timezone

    hero_key = str(hero_id or "").strip()
    name = str(display_name or "").strip()
    evidence = dict(name_evidence or {})
    evidence_name = str(evidence.get("ocr_name") or "").strip()
    confidence = float(evidence.get("ocr_confidence") or 0.0)
    binding = str(evidence.get("binding_method") or "").strip()
    if not hero_key or not name or evidence_name != name or confidence < 0.8 or not binding:
        raise ValueError("portrait sample needs a matching name, >=0.8 name evidence, and explicit binding_method")
    image = _as_rgb_image(portrait)
    if image.width < 24 or image.height < 24:
        raise ValueError("portrait sample is too small")
    payload = load_library(library_path)
    samples = payload.setdefault("samples", {})
    record = samples.get(hero_key)
    if record is not None and str(record.get("display_name") or "") != name:
        raise ValueError(f"refusing conflicting label for {hero_key}")
    if record is None:
        record = {
            "hero_id": hero_key,
            "display_name": name,
            "aliases": [],
            "portrait_samples": [],
            "confidence": confidence,
            "name_binding_status": "LIVE_DETAIL_TITLE_VERIFIED",
        }
        samples[hero_key] = record
    rows = record.setdefault("portrait_samples", [])
    next_id = len(rows) + 1
    hero_dir = library_path.parent / hero_key.lower()
    hero_dir.mkdir(parents=True, exist_ok=True)
    destination = hero_dir / f"sample_{next_id:03d}.png"
    while destination.exists():
        next_id += 1
        destination = hero_dir / f"sample_{next_id:03d}.png"
    image.save(destination, optimize=True)
    row = {
        "path": destination.relative_to(library_path.parent).as_posix(),
        "variant": str(variant),
        "status": "CANDIDATE",
        "fingerprint": {},
        "source_page": str(source_page),
        "source_frame": str(source_frame),
        "source_bbox": [int(v) for v in source_bbox],
        "source_role": str(source_role),
        "name_evidence": evidence,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from .image_hash import phash
        row["fingerprint"] = {"phash": phash(image)}
    except Exception:  # pHash is an index hint, not an admission condition
        pass
    rows.append(row)
    payload["last_built_at"] = row["observed_at"]
    temp = library_path.with_suffix(library_path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(library_path)
    load_library(library_path)
    return destination


def _as_rgb_image(image: Any) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (str, Path)):
        with Image.open(image) as opened:
            return opened.convert("RGB")
    return Image.fromarray(image).convert("RGB")


def match_portrait(
    query: Any,
    *,
    library_path: Path = INDEX,
    min_score: float = IDENTITY_MIN_SCORE,
    min_margin: float = IDENTITY_MIN_MARGIN,
) -> dict[str, Any]:
    """Match a portrait crop, retaining best/second scores and abstaining.

    The crop may be scaled. We resize candidate samples to the current crop,
    then use normalized correlation. Card status (selected/greyed) is not
    folded into identity and must be read separately.
    """
    import cv2
    import numpy as np

    roi = _as_rgb_image(query)
    q = cv2.cvtColor(np.asarray(roi), cv2.COLOR_RGB2GRAY)
    if q.size == 0 or float(q.std()) < 5.0:
        return {"status": "UNKNOWN", "hero_id": None, "best_candidate": None,
                "best_score": 0.0, "second_candidate": None, "second_score": 0.0,
                "margin": 0.0}
    library = load_library(library_path)
    scores: list[tuple[float, str, str]] = []
    for hero_id, record in library.get("samples", {}).items():
        if not isinstance(record, Mapping):
            continue
        best = -1.0
        best_path = ""
        for sample in record.get("portrait_samples") or ():
            if not isinstance(sample, Mapping):
                continue
            try:
                with Image.open(library_path.parent / str(sample["path"])) as opened:
                    candidate = opened.convert("RGB")
                if candidate.size != roi.size:
                    candidate = candidate.resize(roi.size, Image.Resampling.BILINEAR)
                t = cv2.cvtColor(np.asarray(candidate), cv2.COLOR_RGB2GRAY)
                value = float(cv2.matchTemplate(q, t, cv2.TM_CCOEFF_NORMED)[0, 0])
            except (OSError, KeyError, ValueError, cv2.error):
                continue
            if value > best:
                best, best_path = value, str(sample.get("path") or "")
        if best >= 0:
            scores.append((best, str(hero_id), best_path))
    scores.sort(reverse=True)
    best = scores[0] if scores else (0.0, "", "")
    second = scores[1] if len(scores) > 1 else (0.0, "", "")
    margin = best[0] - second[0]
    confirmed = best[0] >= min_score and margin >= min_margin
    return {
        "status": "IDENTITY_CONFIRMED" if confirmed else ("AMBIGUOUS" if best[0] >= min_score else "UNKNOWN"),
        "hero_id": best[1] if confirmed else None,
        "display_name": (library["samples"].get(best[1], {}).get("display_name") if confirmed else None),
        "best_candidate": best[1] or None,
        "best_score": round(best[0], 4),
        "best_sample": best[2] or None,
        "second_candidate": second[1] or None,
        "second_score": round(second[0], 4),
        "margin": round(margin, 4),
    }


def match_picker_hero(
    frame: Any,
    hero_id: str,
    *,
    picker_page_verified: bool,
    library_path: Path = INDEX,
    min_score: float = 0.93,
    min_margin: float = 0.12,
) -> dict[str, Any]:
    """Locate one named hero in the current picker using picker-page samples.

    The caller must first verify the visible 英雄选择 heading. The returned
    tap point is the face patch found in this frame, never a stored screen
    coordinate. Missing or visually changed identities abstain.
    """
    import cv2
    import numpy as np

    if not picker_page_verified:
        return {"status": "BLOCKED_PAGE_UNVERIFIED", "hero_id": hero_id}
    image = _as_rgb_image(frame)
    payload = load_library(library_path)
    records = payload.get("samples", {})
    target = str(hero_id or "").strip()
    if target not in records:
        return {"status": "NO_PICKER_SAMPLE", "hero_id": target}
    width, height = image.size
    x0, y0, x1, y1 = PICKER_LIST_ROI
    region_box = (round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height))
    region = image.crop(region_box)
    q = cv2.cvtColor(np.asarray(region), cv2.COLOR_RGB2GRAY)
    scale_base = width / 720.0
    templates: dict[str, list[tuple[Image.Image, str]]] = {}
    for candidate_id, record in records.items():
        rows = []
        for sample in record.get("portrait_samples") or ():
            if not isinstance(sample, Mapping) or sample.get("variant") != PICKER_FACE_VARIANT:
                continue
            try:
                with Image.open(library_path.parent / str(sample["path"])) as opened:
                    rows.append((opened.convert("RGB"), str(sample.get("path") or "")))
            except (OSError, KeyError, ValueError):
                continue
        if rows:
            templates[str(candidate_id)] = rows
    if target not in templates:
        return {"status": "NO_PICKER_SAMPLE", "hero_id": target}
    best_target: tuple[float, tuple[int, int, int, int], str] | None = None
    for template, sample_path in templates[target]:
        for factor in (0.92, 1.0, 1.08):
            scale = scale_base * factor
            tw = max(24, round(template.width * scale))
            th = max(20, round(template.height * scale))
            resized = template.resize((tw, th), Image.Resampling.BILINEAR)
            t = cv2.cvtColor(np.asarray(resized), cv2.COLOR_RGB2GRAY)
            if t.shape[0] > q.shape[0] or t.shape[1] > q.shape[1]:
                continue
            matrix = cv2.matchTemplate(q, t, cv2.TM_CCOEFF_NORMED)
            _, score, _, point = cv2.minMaxLoc(matrix)
            if best_target is None or score > best_target[0]:
                absolute = (point[0] + region_box[0], point[1] + region_box[1], tw, th)
                best_target = (float(score), absolute, sample_path)
    if best_target is None:
        return {"status": "NO_PICKER_SAMPLE", "hero_id": target}
    score, bbox, sample_path = best_target
    # Compare identities at the SAME face location. Other available heroes are
    # expected elsewhere in the list, so global best scores are not evidence of
    # ambiguity. This local contrast rejects look-alikes without penalizing a
    # second correctly matched hero in another row.
    patch = np.asarray(image.crop((bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3])))
    query_gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    competitor_scores: list[tuple[float, str]] = []
    for candidate_id, rows in templates.items():
        if candidate_id == target:
            continue
        local_best = -1.0
        for template, _path in rows:
            resized = template.resize((bbox[2], bbox[3]), Image.Resampling.BILINEAR)
            candidate = np.asarray(resized)
            color_score = float(cv2.matchTemplate(patch, candidate, cv2.TM_CCOEFF_NORMED)[0, 0])
            gray_score = float(cv2.matchTemplate(
                query_gray,
                cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY),
                cv2.TM_CCOEFF_NORMED,
            )[0, 0])
            local_best = max(local_best, 0.7 * color_score + 0.3 * gray_score)
        if local_best >= 0:
            competitor_scores.append((local_best, candidate_id))
    competitor_scores.sort(reverse=True)
    second_score = competitor_scores[0][0] if competitor_scores else 0.0
    margin = score - second_score
    status = "MATCHED" if score >= min_score and margin >= min_margin else (
        "AMBIGUOUS" if score >= min_score else "UNKNOWN"
    )
    return {
        "status": status,
        "hero_id": target,
        # Identity confidence and game state are separate. A face match does
        # not prove that the hero is selectable; only the current frame's
        # selection brackets prove SELECTED. Until another visible state cue
        # is positively read, keep availability UNKNOWN.
        "hero_state": "SELECTED" if picker_card_selected(image, {
            "bbox": list(bbox),
        }) else "UNKNOWN",
        "best_score": round(score, 4),
        "second_score": round(second_score, 4),
        "margin": round(margin, 4),
        "best_competitor": competitor_scores[0][1] if competitor_scores else None,
        "bbox": list(bbox),
        "tap_point": [bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2],
        "tap_norm": [round((bbox[0] + bbox[2] / 2) / width, 6),
                     round((bbox[1] + bbox[3] / 2) / height, 6)],
        "source_sample": sample_path,
    }


def picker_card_selected(frame: Any, match: Mapping[str, Any]) -> bool:
    """Require the game's four corner brackets around the matched picker card."""
    import cv2
    import numpy as np

    image = _as_rgb_image(frame)
    bbox = match.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    width = image.width
    scale = width / 720.0
    patch_x, patch_y, patch_w, patch_h = (int(value) for value in bbox)
    card_x = round(patch_x - PICKER_CARD_FACE_OFFSET[0] * scale)
    card_y = round(patch_y - PICKER_CARD_FACE_OFFSET[1] * scale)
    card_w = round(PICKER_CARD_REFERENCE_SIZE[0] * scale)
    card_h = round(PICKER_CARD_REFERENCE_SIZE[1] * scale)
    margin = round(17 * scale)
    leg = round(20 * scale)
    boxes = (
        (card_x - margin, card_y - margin, card_x + leg, card_y + leg),
        (card_x + card_w - leg, card_y - margin, card_x + card_w + margin, card_y + leg),
        (card_x - margin, card_y + card_h - leg, card_x + leg, card_y + card_h + margin),
        (card_x + card_w - leg, card_y + card_h - leg, card_x + card_w + margin, card_y + card_h + margin),
    )
    hsv = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2HSV)
    required = max(12, round(45 * scale * scale))
    counts = []
    for x0, y0, x1, y1 in boxes:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(image.width, x1), min(image.height, y1)
        patch = hsv[y0:y1, x0:x1]
        if patch.size == 0:
            return False
        gold = (patch[:, :, 0] >= 12) & (patch[:, :, 0] <= 42) & (patch[:, :, 1] > 100) & (patch[:, :, 2] > 130)
        counts.append(int(gold.sum()))
    return min(counts, default=0) >= required


def formation_slot_boxes(size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    width, height = (int(size[0]), int(size[1]))
    if width <= 0 or height <= 0:
        return []
    return [
        (round(x * width), round(y * height), round(w * width), round(h * height))
        for x, y, w, h in HERO_CARD_RECTS
    ]


def portrait_roi(card: Image.Image) -> Image.Image:
    x0, y0, x1, y1 = PORTRAIT_CORE
    width, height = card.size
    return card.crop((round(x0 * width), round(y0 * height),
                      round(x1 * width), round(y1 * height)))


def recognize_formation_heroes(frame: Any) -> dict[str, Any]:
    """Return identity and occupancy candidates for all three live march slots."""
    image = _as_rgb_image(frame)
    from .hero_badge import detect_badges, badge_slot

    badges = detect_badges(image)
    slot_badges: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    for badge in badges:
        slot = badge_slot(int(badge["centre"][0]), image.size[0])
        slot_badges.setdefault(slot, []).append(badge)
    slots = []
    for number, box in enumerate(formation_slot_boxes(image.size), 1):
        x, y, w, h = box
        card = image.crop((x, y, x + w, y + h))
        identity = match_portrait(portrait_roi(card))
        detected_badges = slot_badges.get(number, [])
        # Empty slots carry a large white outlined plus at their center; filled
        # cards have portrait pixels there. An unreadable/toast-dimmed center is
        # UNKNOWN, never silently treated as empty.
        import numpy as np
        cx, cy = round(0.5 * w), round(0.5 * h)
        center = np.asarray(card.crop((cx - 24, cy - 24, cx + 24, cy + 24)))
        plus_white_fraction = float(np.all(center > 210, axis=2).mean())
        if detected_badges or identity["best_score"] >= 0.55:
            state = "OCCUPIED"
        elif plus_white_fraction >= 0.15:
            state = "EMPTY"
        else:
            state = "UNKNOWN"
        occupied = state == "OCCUPIED"
        slots.append({
            "slot": number,
            "state": state,
            # ``state`` describes slot occupancy for existing callers.
            # ``hero_state`` is a distinct, conservative game-state field.
            # A recognized portrait on PAGE_FORMATION is selected in this
            # march; an unreadable occupied slot stays UNKNOWN, and an empty
            # slot has no hero state at all.
            "hero_state": (
                "SELECTED" if occupied and identity["status"] == "IDENTITY_CONFIRMED"
                else ("UNKNOWN" if occupied or state == "UNKNOWN" else None)
            ),
            "hero_id": identity["hero_id"],
            "display_name": identity.get("display_name"),
            "identity_status": identity["status"] if occupied else "NO_PORTRAIT_MATCH",
            "confidence": identity["best_score"],
            "best_candidate": identity["best_candidate"],
            "second_candidate": identity["second_candidate"],
            "margin": identity["margin"],
            "badge_observed": bool(detected_badges),
            "badge_geometry": [dict(b) for b in detected_badges],
            "empty_plus_white_fraction": round(plus_white_fraction, 4),
            "portrait_roi": [x, y, w, h],
        })
    return {
        "status": "OBSERVED",
        "page": "PAGE_FORMATION",
        "slots": slots,
        "heroes": [slot for slot in slots if slot["state"] == "OCCUPIED"],
        "empty_slots": [slot["slot"] for slot in slots if slot["state"] == "EMPTY"],
        "observed_resolution": list(image.size),
        "source": "CURRENT_FRAME_PORTRAIT_LIBRARY",
    }


def gather_hero_for_resource(resource_type: str) -> str | None:
    """Resolve only the exact live-confirmed specialist for a gather resource."""
    try:
        payload = json.loads((ROOT / "knowledge/heroes/gathering_specialties.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    key = str(resource_type or "").strip().upper()
    record = (payload.get("resources") or {}).get(key)
    if not isinstance(record, Mapping) or record.get("status") != "LIVE_VERIFIED":
        return None
    hero_id = str(record.get("hero_id") or "")
    return hero_id or None


def evaluate_gather_formation(resource_type: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    """Strict resource-specialist-or-empty decision from the current formation."""
    target = gather_hero_for_resource(resource_type)
    if not target:
        return {"status": "BLOCKED_UNKNOWN_RESOURCE", "expected_hero_id": None, "remove_slots": []}
    slots = [item for item in (observation.get("slots") or ()) if isinstance(item, Mapping)]
    if len(slots) != 3 or observation.get("status") != "OBSERVED":
        return {"status": "BLOCKED_UNOBSERVED_FORMATION", "expected_hero_id": target, "remove_slots": []}
    occupied = [item for item in slots if item.get("state") == "OCCUPIED"]
    if any(item.get("state") == "UNKNOWN" for item in slots):
        return {"status": "BLOCKED_REOBSERVE", "expected_hero_id": target, "remove_slots": []}
    unknown = [item for item in occupied if item.get("identity_status") != "IDENTITY_CONFIRMED"]
    correct = [item for item in occupied if item.get("hero_id") == target]
    wrong = [item for item in occupied if item.get("hero_id") != target]
    if unknown:
        return {"status": "CLEANUP_REQUIRED", "expected_hero_id": target,
                "remove_slots": sorted({int(item["slot"]) for item in unknown + wrong})}
    if len(correct) == 1 and not wrong:
        return {"status": "READY_WITH_SPECIALIST", "expected_hero_id": target,
                "remove_slots": []}
    if not occupied and len(observation.get("empty_slots") or ()) == 3:
        availability = str(observation.get("specialist_availability") or "UNKNOWN").upper()
        if availability in {"UNAVAILABLE", "IN_USE", "NOT_OWNED", "LOCKED"}:
            return {"status": "READY_EMPTY", "expected_hero_id": target,
                    "availability": availability, "remove_slots": []}
        if availability == "AVAILABLE":
            return {"status": "SELECT_SPECIALIST_REQUIRED", "expected_hero_id": target,
                    "availability": availability, "remove_slots": []}
        # The gather contract is exact specialist OR no hero. If the current
        # role cannot positively establish specialist identity/availability,
        # an empty formation is the safe valid fallback; do not stall the
        # resource march or substitute a battle/gathering hero from elsewhere.
        return {"status": "READY_EMPTY", "expected_hero_id": target,
                "availability": availability, "fallback_reason": "SPECIALIST_NOT_CONFIRMED_USE_EMPTY",
                "remove_slots": []}
    return {"status": "CLEANUP_REQUIRED", "expected_hero_id": target,
            "remove_slots": [int(item["slot"]) for item in (wrong or occupied)]}
