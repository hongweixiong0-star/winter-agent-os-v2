from __future__ import annotations

import hashlib
import re
import sys
import time
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PIL import Image

from .models import MarchState, Page, WorldState


@dataclass(frozen=True)
class OCRToken:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class OCRResult:
    tokens: tuple[OCRToken, ...]
    backend: str
    cached: bool = False

    @property
    def text(self) -> str:
        return "\n".join(token.text for token in self.tokens)


class OCRBackend(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> tuple[OCRToken, ...]: ...


class RapidOCRBackend:
    """Small optional adapter around the third-party RapidOCR runtime.

    `module_path` may point to a separately installed site-packages directory.
    No legacy Agent code or architecture is imported.
    """

    name = "rapidocr_onnxruntime"

    def __init__(self, module_path: Path | None = None) -> None:
        if module_path is not None:
            resolved = str(module_path.resolve())
            if resolved not in sys.path:
                sys.path.insert(0, resolved)
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()

    def recognize(self, image: Image.Image) -> tuple[OCRToken, ...]:
        import numpy as np

        rows, _ = self._engine(np.asarray(image.convert("RGB")))
        if not rows:
            return ()
        return tuple(
            OCRToken(
                text=str(row[1]).strip(),
                confidence=float(row[2]),
                box=tuple((float(point[0]), float(point[1])) for point in row[0]),
            )
            for row in rows
            if str(row[1]).strip()
        )


class ResilientOCRBackend:
    """Bounded local OCR retry with short exponential backoff.

    Adapted as a V2-native pattern after comparing public WOS automation
    implementations. It wraps the existing backend and does not introduce an
    OCR service, worker manager, or second runtime.
    """

    def __init__(self, backend: OCRBackend, *, retries: int = 2, initial_backoff: float = 0.15,
                 sleeper=time.sleep) -> None:
        self.backend = backend
        self.retries = max(0, int(retries))
        self.initial_backoff = max(0.0, float(initial_backoff))
        self.sleeper = sleeper
        self.name = f"resilient:{backend.name}"

    def recognize(self, image: Image.Image) -> tuple[OCRToken, ...]:
        delay = self.initial_backoff
        for attempt in range(self.retries + 1):
            try:
                return self.backend.recognize(image)
            except (RuntimeError, OSError, ValueError):
                if attempt >= self.retries:
                    raise
                self.sleeper(delay)
                delay *= 2
        return ()


class OCRService:
    """ROI-normalized OCR with screenshot-hash caching."""

    def __init__(self, backend: OCRBackend) -> None:
        self.backend = backend
        self._cache: dict[str, OCRResult] = {}

    @staticmethod
    def _roi_key(roi: dict[str, float] | None) -> str:
        if roi is None:
            return "FULL"
        return ":".join(f"{roi[key]:.6f}" for key in ("x_norm", "y_norm", "w_norm", "h_norm"))

    def recognize(
        self,
        image_path: Path,
        roi: dict[str, float] | None = None,
        upscale: int = 1,
    ) -> OCRResult:
        """OCR the frame (or an ROI of it), optionally after enlarging the crop.

        ``upscale`` exists for very small ROIs.  The recognizer fragments a tiny
        number at native size and the fragments do not agree, which silently
        yields a wrong number; enlarging the crop first returns one clean token.
        Measured on production frames (see :data:`HUD_STAMINA_UPSCALE`).
        """
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        key = f"{digest}:{self._roi_key(roi)}:{self.backend.name}:x{upscale}"
        if key in self._cache:
            previous = self._cache[key]
            return OCRResult(previous.tokens, previous.backend, cached=True)
        with Image.open(image_path) as source:
            image = source.convert("RGB")
            if roi is not None:
                width, height = image.size
                left = round(roi["x_norm"] * width)
                top = round(roi["y_norm"] * height)
                right = round((roi["x_norm"] + roi["w_norm"]) * width)
                bottom = round((roi["y_norm"] + roi["h_norm"]) * height)
                if left < 0 or top < 0 or right > width or bottom > height or right <= left or bottom <= top:
                    raise ValueError("OCR_ROI_OUT_OF_BOUNDS")
                image = image.crop((left, top, right, bottom))
            if upscale > 1:
                image = image.resize((image.width * upscale, image.height * upscale), Image.LANCZOS)
            result = OCRResult(self.backend.recognize(image), self.backend.name)
        self._cache[key] = result
        return result


class OCRPageClassifier:
    """Conservative exact-keyword fallback; ambiguous OCR stays UNKNOWN.

    A keyword may only be listed here when it identifies the *page*, never when
    it is a label that also appears elsewhere in the HUD.  ``常规活动`` was
    removed for exactly that reason: it is a button label on the world map's
    event rail, and it appeared with 0.998 confidence on an ordinary map frame.
    Combined with a template layer that had no map anchor for that layout, it
    made the world map classify as ``Page.EVENT`` — which is what turned a
    successfully dispatched march into ``DISPATCH_NOT_PROVEN`` 28 times.
    ``最强王国`` is the event page's own title and remains valid evidence.

    The general rule for future additions: if the string can be seen while the
    player is *not* on that page, it cannot identify the page.
    """

    RULES: tuple[tuple[Page, tuple[str, ...]], ...] = (
        (Page.EVENT, ("最强王国",)),
        (Page.ALLIANCE, ("联盟科技", "联盟互助", "联盟永续", "联盟宝箱")),
        (Page.RESEARCH, ("科技研究",)),
        (Page.INTEL, ("情报",)),
        (Page.DAILY, ("每日任务",)),
        (Page.HERO, ("英雄招募",)),
    )

    def __init__(self, minimum_confidence: float = 0.88) -> None:
        self.minimum_confidence = minimum_confidence

    def classify(self, result: OCRResult) -> WorldState:
        eligible = [token for token in result.tokens if token.confidence >= self.minimum_confidence]
        exact_texts = {token.text.strip() for token in eligible}
        # Current-client shop skins vary, while the real-currency price is the
        # stable action semantic. OCR may replace the currency glyph under a
        # legacy locale, but a high-confidence decimal price remains intact.
        # Treat it only as a hard-block popup; this never authorizes a click.
        if any(re.search(r"\d{1,5}[.,]\d{2}$", text) for text in exact_texts):
            return WorldState(
                page=Page.POPUP,
                popup="REAL_MONEY_OFFER",
                rewards={"real_money_cost": True, "action": "BLOCKED"},
                confidence=max(token.confidence for token in eligible),
            )
        found: list[Page] = []
        for page, alternatives in self.RULES:
            if any(keyword in exact_texts for keyword in alternatives):
                found.append(page)
        if "训练中" in exact_texts and any(text in exact_texts for text in ("盾兵营", "矛兵营", "射手营")):
            found.append(Page.TRAINING)
        if len(set(found)) != 1:
            return WorldState(page=Page.UNKNOWN, confidence=0.0)
        page = found[0]
        confidence = max(token.confidence for token in eligible)
        alliance: dict[str, object] = {}
        daily: dict[str, object] = {}
        research: dict[str, object] = {}
        training: dict[str, object] = {}
        events: dict[str, object] = {}
        if page is Page.EVENT:
            texts = [token.text.strip() for token in eligible]
            event_name = next((text for text in texts if text not in {"常规活动", "排行榜", "本期英雄", "备战阶段", "子阶段目标", "勋章奖励", "奖励详情"} and text in {"最强王国", "军备竞赛"}), None)
            current_points = None
            remaining_seconds = None
            reward_tiers: list[int] = []
            scoring_stage = None
            for text in texts:
                current = re.search(r"我的积分[：:]\s*([0-9,]+)", text)
                if current: current_points = int(current.group(1).replace(",", ""))
                timer = re.search(r"(.+?)\s*(\d{1,2}):(\d{2}):(\d{2})$", text)
                if timer:
                    scoring_stage = timer.group(1).strip()
                    remaining_seconds = int(timer.group(2)) * 3600 + int(timer.group(3)) * 60 + int(timer.group(4))
                if re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", text):
                    value = int(text.replace(",", ""))
                    if value <= 10_000_000:
                        reward_tiers.append(value)
            # The largest visible personal milestone is only a candidate
            # target. Goal planning may choose a lower F2P tier after costs
            # are known; alliance totals are excluded by UI ordering/scale.
            personal_tiers = tuple(sorted(set(reward_tiers[:3])))
            next_tier = next((tier for tier in personal_tiers if current_points is not None and tier > current_points), None)
            minimum = {
                "event_id": event_name or "CURRENT_EVENT",
                "name": event_name or "CURRENT_EVENT",
                "current_points": current_points,
                "reward_tiers": personal_tiers,
                "target_points": next_tier,
                "points_missing": max(0, next_tier - current_points) if next_tier is not None and current_points is not None else 0,
                "remaining_seconds": remaining_seconds,
                "scoring_stage": scoring_stage,
                "all_target_rewards_claimed": False,
                "source": "LIVE_CLIENT_OCR",
            }
            events = {"active_event": event_name, "minimum_guarantee": minimum}
        if page is Page.ALLIANCE:
            texts = [token.text for token in eligible]
            alliance["section"] = "TECHNOLOGY" if any("联盟科技" in text for text in texts) else "HELP"
            if any("联盟永续" in text for text in texts):
                alliance["section"] = "TECHNOLOGY"
            if "联盟宝箱" in exact_texts:
                alliance["section"] = "GIFTS"
            for text in texts:
                if "您的捐献" in text:
                    number_groups = re.findall(r"[0-9]+", text.split("您的捐献", 1)[1])
                    if number_groups:
                        alliance["personal_contribution"] = int("".join(number_groups))
                attempts = re.search(r"次数[：:]\s*(\d+)\s*/\s*(\d+)", text)
                if attempts:
                    alliance["attempts_remaining"] = int(attempts.group(1))
            contribution_screen = any("恢复1次捐献次数" in text for text in texts)
            if contribution_screen:
                alliance.update({"status":"CONTRIBUTED", "contribution":240 if "240" in exact_texts else 120})
            elif "10,000" in exact_texts and "捐献" in exact_texts:
                alliance.update({"status":"AVAILABLE", "resource":"MEAT", "cost":10000})
            if alliance.get("section") == "GIFTS":
                for text in texts:
                    progress = re.fullmatch(r"([0-9,]+)\s*/\s*150,000", text)
                    if progress:
                        alliance.update({"gift_progress":int(progress.group(1).replace(",", "")), "gift_progress_target":150000})
                    daily = re.search(r"每日战利品宝箱上限[：:]\s*(\d+)\s*/\s*(\d+)", text)
                    if daily:
                        alliance.update({"daily_claimed":int(daily.group(1)), "daily_limit":int(daily.group(2))})
                visible_claim_buttons = sum(1 for text in texts if text == "领取")
                claimable = "一键领取" in exact_texts or visible_claim_buttons > 0
                claimed_visible = sum(1 for text in texts if text == "已领取")
                alliance.update({
                    "tab":"ALLY_GIFT" if any("购买含有盟友赠礼" in text for text in texts) else "VICTORY_LOOT",
                    "status":"CLAIMABLE" if claimable else "CLAIMED" if claimed_visible else "UNKNOWN",
                    "visible_claimed":claimed_visible,
                    "visible_claim_buttons":visible_claim_buttons,
                })
        if page is Page.DAILY:
            texts = [token.text.strip() for token in eligible]
            task = next((re.search(r"完成联盟捐献\s*(\d+)\s*次\s*[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]", text) for text in texts if "完成联盟捐献" in text), None)
            if task:
                goal = int(task.group(1))
                daily.update({"task_id":f"ALLIANCE_CONTRIBUTE_{goal}", "progress":int(task.group(2)), "goal":int(task.group(3))})
            milestone_end = next((index for index, text in enumerate(texts) if text == "325"), -1)
            if milestone_end >= 0:
                activity = next((int(text) for text in texts[milestone_end + 1:] if re.fullmatch(r"\d{1,3}", text)), None)
                if activity is not None:
                    daily["activity"] = activity
            claimable = "一键领取" in exact_texts
            daily.update({"status":"CLAIMABLE" if claimable else "AVAILABLE", "claimable_count":1 if claimable else 0})
        if page is Page.TRAINING:
            training.update({"status":"IN_PROGRESS", "queue_available":False})
            if "盾兵营" in exact_texts:
                training["troop_type"] = "INFANTRY"
            elif "矛兵营" in exact_texts:
                training["troop_type"] = "LANCER"
            elif "射手营" in exact_texts:
                training["troop_type"] = "MARKSMAN"
            for text in exact_texts:
                timer = re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text)
                if timer:
                    training["timer"] = timer.group(0)
                count = re.search(r"正在训练\s*([0-9,]+)\s*位", text)
                if count:
                    training["batch_count"] = int(count.group(1).replace(",", ""))
        if page is Page.RESEARCH:
            texts = [token.text.strip() for token in eligible]
            if "病房扩建VII" in exact_texts:
                research.update({"node":"WARD_EXPANSION_VII", "name":"病房扩建VII", "branch":"GROWTH"})
                if "2/3" in exact_texts:
                    research["level_progress"] = "2/3"
            for text in texts:
                timer = re.fullmatch(r"(?:(\d+)天)?(\d{1,2}:\d{2}:\d{2})", text)
                if timer:
                    research.update({
                        "timer": f"{timer.group(1)}d{timer.group(2)}" if timer.group(1) else timer.group(2),
                        "status": "IN_PROGRESS",
                        "queue_available": False,
                    })
                    break
        return WorldState(page=page, alliance=alliance, daily=daily, research=research, training=training, events=events, confidence=confidence)


# --- world-map HUD stamina gauge -------------------------------------------
# ``world.stamina`` used to be written only on the Intel page (a single OCR
# read of a number there), so on the world map -- where every decision is made
# -- "stamina is full" was unobservable and ``AVOID_STAMINA_WASTE`` could never
# be discovered, which forced AUTO back to gathering.  The operator directive
# of 2026-09-14 makes spending stamina the top priority, so the gauge has to be
# readable from the map itself.
#
# Measured, not eyeballed, on a live 720x1280 frame with
# ``tools/calibrate_hud_stamina.py``: the white stamina number sits at
# x 0.046-0.089, y 0.080-0.091 inside the gauge pill that hangs under the
# avatar in the top-left HUD corner.  The ROI adds a small margin so a longer
# read ("200/200") still fits inside it.
HUD_STAMINA_ROI = {"x_norm": 0.040, "y_norm": 0.0755, "w_norm": 0.058, "h_norm": 0.019}

# The gauge crop is only 42x24 px, and at that size the recognizer splits one
# number into overlapping fragments that disagree with each other.  Measured on
# the production frames kept in
# ``dataset/truth_audit/rescue_start_production_20260914`` (2026-09-14):
#   166 -> '16'(0.975) + '66'(0.937) + '6'(0.999)   -> merged read 16   WRONG
#   189 -> '18'(0.999) + '9'(0.890)                 -> merged read 18   WRONG
# Both are plain digit losses in a value the whole stamina-first policy hangs
# on, and the fragment merge in :func:`parse_stamina_number` cannot recover them
# because the first token covers the second's left edge while the token that
# actually carries the last digit is either below the confidence gate or looks
# like an overlap.  Enlarging the crop before recognition removes the cause:
# at this multiple the same frames return a single '166' (0.981) and '189'
# (0.999), and the already-clean reads ('178', '177') are unchanged.  Re-verify
# with ``tools/probe_hud_stamina.py`` before changing it; do not raise this by
# guesswork, it is a measured value.
HUD_STAMINA_UPSCALE = 3

# The march counter ("5/6") beside the 行军 label.  Measured live: px
# 200-244 x 228-255 on 720x1280.  It is read from its own ROI rather than from
# the full-frame result, because RapidOCR's detector *skips* small numbers on a
# busy 720x1280 frame: on a live map frame it returned the 行军 label but not
# the counter next to it, and the whole-frame pass also missed the stamina
# number that a cropped read returned with 0.999 confidence.  Losing the count
# makes idle_marches unknown, which stops dispatches; losing it silently as
# "0 used" would be worse.
MARCH_COUNT_ROI = {"x_norm": 0.240, "y_norm": 0.172, "w_norm": 0.140, "h_norm": 0.036}


def read_march_count(text: str) -> tuple[int, int] | None:
    """Parse ``used/max`` from the march counter ROI text."""
    match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text.replace("\n", " "))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def read_hud_stamina(
    tokens: tuple[OCRToken, ...],
    width: int,
    height: int,
    *,
    minimum_confidence: float = 0.85,
) -> int | None:
    """Return the stamina number drawn inside the map HUD gauge, or ``None``.

    The gate is deliberately narrow: an integer token lying *entirely* inside
    the measured ROI with high OCR confidence.  A missing gauge, a covered HUD
    or a low-confidence read returns ``None`` so the caller records "stamina
    unknown" rather than a guessed value that would authorize spending.
    """
    roi = HUD_STAMINA_ROI
    x0 = roi["x_norm"] * width
    x1 = (roi["x_norm"] + roi["w_norm"]) * width
    y0 = roi["y_norm"] * height
    y1 = (roi["y_norm"] + roi["h_norm"]) * height
    for token in tokens:
        if token.confidence < minimum_confidence or not token.box:
            continue
        text = token.text.strip().replace(" ", "")
        if re.fullmatch(r"\d{1,4}(?:/\d{1,4})?", text) is None:
            continue
        xs = [point[0] for point in token.box]
        ys = [point[1] for point in token.box]
        if x0 <= min(xs) and max(xs) <= x1 and y0 <= min(ys) and max(ys) <= y1:
            return int(text.split("/")[0])
    return None


def parse_stamina_number(tokens: tuple[OCRToken, ...]) -> int | None:
    """Read the stamina value from a ROI-scoped OCR result.

    Token boxes from a ROI-scoped OCR are relative to the cropped image, so the
    full-frame containment check in :func:`read_hud_stamina` cannot be reused
    here; inside a ROI read the crop *is* the gate.

    The recognizer sometimes splits one rendered number into overlapping
    fragments (live 2026-09-14: the pill showing 295 came back as the tokens
    '29' + '9' + '5', each confidently).  Taking the first token then reported
    29 - a wrong number that would poison every stamina decision.  So merge
    the fragments geometrically: scan left to right and skip any token whose
    left edge falls inside the horizontal span already covered by the accepted
    tokens (it is a re-read of the same digits), appending only the tokens
    that extend further right.
    """
    usable = [
        token
        for token in tokens
        if token.confidence >= 0.85 and token.box and re.search(r"\d", token.text)
    ]
    if not usable:
        return None
    usable.sort(key=lambda token: min(point[0] for point in token.box))
    merged = ""
    covered_to: float | None = None
    for token in usable:
        start = min(point[0] for point in token.box)
        end = max(point[0] for point in token.box)
        if covered_to is not None and start < covered_to - 0.5:
            continue
        text = token.text.strip().replace(" ", "")
        match = re.fullmatch(r"\d{1,4}(?:/\d{1,4})?", text)
        if not match:
            continue
        merged += text.split("/")[0]
        covered_to = end
    if not merged:
        return None
    return int(merged)


def gauge_green_pixels(image_path: Path, roi: dict[str, float] | None = None) -> int:
    """Count saturated gauge pixels in the ROI as supporting evidence.

    This is evidence, never a decision input: it is recorded next to the OCR
    read so a reviewer can see the number really came from the gauge.  Hue is
    not used to reject a read, because the fill drains as stamina is spent.
    """
    area = roi or HUD_STAMINA_ROI
    with Image.open(image_path) as source:
        rgb = source.convert("RGB")
        width, height = rgb.size
        crop = rgb.crop(
            (
                round(area["x_norm"] * width),
                round(area["y_norm"] * height),
                round((area["x_norm"] + area["w_norm"]) * width),
                round((area["y_norm"] + area["h_norm"]) * height),
            )
        )
    pixels = crop.load()
    count = 0
    for y in range(crop.height):
        for x in range(crop.width):
            red, green, blue = pixels[x, y]
            if max(red, green, blue) >= 120 and max(red, green, blue) - min(red, green, blue) >= 60:
                count += 1
    return count


class HybridVision:
    """Template-first observation with OCR only as a conservative fallback."""

    def __init__(self, template_vision, ocr: OCRService, classifier: OCRPageClassifier | None = None) -> None:
        self.template_vision = template_vision
        self.ocr = ocr
        self.classifier = classifier or OCRPageClassifier()

    def observe(self, image_path: Path) -> WorldState:
        primary = self.template_vision.observe(image_path)
        if primary.known:
            # March capacity is a global HUD fact and remains visible on map
            # overlays such as RESOURCE_DETAIL. Read it on both pages so a
            # target dialog can never launch a march after the queue filled
            # between target search and dispatch.
            if primary.page is Page.POPUP and primary.popup == "GET_MORE_STAMINA":
                # The panel is the only place that shows the true stamina
                # (350/200 on 2026-09-14 after a free claim): the map gauge is
                # capped at the maximum.  The free control is proved by its own
                # template, so a paid row can never be mistaken for it.
                result = self.ocr.recognize(image_path)
                reading = None
                for token in result.tokens:
                    if token.confidence < 0.85 or not token.box:
                        continue
                    match = re.fullmatch(r"(\d{1,4})\s*/\s*(\d{1,4})", token.text.strip())
                    if match:
                        reading = (int(match.group(1)), int(match.group(2)))
                        break
                semantic = getattr(self.template_vision, "semantic", None)
                claim = semantic.find(image_path, "BTN_CLAIM_FREE_STAMINA") if semantic else None
                stamina = dict(primary.stamina)
                if reading is not None:
                    stamina.update({"current": reading[0], "max": reading[1], "source": "STAMINA_PANEL"})
                stamina["free_claim_available"] = claim is not None
                return replace(primary, stamina=stamina)
            # Every world-map frame is OCR-enriched, not only the ones where the
            # reviewed layer already saw a march counter: the map is also where
            # the stamina gauge is read, and both facts feed the same decision.
            if primary.page in {Page.MAP, Page.RESOURCE_DETAIL}:
                result = self.ocr.recognize(image_path)
                eligible = [token for token in result.tokens if token.confidence >= 0.80]
                march_used = primary.march_used
                march_max = primary.march_max
                # Read the counter from its own ROI first: the full-frame pass
                # returned the 行军 label without the number beside it, and a
                # missing count stops every dispatch.
                counted = read_march_count(self.ocr.recognize(image_path, MARCH_COUNT_ROI).text)
                if counted is not None:
                    march_used, march_max = counted
                else:
                    for token in eligible:
                        count = re.fullmatch(r"(\d+)\s*/\s*(\d+)", token.text.strip())
                        if count and token.box and max(point[0] for point in token.box) < 300 and max(point[1] for point in token.box) < 360:
                            march_used, march_max = int(count.group(1)), int(count.group(2))
                            break
                texts = [token.text.strip() for token in eligible]
                marches: list[MarchState] = []
                if "行军中" in texts:
                    marches.append(MarchState.MARCHING)
                if "采集中" in texts:
                    marches.append(MarchState.GATHERING)
                if "返回中" in texts:
                    marches.append(MarchState.RETURNING)
                short_timer = any(
                    re.fullmatch(r"00:\d{2}:\d{2}", token.text.strip())
                    and token.box
                    and max(point[0] for point in token.box) < 250
                    and 180 < min(point[1] for point in token.box) < 500
                    for token in eligible
                )
                if short_timer and MarchState.MARCHING not in marches:
                    marches.append(MarchState.MARCHING)
                # OCR may see the five long-running gather rows while the
                # reviewed semantic layer sees the short beast outbound row.
                # Preserve both pieces of evidence instead of allowing OCR to
                # erase the verifier-critical MARCHING state.
                fused_marches = list(primary.marches)
                for march in marches:
                    if march not in fused_marches:
                        fused_marches.append(march)
                stamina = dict(primary.stamina)
                # The gauge is read from a dedicated ROI: the full-frame pass
                # silently omits this small number (measured live 2026-09-14 --
                # it was absent from the frame tokens while the cropped read
                # returned "350" at 0.999 confidence).  Without the ROI read,
                # stamina would look unobservable on frames where it is plainly
                # visible, and the whole stamina-first policy would be skipped.
                # The crop is enlarged first: at native size a three-digit value
                # comes back as disagreeing fragments and merged to a wrong, or
                # one-digit-short, number (see HUD_STAMINA_UPSCALE).
                roi_tokens = self.ocr.recognize(
                    image_path, HUD_STAMINA_ROI, upscale=HUD_STAMINA_UPSCALE
                ).tokens
                with Image.open(image_path) as source:
                    frame_width, frame_height = source.size
                # Token boxes from a ROI-scoped read are crop-relative, so the
                # full-frame containment gate cannot be reused on them.
                current_stamina = parse_stamina_number(roi_tokens)
                if current_stamina is None:
                    current_stamina = read_hud_stamina(result.tokens, frame_width, frame_height)
                if current_stamina is not None:
                    stamina.update({
                        "current": current_stamina,
                        "source": "MAP_HUD",
                        "roi": dict(HUD_STAMINA_ROI),
                        "gauge_pixels": gauge_green_pixels(image_path),
                    })
                return replace(
                    primary,
                    marches=tuple(fused_marches),
                    march_used=march_used,
                    march_max=march_max,
                    stamina=stamina,
                )
            if primary.page is Page.ALLIANCE:
                secondary = self.classifier.classify(self.ocr.recognize(image_path))
                if secondary.page is primary.page and secondary.alliance:
                    alliance = {**primary.alliance, **secondary.alliance}
                    if alliance.get("section") == "GIFTS" and alliance.get("tab") == "ALLY_GIFT":
                        badge = self.ocr.recognize(
                            image_path,
                            {"x_norm": 0.88, "y_norm": 0.265, "w_norm": 0.10, "h_norm": 0.055},
                        )
                        digit = next(
                            (
                                int(token.text)
                                for token in badge.tokens
                                if token.confidence >= 0.65 and re.fullmatch(r"\d{1,3}", token.text)
                            ),
                            None,
                        )
                        if digit is not None:
                            alliance["badge_count"] = digit
                        elif alliance.get("status") == "CLAIMED" and int(alliance.get("visible_claim_buttons", 0)) == 0:
                            alliance["badge_count"] = 0
                    return replace(primary, alliance=alliance)
            if primary.page is Page.DAILY:
                secondary = self.classifier.classify(self.ocr.recognize(image_path))
                if secondary.page is primary.page and secondary.daily:
                    return replace(primary, daily={**primary.daily, **secondary.daily})
            if primary.page is Page.MAIL:
                # Badge numbers vary and OCR occasionally misses a single
                # digit. Detect only the saturated red badge pixels inside
                # the reviewed tab-header regions, then use OCR to enrich the
                # numeric count when available. This detector never clicks.
                result = self.ocr.recognize(image_path)
                badge_regions = {
                    "WAR": (0.175, 0.055, 0.225, 0.095),
                    "ALLIANCE": (0.35, 0.055, 0.405, 0.095),
                    "SYSTEM": (0.54, 0.055, 0.60, 0.095),
                    "REPORT": (0.735, 0.055, 0.795, 0.095),
                    "FAVORITES": (0.92, 0.055, 0.975, 0.095),
                }
                detected: dict[str, int] = {}
                with Image.open(image_path) as source:
                    rgb = source.convert("RGB")
                    width, height = rgb.size
                    for tab, (x0, y0, x1, y1) in badge_regions.items():
                        crop = rgb.crop((round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)))
                        pixels = crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata()
                        red_pixels = sum(1 for red, green, blue in pixels if red >= 175 and green <= 95 and blue <= 110 and red >= green * 1.8)
                        if red_pixels >= 20:
                            detected[tab] = 1
                for token in result.tokens:
                    text = token.text.strip()
                    if token.confidence < 0.75 or not token.box or not re.fullmatch(r"\d{1,3}", text):
                        continue
                    center_x = sum(point[0] for point in token.box) / len(token.box) / 720
                    center_y = sum(point[1] for point in token.box) / len(token.box) / 1280
                    if not 0.055 <= center_y <= 0.095:
                        continue
                    for tab, (x0, _, x1, _) in badge_regions.items():
                        if x0 <= center_x <= x1:
                            detected[tab] = int(text)
                            break
                mail = dict(primary.mail)
                mail.update({
                    "tab_badges": detected,
                    "badge_count": sum(detected.values()),
                    "status": "CLAIMABLE" if detected else "CLAIMED",
                })
                return replace(primary, mail=mail)
            if primary.page is Page.INTEL:
                result = self.ocr.recognize(image_path)
                eligible = [token for token in result.tokens if token.confidence >= 0.80]
                intel = dict(primary.intel)
                for token in eligible:
                    text = token.text.strip()
                    if token.box and re.fullmatch(r"\d{1,3}", text):
                        left = min(point[0] for point in token.box)
                        top = min(point[1] for point in token.box)
                        if left > 540 and top < 90:
                            intel["stamina"] = int(text)
                    refresh = re.search(r"(\d{2})\D+(\d{2}):(\d{2})", text)
                    if refresh and token.box and min(point[1] for point in token.box) < 190:
                        intel["refresh"] = ":".join(refresh.groups())
                # The template layer can only say UNKNOWN here, because it knows
                # the page but not the list.  Measured on 2026-09-14, the two
                # states are separable by OCR alone:
                #   with a mission card -> 击败野兽等级10 ... 前往查看 (px 292,914)
                #   empty list          -> only 情报 / 体力 / 下次刷新 header
                # Deciding from template *absence* would be unsafe instead: the
                # card templates do go stale (see the beast target card fix), and
                # a stale template would then be reported as "no missions" and
                # silently end the goal.  Only the two measured states are
                # claimed; anything else stays UNKNOWN.
                if str(intel.get("status", "UNKNOWN")).upper() == "UNKNOWN":
                    texts = [token.text.strip() for token in eligible]
                    has_card = any(
                        keyword in text for text in texts for keyword in ("前往查看", "查看")
                    )
                    has_header = any("下次刷新" in text for text in texts)
                    if has_card:
                        intel.update({"status": "AVAILABLE", "available_count": 1, "list_read": True})
                    elif has_header:
                        intel.update({"status": "NOT_AVAILABLE", "available_count": 0, "list_read": True})
                return replace(primary, intel=intel)
            if primary.page is Page.TRAINING and primary.training.get("status") == "IN_PROGRESS" and primary.training.get("timer") in {None, "VISIBLE"}:
                secondary = self.classifier.classify(self.ocr.recognize(image_path))
                if secondary.page is primary.page and secondary.training:
                    return replace(primary, training={**secondary.training, **primary.training, **({"timer": secondary.training["timer"]} if "timer" in secondary.training else {})})
            if primary.page is Page.RESEARCH and primary.research.get("status") == "IN_PROGRESS" and primary.research.get("timer") in {None, "VISIBLE"}:
                secondary = self.classifier.classify(self.ocr.recognize(image_path))
                if secondary.page is primary.page and secondary.research:
                    merged = {**secondary.research, **primary.research}
                    if "timer" in secondary.research:
                        merged["timer"] = secondary.research["timer"]
                    return replace(primary, research=merged)
            return primary
        return self.classifier.classify(self.ocr.recognize(image_path))
