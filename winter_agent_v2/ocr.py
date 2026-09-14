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

    def recognize(self, image_path: Path, roi: dict[str, float] | None = None) -> OCRResult:
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
    """Conservative exact-keyword fallback; ambiguous OCR stays UNKNOWN."""

    RULES: tuple[tuple[Page, tuple[str, ...]], ...] = (
        (Page.EVENT, ("常规活动", "最强王国")),
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
            if (primary.page is Page.MAP and primary.march_used is not None) or primary.page is Page.RESOURCE_DETAIL:
                result = self.ocr.recognize(image_path)
                eligible = [token for token in result.tokens if token.confidence >= 0.80]
                march_used = primary.march_used
                march_max = primary.march_max
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
                return replace(
                    primary,
                    marches=tuple(fused_marches),
                    march_used=march_used,
                    march_max=march_max,
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
