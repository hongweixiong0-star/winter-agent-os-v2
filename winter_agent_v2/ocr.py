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


# The 出征 formation page draws the target it is about to attack in its title
# bar and nowhere else.  Measured 2026-09-15 on six live frames (720x1280): the
# text occupies x 86-260, y 15-75, so this ROI is that region widened slightly
# so a longer target name cannot be clipped.
FORMATION_TITLE_ROI = {"x_norm": 0.08, "y_norm": 0.004, "w_norm": 0.42, "h_norm": 0.062}

# ``目标：<name>`` is drawn by the world-map wilderness flow.  The intel flow
# shows the bare page title instead, and that is the only structural difference
# between the two populations sharing this page.
FORMATION_TARGET_PATTERN = re.compile(r"目标[:：]\s*(?P<name>[^\s:：]+)")
FORMATION_INTEL_TITLE = "出征"


def read_formation_target(text: str) -> tuple[str | None, str | None]:
    """Split a formation-page title into ``(target name, target kind)``.

    ``("麝牛", "WILDERNESS")`` for ``目标：麝牛``, ``(None, "INTEL")`` for the
    bare ``出征`` title, and ``(None, None)`` when the strip cannot be read.

    An unreadable title must never resolve to either kind: this field decides
    which dispatch skill runs and therefore whether stamina is spent, so
    "unknown" has to stay distinguishable from both answers.
    """
    match = FORMATION_TARGET_PATTERN.search(text)
    if match:
        name = match.group("name").strip()
        return (name, "WILDERNESS") if name else (None, None)
    if FORMATION_INTEL_TITLE in text:
        return None, "INTEL"
    return None, None


def _intel_pin_count(image_path: Path) -> int:
    """Mission pins visible on an intel frame, or 0 when they cannot be counted.

    The intel page is a pin map, so the pin detector is the only signal that
    sees the board itself rather than the card that a tap produces.  A detector
    error deliberately returns 0: the caller then falls back to its previous
    text rule, so a broken detector can never invent an available board.
    """
    try:
        from .intel_pins import intel_pin_centers

        return len(intel_pin_centers(image_path))
    except Exception:
        return 0


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
    ) -> OCRResult:
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        key = f"{digest}:{self._roi_key(roi)}:{self.backend.name}"
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


# The free-gift row of the 获取更多 panel states *when* the next gift arrives as
# an absolute countdown (下次补给 06:47:35).  Unlike the 150 it sits under, this
# countdown only exists while the gift is NOT claimable -- a claimable panel
# draws the green 领取 button in its place (both states are archived in
# ``dataset/truth_audit/free_stamina_claim_20260915``).
#
# Measured on live 720x1280 panels with the production OCR stack (2026-09-15):
#
#     frame                     label          countdown   conf   x       y
#     ------------------------  -------------  ----------  -----  ------  ------
#     04_panel_after_claim      下次补给      06:47:35    0.936  524-635 382-413
#     04_stamina_panel_opened   下次补给      00:55:33    0.952  525-635 381-412
#     02_stamina_refusal_popup  下次补给      00:13:18    0.963  (same row)
#     00:00:15 seen at 03:59:46.7Z           00:00:15    0.965  (same row)
#
# Two frames taken 13 minutes apart implied the same instant to within a second,
# so this is a real clock, not an animation.  The ROI spans the whole right-hand
# column of the gift row so a shorter countdown cannot fall outside it.
NEXT_SUPPLY_ROI = {"x_norm": 0.700, "y_norm": 0.288, "w_norm": 0.200, "h_norm": 0.040}

_NEXT_SUPPLY_PATTERN = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def read_next_supply_seconds(tokens: tuple[OCRToken, ...]) -> int | None:
    """Parse the ``下次补给 HH:MM:SS`` countdown into seconds, or ``None``.

    Returns ``None`` -- never ``0`` -- when the countdown is absent or unreadable:
    a claimable panel legitimately has no countdown, and "unknown" must not be
    mistaken for "due now" by the caller.
    """
    for token in tokens:
        if token.confidence < 0.85:
            continue
        match = _NEXT_SUPPLY_PATTERN.fullmatch(token.text.strip().replace(" ", ""))
        if match is None:
            continue
        hours, minutes, seconds = (int(group) for group in match.groups())
        if minutes > 59 or seconds > 59:
            continue
        return hours * 3600 + minutes * 60 + seconds
    return None


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

    The recognizer splits one rendered number into several overlapping partial
    reads of the SAME digits, and the fragments disagree about how much of it
    each one saw.  Measured on the live 42x24 HUD crop (2026-09-14, frames kept
    in ``dataset/truth_audit/``):

    ==========  ==========================  ==============
    true value  recognizer returned           first-token read
    ==========  ==========================  ==============
    295         '295' + '5'                  295  (ok)
    295         '29' + '95'                  29   WRONG
    166         '16' + '66' + '6'            16   WRONG
    189         '18' + '9'                   18   WRONG
    ==========  ==========================  ==============

    Every fragment is a substring of the true value, so the value is the
    shortest string containing all of them: stitch the fragments in reading
    order, overlapping each one on the longest run of digits it shares with what
    is already assembled.  That reproduces all four rows above.  Taking the
    first token read 16 for 166; a left-edge containment test read 29 for 295.
    Enlarging the crop is NOT the answer - it turns a clean '295' into
    '29' + '95', which is what the containment test then got wrong.
    """
    fragments: list[tuple[float, str]] = []
    for token in tokens:
        if token.confidence < 0.85 or not token.box:
            continue
        text = token.text.strip().replace(" ", "")
        if not re.fullmatch(r"\d{1,4}(?:/\d{1,4})?", text):
            continue
        fragments.append((min(point[0] for point in token.box), text.split("/")[0]))
    if not fragments:
        return None
    fragments.sort(key=lambda item: item[0])

    merged = ""
    for _left, text in fragments:
        if text in merged:
            continue  # a re-read of digits already assembled
        overlap = 0
        for size in range(min(len(merged), len(text)), 0, -1):
            if merged.endswith(text[:size]):
                overlap = size
                break
        merged += text[overlap:]
    if not merged or len(merged) > 4:
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


def unaffordable_cost_pixels(
    image_path: Path,
    roi: dict[str, float],
    *,
    minimum_red: int = 40,
) -> bool | None:
    """Read the client's own affordability verdict: the cost's colour.

    The client renders a stamina cost **white** when it can be paid and **red**
    when it cannot -- the same widget, one colour difference.  Measured
    2026-09-15 across three different cost-bearing buttons (see
    ``tools/probe_cost_colour.py``), red pixels appear on exactly the frames
    where stamina is below the displayed cost and on none of the others:

        ==============================  =========  =====  =======
        frame                           stamina    cost   red px
        ==============================  =========  =====  =======
        beast dispatch (live 04:11Z)    0          10     452
        hero camp panel                 7          10     220
        hero camp panel                 16         10     0
        hero squad page (dispatched)    10         10     0
        beast dispatch (template src)   payable    10     0
        ==============================  =========  =====  =======

    5 of 5, and it is not a threshold judgement: the affordable frames contain
    **zero** red pixels, so any appearance of the colour is the signal.

    This matters because the HUD gauge does *not* cover these cases: its ROI
    reads only 19 of 25 camp-panel frames, and it cannot read a lone ``0`` at
    all (``tools/probe_stamina_zero.py``: best confidence 0.73, flipping
    between '0' and 'O').  The colour needs no OCR.

    Returns ``None`` when the ROI is not in the frame, so a caller cannot read
    that as "affordable": **an unreadable verdict must not authorize spending.**
    """
    with Image.open(image_path) as source:
        rgb = source.convert("RGB")
        width, height = rgb.size
    x0 = round(roi["x_norm"] * width)
    y0 = round(roi["y_norm"] * height)
    x1 = round((roi["x_norm"] + roi["w_norm"]) * width)
    y1 = round((roi["y_norm"] + roi["h_norm"]) * height)
    if x1 <= x0 or y1 <= y0 or x0 < 0 or y0 < 0 or x1 > width or y1 > height:
        return None
    with Image.open(image_path) as source:
        # The cost sits to the right of the button label; counting the whole
        # button would let its own artwork swamp the digits.
        crop = source.convert("RGB").crop((x0, y0, x1, y1))
        right = crop.crop((crop.width // 2, 0, crop.width, crop.height))
    pixels = right.load()
    red = 0
    for y in range(right.height):
        for x in range(right.width):
            r, g, b = pixels[x, y]
            if r > 110 and (r - g) > 45 and (r - b) > 45:
                red += 1
    if red < minimum_red:
        return False
    return True


class HybridVision:
    """Template-first observation with OCR only as a conservative fallback."""

    def __init__(self, template_vision, ocr: OCRService, classifier: OCRPageClassifier | None = None) -> None:
        self.template_vision = template_vision
        self.ocr = ocr
        self.classifier = classifier or OCRPageClassifier()

    def _semantic_roi(self, semantic: str) -> dict[str, float] | None:
        """Return the ROI the manifest registered for ``semantic``, or ``None``.

        A registered ROI is already a measured statement about where that
        control is drawn, so it is the one place a pixel check should come from
        -- a second hardcoded rectangle would drift away from the template it
        describes.
        """
        records = getattr(getattr(self.template_vision, "semantic", None), "records", None)
        if not records:
            return None
        for record in records:
            if record.get("semantic") == semantic and record.get("roi_norm"):
                return dict(record["roi_norm"])
        return None

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
                # The panel also states when the next free gift arrives, as an
                # absolute countdown (下次补给).  Measured 2026-09-15 on four
                # real panels: 00:13:18 / 00:00:15 / 06:47:35 all read at
                # 0.936-0.965 confidence, and two frames taken 13 minutes apart
                # implied the same instant to within a second.  There is no
                # countdown at all on a panel whose gift is claimable -- the
                # 领取 button sits there instead -- so its absence is also a fact.
                countdown = read_next_supply_seconds(
                    self.ocr.recognize(image_path, NEXT_SUPPLY_ROI).tokens
                )
                if countdown is not None:
                    stamina["next_supply_in_seconds"] = countdown
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
                # A counter that is simply not drawn is not an unreadable counter.
                #
                # Measured 2026-09-15 across every recorded MAP observation in the
                # corpus: (march_used is None, no march states) occurs 98 times,
                # while (march_used is None, march states present) occurs 35 times.
                # The first is the client drawing no counter because nothing is out;
                # the second is a count we genuinely cannot read.  Only the first
                # may be read as idle -- and it has to be, because leaving it
                # unknown stops the entire gather workflow at its first step
                # (CHECK_MARCH / MARCH_COUNT_NOT_READ, live 2026-09-15T12:59:36Z)
                # with no way to recover.
                #
                # The cost is asymmetric in the right direction: if this is ever
                # wrong, the dispatch fails its verifier and costs one action;
                # treating a genuinely idle queue as unreadable costs the whole
                # gather goal, permanently.  The guard uses fused_marches, so
                # evidence of a march from either layer keeps the count unknown
                # rather than guessing.
                if march_used is None and not fused_marches:
                    march_used = 0
                stamina = dict(primary.stamina)
                # The gauge is read from a dedicated ROI: the full-frame pass
                # silently omits this small number (measured live 2026-09-14 --
                # it was absent from the frame tokens while the cropped read
                # returned "350" at 0.999 confidence).  Without the ROI read,
                # stamina would look unobservable on frames where it is plainly
                # visible, and the whole stamina-first policy would be skipped.
                roi_tokens = self.ocr.recognize(image_path, HUD_STAMINA_ROI).tokens
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
            if (
                primary.page is Page.EXPLORATION
                and primary.exploration.get("stamina_cost_displayed") is not None
            ):
                # The Hero Journey camp panel is a *map overlay*: the world-map
                # HUD stays on screen behind it, so the stamina gauge sits at
                # exactly the position it does on Page.MAP.
                #
                # Measured 2026-09-15 over the 25 production frames where the
                # brain saw this panel (dataset/truth_audit/
                # stamina_check_live_20260915 plus every recorded EXPLORATION
                # frame carrying a displayed cost, via
                # tools/probe_camp_panel_stamina.py): HUD_STAMINA_ROI reads a
                # number on 19 of 25 -- 157, 165, 165, 165, 18, 18, 186, 155,
                # 155, 145, 36, 36, 157, 157, 11, 11, 2, 2, 9 -- and on the
                # live frame it returns ('9', 0.999), character for character
                # identical to the map frame's read.
                #
                # The 6 misses are OCR failures, not a wrong ROI: the digit sits
                # next to a red badge and is read as 'A'/'m' at ~0.7 confidence
                # (one frame's tokens are empty).  The MAP branch's whole-frame
                # fallback rescues none of them (measured: 0 of 6), so it is not
                # repeated here -- a missing read leaves stamina unknown and the
                # brain falls back to its previous behaviour, which is the safe
                # direction.
                #
                # Without this read the brain stands on a 探险 ⚡10 button with
                # no idea whether it can afford the fight.  Live
                # 2026-09-15T03:03:57Z: stamina 9 against a displayed cost of 10,
                # the tap was refused, and the run burned its remaining three
                # actions opening and closing the stamina panel.  Gated on the
                # displayed cost so the idle-income exploration page (EXPLORATION
                # with no cost) pays no OCR cost.
                #
                # Assigned rather than returned: nothing after this point
                # branches on Page.EXPLORATION today, and keeping the state
                # flowing means a future branch still sees it.
                roi_tokens = self.ocr.recognize(image_path, HUD_STAMINA_ROI).tokens
                current_stamina = parse_stamina_number(roi_tokens)
                if current_stamina is not None:
                    stamina = dict(primary.stamina)
                    stamina.update({
                        "current": current_stamina,
                        "source": "CAMP_PANEL_HUD",
                        "roi": dict(HUD_STAMINA_ROI),
                        "gauge_pixels": gauge_green_pixels(image_path),
                    })
                    primary = replace(primary, stamina=stamina)
                # The client also states affordability without any OCR: it draws
                # the cost in red when it cannot be paid.  That covers the 6 of
                # 25 frames the gauge above cannot read -- and it is the verdict
                # the client itself will act on, which no pixel-read number is.
                # See ``unaffordable_cost_pixels`` for the measurement.
                cost_roi = self._semantic_roi("BTN_HERO_CAMP_FIGHT")
                if cost_roi is not None:
                    blocked = unaffordable_cost_pixels(image_path, cost_roi)
                    if blocked is not None:
                        stamina = dict(primary.stamina)
                        stamina["cost_affordable"] = not blocked
                        stamina["cost_verdict_source"] = "BUTTON_COST_COLOUR"
                        primary = replace(primary, stamina=stamina)
            if primary.page is Page.ALLIANCE:
                secondary = self.classifier.classify(self.ocr.recognize(image_path))
                if secondary.page is primary.page and secondary.alliance:
                    alliance = {**primary.alliance, **secondary.alliance}
                    # Vision is template-first: OCR may add the structured fields
                    # the template layer does not carry (gift counters, personal
                    # contribution, attempts), but it must not overwrite a
                    # `section` the template layer has already decided.
                    #
                    # Measured 2026-09-15.  `OCRPageClassifier` sets
                    # section=GIFTS whenever the exact text 联盟宝箱 is present,
                    # and 联盟宝箱 is also an entry TILE on the alliance HOME
                    # page: it is an exact token on all 5 home frames AND on all
                    # 3 gifts frames, so on its own it identifies no page at
                    # all.  Letting it win reported the live home page as
                    # section=GIFTS / status=UNKNOWN, which silently broke two
                    # things: brain.py dispatches OPEN_ALLIANCE_GIFTS only when
                    # section == HOME, so the loop always ended in SAFE_STOP
                    # alliance_state_unknown, and verify_open_alliance_gifts
                    # requires before.section == HOME, so the skill could never
                    # have passed anyway.  The live Alliance page carried a 99+
                    # unclaimed-gift badge the whole time.
                    #
                    # The reviewed template layer already distinguishes the four
                    # alliance sections with page anchors measured over 2757
                    # frames (PAGE_ALLIANCE_GIFTS d=0 on gifts, PAGE_ALLIANCE_TECH
                    # d=2 on technology, PAGE_ALLIANCE_HELP d=4 on help,
                    # PAGE_ALLIANCE + an entry tile on home), so its answer is
                    # the one to keep.
                    if primary.alliance.get("section"):
                        alliance["section"] = primary.alliance["section"]
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
                # the page but not the list.  Two earlier claims about this
                # branch were measured and then FALSIFIED on the live client, so
                # they are recorded rather than quietly dropped:
                #
                # 1. "the two states are separable by OCR alone" is wrong.  The
                #    intel page is a PIN MAP: the mission card only exists after
                #    a pin is tapped, so a board full of work OCRs as nothing but
                #    the 情报 / 体力 / 下次刷新 header.  Reproduced live
                #    2026-09-15 07:36 with 5 pins on screen: OCR saw only the
                #    header, the rule below reported NOT_AVAILABLE with
                #    available_count=0, and goal_library turns that into
                #    CLEAR_INTEL=COMPLETE - a silent, successful-looking stop.
                #    That same frame's header read 下次刷新:00:23:06 while the
                #    board was full, so the countdown is not a usable signal
                #    either.
                # 2. Deciding from template *absence* remains unsafe for the
                #    reason it always was: card templates go stale, and a stale
                #    template would be reported as "no missions".
                #
                # The primary evidence is therefore the pin detector, which sees
                # the board itself.  Pins > 0 is a positive sighting and upgrades
                # the page to AVAILABLE.  The change is strictly additive: when no
                # pin is seen the previous OCR rule runs unchanged, so a detector
                # failure degrades to the old behaviour instead of inventing an
                # available board.
                if str(intel.get("status", "UNKNOWN")).upper() == "UNKNOWN":
                    pins = _intel_pin_count(image_path)
                    if pins:
                        intel.update({"status": "AVAILABLE", "available_count": pins,
                                      "pins": pins, "list_read": True})
                    else:
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
            if primary.page is Page.MARCH:
                # The formation page's 出征 control states both the price and, in
                # colour, whether the account can pay it.  Recording that verdict
                # here is what keeps an unaffordable dispatch a *spending*
                # decision instead of a vision defect.
                #
                # Measured 2026-09-15 over every recorded beast dispatch in
                # learning/episodes.jsonl:
                #
                #   result   n   phash distance   strong-red px   verdict
                #   success  25  0 (all identical)   0             affordable
                #   failure   4  26 (all identical)  452            unaffordable
                #
                # The four failures were all reported as
                # SEMANTIC_TARGET_NOT_VERIFIED, which reads as "the control could
                # not be found" -- but the control was on screen the whole time
                # and plainly visible; its cost digit was drawn red, which is
                # what moved the pixel hash off the reviewed template.  The same
                # red/white signal already gates the hero camp panel (see
                # ``unaffordable_cost_pixels`` and brain.py's camp branch), so
                # this is the same measurement applied to the other cost-bearing
                # control rather than a new rule.
                #
                # The ROI comes from the manifest record, not a second
                # hand-written rectangle, for the reason ``_semantic_roi`` gives.
                # It is read on every MARCH frame, including the gathering
                # formation page: both dispatch buttons are the same control
                # (see the identity note below).
                cost_roi = self._semantic_roi("BTN_BEAST_DISPATCH")
                if cost_roi is not None:
                    blocked = unaffordable_cost_pixels(image_path, cost_roi)
                    if blocked is not None:
                        stamina = dict(primary.stamina)
                        stamina["cost_affordable"] = not blocked
                        stamina["cost_verdict_source"] = "DISPATCH_COST_COLOUR"
                        primary = replace(primary, stamina=stamina)
            if primary.page is Page.MARCH and primary.beast:
                # The 出征 formation page is shared by the map wilderness beast
                # and the intel beast target, and the template layer cannot
                # tell them apart: the two dispatch buttons and the two
                # 胜券在握 strips are crops of the same controls and match both
                # frames at distance 0 (tools/probe_beast_formation_identity.py).
                # The template layer therefore asserts only the safety line it
                # really sees, and the target identity is read here, from the
                # title bar, which is the only place the client draws it.
                #
                # Gated on a non-empty ``primary.beast``: the gathering
                # formation page also classifies as MARCH, and filling its
                # empty beast dict would make the brain treat a resource march
                # as a beast march.
                #
                # Nothing is added when the strip cannot be read.  An unread
                # title leaves the state without an identity, and the brain
                # refuses to spend stamina on a target it cannot name.
                title = self.ocr.recognize(image_path, FORMATION_TITLE_ROI)
                name, kind = read_formation_target(title.text)
                if name or kind:
                    beast = dict(primary.beast)
                    if name:
                        beast["name"] = name
                    if kind:
                        beast["target_kind"] = kind
                    return replace(primary, beast=beast)
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
