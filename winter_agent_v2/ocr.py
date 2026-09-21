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

from .building_identity import UNKNOWN as UNKNOWN_IDENTITY
from .building_identity import read_building_identity
from .camp_training import CAMP_LABELS, LABEL_TO_CAMP, TROOP_TO_CAMP
from .camp_training import camp_from_selected_label, merge_camps, observe_camps
from .models import MarchState, Page, RoleIdentity, WorldState


#: Training-page titles seen on the live client -> the troop the page is training.
#:
#: Keyed on the full title rather than on the troop word alone so a title that is a substring
#: of another (a hypothetical 盾兵营 vs 盾兵 title) cannot cross-match.  The wording is not a
#: constant across camps -- 英勇盾兵, 刚毅矛兵, 王牌矛兵 and 王牌射手 have all been measured --
#: so the table is data, extended from frames, and a title not in it is simply not read rather
#: than guessed at.  Every entry here was read off a real frame; see the camp frames under
#: ``dataset/raw/live_train_*``.
TITLE_TO_TROOP: dict[str, str] = {
    "英勇盾兵": "INFANTRY",
    "盾兵": "INFANTRY",
    "刚毅矛兵": "LANCER",
    "王牌矛兵": "LANCER",
    "矛兵": "LANCER",
    "刚毅射手": "MARKSMAN",
    "王牌射手": "MARKSMAN",
    "射手": "MARKSMAN",
}

#: A camp's tab label -> its troop.  Used only as a fallback, and only when exactly one label
#: is present: the client draws all three at once, so presence normally decides nothing.
LABEL_TO_TROOP: dict[str, str] = {
    label: troop for troop, label in (
        ("INFANTRY", CAMP_LABELS["SHIELD_CAMP"]),
        ("LANCER", CAMP_LABELS["LANCER_CAMP"]),
        ("MARKSMAN", CAMP_LABELS["MARKSMAN_CAMP"]),
    )
}


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
            # Which barracks this page *is* -- decided by the PAGE TITLE, never by a tab label.
            #
            # Measured 2026-09-21 on every reviewed camp frame: the client draws **all three**
            # tab labels at once (盾兵营 / 矛兵营 / 射手营, all three read on all five frames),
            # so their presence is the same on every camp page and *decides nothing*.  The
            # previous ``if 盾兵营 ... elif 矛兵营 ... elif 射手营 ...`` chain therefore did not
            # read the camp at all: it returned whichever label happened to be listed first, so
            # every camp page answered SHIELD_CAMP/盾兵营 and the three camps were not being
            # read independently -- the exact failure the per-camp WorldState exists to prevent.
            #
            # The title is the signal that discriminates, because it is drawn once, for the open
            # camp only: 王牌射手 on the marksman page, 王牌矛兵 on the lancer page.  OCR reads
            # it cleanly on every frame (verified on all five), including the ones where the tab
            # labels are ambiguous.
            #
            # The title wording is not a constant across camps (英勇盾兵 / 刚毅矛兵 / 王牌射手 /
            # 王牌矛兵 have all been seen), so the match is on the TROOP WORD the title contains
            # rather than on a full title string -- and 射手/矛兵/盾兵 are distinct words, so it
            # stays unambiguous.  The tab labels are still recorded in ``camps_seen`` as
            # corroboration, and ``camp_open_label`` is only claimed when the open camp's own
            # label is among them.
            titles = [text for text in exact_texts if text in TITLE_TO_TROOP]
            named = {
                TITLE_TO_TROOP[title]
                for title in titles
            }
            if len(named) == 1:
                training["troop_type"] = named.pop()
            elif not named:
                # No title read: fall back to a tab label ONLY when exactly one is present, so a
                # frame that drew all three (the normal case) is left un-attributed rather than
                # guessed.  ``None`` is the honest reading and keeps the camp unknown.
                present = [label for label in CAMP_LABELS.values() if label in exact_texts]
                if len(present) == 1:
                    training["troop_type"] = LABEL_TO_TROOP[present[0]]
            for text in exact_texts:
                timer = re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", text)
                if timer:
                    training["timer"] = timer.group(0)
                count = re.search(r"正在训练\s*([0-9,]+)\s*位", text)
                if count:
                    training["batch_count"] = int(count.group(1).replace(",", ""))
            # Which barracks this page *is*.
            #
            # The page title names the troop (英勇盾兵 / 刚毅矛兵 / 刚毅射手), and that is the
            # signal this field is built on: `troop_type` above already comes from the camp
            # names the client draws, and the title is drawn only for the open camp.  The tab
            # labels are recorded alongside it as corroboration -- measured 2026-09-21, all
            # three are drawn at once (盾兵营 / 矛兵营 / 射手营, conf 1.00 / 0.99 / 1.00) at
            # y_norm ~0.945, so *presence decides nothing*, and `camps_seen` exists to say that
            # all three were visible rather than to pick one.
            #
            # A "which tab is highlighted" pixel test was measured and rejected: sampling the
            # tile fills gives a muted light plate for the selected tab (225,239,242) against
            # saturated blue for the other two (107,159,216), but the same statistic fires on
            # 7 of 14 frames from *other* pages, and the per-tile score is not clean even on
            # the training frame (one unselected tile scored blue on only 1 of 4 samples).
            # A discriminator that unreliable would mislabel a camp, and a mislabelled camp is
            # worse than an unattributed one -- so the tab labels are evidence, and the troop
            # name is the answer.
            camp_labels = ("盾兵营", "矛兵营", "射手营")
            training["camps_seen"] = [label for label in camp_labels if label in exact_texts]
            # Reported only when exactly the open camp's label is present among the ones the
            # reader is confident about, so a frame that draws a different camp's tab as the
            # prominent one does not silently override the title.
            open_label = CAMP_LABELS.get(TROOP_TO_CAMP.get(training.get("troop_type") or "", ""))
            if open_label in training["camps_seen"]:
                training["camp_open_label"] = open_label
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
# Widened on 2026-09-19 from w_norm 0.058, which was measured too tight for the recogniser:
# the detector under-segments a small number and can stop after the second digit, so a
# three-digit value came back as its first two digits.  Measured on four live frames kept in
# ``dataset/truth_audit/stamina_hud_roi_20260919`` (the HUD itself says 527 -- the 7 ends at
# frame x 63, *inside* the old right edge at x 70, so this is a detector failure and not a
# clipped glyph): at 0.058 two frames read 52 for 527, at 0.075 both read 527 while the
# already-correct frame still reads 382.  The number is not clipped at 0.075 either -- the
# green pill runs to about x 88 -- so the extra width is margin for the detector, not content.
# It matters because AVOID_STAMINA_WASTE spends or stops spending on this number, and a
# dropped digit reads as "nearly empty" when stamina is in fact plentiful.
HUD_STAMINA_ROI = {"x_norm": 0.040, "y_norm": 0.0755, "w_norm": 0.075, "h_norm": 0.019}

# The march counter ("5/6") beside the 行军 label.  Measured live: px
# 200-244 x 228-255 on 720x1280.  It is read from its own ROI rather than from
# the full-frame result, because RapidOCR's detector *skips* small numbers on a
# busy 720x1280 frame: on a live map frame it returned the 行军 label but not
# the counter next to it, and the whole-frame pass also missed the stamina
# number that a cropped read returned with 0.999 confidence.  Losing the count
# makes idle_marches unknown, which stops dispatches; losing it silently as
# "0 used" would be worse.
MARCH_COUNT_ROI = {"x_norm": 0.240, "y_norm": 0.172, "w_norm": 0.140, "h_norm": 0.036}


_MARCH_COUNT_TOKEN = re.compile(r"^(\d{1,2})\s*/\s*(\d{1,2})$")
# Delimited by non-digits on both sides: a count must not be carved out of a
# longer number.  Without this `'200/200'` matched as ``0/20``.
_MARCH_COUNT_LOOSE = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")


def read_march_count(text: str) -> tuple[int, int] | None:
    """Parse ``used/max`` from the march counter ROI text.

    ``OCRResult.text`` puts one detected token on each line, so a line *is* a
    token -- and that separation is load-bearing.  Measured 2026-09-16 on the
    live frame that carries account A's counter: the ROI OCR returned two tokens,
    ``'3/'`` and ``'3/6'``, and joining them before matching let the pattern read
    ``3/ 3``.  The episode recorded capacity 3 on a client that said 6.  A stray
    fragment must never be able to rewrite the one number the whole dispatch path
    rests on, so a token that *is* the pattern wins outright; only when no token
    is a whole count is a single unambiguous embedded one accepted.  Anything
    genuinely ambiguous returns ``None``, which the caller already treats as
    "unread" -- the honest answer, per "证据不足不要强猜".
    """
    whole = [match for match in (_MARCH_COUNT_TOKEN.match(line.strip())
                                 for line in text.splitlines()) if match is not None]
    if len(whole) == 1:
        return int(whole[0].group(1)), int(whole[0].group(2))
    if len(whole) > 1:
        return None
    loose = [match for match in (_MARCH_COUNT_LOOSE.search(line) for line in text.splitlines())
             if match is not None]
    if len(loose) != 1:
        return None
    return int(loose[0].group(1)), int(loose[0].group(2))


# --- 领主档案: which role is logged in ---------------------------------------
#
# Measured 2026-09-16 on a live 720x1280 frame captured by
# ``tools/role_identity_probe.py`` (archived in
# ``dataset/truth_audit/role_identity_20260916``).  One tap on the top-left
# avatar opens this panel and it states the account, the name and the kingdom.
#
# Do not look for the name on the HUD: measured first, and it is not there.  Both
# the city view and the world map draw avatar portrait / power / stamina /
# alliance rank (统帅N) / date, and no name at all.  Nor is any of those usable as
# a key -- power moves by the hour and an alliance rank is shared by everyone
# holding it.
#
# The title gate is not decoration.  ``账号：`` also appears on account-management
# screens, which is exactly where ``config.risk.block_account_or_role_delete``
# applies, so an identity is accepted only when the panel's own title is on the
# frame as well.  Two independent facts or nothing.
ROLE_PROFILE_TITLE = "领主档案"
ROLE_PROFILE_TITLE_ROI = {"x_norm": 0.100, "y_norm": 0.012, "w_norm": 0.280, "h_norm": 0.040}
# One ROI over the whole information block, not one per row: the client lays the
# rows out, and a long name must not be clipped by a rectangle drawn around the
# name we happened to observe.  Rows are recovered from token geometry instead.
ROLE_PROFILE_INFO_ROI = {"x_norm": 0.355, "y_norm": 0.650, "w_norm": 0.590, "h_norm": 0.215}

_ROLE_ACCOUNT = re.compile(r"账号[：:]\s*([0-9]{6,14})")
_ROLE_KINGDOM = re.compile(r"所在王国[：:]\s*([0-9]{1,5})")
_ROLE_ALLIANCE_TAG = re.compile(r"^\[([^\]]{1,12})\]\s*(.+)$")
_ROLE_POWER = re.compile(r"(?<![\d.])([0-9][0-9,.]*万)(?![\d万])")
_ROLE_LABELLED = ("账号", "所在王国", "联盟", "击败")


def read_role_identity_rows(tokens, tolerance: float = 14.0) -> list[str]:
    """Group OCR tokens into drawn rows, top to bottom, each joined left to right.

    ``tolerance`` is in ROI-crop pixels.  Measured row pitch on the live panel is
    ~41 px, so 14 px cannot merge two rows while still absorbing the baseline
    wobble within one.  Token boxes from a ROI-scoped read are crop-relative,
    which is why this works on the crop and not on full-frame coordinates.
    """
    placed: list[tuple[float, float, str]] = []
    for token in tokens:
        text = token.text.strip()
        if not text or not token.box:
            continue
        ys = [point[1] for point in token.box]
        xs = [point[0] for point in token.box]
        placed.append((sum(ys) / len(ys), min(xs), text))
    placed.sort()
    rows: list[list[tuple[float, float, str]]] = []
    for y, x, text in placed:
        if rows and abs(y - rows[-1][0][0]) <= tolerance:
            rows[-1].append((y, x, text))
        else:
            rows.append([(y, x, text)])
    return [" ".join(text for _, _, text in sorted(row, key=lambda item: item[1])) for row in rows]


def parse_role_identity(title_text: str, rows: list[str], *, confidence: float = 0.0) -> RoleIdentity | None:
    """Build a :class:`RoleIdentity` from the panel's own text, or ``None``.

    ``None`` unless the title says this is the profile panel *and* both the name
    and the account rows parse.  A partial reading is not an identity, and
    inventing one would key persisted state to the wrong role -- which is the
    exact failure this whole capability exists to prevent.
    """
    if ROLE_PROFILE_TITLE not in title_text or not rows:
        return None
    account = None
    for row in rows:
        match = _ROLE_ACCOUNT.search(row)
        if match:
            account = match.group(1)
            break
    if account is None:
        return None
    # The block's first drawn row is the name row -- the panel's own layout, so it
    # is read from position rather than from a hand-drawn rectangle.  If the
    # topmost row is a labelled row instead, OCR missed the name, and "no
    # identity" is the honest answer.
    name_row = rows[0]
    if any(label in name_row for label in _ROLE_LABELLED):
        return None
    name = name_row.strip()
    if not name or name.isdigit():
        return None

    alliance_tag = None
    match = _ROLE_ALLIANCE_TAG.match(name)
    if match:
        alliance_tag, name = match.group(1), match.group(2).strip()
    if not name:
        return None

    kingdom = None
    for row in rows:
        match = _ROLE_KINGDOM.search(row)
        if match:
            kingdom = match.group(1)
            break

    # The power row carries no label, so it is the first unlabelled row below the
    # name that states a rounded total.  Kept as text: the panel rounds (54.2万
    # against a HUD reading of 542,443) and an int would claim precision the
    # client never drew.
    power_text = None
    for row in rows[1:]:
        if any(label in row for label in _ROLE_LABELLED):
            continue
        match = _ROLE_POWER.search(row)
        if match:
            power_text = match.group(1)
            break

    return RoleIdentity(
        role_id=account,
        role_name=name,
        alliance_tag=alliance_tag,
        kingdom=kingdom,
        power_text=power_text,
        confidence=confidence,
    )


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

# The Intel mission dialogs on this client each announce themselves in their title,
# so which one is on screen is READ, not template-matched (CAP-A01, 2026-09-17).
#
# Why this is not a template question.  Measured on the four archived dialogs:
#
#   frame                template layer              title band OCR
#   击败野兽 (beast)     INTEL_BEAST_MISSION/BEAST   击败野兽等级10
#   英雄之旅 等级10      INTEL_HERO_JOURNEY (d=2)    英雄之旅等级10
#   英雄之旅 等级2       INTEL_BEAST_MISSION/BEAST   英雄之旅等级2   <-- wrong
#   大师悬赏             INTEL_MASTER_BOUNTY         大师悬赏：20号
#
# The generic anywhere matcher ``TARGET_INTEL_BEAST_MISSION`` (gate 54) answers
# d=28 on EVERY Intel dialog -- including the beast one -- so it cannot discriminate
# at all; and the specific title matchers bake the level into their crop
# (``POPUP_INTEL_HERO_JOURNEY_TITLE`` was cropped from 英雄之旅等级10, so it sat at
# d=16, threshold 8, on a 等级2 dialog).  The generic one therefore answered, a
# 英雄之旅 dialog became a beast mission, and ``OPEN_INTEL_BEAST_TARGET`` went
# looking for a beast target that was never on screen.
#
# The level is inside the OCR text too, but OCR reads it rather than hashing it, so
# the variability is harmless -- and the level is a real reading that ``vision.py``
# had been hardcoding to 10 for every mission.
INTEL_TITLE_ROI = {"x_norm": 0.15, "y_norm": 0.19, "w_norm": 0.70, "h_norm": 0.14}

# (title text, popup semantic, mission type).  Only names actually observed on this
# client are here; anything else leaves the template layer's answer untouched rather
# than guessing which mission it might be.
INTEL_DIALOG_TITLES: tuple[tuple[str, str, str], ...] = (
    ("击败野兽", "INTEL_BEAST_MISSION", "BEAST"),
    ("英雄之旅", "INTEL_HERO_JOURNEY", "HERO_JOURNEY"),
    ("大师悬赏", "INTEL_MASTER_BOUNTY", "MASTER_BOUNTY"),
)

# The mission_id prefix each type must carry.  When the title corrects the type, a
# mission_id the wrong branch invented is dropped instead of being kept: keeping it
# would leave ``intel.mission_id = INTEL_BEAST_10`` attached to a hero journey.
INTEL_MISSION_ID_PREFIX = {
    "BEAST": "INTEL_BEAST_",
    "FIREBEAST": "INTEL_FIREBEAST_",
    "RESCUE_SURVIVORS": "INTEL_RESCUE_SURVIVORS_",
}

_LEVEL_IN_TITLE = re.compile(r"等级\s*(\d{1,3})")

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


def looks_like_a_dropped_digit(previous: int | None, current: int | None) -> bool:
    """Is ``current`` the leading digits of ``previous``?

    That is the exact signature the HUD recogniser produced on 2026-09-19: the frame said 527
    and it returned 52, having stopped after the second digit (raw tokens and the frames are in
    ``dataset/truth_audit/stamina_hud_roi_20260919``).  Widening the ROI fixed the two frames
    that were measured, but the failure is a property of the recogniser on a small number, so it
    can come back on a frame nobody has looked at yet.

    Why this is worth a guard rather than a comment: a dropped digit makes a plentiful stamina
    look nearly empty, and ``AVOID_STAMINA_WASTE`` reads this number to decide whether anything
    is left to *spend*.  A false low reading therefore stops the spending the goal exists to
    cause, silently.

    The rule is deliberately narrow, and the narrowness is the point:

    * it only fires when the new value is a strict leading-digit prefix of the old one, which
      means the apparent change is at least a factor of ten.  Stamina moves in tens per mission
      and in hundreds for a free gift, so a genuine single-frame collapse of that size is not a
      thing this account does;
    * it cannot fire on a *rise* (a free claim goes 382 -> 502, which is no prefix of 382), so
      the guard can never suppress a real gain;
    * it does **not** catch the other misread seen the same day, where the last digit is
      recognised as the wrong digit (527 -> 502).  That one differs by 25, which is
      indistinguishable from a real change on one frame, and pretending otherwise would be a
      guard that fires on healthy data.  It stays open, named in the issue ledger.
    """
    if previous is None or current is None:
        return False
    before, after = str(int(previous)), str(int(current))
    return len(after) < len(before) and before.startswith(after) and before != after


# The band the beast and its label occupy on the world map.  Measured 2026-09-19 on the frames in
# dataset/raw/live_runtime/stamina_verify{,_2}: the animal is drawn mid-left and its name label sat
# at (0.269, 0.655) on one frame and (0.189, 0.645) on another, so this is a *search band* and not
# a point.  It is deliberately generous; the name whitelist is what makes the read precise.
#
# WIDENED 2026-09-20, from a measurement that showed the old band was the binding constraint.
# Over 40 live MAP frames, OCR of the whole frame found a registered beast name on 2 of them --
# and BOTH were outside the old x 0.05-0.50 / y 0.45-0.80 box:
#
#   runtime_auto/20260920_232511_351867/…_step_003_before  霜鳞避役 at (0.516, 0.283), conf 0.91
#   runtime_auto/20260920_232511_351867/…_step_002_after   冰霜古猿 at (0.724, 0.243), conf 0.98
#   (plus the 2026-09-19 frame at (0.269, 0.655) that the old band did contain)
#
# Those two frames are from THE live stamina round that had just switched to BEAST_HUNT: the pan
# brought a named beast into view and the route panned past it, because the band only ever covered
# the left half of the screen.  The label is drawn wherever the animal stands, so the band has to
# be the play area.  Measured chrome to exclude: the top HUD ends at y 0.13 (the 24公里 pill sits at
# 0.118) and the bottom coordinate bar starts at y 0.836, so y 0.12-0.80 leaves both out while
# containing every label seen.  Widening does not weaken the read: the guard is the name whitelist
# (building names, alliance flags and 未驻防 all appear in this area and none of them match a
# registered beast name), which is what named_beast_label applies.
BEAST_LABEL_BAND = {"x_norm": 0.0, "y_norm": 0.12, "w_norm": 1.0, "h_norm": 0.68}


def named_beast_label(
    tokens: tuple[OCRToken, ...],
    known_names: Iterable[str],
    *,
    min_confidence: float = 0.8,
    fuzzy_min_confidence: float = 0.75,
) -> str | None:
    """The client's own name for a beast on the map, or None.

    Measured 2026-09-19: the name is printed beside the animal and reads cleanly -- ``霜鳞避役`` at
    0.89 and ``猛犸象`` at 0.88 -- while the templates meant to find the animal by its sprite matched
    nothing on any of 23 frames, because they search a patch of bare snow (see the issue ledger).
    Reading the client's own word is cheaper and more robust than one large animated sprite per
    species, and it is species-agnostic: the same read works for a beast nobody has templated.

    ``known_names`` is the whitelist, and it is the whole reason this is safe: the same band also
    carries alliance flags, 未驻防 markers and building names (联盟畜牧场, 联盟木材场, 铁厂, 开), so an
    unfiltered read would call a sawmill a beast.  Nothing is invented here -- a label no known name
    matches answers None rather than being guessed at, because the answer decides whether a march
    is dispatched.

    The caller restricts the read by passing ``BEAST_LABEL_BAND`` as the ROI to the recogniser, so
    these tokens are already only that band's.
    """
    names = tuple(str(name) for name in known_names if str(name))
    if not names:
        return None
    found = _beast_name_match(tokens, names, min_confidence=min_confidence,
                              fuzzy_min_confidence=fuzzy_min_confidence)
    return found[0] if found is not None else None


def _beast_name_match(
    tokens: tuple[OCRToken, ...],
    names: tuple[str, ...],
    *,
    min_confidence: float = 0.8,
    fuzzy_min_confidence: float = 0.75,
) -> tuple[str, OCRToken] | None:
    """The registered name a token carries, and the token itself.

    Returns the token as well as the name because three later reads need its box: the level badge
    is found *beside* it, the tap point is its centre, and the confidence that must travel with the
    evidence is its own.  Re-deriving the match for each of those (which is what the first version
    did) silently failed wherever the match was a fuzzy one, and reported a confidence of 0.0 for a
    read that had in fact matched.
    """
    best: tuple[float, str, OCRToken] | None = None
    for token in tokens:
        if not token.box:
            continue
        text = str(token.text or "").strip()
        if not text:
            continue
        # A beast's *map* nameplate never carries a digit -- the level is a separate badge beside
        # it.  Measured 2026-09-20, immediately after the band was widened: a beast CARD drawn over
        # the map (集结 control, 推荐实力683,100,000) contributes its own title 等级7霜鳞避役 at
        # confidence 1.00, which outranks the map label underneath at 0.88 and was therefore picked
        # as the map identity -- with a tap point on the card's title bar rather than on an animal.
        # The digit rule separates them on the shape of the word itself: the card title is
        # 等级<N><name>, a composite, and no registered beast name contains a digit.
        if any(character.isdigit() for character in text):
            continue
        if token.confidence >= min_confidence:
            matched = next((name for name in names if name in text or text in name), None)
            if matched is not None:
                if best is None or token.confidence > best[0]:
                    best = (token.confidence, matched, token)
                continue
        # One misread glyph, and only one, and only when the answer is unambiguous.
        #
        # Added 2026-09-20 from a measured read: on the live stamina round's third frame the client's
        # 霜鳞避役 came back as 霜解避役 at 0.78 -- one character wrong, below the 0.80 floor, and
        # not a substring of the registered name either, so both gates refused it and the beast the
        # pan had just brought into view was invisible again.  That is the third defect in this one
        # read (the band clipped it, the level key rejected it, the glyph ended it), and of the three
        # this is the one worth fixing in the reader rather than around it: a four-glyph string that
        # differs from exactly one registered beast name by exactly one glyph is strong evidence,
        # and "exactly one" is what stops near-misses being a free pass for any of them.  Two
        # candidates within one glyph of the token answer None.
        #
        # The lower floor is scoped to this path on purpose: a misread glyph is what lowers the
        # engine's own confidence, so applying the exact-match floor here would re-refuse the very
        # case the path exists for.  0.75 is the measured value rounded down (0.78 observed).
        if token.confidence < fuzzy_min_confidence:
            continue
        near = [name for name in names if _one_glyph_apart(text, name)]
        if len(near) == 1 and (best is None or token.confidence > best[0]):
            best = (token.confidence, near[0], token)
    return (best[1], best[2]) if best is not None else None


def _one_glyph_apart(text: str, name: str) -> bool:
    """Same length, differing in exactly one character."""
    if len(text) != len(name) or text == name:
        return False
    return sum(1 for a, b in zip(text, name) if a != b) == 1


def level_beside_label(
    tokens: tuple[OCRToken, ...],
    name_token: OCRToken | None = None,
    *,
    min_confidence: float = 0.8,
    max_distance_px: float = 260.0,
) -> int | None:
    """The level badge printed beside the beast's name, or None when the frame is ambiguous.

    Measured: ``20`` at full confidence beside ``霜鳞避役``, and ``25``/``28``/``27`` beside other
    animals.

    REVISED 2026-09-20.  This used to be "the only bare number in the band", which only worked while
    the band was small enough to hold one number -- and the band was small enough to hold one number
    because it was clipping whole beasts (see BEAST_LABEL_BAND).  Widening it would have made this
    answer None on every frame, so "beside" is now implemented as what it always meant: the bare
    number **nearest the name token**, and only if it is reachable at all.

    Measured on the three live frames where a name was read, name centre to badge centre:
    89 px (霜鳞避役/20), 198 px (霜鳞避役/19), and the next-nearest bare number on the first of
    those frames sat 850 px away -- so a 260 px radius separates the badge from the page furniture
    with a wide margin either side.  With no name token the old single-candidate rule is kept, so
    callers that cannot name the token still get an honest answer rather than a guess.
    """
    numbers: list[tuple[float, float, int]] = []
    for token in tokens:
        if token.confidence < min_confidence or not token.box:
            continue
        text = str(token.text or "").strip()
        if not (text.isdigit() and 1 <= len(text) <= 2):
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        numbers.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, int(text)))
    if name_token is None or not name_token.box:
        candidates = {value for _, _, value in numbers}
        return candidates.pop() if len(candidates) == 1 else None
    anchor_x = (min(p[0] for p in name_token.box) + max(p[0] for p in name_token.box)) / 2.0
    anchor_y = (min(p[1] for p in name_token.box) + max(p[1] for p in name_token.box)) / 2.0
    best: tuple[float, int] | None = None
    for x, y, value in numbers:
        distance = ((x - anchor_x) ** 2 + (y - anchor_y) ** 2) ** 0.5
        if distance > max_distance_px:
            continue
        if best is None or distance < best[0]:
            best = (distance, value)
    return best[1] if best is not None else None


#: The resource-search tab strip's printed labels, as RapidOCR reads them, and what each one
#: means for the route.  This table exists because the strip's *order* is not stable and never
#: has been: ``vision.resource_tab_order`` carries a WARNING measured on 2026-09-18 saying the
#: front three names are the part that drifts and that the durable fix is to read the anchored
#: tab's own printed label rather than trust any list.  That fix is implemented here.
#:
#: Measured live 2026-09-21 on the frame the beast search failed on
#: (``live_runtime_step_003_before_20260921T100350023898.png``): the strip read
#: 野兽 0.95 / 冰原巨兽 0.98 / 生肉 1.00 / 木材 1.00 / 煤矿 1.00 -- i.e. the client had put 野兽
#: at the leftmost position, where the 2026-09-18 list and the template cut from
#: ``beast_search_exploration/beast_tab.png`` both expected 冰原巨兽.  A template at that
#: position therefore matched nothing (all three beast-search templates scored NO MATCH on the
#: live frame) and the search chain could not take its second hop.
#:
#: The two monster tabs mean different things to the route and must not be conflated:
#:
#: * ``BEAST``       平民野兽.  These are the ordinary huntable animals; the "attack" entry the
#:                    spend goal needs is on their card.
#: * ``GIANT_BEAST`` 冰原巨兽.  These are the rally targets -- the measured level-5 mammoth card
#:                    offered only 集结, no 攻击 -- so a route looking for a solo kill must NOT
#:                    treat this tab as equivalent.
RESOURCE_TAB_LABEL_TO_KIND: dict[str, str] = {
    "野兽": "BEAST",
    "冰原巨兽": "GIANT_BEAST",
    "失控的雪怪": "SNOW_MONSTER",
    "生肉": "MEAT",
    "木材": "WOOD",
    "煤矿": "COAL",
    "铁矿": "IRON",
}


def read_resource_tab_labels(
    image_path,
    ocr,
    *,
    band: tuple[float, float] = (0.655, 0.795),
    min_confidence: float = 0.7,
) -> dict[str, tuple[float, float]]:
    """Read the search panel's tab strip and return each tab's kind -> its centre.

    Why this exists rather than a template per tab: the strip's order drifts between client
    versions (see :data:`RESOURCE_TAB_LABEL_TO_KIND` for the measurement), so a template pinned
    to a position starts matching the *wrong* tab the moment the client reorders them -- which
    is exactly what happened to the beast search on 2026-09-21.  The printed label is drawn by
    the client and read at 0.95-1.00 confidence, so it is both the durable and the cheap answer.

    Returns only the tabs whose label was positively read, so a caller can ask "is the beast tab
    on screen" without a missing tab being confused with an unreadable one.  The band defaults to
    the strip's own measured y-range and is a parameter because the panel is drawn on the map,
    whose HUD sits above it.
    """
    with Image.open(image_path) as source:
        frame_width, frame_height = source.size
    top = band[0]
    height = band[1] - band[0]
    roi = {"x_norm": 0.0, "y_norm": top, "w_norm": 1.0, "h_norm": height}
    tokens = ocr.recognize(image_path, roi).tokens

    found: dict[str, tuple[float, float]] = {}
    for token in tokens:
        if token.confidence < min_confidence or not token.box:
            continue
        kind = RESOURCE_TAB_LABEL_TO_KIND.get(token.text.strip())
        if kind is None or kind in found:
            continue
        xs = [point[0] for point in token.box]
        ys = [point[1] for point in token.box]
        # ROI-scoped token boxes are crop-relative, so the band's top is added back before the
        # point is normalised -- otherwise every returned centre would be off by the crop offset
        # and a tap would land above the tab it names.
        centre_x = (min(xs) + max(xs)) / 2.0 / frame_width
        centre_y = ((min(ys) + max(ys)) / 2.0 + top * frame_height) / frame_height
        found[kind] = (centre_x, centre_y)
    return found


def beast_from_its_label(image_path, ocr, frame_size: tuple[int, int] | None = None) -> dict:
    """The beast the client's own label names, plus where to tap it.

    Measured 2026-09-19: the two sprite templates that were meant to find a beast on the map match
    nothing on 23 live frames, because they search a patch of bare snow, while the client prints the
    animal's name beside it (猛犸象 at 0.88, 霜鳞避役 at 0.89) with a level badge at full confidence.

    REVISED 2026-09-20.  This used to publish only when the beast table said the target could be
    dispatched, which is a per-species pre-approval; it now publishes whenever the identity could be
    *read*, and carries the tap point with it.  The two are different questions and the old code
    answered the wrong one -- the measured consequence was that a live frame whose 霜鳞避役/20 read
    perfectly (name at 0.89, badge at 1.00, row registered) produced ``{}``, so the route recorded
    nothing and went back to panning the map.  The spend is still not authorised here: it is decided
    on the card by the client's own printed assessment, which is what ``is_dispatchable`` now reads.
    What this function may authorise is a tap, and a tap costs no stamina.

    ``tap_norm`` is the centre of the name label's own box, mapped back into frame coordinates.
    Measured on that same frame: the label 霜鳞避役 sits at x 157-204, y 838 in a 720x1280 frame,
    i.e. (0.268, 0.655), and the animal's body occupies x 90-330 / y 760-900 at that column -- the
    client draws the nameplate on top of the animal, so its centre is on the beast and tapping it
    selects that beast.  It is a reading from the same frame, not a calibrated constant.

    ``frame_size`` is required for that mapping because ROI-scoped token boxes are crop-relative;
    without it the identity is still returned and ``tap_norm`` is omitted rather than guessed.
    """
    try:
        from .beast_targets import lookup_by_name, load, may_evaluate

        targets = load()
        if not targets:
            return {}
        names = {target.name for target in targets if target.name}
        tokens = ocr.recognize(image_path, BEAST_LABEL_BAND).tokens
        found = _beast_name_match(tokens, tuple(sorted(names)))
        if found is None:
            return {}
        name, name_token = found
        # Resolved by NAME, not by (name, level).  The old exact pair meant a beast whose badge
        # disagreed with the row's level resolved to nothing -- measured live 2026-09-20: the row
        # is FROST_SCALED_RUNNER_20 while the animal on the 23:26 map frame carried 19, so a
        # perfectly read name produced no target at all.  The level is data about the animal, not a
        # gate on acting on it: whether the fight is winnable is the client's own verdict later.
        row = lookup_by_name(name, None, targets)
        if row is None:
            return {}
        badge = level_beside_label(tokens, name_token)
        beast = {
            "visible_target": row.species,
            "level": badge if badge is not None else row.level,
            "available": True,
            "source": "BEAST_LABEL",
            # The matched token's own confidence, so the evidence carries the number the engine
            # actually reported rather than a second read that may not reproduce it.
            "label_confidence": round(float(name_token.confidence), 4),
            "label_text": str(name_token.text or "").strip(),
            "table_level": row.level,
            "level_matches_table": badge is None or badge == row.level,
        }
        tap = _label_tap_norm(name_token, frame_size)
        if tap is not None:
            beast["tap_norm"] = tap
        if row.refused:
            # The client has already been seen turning this one down; say so rather
            # than emitting a target the route may not tap.
            beast["refused_by_evidence"] = True
        if not may_evaluate(beast, targets):
            return {}
    except Exception:  # noqa: BLE001 - recognition must never take the frame with it
        return {}
    return beast


def _name_token(tokens: tuple[OCRToken, ...], name: str, *, min_confidence: float = 0.8) -> OCRToken | None:
    """The token the name was read from, so its box can anchor the level read and the tap."""
    best: OCRToken | None = None
    for token in tokens:
        text = str(token.text or "").strip()
        if token.confidence < min_confidence or not token.box or not text:
            continue
        if name in text or text in name:
            if best is None or token.confidence > best.confidence:
                best = token
    return best


def _label_tap_norm(
    name_token: OCRToken,
    frame_size: tuple[int, int] | None,
) -> tuple[float, float] | None:
    """Centre of the name label's box in frame-normalised coordinates, or ``None``.

    ROI-scoped boxes are relative to the crop, so the band's own origin is added back and
    the sum is divided by the frame size.  ``None`` (no size, or no box) is the honest
    answer; a coordinate invented from a hardcoded fraction is what the executor would
    then tap.
    """
    if not frame_size or not name_token.box:
        return None
    width, height = (int(frame_size[0]), int(frame_size[1]))
    if width <= 0 or height <= 0:
        return None
    xs = [float(point[0]) for point in name_token.box]
    ys = [float(point[1]) for point in name_token.box]
    x_norm = BEAST_LABEL_BAND["x_norm"] + ((min(xs) + max(xs)) / 2.0) / width
    y_norm = BEAST_LABEL_BAND["y_norm"] + ((min(ys) + max(ys)) / 2.0) / height
    if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
        return None
    return (round(x_norm, 4), round(y_norm, 4))


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

    def read_role_identity(self, image_path: Path) -> RoleIdentity | None:
        """Read which role is logged in, or ``None`` when this is not that panel.

        Deliberately separate from :meth:`observe`.  Identity is a session-level
        fact, not a per-frame one: putting it in ``WorldState`` would make every
        observation carry it, and the identification step is the only caller.

        Gated on two independent facts -- the panel's own title *and* the account
        row -- because the same panel holds the 设置 tab, which is where
        ``config.risk.block_account_or_role_delete`` applies.  A frame that is not
        plainly this panel yields ``None`` rather than a guess.
        """
        title_tokens = self.ocr.recognize(image_path, ROLE_PROFILE_TITLE_ROI).tokens
        title = "".join(token.text.strip() for token in title_tokens if token.confidence >= 0.80)
        if ROLE_PROFILE_TITLE not in title:
            return None
        info = self.ocr.recognize(image_path, ROLE_PROFILE_INFO_ROI)
        tokens = [token for token in info.tokens if token.confidence >= 0.80]
        if not tokens:
            return None
        return parse_role_identity(
            title,
            read_role_identity_rows(tokens),
            confidence=min(token.confidence for token in tokens),
        )

    def _building_is_selected(self, image_path: Path) -> bool:
        """True when the city frame is showing a selected building's action controls.

        Cheap template gate, so the OCR pass below only runs on frames where the label
        can actually be there.  The two entries are the two selection states measured so
        far, each cropped from the frame that shows it:

          * ``BTN_UPGRADE`` -- the 升级 control of a selected 仓库
            (``live_build_quest_navigation.png``);
          * ``BTN_TRAINING_MENU_LABEL`` / ``BTN_OPEN_TRAINING_FROM_CAMP`` -- the radial
            menu of a selected 盾兵营, live 2026-09-17 19:51 GMT+8
            (``dataset/truth_audit/power_route_20260917/build_live2_...after_tap_280_640.png``).

        Deliberately a tuple of *observed* states rather than "any HOME frame": extending
        it as new selection states are measured is cheap, while OCR-ing every city frame
        would tax the loop for a read that usually has nothing to read.
        """
        semantic = getattr(self.template_vision, "semantic", None)
        if semantic is None:
            return False
        for name in ("BTN_UPGRADE", "BTN_TRAINING_MENU_LABEL", "BTN_OPEN_TRAINING_FROM_CAMP"):
            try:
                if semantic.find(image_path, name) is not None:
                    return True
            except Exception:  # noqa: BLE001 - a missing template must not break observation
                continue
        return False

    def _read_intel_dialog_title(self, image_path: Path, primary: WorldState) -> WorldState | None:
        """Correct the Intel dialog's type from its title, or ``None`` for any other frame.

        ``None`` means "not an Intel dialog" and leaves the template layer's answer
        alone.  A frame that *is* an Intel dialog but whose title names no known
        mission is also left alone -- the alternative would be guessing which mission
        it is, and a wrong type sends the brain down a route whose verifier then fails
        for a reason that is not the real one.

        The corrected state keeps every field the template layer read (status, pins,
        stamina) and only rewrites what the title actually determines: the popup, the
        mission type, and the level, which the template layer had hardcoded.
        """
        if primary.page is not Page.POPUP or not (primary.popup or primary.intel):
            return None
        tokens = self.ocr.recognize(image_path, INTEL_TITLE_ROI).tokens
        joined = "".join(token.text for token in tokens if token.confidence >= 0.85)
        if not joined:
            return None
        for title, popup, mission_type in INTEL_DIALOG_TITLES:
            if title not in joined:
                continue
            intel = dict(primary.intel or {})
            level = _LEVEL_IN_TITLE.search(joined)
            intel["mission_type"] = mission_type
            intel.setdefault("status", "AVAILABLE")
            if level is not None:
                intel["mission_level"] = int(level.group(1))
            # A mission_id belonging to a different type was invented by the branch
            # that got the type wrong, so it is dropped rather than carried over.
            prefix = INTEL_MISSION_ID_PREFIX.get(mission_type)
            current_id = str(intel.get("mission_id") or "")
            if current_id and (prefix is None or not current_id.startswith(prefix)):
                intel.pop("mission_id", None)
            if primary.popup == popup and primary.intel == intel:
                return None
            return replace(primary, popup=popup, intel=intel)
        return None

    def _read_building_identity(self, image_path: Path, primary: WorldState) -> WorldState | None:
        """Attach building identity read off pixels, or ``None`` when this is not that frame.

        The distinction between "not this frame" (``None``) and "this frame, nothing
        readable" (keys set to UNKNOWN) is deliberate: the first leaves whatever the
        template layer said, the second records that a read was attempted and failed.
        Nothing here invents a value -- an unreadable name, a name outside the table, or
        a name with no spatially associated number all end as UNKNOWN.
        """
        is_dialog = primary.page is Page.BUILDING
        if not is_dialog and not (primary.page is Page.HOME and self._building_is_selected(image_path)):
            return None

        tokens = [token for token in self.ocr.recognize(image_path).tokens
                  if token.confidence >= 0.80]
        if not tokens:
            return None
        identity = read_building_identity(tokens, quest_texts=[token.text for token in tokens])
        read = identity.as_state()

        state = dict(primary.building)
        for key in ("id", "name", "level", "target_level"):
            value = read[key]
            # Never overwrite a previously read value with UNKNOWN/None, never invent one.
            if value not in (None, UNKNOWN_IDENTITY):
                state[key] = value
            elif key not in state:
                state[key] = value
        state["identity_confidence"] = read["identity_confidence"]
        state["identity_source"] = read["identity_source"]
        return replace(primary, building=state)

    def observe(self, image_path: Path) -> WorldState:
        primary = self.template_vision.observe(image_path)
        # A frame the template layer cannot name gets the OCR classifier, and the training
        # page is the one case that needs to be *recognised* here rather than merely enriched.
        #
        # Measured 2026-09-21: the training branch used to sit nested under ``if
        # primary.known:`` while its own guard was ``primary.page is Page.UNKNOWN``.
        # ``UNKNOWN`` means ``not known``, so the branch was unreachable and the training page
        # was never recognised through the production entry point -- the unit test passed
        # because it called ``OCRPageClassifier.classify`` directly, one layer lower.  The
        # dead-page problem it was written to solve was still unsolved, and nothing said so.
        #
        # It runs before the known-page chain because only an unnamed frame can reach it.
        # The classifier's own gate (it must answer TRAINING itself, which requires both a
        # training-status token and a camp name) is what stops a genuinely unknown frame from
        # becoming a training page, not this branch.
        if primary.page is Page.UNKNOWN:
            classified = self.classifier.classify(self.ocr.recognize(image_path))
            if classified.page is Page.TRAINING and classified.training:
                # The camp model turns the classifier's selected-tab reading into the
                # per-barracks answer.  Only the open camp is described: the other two were
                # not on screen, and writing "idle" about a barracks nobody opened is the
                # claim that let one busy camp close the whole training goal (#86).
                camps = observe_camps(
                    page_is_training=True,
                    selected_camp=camp_from_selected_label(
                        [classified.training.get("camp_selected_label") or ""]
                    ),
                    training=classified.training,
                )
                return replace(
                    classified,
                    camps=merge_camps(primary.camps, camps),
                    confidence=max(primary.confidence, classified.confidence),
                )
            return classified
        if primary.known:
            # The march counter is drawn on the map HUD and stays drawn under map
            # overlays such as RESOURCE_DETAIL. Read it on both pages so a target
            # dialog can never launch a march after the queue filled between
            # target search and dispatch.
            #
            # Corrected 2026-09-16: this used to call march capacity "a global HUD
            # fact".  It is neither global nor constant.  Capacity is a property of
            # the logged-in role and it moves: account A (2026-09-14) drew 行军 3/6
            # while account B, `xhw小号` (2026-09-16), drew 1/2 on the same server
            # #4298.  Only ``march_max`` read off a counter is a fact; nothing here
            # may supply one when the client did not draw it.
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
            # CAP-A01 (2026-09-17).  Which Intel mission dialog is drawn is written in
            # its title, so it is read here.  See INTEL_DIALOG_TITLES for the measured
            # table that makes this a measurement rather than a preference: the loose
            # generic matcher answers the same distance on every Intel dialog, so the
            # template layer cannot answer this question at all.
            intel_state = self._read_intel_dialog_title(image_path, primary)
            if intel_state is not None:
                return intel_state
            # CAP-B01 (2026-09-18).  A building's identity is text, so it is read here
            # and never guessed by the template layer.  Two frames carry it, and both are
            # gated on something that proves the frame really is that frame:
            #   * the city frame with a building selected -- floating label ``26 仓库``
            #     above it, quest banner naming the target, gated on BTN_UPGRADE (the
            #     升级 control, cropped from the same live frame as the label);
            #   * the upgrade dialog, gated on Page.BUILDING, whose title carries the
            #     name (the dialog has no current level -- only the prerequisite row).
            # ``None`` means "not one of those frames" and leaves the state untouched.
            building_state = self._read_building_identity(image_path, primary)
            if building_state is not None:
                return building_state
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
                # A counter that is simply not drawn is not an unreadable counter --
                # but "not drawn" may only be concluded where the HUD is actually on
                # screen.  The rule is therefore restricted to a plain MAP page.
                #
                # Measured 2026-09-16 while tracking a live dispatch: on the MAP frame
                # right after the march left, the ROI read '1/2' and marches=MARCHING.
                # Twenty seconds later, with the resource dialog open, the same run
                # observed page=RESOURCE_DETAIL / ROI='' / marches=() and the rule
                # below reported used=0 -- "idle" -- while that march was still out and
                # could not have finished a gather.  The overlay covers both the
                # counter and the march list, so absence of evidence was being read as
                # evidence of absence.  A RESOURCE_DETAIL or POPUP frame may therefore
                # only ever report used=None (unknown); observed for POPUP frames
                # already, which is the safe direction.
                #
                # Original justification, which still holds for true MAP frames:
                # measured 2026-09-15 across every recorded MAP observation in the
                # corpus, (march_used is None, no march states) occurs 98 times while
                # (march_used is None, march states present) occurs 35.  The first is
                # the client drawing no counter because nothing is out; the second is a
                # count we genuinely cannot read.  Only the first may be read as idle --
                # and it has to be, because leaving it unknown stops the entire gather
                # workflow at its first step (CHECK_MARCH / MARCH_COUNT_NOT_READ, live
                # 2026-09-15T12:59:36Z) with no way to recover.
                #
                # The cost is asymmetric in the right direction: if this is ever wrong,
                # the dispatch fails its verifier and costs one action; treating a
                # genuinely idle queue as unreadable costs the whole gather goal,
                # permanently.  The guard uses fused_marches, so evidence of a march
                # from either layer keeps the count unknown rather than guessing.
                if march_used is None and not fused_marches and primary.page is Page.MAP:
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
                beacon_beast = dict(primary.beast) or beast_from_its_label(
                    image_path, self.ocr, frame_size=(frame_width, frame_height)
                )
                # Which monster tab the open panel is actually on, read from the client's own
                # printed label rather than from a template pinned to a position.
                #
                # Measured 2026-09-21: the three beast-search templates all scored NO MATCH on
                # the live frame, because the client had moved 野兽 to the leftmost slot where
                # the template (cut from an archived frame whose leftmost was 冰原巨兽) expected
                # it.  ``vision.resource_tab_order`` already carries a WARNING from 2026-09-18
                # that this part of the strip drifts and that the durable answer is to read the
                # label; this is that read.  It is done here rather than in the template layer
                # because the template layer has no OCR, and the label is an OCR-layer fact.
                tab_labels = (
                    read_resource_tab_labels(image_path, self.ocr)
                    if primary.resource_search_open else {}
                )
                return replace(
                    primary,
                    marches=tuple(fused_marches),
                    march_used=march_used,
                    march_max=march_max,
                    stamina=stamina,
                    # The tab itself, by its own name.  A search panel whose strip was read is
                    # described by the tabs that were positively found; the bool keeps the
                    # template-layer meaning ("the 冰原巨兽 control is drawn") for callers that
                    # still key on it, and the kind is what the route should act on.
                    resource_beast_tab=bool(tab_labels),
                    resource_tab_kinds=tuple(sorted(tab_labels)),
                    resource_beast_tab_norm=tab_labels.get("BEAST"),
                    resource_giant_beast_tab_norm=tab_labels.get("GIANT_BEAST"),
                    # The client's beast search ran and left a target on the map.
                    #
                    # Measured 2026-09-21 on ``beast5_found.png``: after 搜索 the
                    # panel stays open on the beast tab and the result card is
                    # drawn on top of it, so "the panel is gone" would never be
                    # true for a successful search.  The state that is actually
                    # observable is the pair -- beast tab still selected AND a
                    # beast now on the map -- and the beast is taken from the
                    # label read rather than a species sprite, because the search
                    # returned a 25-level mammoth that ``TARGET_BEAST_MAMMOTH_5``
                    # does not match; keying on the sprite would have reported
                    # that success as a failure.
                    #
                    # This is a fusion-layer fact on purpose: the beast tab is a
                    # template-layer reading and the label is an OCR-layer one, so
                    # neither layer alone can state it.
                    beast_search_submitted=bool(
                        primary.resource_beast_tab and beacon_beast
                    ),
                    # Only when the template path found nothing: that path is LIVE_VERIFIED and
                    # its values are not re-decided here.  The frame size goes along because the
                    # label read carries a tap point with it, and an ROI-scoped token box can
                    # only be mapped back to the frame with it.
                    beast=beacon_beast,
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
