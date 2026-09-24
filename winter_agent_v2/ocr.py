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
from .entry_badges import read_all

def _frame_stamp(frame: Path) -> str:
    """When this frame was written, taken from the file itself.

    The frame's *name* carries a step timestamp (``..._20260922T160220374378.png``), but that is the
    container's clock and it has already been misread once in this project's analysis; the file's own
    mtime is the clock the runtime wrote it with, so that is the one published.
    """
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(frame.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return ""

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


#: The troop word inside a page title, and the troop it names.  This is the *derivation* the
#: classifier's own note asked for -- "the title wording is not a constant across camps, so the
#: match is on the TROOP WORD the title contains rather than on a full title string" -- and it
#: exists because the full-title table above could not keep up with the client: measured live
#: 2026-09-22T05:24:12Z, the 射手营 page drew ``英勇射手``, which was in no table, so the page
#: read UNKNOWN and a tap that had opened the camp was recorded as an unproven switch.
TROOP_WORDS: tuple[tuple[str, str], ...] = (
    ("盾兵", "INFANTRY"),
    ("矛兵", "LANCER"),
    ("射手", "MARKSMAN"),
)


def troop_from_title(text: str) -> str | None:
    """The troop a page title names, or ``None`` when this token is not a camp title.

    Deliberately *not* a table lookup: the client varies the adjective (英勇 / 刚毅 / 王牌) and
    has been measured changing it, while 盾兵 / 矛兵 / 射手 have held.  A token that ends in 营 is
    a tab label rather than a title and is refused, because all three tabs are drawn at once and
    accepting them would report three troops for one page.
    """
    value = str(text or "").strip()
    if not value or value.endswith("营"):
        return None
    for word, troop in TROOP_WORDS:
        if word in value:
            return troop
    return None


@dataclass(frozen=True)
class OCRToken:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...] = ()

    @property
    def centre(self) -> tuple[float, float]:
        """The token's box centre, or ``(0.0, 0.0)`` when it carried no box.

        Readers that ask "did the client draw this on the same line as that" need
        a position, and boxes arrive as four corner points rather than a rect.
        A token without a box cannot answer, and the origin is the value that
        makes a same-line test fail rather than silently pass.
        """
        if not self.box:
            return (0.0, 0.0)
        xs = [point[0] for point in self.box]
        ys = [point[1] for point in self.box]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


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


#: The section headers of the 快捷面板, in the order the client draws them.
#:
#: The panel opens *over* another page, so these words can be on screen while the
#: player is not on the page they would otherwise name -- 科技研究 is also the
#: research lab's own header.  Both the page classifier below and
#: ``read_quick_panel`` are built on this list, so the two can never disagree about
#: what the panel says.
QUICK_PANEL_SECTIONS: tuple[str, ...] = ("建筑队列", "部队训练", "科技研究")

#: The sections the **panel reader** accepts and reads, in the client's own order.
#:
#: Wider than ``QUICK_PANEL_SECTIONS`` on purpose, and the difference is not an oversight: that tuple
#: is the *classifier's* page-identity evidence, and 联盟捐献 is printed by the alliance page as well,
#: so it must not name a page.  The panel does draw it, though -- measured on the operator's frame
#: 2026-09-22 21:50, 联盟捐献 可捐献25/25 和 英雄招募 免费招募 都在这块面板里，两个状态正是指令 §三
#: 要读的东西.  Hence one list per job.
#: The quick panel's row arrow buttons: how the button is LOCATED, and how its blue is read once it is.
#:
#: The locator is the white chevron the client draws inside the button, because the blue cannot say where
#: the button *is* -- it says where blue is, and past the panel's edge the city is blue too.  Measured on
#: ten live panel frames (40 row-readings): 37 give exactly x 396-416 (20 px wide, centre 0.5639,
#: **spread 0.0000**), and the three misses are the 已完成 rows, whose button is replaced by the client's
#: green tick -- i.e. the right answer, not a failure.
#:
#: This replaces a band of (0.45, 0.80), whose right edge is x 576 while the panel ends around 476-484:
#: 155 px of city inside the search, taken as min..max with the WIDEST scan line preferred, which
#: actively selected the contaminated line.  On 2026-09-22 19:31:04 the four rows read 384-477, 384-498,
#: 386-574, 401-494 (centres 0.5979-0.6667, the last outside the panel) against a button whose own cyan
#: (76,198,244) spans x 384-425.  Those points are what the resolver taps: the ledger has 19:32:04
#: [448,804] leaving the panel open (PANEL_ROW_RESEARCH_BAR_NOT_PROVEN), 17:16:14 [480,804] and 17:54:12
#: [448,804] failing the same way, and 18:55:10 [404,804] -- inside the button -- succeeding.
QUICK_PANEL_ARROW_BLUE_MIN: int = 150
QUICK_PANEL_ARROW_BLUE_OVER_RED: int = 35
QUICK_PANEL_ARROW_MIN_RUN_PX: int = 40

#: The white chevron inside the button, and where it may be looked for.
#:
#: All three channels at 245 or above, because the panel dims the city behind it and the palest city
#: pixel measured on those frames is 200-227 -- a threshold the city cannot pass.  The column starts
#: right of the row's own text (a label would otherwise qualify) and stops short of the panel's edge.
QUICK_PANEL_CHEVRON_MIN: int = 245
QUICK_PANEL_CHEVRON_MIN_RUN_PX: int = 8
QUICK_PANEL_BUTTON_COLUMN_X_NORM: tuple[float, float] = (0.38, 0.62)

#: How far the button's blue reaches beyond the chevron -- measured on the same frame, chevron 396-416
#: inside button 384-425, i.e. 12 px left and 9 px right.  12 is used on both sides.
QUICK_PANEL_BUTTON_PAD_PX: int = 12

#: The client's unclaimed-task dot, which is drawn at the button's TOP-RIGHT corner.
#:
#: The note here used to say "the button's left part" and quote the dot at x 0.569-0.589.  Both came from
#: a box the contaminated scan had stretched to 0.539-0.644; on the button's true extent, measured
#: x 384-425, the dot at 412-420 is its right end.  Measured on the 19:31:04 frame: 盾兵 空闲中 and
#: 科技研究 空闲中 carry it, the two training rows and the finished one do not.
QUICK_PANEL_BADGE_RED_MIN: int = 150
QUICK_PANEL_BADGE_OVER_GREEN: int = 60
QUICK_PANEL_BADGE_OVER_BLUE: int = 60
QUICK_PANEL_BADGE_MIN_PX: int = 4

#: How far above and below a row's own y the badge is searched, as a fraction of the frame height.
#: Measured: the dot sits within ~0.013 of the row's y, so this keeps it off the neighbouring row.
QUICK_PANEL_BADGE_HALF_HEIGHT: float = 0.013

#: Which panel section's own row is named by which row key.  The section that draws *several*
#: sub-rows (部队训练 -> 盾兵/矛兵/射手, 英雄招募 -> 高级招募/史诗招募) is not here: those rows are named
#: by their own words and resolved through ``TROOP_TO_CAMP`` or the section's own branch.
SECTION_ROW_KEYS: dict[str, str] = {
    "建筑队列": "BUILDING",
    "科技研究": "RESEARCH",
    "联盟捐献": "ALLIANCE_DONATION",
    "英雄招募": "HERO_RECRUIT",
    "我的奖励": "MY_REWARDS",
}

QUICK_PANEL_READ_SECTIONS: tuple[str, ...] = (
    "建筑队列",
    "部队训练",
    "科技研究",
    "联盟捐献",
    "英雄招募",
    "我的奖励",
    "市场切换",
)


def _read_research_node_candidates(tokens, frame_size: tuple[int, int] | None) -> list[dict]:
    """Read named, leveled research nodes and their current-frame tap points.

    A technology is only a *candidate* here.  The progress pill identifies which
    name belongs to a node, and the label's own OCR box supplies the location; no
    remembered screen coordinates or readiness-to-spend claim is produced.
    """
    if not frame_size or frame_size[0] <= 0 or frame_size[1] <= 0:
        return []
    width, height = frame_size
    positioned = [token for token in tokens if token.box and token.confidence >= 0.88]
    progress = []
    for token in positioned:
        match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", token.text)
        if match and int(match.group(2)) > 0:
            progress.append((token, int(match.group(1)), int(match.group(2))))
    labels = [
        token for token in positioned
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]+(?:[IVXLCDM]+|\d+)", token.text.strip())
    ]
    rows: list[dict] = []
    used_progress: set[int] = set()
    for label in sorted(labels, key=lambda token: (token.centre[1], token.centre[0])):
        x, y = label.centre
        nearby = [
            (abs(x - pill.centre[0]) + abs(y - pill.centre[1]) * 0.6, index, pill, current, total)
            for index, (pill, current, total) in enumerate(progress)
            if index not in used_progress
            and 0 < y - pill.centre[1] <= 110
            and abs(x - pill.centre[0]) <= 110
        ]
        if not nearby:
            continue
        _, index, pill, current, total = min(nearby, key=lambda row: row[0])
        used_progress.add(index)
        node_name = label.text.strip()
        rows.append({
            "node_id": node_name,
            "name": node_name,
            "level": current,
            "level_max": total,
            "progress": f"{current}/{total}",
            "status": "MAXED" if current >= total else "UNFINISHED",
            "tap_norm": [round(x / width, 5), round(y / height, 5)],
            "confidence": round(min(label.confidence, pill.confidence), 4),
            "source": "CURRENT_FRAME_OCR",
        })
    return rows


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
        # ``科技研究`` was removed from this list, for the reason the docstring
        # above already states.  The left triangle opens the 城镇/野外 快捷面板,
        # and that panel draws 科技研究 twice -- once as its third section
        # header (measured 2026-09-21 at y_norm 0.61, x_norm 0.13) and once as
        # the research row's own label beside 空闲中 (y_norm 0.64).  Both are
        # labels *inside a panel that opens over HOME*, so the string is visible
        # while the player is not on the research page.
        #
        # Measured on the operator's own screenshot, the damage was the whole
        # training route:
        #
        #     template layer   Page.UNKNOWN                     (correct)
        #     hybrid           Page.RESEARCH  conf 0.9998       (this rule)
        #     training         {}          <- the three barracks were never read
        #     research         {timer: "06:39:17", status: "IN_PROGRESS",
        #                       queue_available: false}
        #
        # ``06:39:17`` is not research at all: it is the 使馆升级中 BUILDING
        # countdown at y_norm 0.33.  The classifier borrowed it because the
        # research branch matches any HH:MM:SS anywhere on the frame, and then
        # reported IN_PROGRESS for a row whose own word reads 空闲中 (idle).
        #
        # brain.py reads that as a busy queue and answers SAFE_STOP
        # 'training_queue_busy' without ever looking at a barracks -- so the
        # route never trained, and the three 已完成 rows (盾兵/矛兵/射手) sitting
        # in the same panel were invisible.  A confident wrong answer here is
        # worse than UNKNOWN, which is what the template layer had said.
        #
        # The page's own identity is its header, and the header is exactly where
        # ``_is_quick_panel_section`` refuses to count the words.  Keeping the
        # keyword therefore costs nothing on the panel and still names a real
        # research page for callers that reach the classifier with no frame size
        # (a unit test, an ROI-scoped read), so it is restored rather than lost.
        (Page.RESEARCH, ("科技研究",)),
        (Page.INTEL, ("情报",)),
        (Page.DAILY, ("每日任务",)),
        (Page.HERO, ("英雄招募",)),
    )

    # Section headers of the 快捷面板, which opens *over* another page and
    # therefore must never be read as that page's identity.  Listed explicitly
    # so the next keyword added for one of these panels can be checked against
    # it rather than rediscovered live.  The list itself lives at module level
    # (see ``QUICK_PANEL_SECTIONS``) because ``read_quick_panel`` reads the panel
    # by those same words, and one list is what keeps the two in step.
    QUICK_PANEL_SECTIONS = QUICK_PANEL_SECTIONS

    # How far below a countdown to look when asking which queue owns it.  The 快捷面板
    # draws a row's text *above* its countdown (使馆升级中 y=393, 06:39:17 y=422, a
    # 29px gap), so this reaches past a same-row band while staying short of the next
    # section's rows, which are a full row height away.
    OWNER_LOOKUP_PX: float = 36.0

    def __init__(self, minimum_confidence: float = 0.88) -> None:
        self.minimum_confidence = minimum_confidence

    def classify(
        self,
        result: OCRResult,
        *,
        frame_size: tuple[int, int] | None = None,
    ) -> WorldState:
        eligible = [token for token in result.tokens if token.confidence >= self.minimum_confidence]
        # The quick panel's section headers are drawn near the middle of the
        # frame, over whatever page is underneath, so any keyword that is one of
        # them cannot identify a page.  Measured y_norm for the three on the
        # operator's screenshot: 建筑队列 0.28, 部队训练 0.42, 科技研究 0.61.
        #
        # The band is deliberately generous (0.18..0.82) because the panel is
        # dragged open and could sit higher, and because a false *exclusion*
        # only costs a keyword match the template layer already covers, while a
        # false *inclusion* is the failure above.
        #
        # With no frame size the test cannot run, and the honest default is to
        # leave the keywords alone: guessing a height would exclude the wrong
        # tokens, and the caller that matters (``HybridVision.observe``) always
        # has the size to pass.
        def _is_quick_panel_section(token) -> bool:
            if token.text.strip() not in self.QUICK_PANEL_SECTIONS:
                return False
            if not frame_size or frame_size[1] <= 0:
                return False
            ys = [point[1] for point in token.box]
            if not ys:
                return False
            centre = (sum(ys) / len(ys)) / float(frame_size[1])
            return 0.18 <= centre <= 0.82

        section_texts = {token.text.strip() for token in eligible}
        exact_texts = section_texts - {
            token.text.strip()
            for token in eligible
            if _is_quick_panel_section(token)
        }
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
        # The new-troop reveal, measured live 2026-09-22T04:39:04Z.
        #
        # It is what the client answers with the first time a barracks tab is opened: a
        # full-screen troop card, ``新`` in the corner, the unit named as ``6级英勇射手``, and
        # the client's own instruction ``点击任意位置继续`` at the foot.  The frame was recorded
        # as an unknown page, so ``SELECT_TRAINING_CAMP``'s verifier answered
        # TRAINING_CAMP_SWITCH_NOT_PROVEN on a tap that had in fact switched the page -- the
        # camp had been reached and the run could not see it.
        #
        # Two of the client's own words, and the second is what makes it specific rather than a
        # guess about any splash: the instruction it prints is the dismissal, so naming this
        # screen is enough for the runtime's existing "the client declared its own exit" path to
        # clear it (``read_tap_anywhere_instruction`` already covers 点击任意位置继续).
        title = next(
            (text for text in exact_texts if re.fullmatch(r"\d+级(英勇|刚毅|王牌)?(盾兵|矛兵|射手)", text)),
            None,
        )
        if title is not None and any(
            phrase in text for text in exact_texts for phrase in CLIENT_TAP_ANYWHERE_PHRASES
        ):
            return WorldState(
                page=Page.POPUP,
                popup="NEW_TROOP_UNLOCK",
                rewards={"unlocked_troop_title": title},
                confidence=max(token.confidence for token in eligible),
            )
        # The 挂机收益 dialog, measured live 2026-09-22T11:21:44Z.
        #
        # The runtime taps 领取 on the exploration page, the client answers with this dialog, and the
        # frame was read as an unknown page -- so ``EXPLORATION_IDLE_CLAIM``'s verifier reported
        # EXPLORATION_IDLE_DIALOG_NOT_PROVEN on a tap that had in fact opened the dialog, and no skill
        # could act on it afterwards (the skill that confirms it requires Page.POPUP).  The run ended
        # with the green 领取 button on screen and nobody to press it.
        #
        # ``POPUP_EXPLORATION_IDLE_DIALOG`` exists in the template manifest with **zero templates**,
        # so that path can never match; what identifies the dialog is the words the client prints on
        # it, which OCR reads at 1.00.  Two of them: the title and the header beneath it.
        if (
            IDLE_INCOME_DIALOG_TITLE in exact_texts
            and IDLE_INCOME_DIALOG_SUBTITLE in exact_texts
        ):
            return WorldState(
                page=Page.POPUP,
                popup="EXPLORATION_IDLE_DIALOG",
                exploration={"status": "CLAIMABLE", "idle_dialog": True},
                confidence=max(token.confidence for token in eligible),
            )
        found: list[Page] = []
        for page, alternatives in self.RULES:
            if any(keyword in exact_texts for keyword in alternatives):
                found.append(page)
        if "训练中" in exact_texts and any(text in exact_texts for text in ("盾兵营", "矛兵营", "射手营")):
            found.append(Page.TRAINING)
        # The second render of the same page, measured live 2026-09-22.
        #
        # The queue line is not always drawn with the word 训练中.  On the frame that reached the
        # training page for the first time in the project's history
        # (``20260922_120820_865903_step_006_after_refresh_2``, 720x1280) the client drew
        # 原始时间：03:28:53 instead, the 训练 control underneath a tutorial hand (OCR read it as
        # ``训`` alone, conf 1.000), and the three camp tabs 盾兵营 / 矛兵营 / 射手营 at the foot of
        # the page (conf 0.995-0.997).  Nothing above matched, the classifier answered UNKNOWN,
        # ``verify_training_page_open`` answered TRAINING_PAGE_NOT_PROVEN, and a tap that had
        # landed exactly right was recorded as a failure.
        #
        # Two structural words, both drawn by the client, and the conjunction is what makes this
        # specific rather than a guess:
        #
        # * **all three camp tabs at once** -- 盾兵营 / 矛兵营 / 射手营 with the 营 suffix are drawn
        #   together on this page and nowhere else (the 快捷面板 draws 盾兵 / 矛兵 / 射手, without
        #   营, which is why presence of the bare words cannot be used here);
        # * **a camp title from TITLE_TO_TROOP** -- the page title names the troop being trained
        #   (英勇盾兵 here, conf 0.996), and a title only exists for the camp the page is open on.
        if (
            all(text in exact_texts for text in ("盾兵营", "矛兵营", "射手营"))
            and any(troop_from_title(text) for text in exact_texts)
        ):
            found.append(Page.TRAINING)
        # A tutorial hand can obscure a selected building's upgrade sheet and
        # defeat the template page detector. Require its own two-column layout
        # and several independent values. This proves only that navigation
        # reached the sheet; it never sets ``upgradeable`` or permits spending.
        building_sheet = self._building_upgrade_sheet_evidence(
            eligible, frame_size=frame_size
        )
        if building_sheet:
            found.append(Page.BUILDING)
        if len(set(found)) != 1:
            return WorldState(page=Page.UNKNOWN, confidence=0.0)
        page = found[0]
        confidence = max(token.confidence for token in eligible)
        alliance: dict[str, object] = {}
        daily: dict[str, object] = {}
        building: dict[str, object] = (
            {"upgrade_dialog_visible": True, "identity": "UNKNOWN"}
            if page is Page.BUILDING and building_sheet else {}
        )
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
            # This used to say ``{"status": "IN_PROGRESS", "queue_available": False}`` before a single
            # token was looked at, which made "the client is on the training page" mean "a queue is
            # running" -- and the brain's own gate for TRAIN_TROOPS is
            # ``training.get("trainable")``, a key this branch never set.  Measured on the live
            # frames: the page was startable (訓練 button lit, 282 troops set, 03:28:53 projected),
            # the reading called it busy, and the route switched camps twice and then left for the
            # city with the button untouched.
            #
            # What the frame actually says is decided below, from the evidence it draws: a batch
            # count (``正在训练N位``) or a queue countdown above the action bar means running, and the
            # training button's own label means startable.  Nothing is written until then.
            batch_count: int | None = None
            queue_timer: str | None = None
            has_train_button = False
            button_caption: str | None = None
            train_button_norm: list[float] | None = None
            caption_norm: list[float] | None = None
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
            titles = [text for text in exact_texts if troop_from_title(text)]
            named = {troop_from_title(title) for title in titles}
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
                if timer and _above_the_action_bar(timer, eligible, frame_size):
                    # Only a countdown drawn above the action bar is the queue's own; the training
                    # button's caption sits inside the bar and is the batch's projected duration.
                    queue_timer = timer.group(0)
                elif timer is not None:
                    # ...and that caption is *evidence the button is drawn*.  Measured 2026-09-23 on
                    # the 矛兵营 page the panel had just entered
                    # (20260923_001145_train_step_004_after_20260922T161254908568.png): the client
                    # paints its own hand cursor over the 訓練 label right after the tap, so the label
                    # itself is unreadable, the page read UNKNOWN, and the brain -- whose gate is
                    # ``trainable`` -- emitted no TRAIN_TROOPS on a page whose button was lit.  The
                    # caption is the same fact in a place the hand does not cover: on that frame
                    # ``02:33:11`` sits at (x 0.760, y 0.888) while 訓練 would be at y 0.862.
                    #
                    # The running page draws no such caption -- measured on the 射手营 page of the
                    # same run, its right-hand button reads 加速 with no time under it, and its queue
                    # countdown ``00:11:02`` is drawn *above* the bar at y 0.732 next to 訓練中.  So
                    # this is the button's caption and cannot be a queue's countdown.
                    button_caption = timer.group(0)
                    caption_norm = _token_centre_norm(text, eligible, frame_size)
                count = re.search(r"正在训练\s*([0-9,]+)\s*位", text)
                if count:
                    batch_count = int(count.group(1).replace(",", ""))
                if text == TRAINING_BUTTON_LABEL:
                    has_train_button = True
                    train_button_norm = _token_centre_norm(text, eligible, frame_size)
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
            # Now the training page can be read as what it is.  A batch count or a queue countdown
            # is a queue at work; the button's own label without either of those is a camp that can
            # be started, which is the state ``trainable`` names and the one this project kept
            # failing to reach.  With neither, the honest reading is UNKNOWN -- and no
            # ``queue_available`` at all, so a page nobody could read is not mistaken for a busy one.
            if batch_count is not None or queue_timer is not None:
                training.update({"status": "IN_PROGRESS", "queue_available": False})
            elif has_train_button or button_caption is not None:
                # Two ways of seeing the same button: its label, or the projected duration printed
                # under that label.  Either one says the button is drawn, which is what ``trainable``
                # claims -- and reading it from the caption is what survives the client's own hand
                # cursor sitting on the word.
                training.update({"status": "AVAILABLE", "queue_available": True, "trainable": True})
                training["train_button_basis"] = (
                    "LABEL" if has_train_button else "BUTTON_CAPTION"
                )
                # Where the button *is*, on this frame.  The client draws the label at the button's
                # upper line and its projected duration at the lower one, so either centre is a point
                # inside the button -- and the caption is the one that survives the client's own hand
                # cursor sitting on the word, which is the frame this exists for.  The template for
                # ``BTN_START_TRAINING`` is the whole button including its text, so a hand over it is
                # exactly what makes that template score no match; the reading is the durable answer.
                training["train_button_norm"] = train_button_norm or caption_norm
            else:
                training.update({"status": "UNKNOWN"})
            if queue_timer is not None:
                training["timer"] = queue_timer
            if batch_count is not None:
                training["batch_count"] = batch_count
            training["camps_seen"] = [label for label in camp_labels if label in exact_texts]
            # Reported only when exactly the open camp's label is present among the ones the
            # reader is confident about, so a frame that draws a different camp's tab as the
            # prominent one does not silently override the title.
            open_label = CAMP_LABELS.get(TROOP_TO_CAMP.get(training.get("troop_type") or "", ""))
            if open_label in training["camps_seen"]:
                training["camp_open_label"] = open_label
            # Where each tab is drawn *on this frame*.  The labels above answer which camp the
            # page is; these answer where to tap in order to reach a different one, and the two
            # have to come from the same frame or the tap lands on a tab that has moved.
            #
            # Measured 2026-09-22 on the live training page: 盾兵营 (134,1260) / 矛兵营 (361,1260)
            # / 射手营 (586,1260), all three drawn at once, read at 0.990-0.997.  Note what this
            # is *not*: a decision.  All three are present on every camp page, so presence cannot
            # say which is open -- the title above does that.  These are positions only.
            #
            # The reader was written 2026-09-21 and referenced by nothing until now, which is why
            # "switch to the idle barracks" had no route: the goal asked for it, and nothing could
            # turn the tab's name into a pixel.
        if page is Page.RESEARCH:
            texts = [token.text.strip() for token in eligible]
            # The tech tree does not print a generic "researchable" state.  Its current
            # nodes are the live evidence: each node has a name, a progress pill and a
            # position on this frame.  Keep those observations separate from the
            # permission to spend resources; RuleBrain may use them to inspect a node,
            # but the presence of an unfinished node alone never enables RESEARCH.
            research["node_candidates"] = _read_research_node_candidates(eligible, frame_size)
            # On the detail sheet the node is named again beside its own 研究 control.
            # The tree header 科技研究 must not count as that control.
            detail_controls = [
                token for token in eligible
                if token.text.strip() in {"研究", "开始研究"}
            ]
            if detail_controls:
                candidates = research["node_candidates"]
                label_tokens = [
                    token for token in eligible
                    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]+(?:[IVXLCDM]+|\d+)", token.text.strip())
                ]
                visible_names = {token.text.strip() for token in label_tokens}
                named = [item for item in candidates if item["name"] in visible_names]
                if len(visible_names) == 1:
                    selected_name = next(iter(visible_names))
                elif named:
                    selectable = [item for item in named if item["level"] > 0 and item["status"] == "UNFINISHED"]
                    selected_name = min(selectable or named, key=lambda item: item["tap_norm"][1])["name"]
                else:
                    selected_name = ""
                if selected_name:
                    research["selected_node"] = selected_name
                    research["selected_node_name"] = selected_name
                    research["node_detail_visible"] = True
                    control = max(detail_controls, key=lambda token: token.confidence)
                    research["research_control_norm"] = _token_centre_norm(
                        control.text.strip(), eligible, frame_size
                    )
            if "病房扩建VII" in exact_texts:
                research.update({"node":"WARD_EXPANSION_VII", "name":"病房扩建VII", "branch":"GROWTH"})
                if "2/3" in exact_texts:
                    research["level_progress"] = "2/3"
            # A countdown drawn in the queue's own row is the queue's timer, and the
            # client draws a countdown only while the queue is running -- see
            # ``knowledge/resources/mechanism_cards.json``: "队列进行中 -> 使用加速 ->
            # 剩余时间下降", a remaining time exists only for a running queue.  So a
            # countdown is itself the proof of IN_PROGRESS, and no separate status word
            # is required next to it.
            #
            # What the row test is for is *ownership*: picking the countdown that
            # belongs to research rather than the first one on the frame.
            #
            # Measured 2026-09-21.  The previous loop took the first ``HH:MM:SS``
            # anywhere, and on the operator's 快捷面板 screenshot that was ``06:39:17``
            # -- the countdown of 使馆升级中, the **building** queue, a different feature
            # drawn in a different row of the same panel.  The panel also prints 科技研究,
            # so the classifier had already named the page RESEARCH; the borrowed timer
            # then set ``queue_available=False``, and brain.py (both on HOME, line ~872,
            # and on the page itself, line ~1000) answered SAFE_STOP
            # ``research_queue_busy`` / ``training_queue_busy`` without ever looking at a
            # barracks.  One row's timer silently became another feature's state, and the
            # three idle camps in that same panel were never opened.
            #
            # The test is a *vertical band above the countdown*, not a same-row match,
            # because in the panel the countdown sits *under* the text it belongs to:
            # 使馆升级中 y=393 with 06:39:17 y=422.  A same-row test would find nothing
            # there, and a test that finds nothing lets the borrowed countdown back in.
            # The band reaches to the row above so it can prove the countdown is *not*
            # part of it, while still reaching the queue label that owns it.
            for token in eligible:
                timer = re.fullmatch(r"(?:(\d+)天)?(\d{1,2}:\d{2}:\d{2})", token.text.strip())
                if not timer:
                    continue
                centre = token.centre[1]
                above = [
                    other.text.strip()
                    for other in eligible
                    if centre - self.OWNER_LOOKUP_PX <= other.centre[1] < centre
                ]
                # The 快捷面板 repeats the section header above each of its rows, so a
                # countdown whose header reads 建筑队列 belongs to the building queue. Keep
                # that reading on its own queue instead of borrowing it for research (the old
                # bug) or dropping it (which made an occupied builder look unobserved).
                building_owner = any("建筑队列" in text or "升级中" in text for text in above)
                if building_owner:
                    building.update({
                        "timer": f"{timer.group(1)}d{timer.group(2)}" if timer.group(1) else timer.group(2),
                        "status": "UPGRADING",
                        "queue_available": False,
                        "source": "LIVE_CLIENT_OCR",
                    })
                    continue
                research.update({
                    "timer": f"{timer.group(1)}d{timer.group(2)}" if timer.group(1) else timer.group(2),
                    "status": "IN_PROGRESS",
                    "queue_available": False,
                })
                break
            if "queue_available" not in research and "空闲中" in exact_texts:
                research.update({"status": "IDLE", "queue_available": True})
            if (
                building.get("queue_available") is not False
                and any("建筑队列" in text for text in exact_texts)
                and "空闲中" in exact_texts
            ):
                building.update({"status": "IDLE", "queue_available": True, "source": "LIVE_CLIENT_OCR"})
        return WorldState(page=page, alliance=alliance, daily=daily, building=building,
                          research=research, training=training, events=events, confidence=confidence)

    @staticmethod
    def _building_upgrade_sheet_evidence(tokens, *, frame_size: tuple[int, int] | None) -> bool:
        """Recognize the upgrade sheet from positioned OCR, without guessing its identity."""
        if not frame_size or frame_size[0] <= 0 or frame_size[1] <= 0:
            return False
        placed = []
        for token in tokens:
            if not token.box:
                continue
            xs = [point[0] for point in token.box]
            ys = [point[1] for point in token.box]
            rect = (min(xs) / frame_size[0], min(ys) / frame_size[1],
                    max(xs) / frame_size[0], max(ys) / frame_size[1])
            placed.append((token.text.strip(), rect))

        def has(text: str, *, x=None, y=None) -> bool:
            return any(
                value == text
                and (x is None or x[0] <= (rect[0] + rect[2]) / 2 <= x[1])
                and (y is None or y[0] <= (rect[1] + rect[3]) / 2 <= y[1])
                for value, rect in placed
            )

        duration = any(
            re.fullmatch(r"\d{1,3}\s*秒", text)
            and 0.28 <= (rect[1] + rect[3]) / 2 <= 0.67
            for text, rect in placed
        )
        attribute = any(
            re.fullmatch(r"\d+(?:\.\d+)?\s*\+\s*\d+(?:\.\d+)?", text)
            and 0.32 <= (rect[1] + rect[3]) / 2 <= 0.72
            for text, rect in placed
        )
        # The cost is often partly covered by the tutorial hand on a newly selected
        # building.  It is useful corroboration when readable, but page identity only
        # needs the distinctive two-column upgrade sheet.  This fallback proves
        # navigation only; it never identifies the building or authorizes spending.
        return (
            has("时间", x=(0.04, 0.24), y=(0.56, 0.66))
            and has("属性", x=(0.04, 0.24), y=(0.60, 0.72))
            and has("升级", x=(0.72, 0.96), y=(0.46, 0.56))
            and duration and attribute
        )


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


# --- the 快捷面板 -----------------------------------------------------------
# The left-edge triangle opens a panel drawn *over* the current page.  It repeats
# the three queue states the route otherwise walks to one at a time, and it is the
# only surface that shows all three barracks together -- which matters because the
# training page reveals one camp per visit (#86).
#
# The panel has a regular shape, measured 2026-09-21 on a live frame open over the
# city view: each row prints its name and its state on consecutive lines about 30px
# apart, name above state.
#
#     y=321 建筑队列      (section header)
#     y=360 使馆升级中
#     y=390 06:14:58
#     y=433 队列2
#     y=464 购买队列
#     y=507 部队训练      (section header)
#     y=546 盾兵           y=576 已完成
#     y=619 矛兵           y=649 已完成
#     y=692 射手           y=723 已完成
#     y=765 科技研究      (section header)
#     y=805 科技研究       y=835 空闲中
#
# The reader therefore walks the section headers in vertical order and assigns the
# rows between one header and the next to that section.  It is driven by the section
# headers rather than by absolute positions because the panel is draggable and its
# rows are scrolled, and a reading pinned to y would be wrong the moment it moved.
#: The state words the panel prints under a row's name.
QUICK_PANEL_IDLE_WORDS: tuple[str, ...] = ("空闲中",)
QUICK_PANEL_COMPLETED_WORDS: tuple[str, ...] = ("已完成",)
QUICK_PANEL_BUSY_WORDS: tuple[str, ...] = ("训练中", "升级中", "研究中", "进行中")


def _quick_panel_queue_state(word: str) -> tuple[str, bool | None]:
    """Map a client-drawn queue word without conflating finished and idle states."""
    value = str(word or "").strip()
    if value in QUICK_PANEL_COMPLETED_WORDS:
        return "COMPLETED", False
    if value in QUICK_PANEL_IDLE_WORDS:
        return "IDLE", True
    if value in QUICK_PANEL_BUSY_WORDS:
        return "IN_PROGRESS", False
    if re.fullmatch(r"(?:(\d+)天)?\d{1,2}:\d{2}:\d{2}", value):
        return "IN_PROGRESS", False
    return "UNKNOWN", None

#: How far below a row's name its state line is drawn.  Measured at 30px on a
#: 720x1280 frame; the band is generous because the two lines are separate OCR
#: tokens whose boxes vary a little, and because the state word is short.
QUICK_PANEL_STATE_OFFSET_PX: float = 30.0

#: How far right of the panel's own text the per-task arrows and the handle sit, in pixels of a
#: 720-wide frame.  Measured from the panel's row block on the one live capture of the expanded
#: panel this project owns; the reader reports the resulting point with ``PANEL_RELATIVE_ESTIMATE``
#: as its basis, because the arrows and the triangle are icons that have not been confirmed
#: pixel-by-pixel yet -- an estimated region is a candidate to try, not a measurement to trust.
QUICK_PANEL_ARROW_MARGIN_PX: float = 8.0

#: How far below a section's header its own rows may sit.  Measured on the expanded panel: the
#: section's rows are ~73 px apart and the third one (射手, y=0.541) is 185 px below the 部队训练
#: header, while the bottom navigation bar sits 487 px below the 科技研究 header.  260 separates them
#: without dropping a real row -- 120 was tried first and silently lost 射手.
QUICK_PANEL_MAX_ROW_OFFSET_PX: float = 260.0

#: The panel is a left-hand strip.  Its right edge has to be measured from the tokens *inside* it:
#: the same y band also carries the right-hand HUD (00:00:00 at x 0.86-0.98 measured), and including
#: it pushed the computed edge to the clamp and put the arrows off the panel entirely.
QUICK_PANEL_COLUMN_MAX_X_NORM: float = 0.55


#: Where the 快捷面板 is drawn, as an ROI.
#:
#: Measured 2026-09-21 on a live 720x1280 frame with the panel open over the city: every
#: token it draws sits between x_norm 0.10 and 0.34 -- headers at 0.11, row names and
#: states at 0.31 -- and between y_norm 0.25 (建筑队列) and 0.66 (科技研究's 空闲中).  The
#: ROI is that box with margin, because the panel is draggable and can be pulled wider
#: when a row's text is long.
#:
#: Narrower than the full frame on purpose: it carries none of the words that identify a
#: *page*, so a cropped read of it cannot let the panel's own section headers name the
#: page underneath, which is the defect this whole area exists to fix.
QUICK_PANEL_ROI = {"x_norm": 0.02, "y_norm": 0.20, "w_norm": 0.46, "h_norm": 0.52}

#: The part of the frame the panel's plate covers, as ``(left, top, right, bottom)``
#: fractions.  Used only by the pixel gate that decides whether to OCR the panel at all;
#: the reader itself works from the tokens, so this box does not have to be exact.
QUICK_PANEL_PLATE_ROI: tuple[float, float, float, float] = (0.10, 0.26, 0.42, 0.66)

#: How much of ``QUICK_PANEL_PLATE_ROI`` must carry the plate's fill before the panel is
#: considered drawn.  Measured 0.674 with the panel open against 0.038 or less without,
#: so the value sits in the middle of a wide gap rather than on a measured edge.
QUICK_PANEL_PLATE_MIN_FRACTION: float = 0.30


def _is_quick_panel_plate_pixel(pixel: tuple[int, int, int]) -> bool:
    """True when ``pixel`` is the colour of the 快捷面板's card.

    The plate is a flat dark navy: blue clearly above both red and green, a moderate
    blue-over-green separation, and a low red.  Measured samples from the live panel
    frame include ``(53, 62, 91)``, ``(56, 70, 102)`` and ``(61, 74, 104)``.
    """
    red, green, blue = pixel
    return (
        90 <= blue <= 130
        and blue > red
        and blue > green
        and 15 <= blue - green <= 45
        and 40 <= red <= 80
    )


def _roi_box(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Pass through an already-absolute ROI box, for symmetry with dict ROIs."""
    return rect


def _panel_done_marker(
    pixels: list[list[tuple[int, int, int]]] | None, row_y_norm: float
) -> tuple[list[float] | None, dict | None]:
    """The client's green done-marker on this row, when it drew one.

    See :data:`QUICK_PANEL_DONE_GREEN_MIN` for the measurement.  Returns the centre and box in
    normalised coordinates, or ``(None, None)`` for a row the client drew an enter-arrow on -- which is
    the ordinary case and must stay silent.
    """
    if not pixels or not pixels[0]:
        return None, None
    height = len(pixels)
    width = len(pixels[0])
    y = int(round(row_y_norm * height))
    half = max(1, int(QUICK_PANEL_DONE_HALF_HEIGHT * height))
    left_bound = int(QUICK_PANEL_DONE_BAND_X_NORM[0] * width)
    right_bound = min(int(QUICK_PANEL_DONE_BAND_X_NORM[1] * width), width)
    hits: list[tuple[int, int]] = []
    for scan_y in range(max(0, y - half), min(height, y + half + 1)):
        row = pixels[scan_y]
        for scan_x in range(left_bound, right_bound):
            red, green, blue = row[scan_x]
            if (green >= QUICK_PANEL_DONE_GREEN_MIN
                    and green - red >= QUICK_PANEL_DONE_OVER_RED
                    and green - blue >= QUICK_PANEL_DONE_OVER_BLUE):
                hits.append((scan_x, scan_y))
    if len(hits) < QUICK_PANEL_DONE_MIN_PIXELS:
        return None, None
    xs = [item[0] for item in hits]
    ys = [item[1] for item in hits]
    if len(set(ys)) < QUICK_PANEL_DONE_MIN_ROWS or max(xs) - min(xs) < QUICK_PANEL_DONE_MIN_WIDTH_PX:
        return None, None
    centre = [round(((min(xs) + max(xs)) / 2) / width, 4), round(((min(ys) + max(ys)) / 2) / height, 4)]
    box = {
        "x_norm": round(min(xs) / width, 4),
        "y_norm": round(min(ys) / height, 4),
        "w_norm": round((max(xs) - min(xs)) / width, 4),
        "h_norm": round((max(ys) - min(ys)) / height, 4),
    }
    return centre, box


def _panel_button_chevron(
    pixels: list[list[tuple[int, int, int]]] | None, y: int, half: int, width: int
) -> tuple[int, int] | None:
    """The white chevron inside a row's own button: the button's locator, taken from the button itself.

    Returns the widest near-white run in the button's column over the row's scan band, or ``None`` --
    no pixels, no run wide enough to be a glyph -- which the caller reads as "this row carries no
    enter-arrow".  That is not a failure: the client draws its green done tick on a finished row, and
    those are exactly the three misses out of forty row-readings measured on live frames.

    Why the chevron and not the blue: the blue rule cannot say where the button *is*, only where blue is,
    and 155 px of blue city used to sit inside the search band past the panel's edge.
    """
    if not pixels or not pixels[0] or half < 1:
        return None
    height = len(pixels)
    lo = max(0, int(QUICK_PANEL_BUTTON_COLUMN_X_NORM[0] * width))
    hi = min(width, int(QUICK_PANEL_BUTTON_COLUMN_X_NORM[1] * width))
    if hi - lo < QUICK_PANEL_CHEVRON_MIN_RUN_PX:
        return None

    def is_chevron(pixel: tuple[int, int, int]) -> bool:
        return min(pixel) >= QUICK_PANEL_CHEVRON_MIN

    best: tuple[int, int] | None = None
    for scan_y in range(max(0, y - half), min(height, y + half + 1)):
        xs = [x for x in range(lo, hi) if is_chevron(pixels[scan_y][x])]
        if not xs:
            continue
        runs: list[tuple[int, int]] = []
        start = previous = xs[0]
        for x in xs[1:]:
            if x - previous <= 4:
                previous = x
                continue
            runs.append((start, previous))
            start = previous = x
        runs.append((start, previous))
        for run in runs:
            if run[1] - run[0] + 1 < QUICK_PANEL_CHEVRON_MIN_RUN_PX:
                continue
            if best is None or run[1] - run[0] > best[1] - best[0]:
                best = run
    return best


def _panel_arrow_and_badge(
    pixels: list[list[tuple[int, int, int]]] | None, row_y_norm: float
) -> tuple[list[float] | None, str, dict | None]:
    """The row's own blue arrow button, and whether it carries the client's red dot.

    ``pixels`` is the frame as rows of RGB triples (``None`` when the frame could not be read).
    Returns the button's centre in normalised coordinates (or ``None``), the badge state
    (``PRESENT`` / ``ABSENT`` / ``UNKNOWN``) and the button's normalised box.

    The button is located by the white chevron inside it, and its blue is then read only in that
    neighbourhood.  Two older notes here went with the box the old band had stretched into the city and
    are corrected above rather than left standing: "the button's real centre is 0.644" (the button is
    x 384-425 on the measured frame, centre 0.5618) and the claim that the search had to span several
    rows because a one-line scan missed 射手 and 矛兵.  Scanning several rows is kept -- the button does
    span both of the row's lines -- but it is no longer what keeps the scan off the wrong pixels.

    A row with no chevron gets no point: the client draws its green done tick there instead, and
    "not enterable" is the true answer for such a row.

    The badge is only ever judged inside a button that was found.  No button means no place to look,
    which is UNKNOWN -- the operator's §四: UNKNOWN must never be read as ABSENT.
    """
    if not pixels or not pixels[0]:
        return None, "UNKNOWN", None
    height = len(pixels)
    width = len(pixels[0])
    y = int(round(row_y_norm * height))
    if not 0 <= y < height:
        return None, "UNKNOWN", None
    half = max(1, int(QUICK_PANEL_BADGE_HALF_HEIGHT * height))
    chevron = _panel_button_chevron(pixels, y, half, width)
    if chevron is None:
        # No chevron, no enter-arrow: see _panel_button_chevron.  None here means the caller falls back
        # to the labelled text-column estimate, which the enter paths refuse -- so the row is left alone
        # rather than tapped at a point nobody measured.
        return None, "UNKNOWN", None
    left_bound = max(0, chevron[0] - QUICK_PANEL_BUTTON_PAD_PX)
    right_bound = min(width, chevron[1] + QUICK_PANEL_BUTTON_PAD_PX)

    def is_button(pixel: tuple[int, int, int]) -> bool:
        red, green, blue = pixel
        return blue >= QUICK_PANEL_ARROW_BLUE_MIN and blue - red >= QUICK_PANEL_ARROW_BLUE_OVER_RED

    def blue_span(scan_y: int) -> tuple[int, int] | None:
        """The button's blue extent on one frame row.

        The extent is **min..max** of the blue pixels, not the longest unbroken run, and the measurement
        is why: the client draws the unclaimed dot *on the button's left end*, so on a row that has one
        the leftmost blue starts after it (0.625 where the button begins at 0.539).  A run-based extent
        therefore began past the dot and the badge window built from it missed the very dot it exists to
        find.  Taking min..max gives the button's true extent on every row measured, and the caller's
        badge window then starts at the button's own left edge.
        """
        xs = [x for x in range(left_bound, right_bound) if is_button(pixels[scan_y][x])]
        if not xs or xs[-1] - xs[0] < QUICK_PANEL_ARROW_MIN_RUN_PX:
            return None
        return xs[0], xs[-1]

    best: tuple[int, int, int] | None = None
    for scan_y in range(max(0, y - half), min(height, y + half + 1)):
        span = blue_span(scan_y)
        if span is None:
            continue
        if best is None or span[1] - span[0] > best[1] - best[0]:
            best = (span[0], span[1], scan_y)
    if best is None:
        return None, "UNKNOWN", None
    left, right, button_y = best
    centre_x = (left + right) / 2

    # The dot is drawn at the button's top-right corner, so the window is the button's own RIGHT third.
    # The note here used to say "left end" and the window looked there; on the button's true extent
    # (measured x 384-425) the dot sits at 412-420, and a left-third window only ever found it because
    # the contaminated box had made the button look about 50 px wider than it is.
    badge_left = max(0, right - max(8, (right - left) // 3))
    badge_right = min(width, right + 1)
    reds = 0
    for scan_y in range(max(0, button_y - half), min(height, button_y + half)):
        for scan_x in range(badge_left, badge_right):
            red, green, blue = pixels[scan_y][scan_x]
            if (red >= QUICK_PANEL_BADGE_RED_MIN
                    and red - green >= QUICK_PANEL_BADGE_OVER_GREEN
                    and red - blue >= QUICK_PANEL_BADGE_OVER_BLUE):
                reds += 1
    box = {
        "x_norm": round(left / width, 4),
        "y_norm": round((button_y - half) / height, 4),
        "w_norm": round((right - left) / width, 4),
        "h_norm": round((2 * half) / height, 4),
    }
    centre = [round(centre_x / width, 4), round(row_y_norm, 4)]
    return centre, ("PRESENT" if reds >= QUICK_PANEL_BADGE_MIN_PX else "ABSENT"), box


def _tokens_in_frame_space(
    result: OCRResult, roi: Mapping[str, float], frame_size: tuple[int, int] | None
) -> OCRResult:
    """The same tokens, moved out of the roi crop's space and into the frame's.

    ``OCRService.recognize(path, roi)`` crops the image and returns its boxes in the **crop's**
    coordinates.  A consumer that compares those boxes with frame-space quantities -- which is exactly
    what ``read_quick_panel`` does when it reports ``y_norm`` and locates each row's own button -- then
    reads every row shifted by the crop's top edge.

    Measured 2026-09-22, and it is what made a row arrow tap miss: the panel's four rows came out at
    y 0.2262 / 0.2832 / 0.3402 / 0.4285 through ``HybridVision.observe``, while the same frame read
    0.427 / 0.484 / 0.541 / 0.6283 through ``read_quick_panel`` on the whole image -- a uniform
    0.2008, which is ``QUICK_PANEL_ROI``'s ``y_norm`` 0.20 times the frame height, i.e. the crop's top
    edge and nothing else.  The tap issued from that reading landed one row above the intended arrow
    (``TRAINING_PAGE_NOT_PROVEN``, ``NUMBER_CHANGED``, the client still on HOME).
    """
    if not frame_size or not roi:
        return result
    width, height = int(frame_size[0]), int(frame_size[1])
    if width <= 0 or height <= 0:
        return result
    left = round(float(roi.get("x_norm") or 0.0) * width)
    top = round(float(roi.get("y_norm") or 0.0) * height)
    if left == 0 and top == 0:
        return result
    return OCRResult(
        tuple(
            OCRToken(
                text=token.text,
                confidence=token.confidence,
                box=tuple((float(point[0]) + left, float(point[1]) + top) for point in token.box),
            )
            for token in result.tokens
        ),
        result.backend,
        result.cached,
    )


def read_quick_panel(image_path, ocr, *, result: OCRResult | None = None) -> dict:
    """Read the 快捷面板 as its own surface, or ``{}`` when it is not open.

    Returns ``{"open": True, "building": {...}, "camps": {...}, "research": {...}}``,
    where only the sections whose rows were positively read appear: a section that
    could not be read is *absent* rather than reported idle.  The panel is an
    overlay, so nothing here names a ``Page``.

    ``camps`` is keyed by ``SHIELD_CAMP`` / ``LANCER_CAMP`` / ``MARKSMAN_CAMP`` --
    the same keys ``WorldState.camps`` uses -- so one per-camp model serves both the
    panel and the training page, and a consumer does not need to know which surface
    the reading came from.

    The triangle is not a template yet, so "the panel is open" is decided by the
    section headers being present and *stacked in the order and spacing the client
    draws them*, which a page that merely mentions one of these words cannot fake.

    ``result`` lets a caller that has already recognised the frame pass that reading
    in rather than paying for a second pass.  ``HybridVision.observe`` does exactly
    that on the pages it OCRs anyway; a page the template layer resolves on its own
    is never recognised, so the panel cannot be seen there -- which is the same
    trade the rest of ``observe`` makes, and it is why the panel reading is advisory
    rather than the only path to a training decision.
    """
    if result is None:
        result = ocr.recognize(image_path)
    tokens = [token for token in result.tokens if token.confidence >= 0.80]
    if not tokens:
        return {}
    by_y = sorted(tokens, key=lambda token: token.centre[1])

    def section_of(text: str) -> str | None:
        """Which section header ``text`` is, tolerating the noise OCR adds.

        Measured 2026-09-21: the 科技研究 header was read as ``X科技研究`` at
        confidence 0.90 -- the panel draws a small icon immediately left of each
        header and the recogniser occasionally folds a stroke of it into the word.
        An exact match would drop that header and, with it, the whole research
        section.  A containment test is used instead, and it is safe here because
        the three headers are not substrings of one another and the reader already
        requires all three to be present in the client's own order before it
        believes the panel is open.
        """
        stripped = text.strip()
        for section in QUICK_PANEL_READ_SECTIONS:
            if section in stripped:
                return section
        return None

    headers: list[tuple[int, str]] = []
    for index, token in enumerate(by_y):
        section = section_of(token.text)
        if section is None:
            continue
        # A section's own header is followed by a row that repeats its name (the
        # 科技研究 header at y=765 is followed by the 科技研究 row at y=805), and
        # OCR can also read the header twice.  Only the first of a run counts, so
        # the section list stays one entry per section.
        if headers and headers[-1][1] == section:
            continue
        headers.append((index, section))
    # Two or more *known* headers, each below the last and in the client's own order: that is the
    # panel.  It used to demand all three of ``QUICK_PANEL_READ_SECTIONS``' first three, which made
    # a scrolled panel unreadable -- measured on the operator's frame 2026-09-22 21:50: the visible
    # headers were 科技研究 / 联盟捐献 / 英雄招募 and the reader returned ``{}``, i.e. "no panel",
    # for a frame whose whole left column is the panel.
    #
    # One header is not enough, and the order is not negotiable: the research lab prints 科技研究 on
    # its own, the alliance page prints 联盟捐献, and the bottom navigation bar prints 英雄 -- which
    # is why the membership test below is exact and not a containment test, and why the order check
    # stays (it is what a knowledge page or the 城镇 tab strip cannot reproduce).
    if len(headers) < 2:
        return {}
    order = [QUICK_PANEL_READ_SECTIONS.index(section) for _, section in headers]
    if order != sorted(order) or len(set(order)) != len(order):
        return {}

    panel: dict[str, object] = {"open": True}

    #: The frame's own width, so a token's x can be tested against the panel's column.  Resolved
    #: here rather than only where the geometry below needs it, because the section loop needs it too;
    #: ``read_frame_size`` returns None for a frame it cannot open, and the same guard the geometry
    #: uses keeps a stub path from raising here.
    try:
        frame_size = read_frame_size(image_path)
    except (OSError, ValueError, AttributeError, TypeError):
        frame_size = None
    frame_width = int(frame_size[0]) if frame_size else 0

    def drawn_by_the_panel(token) -> bool:
        """Whether the panel drew ``token``, judged by where it sits.

        The panel's own tokens measure x_norm 0.10-0.34 and ``QUICK_PANEL_COLUMN_MAX_X_NORM`` is the
        left-edge bound the geometry below has always used for exactly this question.  Without the test
        a row's *identity* can be taken from text the panel never drew: measured 2026-09-23, the
        科技研究 section's row was reported as 梦境寻忆 -- a token at x 0.769, out on the city's event
        rail -- because it sat by y between that section's header and its own row, so it became the
        section's first row and the real 科技研究 / 空闲中 row was not reported at all (issue #99).

        A frame whose width could not be read leaves every token acceptable, which is the same trade
        the geometry section makes: a position test that cannot run does not run.
        """
        if frame_width <= 0:
            return True
        return (
            min(float(point[0]) for point in token.box) / frame_width
            <= QUICK_PANEL_COLUMN_MAX_X_NORM
        )

    def state_below(name_y: float) -> str | None:
        """The state word drawn under the row whose name is at ``name_y``.

        Only a word the panel drew counts -- the same reason as ``drawn_by_the_panel`` above: a state
        word read off some other surface would decide whether this row is idle.
        """
        for token in by_y:
            if not drawn_by_the_panel(token):
                continue
            offset = token.centre[1] - name_y
            if not 4.0 <= offset <= QUICK_PANEL_STATE_OFFSET_PX * 1.6:
                continue
            text = token.text.strip()
            if (text in QUICK_PANEL_IDLE_WORDS or text in QUICK_PANEL_COMPLETED_WORDS
                    or text in QUICK_PANEL_BUSY_WORDS):
                return text
            # The 联盟捐献 row and the 英雄招募 row state themselves in their own words
            # (可捐献25/25, 免费招募) rather than with 空闲中: measured on the operator's frame
            # 2026-09-22 21:50.  Recognising them here keeps one place that decides "is this a state",
            # and the section branches above read the meaning.
            if "可捐献" in text or "免费" in text:
                return text
            # 训练中 is also drawn as 训练中 03:12:45, so the prefix is what counts.
            for word in QUICK_PANEL_BUSY_WORDS:
                if text.startswith(word):
                    return word
            # 建筑队列's row states itself with a countdown rather than a status word
            # (使馆升级中 06:14:58).  A countdown means the queue is running -- see
            # ``knowledge/resources/mechanism_cards.json``: "队列进行中 -> 使用加速 ->
            # 剩余时间下降" -- so it is returned as the state and the caller treats it
            # as busy, the same way the research reader does.
            if re.fullmatch(r"(?:(\d+)天)?\d{1,2}:\d{2}:\d{2}", text):
                return text
        return None

    def rows_between(start: int, end: int) -> list[tuple[str, float]]:
        return [
            (by_y[index].text.strip(), by_y[index].centre[1])
            for index in range(start, end)
            if drawn_by_the_panel(by_y[index])
        ]

    section_rows: list[tuple[str, str, float]] = []
    for position, (index, section) in enumerate(headers):
        after = headers[position + 1][0] if position + 1 < len(headers) else len(by_y)
        header_y = by_y[index].centre[1]
        rows = rows_between(index + 1, after)
        for row_name, row_y in rows:
            # A section ends where the next header begins, and the *last* section has no next
            # header -- so without this bound the bottom navigation bar (野外 / 英雄 / 联盟 /
            # 探险 / 商店, measured at y 0.97-0.99) was read as the research section's rows, and one
            # of them became a "research" row.  A row is only this section's while it sits a few
            # line heights under its header.
            if row_y - header_y > QUICK_PANEL_MAX_ROW_OFFSET_PX:
                break
            section_rows.append((section, row_name, row_y))

        if section == "建筑队列":
            # The row is named by its own text (使馆升级中) and states itself with the
            # countdown under it, so both lines are read and the row is judged busy when
            # either says so.  Only the first row is taken: the panel draws 队列2 below
            # it when the player owns a second building queue, and that row belongs to
            # the same section rather than being a separate reading.
            for name, name_y in rows:
                state = state_below(name_y)
                if state is None:
                    continue
                running = name in QUICK_PANEL_BUSY_WORDS or any(
                    word in name for word in QUICK_PANEL_BUSY_WORDS
                )
                if re.fullmatch(r"(?:(\d+)天)?\d{1,2}:\d{2}:\d{2}", state):
                    running = True
                completed = state in QUICK_PANEL_COMPLETED_WORDS
                panel["building"] = {
                    "name": name,
                    "timer": state if running and re.fullmatch(r"(?:(\d+)天)?\d{1,2}:\d{2}:\d{2}", state) else None,
                    "status": "IN_PROGRESS" if running else "COMPLETED" if completed else "IDLE",
                    "queue_available": not running and not completed,
                    "source_word": state,
                }
                break

        elif section == "部队训练":
            camps: dict[str, dict[str, object]] = {}
            for name, name_y in rows:
                camp = TROOP_TO_CAMP.get(TITLE_TO_TROOP.get(name, ""))
                if camp is None:
                    continue
                state = state_below(name_y)
                if state is None:
                    continue
                queue_status, queue_available = _quick_panel_queue_state(state)
                camps[camp] = {
                    "troop_type": TITLE_TO_TROOP[name],
                    "label": name,
                    "status": queue_status,
                    "queue_available": queue_available,
                    "source_word": state,
                }
            if camps:
                panel["camps"] = camps
            camps_from_the_header = set(camps)

        elif section == "联盟捐献":
            # The row states itself with its own count: 可捐献25/25 (green) while a donation is
            # possible, and a countdown or a plain count once it is spent.  The number is read out of
            # the client's own words rather than inferred, and the row is kept on the panel only when
            # a state was actually read -- an unread row is absent, never reported as unavailable.
            for name, name_y in rows:
                state = state_below(name_y)
                if state is None:
                    continue
                numbers = re.findall(r"(\d+)", state)
                panel["alliance_donation"] = {
                    "name": name,
                    "status": "AVAILABLE" if "可捐献" in state else "UNAVAILABLE",
                    "available": int(numbers[0]) if numbers else None,
                    "total": int(numbers[1]) if len(numbers) > 1 else None,
                    "source_word": state,
                }
                break

        elif section == "英雄招募":
            # Measured on the device 2026-09-22 22:02: this section draws two rows -- 高级招募
            # 免费招募 and 史诗招募 1天01:51:08 -- so reading only the first hid the running one.
            # A row whose state is a countdown is in progress; 免费/可 marks one that is waiting.
            recruit_rows: list[dict[str, object]] = []
            for name, name_y in rows:
                state = state_below(name_y)
                if state is None:
                    continue
                running = bool(re.fullmatch(r"(?:(\d+)天)?\d{1,2}:\d{2}:\d{2}", state))
                recruit_rows.append({
                    "name": name,
                    "status": "IN_PROGRESS" if running else ("AVAILABLE" if ("免费" in state or "可" in state) else "UNKNOWN"),
                    "timer": state if running else None,
                    "source_word": state,
                })
            if recruit_rows:
                panel["hero_recruit"] = recruit_rows[0]
                panel["hero_recruit_rows"] = recruit_rows

        elif section == "科技研究":
            for name, name_y in rows:
                state = state_below(name_y)
                if state is None:
                    continue
                queue_status, queue_available = _quick_panel_queue_state(state)
                panel["research"] = {
                    "name": name,
                    "status": queue_status,
                    "queue_available": queue_available,
                    "source_word": state,
                }
                break

    # The camp rows are read **panel-wide**, not only under a 部队训练 header.
    #
    # The panel scrolls, and measured on the operator's frame 2026-09-22 21:50 the three barracks
    # were on screen (盾兵 03:04:16, 矛兵 空闲中, 射手 02:33:49) while the 部队训练 header sat above
    # the visible area -- so a reader that only looked under that header could not see the one thing
    # the panel exists for.  The names are the client's own troop names and are read exactly, with a
    # state word below them, which is what keeps this from matching the training page's tab strip
    # (盾兵营 / 矛兵营 / 射手营) or the bottom navigation bar.
    camps_panel_wide: dict[str, dict[str, object]] = dict(panel.get("camps") or {})
    for token in by_y:
        if not drawn_by_the_panel(token):
            continue  # not the panel's text, so not one of the panel's rows (issue #99)
        name = token.text.strip()
        troop = TITLE_TO_TROOP.get(name)
        camp = TROOP_TO_CAMP.get(troop or "")
        if camp is None:
            continue
        if any(section == "部队训练" and row_name == name for section, row_name, _ in section_rows):
            continue  # already read under its header
        state = state_below(token.centre[1])
        if state is None:
            continue
        queue_status, queue_available = _quick_panel_queue_state(state)
        camps_panel_wide[camp] = {
            "troop_type": troop,
            "label": name,
            "status": queue_status,
            "queue_available": queue_available,
            "source_word": state,
        }
        section_rows.append(("部队训练", name, token.centre[1]))
    if camps_panel_wide:
        panel["camps"] = camps_panel_wide
    # ---- the panel's own geometry: its rows, and what hangs off its right edge ---------------
    #
    # Measured on the one real capture of the expanded panel this project owns
    # (20260921_213506_694242 step_001): headers at x 0.024-0.203, rows at x 0.24-0.39, the
    # 部队训练 rows at y 0.427 (盾兵) / 0.484 (矛兵) / 0.541 (射手) and 科技研究 at y 0.629.
    #
    # So a task row is identified by *its own y*, and the arrow that navigates to that task is the
    # panel's right-hand column on the same row -- never "a blue arrow that looks like the others".
    # A row's state is the word under it, which is why an arrow's presence is never read as idle:
    # the arrows are not read at all here, only located.
    # The geometry below is an addition to this reader, so a frame it cannot measure (a stub path
    # in a test, a capture that vanished) must leave the sections exactly as they were rather than
    # raise: the sections are what the panel's consumers have always read.
    size = frame_size
    if section_rows and size and int(size[0]) > 0 and int(size[1]) > 0:
        width, height = int(size[0]), int(size[1])
        row_ys = [name_y for _, _, name_y in section_rows]
        block_top = min(row_ys) - QUICK_PANEL_STATE_OFFSET_PX
        block_bottom = max(row_ys) + QUICK_PANEL_STATE_OFFSET_PX * 2
        block_tokens = [
            token
            for token in tokens
            if block_top <= token.centre[1] <= block_bottom
            and min(float(point[0]) for point in token.box) / width <= QUICK_PANEL_COLUMN_MAX_X_NORM
        ]
        right_px = max(
            (max(float(point[0]) for point in token.box) for token in block_tokens), default=0.0
        )
        arrow_x = min(0.62, (right_px + QUICK_PANEL_ARROW_MARGIN_PX) / width) if right_px else None
        if arrow_x is not None:
            # The frame's pixels, read once for all the row scans (a per-row decode would decode the
            # same file four times).  A frame that cannot be read leaves every row on the estimate and
            # every badge UNKNOWN, which is the honest reading of "this frame could not be examined".
            frame_pixels: list[list[tuple[int, int, int]]] | None = None
            try:
                with Image.open(image_path) as image:
                    rgb = image.convert("RGB")
                    flat = list(rgb.getdata())
                    frame_width = rgb.width
                    frame_pixels = [flat[i:i + frame_width] for i in range(0, len(flat), frame_width)]
            except (OSError, ValueError, AttributeError, TypeError):
                frame_pixels = None
            out_rows: list[dict] = []
            keyed_sections: set[str] = set()
            for section, name, name_y in section_rows:
                camp = TROOP_TO_CAMP.get(TITLE_TO_TROOP.get(name, ""))
                # A section's own entry row is its *first* row, and that is the one a consumer
                # navigates from: measured on the device, 科技研究 names itself, 联盟捐献 names
                # itself, but 我的奖励's row is 仓库补给 and 英雄招募's first row is 高级招募 -- so
                # "the row repeats the section's name" would have missed two of the four.  The extra
                # rows of a section (史诗招募 under 英雄招募) carry their own state and keep no key.
                key = camp
                if key is None:
                    section_key = SECTION_ROW_KEYS.get(section)
                    if section_key and section not in keyed_sections:
                        key = section_key
                        keyed_sections.add(section)
                if key is None:
                    continue
                state_word = state_below(name_y)
                located, badge, box = _panel_arrow_and_badge(frame_pixels, name_y / height)
                # The tick is looked for on **every** row, not only where the arrow scan failed.
                # Measured: some 已完成 rows carry the client's blue button with the green tick inside
                # it (16:41 射手 row, 22:02 我的奖励 row -- both frames draw a ~1270 px green block and
                # their blue scan also succeeds), while others carry the tick alone (17:21 盾兵 row,
                # whose blue scan finds nothing).  The tick is what says the row is waiting to be
                # collected, so it decides the row's identity and the arrow is the alternative.
                done_norm, done_box = _panel_done_marker(frame_pixels, name_y / height)
                queue_status, _queue_available = _quick_panel_queue_state(state_word)
                record = {
                    # The kind is the row's own identity, not a two-way guess: a consumer matches it
                    # against the row kinds its goal works from, so labelling 联盟捐献 as RESEARCH
                    # (which the earlier two-way form did) would have let a research goal tap it.
                    "kind": "CAMP" if camp else key,
                    "key": key,
                    "label": name,
                    "y_norm": round(name_y / height, 4),
                    "status": queue_status,
                    "source_word": state_word,
                    # The row's own button when this frame draws it; the old text-column estimate only
                    # as a labelled fallback, because a tap from it lands on the row's state word
                    # (measured: 0.4097 against a button at 0.539-0.749).
                    "arrow_norm": located if located else [round(arrow_x, 4), round(name_y / height, 4)],
                    "arrow_basis": (
                        QUICK_PANEL_ARROW_BASIS_SCAN if located else QUICK_PANEL_ARROW_BASIS_ESTIMATE
                    ),
                    "badge": badge,
                    # What the client drew in this row's own control slot.  A row whose task is done
                    # gets a green tick instead of an enter-arrow, and which one it is decides what
                    # the row is for: tapping a tick is collecting, and tapping a tick as if it were an
                    # enter-arrow is the wrong action.  None of ``arrow_norm`` above changes -- it stays
                    # the arrow's own point, with the labelled estimate as its fallback.
                    "control": (
                        QUICK_PANEL_CONTROL_DONE if done_norm is not None
                        else QUICK_PANEL_CONTROL_ARROW if located is not None
                        else QUICK_PANEL_CONTROL_NONE
                    ),
                }
                if box is not None:
                    record["arrow_box_norm"] = box
                if done_norm is not None:
                    record["done_norm"] = done_norm
                if done_box is not None:
                    record["done_box_norm"] = done_box
                out_rows.append(record)
                # Bind the badge to this camp identity as well as retaining the
                # row record. Goal discovery can then carry the same-frame badge
                # alongside queue state without treating it as action authority.
                if camp and camp in camps_panel_wide:
                    camps_panel_wide[camp]["badge"] = badge
            if out_rows:
                panel["rows"] = out_rows
            # Where the handle actually is, measured, with the panel-relative estimate kept only as
            # the fallback.  Measured 2026-09-22: the estimate put the expanded handle at
            # (0.3708, 0.2779) -- the middle of the panel -- while the tab with its left-pointing
            # triangle is at (0.6431, 0.4301), i.e. a tap issued from the estimate would have landed
            # on the panel's own content instead of the control.  The estimate was written when the
            # appearance was unknown; now it is measured, and the weaker evidence must not outrank it.
            measured = find_quick_panel_handle(image_path, panel_open=True)
            if measured is not None:
                panel["handle"] = measured
            else:
                panel["handle"] = {
                    "state": "EXPANDED",
                    "point_norm": [
                        round(arrow_x, 4),
                        round((min(row_ys) + max(row_ys) + QUICK_PANEL_STATE_OFFSET_PX) / 2.0 / height, 4),
                    ],
                    "basis": "PANEL_RELATIVE_ESTIMATE",
                }
    return panel


#: How a quick-panel row's tap point was obtained, and the two answers are not equivalent.
#:
#: ``SCAN`` is the row's own blue arrow button located **in this frame's pixels**; ``ESTIMATE`` is the
#: reading's fallback when that scan found nothing.  They are named once, here, because a consumer has
#: to be able to tell them apart to decide whether to tap at all -- measured 2026-09-23 17:21:50, the
#: 盾兵 row drew the client's **green check** (its batch was 已完成) instead of a blue arrow, the scan
#: correctly found none, and the estimate (x 0.4042) was tapped anyway: the tap landed on the row's
#: text at x 291 and opened nothing.
#: The client's done-marker: the green tick it draws in the control slot of a row whose task has
#: finished and is waiting to be collected.  Measured on three frames (2026-09-23, 720x1280): the block
#: is x 0.533-0.590, ~41x31 px, ~1270 green pixels, at the row's own y -- and a frame whose every row is
#: idle draws none at all.  The threshold is the measured signature, not a guess.
QUICK_PANEL_DONE_GREEN_MIN: int = 150
QUICK_PANEL_DONE_OVER_RED: int = 50
QUICK_PANEL_DONE_OVER_BLUE: int = 50
#: The slot the tick shares with the enter-arrow.  Right of the row's text column, inside the panel.
QUICK_PANEL_DONE_BAND_X_NORM: tuple[float, float] = (0.50, 0.66)
#: How far either side of the row's own y the tick may sit, and how big it has to be to count.  The
#: measured centre sits ~0.011 below the row's name line and the block is ~30 px tall.
QUICK_PANEL_DONE_HALF_HEIGHT: float = 0.022
QUICK_PANEL_DONE_MIN_PIXELS: int = 200
QUICK_PANEL_DONE_MIN_ROWS: int = 8
QUICK_PANEL_DONE_MIN_WIDTH_PX: int = 20

#: What the client drew in a row's own control slot.
QUICK_PANEL_CONTROL_ARROW: str = "ARROW"
QUICK_PANEL_CONTROL_DONE: str = "DONE"
QUICK_PANEL_CONTROL_NONE: str = "NONE"

QUICK_PANEL_ARROW_BASIS_SCAN: str = "ROW_BUTTON_SCAN"
QUICK_PANEL_ARROW_BASIS_ESTIMATE: str = "PANEL_RELATIVE_ESTIMATE"


#: The training button's own printed label.
TRAINING_BUTTON_LABEL: str = "训练"


def _token_centre_norm(text: str, tokens, frame_size) -> list[float] | None:
    """The centre of the token that read ``text``, in normalised frame coordinates.

    The counterpart of :func:`_above_the_action_bar`: that one asks *where* a time token is drawn, this
    one asks where the token carrying a given word is drawn.  Both exist because the client prints a
    control and its text together, so the text's own box is the control's own position -- the only
    answer available when a template cannot be cut from a control the client's hand is covering.
    """
    if not frame_size or frame_size[0] <= 0 or frame_size[1] <= 0:
        return None
    for token in tokens:
        if token.text.strip() != text:
            continue
        xs = [point[0] for point in token.box]
        ys = [point[1] for point in token.box]
        if not xs or not ys:
            continue
        return [round(sum(xs) / len(xs) / float(frame_size[0]), 4),
                round(sum(ys) / len(ys) / float(frame_size[1]), 4)]
    return None


def _above_the_action_bar(timer: "re.Match", tokens, frame_size) -> bool:
    """True when a time token sits above the training page's action bar.

    See :data:`TRAINING_QUEUE_TIMER_MAX_Y`.  A ``False`` here does not lose the token -- the caller
    simply does not treat it as a queue countdown, which is the point: the training button prints the
    projected duration of the batch it would start, in the same ``HH:MM:SS`` shape as a countdown.
    """
    if not frame_size or frame_size[1] <= 0:
        return True
    for token in tokens:
        if token.text.strip() != timer.group(0):
            continue
        ys = [point[1] for point in token.box]
        if not ys:
            continue
        return (sum(ys) / len(ys)) / float(frame_size[1]) < TRAINING_QUEUE_TIMER_MAX_Y
    return True


#: Where a training page's *action bar* starts, and above which a time token can still be a running
#: queue's own countdown.
#:
#: Measured 2026-09-22 on six archived training pages (three camps, two sessions each).  Every one of
#: them draws, at the same places:
#:
#:     原始时间：04:42:00      y 0.815   x 0.66-0.76   the base duration label
#:     立即完成                y 0.863   x 0.267       the diamond button
#:     训练                    y 0.862   x 0.736       the training button
#:     <a bare HH:MM:SS>       y 0.888   x 0.761       the training button's OWN caption
#:
#: That last line is the defect this constant exists for: the training button is drawn as two lines
#: (训练 over the projected duration of the batch that would be started), and a bare ``\d{1,2}:\d{2}:\d{2}``
#: regex cannot tell it from a queue countdown.  So it was read as one, the camp was declared busy, and
#: the route left a page whose 训练 button was lit.  A queue's own countdown is drawn in the queue row
#: *above* this line; everything at or below it belongs to the action bar.
TRAINING_QUEUE_TIMER_MAX_Y: float = 0.80

#: The 挂机收益 (idle income) dialog's own static words, measured on the live capture.
#:
#: The frame reads: 挂机收益 1.00 @ (0.501, 0.233), 挂机时间 1.00 @ (0.501, 0.284), 领取 0.99 @
#: (0.501, 0.723), 挂机最多可获得9小时收益。 1.00 @ (0.488, 0.784).  The amounts beside the icons
#: (411 / 1,438) are dynamic and are deliberately NOT part of the identity -- the same lesson as the
#: 10:03:12 countdown that used to be part of the training button's identity.
IDLE_INCOME_DIALOG_TITLE: str = "挂机收益"
IDLE_INCOME_DIALOG_SUBTITLE: str = "挂机时间"

#: The 快捷面板 handle's own drawn structure, measured on real frames 2026-09-22.
#:
#: The handle is a small slate tab with a white outline and a white triangle, and it is the one
#: control in this file that has **no text at all** -- which is why it could not be located while the
#: panel was closed: the panel reader anchored everything to the panel's own section headers, and a
#: collapsed panel draws none.  What follows is the measurement that replaces that anchor, taken from
#: two independent captures of the same client (a MuMu 720x1280 frame and the operator's own
#: screenshot, whose game viewport is 690x1231 -- a 4% scale difference, and the two agree to within
#: 0.015 in both axes):
#:
#:   collapsed (MuMu, HOME frame 20260922_185821_069146 step_008)
#:       triangle   x   6- 20  y 538-566   apex RIGHT   (norm x 0.008-0.028, y 0.420-0.442)
#:       outline    x  28- 33  (a 6 px white vertical bar to the right of the triangle)
#:       red badge  x  21- 37  y 502-514   (the corner badge; not used for locating)
#:   collapsed (operator screenshot, viewed at 690x1231)
#:       triangle   x  55- 73  y 524-545   apex RIGHT   (norm x 0.009-0.035, y 0.426-0.443)
#:   expanded  (MuMu, the one frame whose panel read as open)
#:       triangle   x 450-464  y 538-566   apex LEFT    (norm x 0.625-0.644, y 0.420-0.442)
#:       the same 6 px white bar sits at x 471-476, i.e. always to the *right* of the triangle
#:
#: So the triangle's pointing side is the state (it points the way the panel will move), and the tab
#: itself is anchored to a screen edge rather than to a coordinate: the frame's own left edge when
#: collapsed, the panel's right edge when expanded.  Nothing here is a stored position.
QUICK_PANEL_HANDLE_BAND_NORM: tuple[float, float] = (0.30, 0.56)

#: The collapsed handle's search strip, as an x fraction.  Measured: the tab's visible part ends
#: at x 0.046 on the device and at x 0.041 of the *game viewport* on the operator's frame (that
#: screenshot carries a 49 px white margin, so the same tab lands at x 0.074 of the file).  0.10
#: covers both, and it is only ever searched while the panel is closed -- the expanded handle lives
#: at the panel's right edge, an entirely different window.
QUICK_PANEL_HANDLE_STRIP_X_NORM: float = 0.10

#: Where the expanded handle is looked for: to the right of the panel's body.  Measured x 0.625-0.68.
QUICK_PANEL_HANDLE_OPEN_X_NORM: tuple[float, float] = (0.45, 0.80)

QUICK_PANEL_HANDLE_BRIGHT_MIN: int = 190
QUICK_PANEL_HANDLE_TRIANGLE_MIN_PX: int = 5

#: The width a row must reach before it is treated as part of the triangle rather than the tab's
#: outline.  Measured: the outline bar is 6 px wide and 88 px tall (it outlives the triangle), while
#: the triangle itself reaches 15-20 px on the device and 19 px on the operator's frame.  Selecting
#: rows by this width is what separates the two shapes -- without it the bar's own rows join the
#: profile, the profile then has *two* flat edges, and every real handle is rejected (measured: that
#: is exactly what the first version of this function did on all three known frames).
#: The widest a row of the triangle may be.  Measured 19-20 px in both states, so 40 is generous --
#: and it has to be a bound at all because the operator's own screenshot carries a 49 px white margin
#: down its left side (a capture artifact: the bottom navigation bar is cut by the same band), and an
#: unbounded run would let that margin be the widest thing in every row it touches, hiding the tab
#: behind it.  With the bound, that frame reads like any device frame.
QUICK_PANEL_HANDLE_TRIANGLE_MAX_PX: int = 40
QUICK_PANEL_HANDLE_SELECT_MIN_PX: int = 10
QUICK_PANEL_HANDLE_TRIANGLE_MIN_ROWS: int = 10
QUICK_PANEL_HANDLE_BAR_MIN_PX: int = 3
QUICK_PANEL_HANDLE_BAR_MAX_PX: int = 12
QUICK_PANEL_HANDLE_BAR_MAX_GAP_PX: int = 30
QUICK_PANEL_HANDLE_EDGE_FLAT_PX: int = 3
QUICK_PANEL_HANDLE_BAR_COVERAGE: float = 0.75

#: How much of the tab's own fill must surround the triangle, and what that fill is.
#:
#: Measured 2026-09-22, because without this the reader produced a real false positive: the alliance
#: page's numbered-list card (a big white rounded panel) contains runs between its own glyphs that
#: pass every shape test above it, and it was read as a COLLAPSED handle at (0.0569, 0.3551).  What
#: separates the two is what the triangle is drawn *on*:
#:
#:   genuine handle, device collapsed   rgb(54, 97,150) left of the base, rgb(59,101,155) at the apex
#:   genuine handle, operator's frame   rgb(80,117,172) inside the tab
#:   the alliance card's false triangle rgb(227,241,254) -- white
#:
#: So the fill is a muted blue that is clearly not white, and the test is on the patches just above
#: and just below the triangle, which works for both pointing directions.
QUICK_PANEL_HANDLE_FILL_MIN_FRACTION: float = 0.60
QUICK_PANEL_HANDLE_FILL_PATCH_PX: int = 9


def _bright_runs(row) -> list[tuple[int, int]]:
    """Consecutive runs of near-white pixels in one row, as inclusive ``(start, end)`` pairs."""
    runs: list[tuple[int, int]] = []
    opener = None
    for index, value in enumerate(row):
        if value and opener is None:
            opener = index
        elif not value and opener is not None:
            runs.append((opener, index - 1))
            opener = None
    if opener is not None:
        runs.append((opener, len(row) - 1))
    return runs


def _widest(runs: list[tuple[int, int]]) -> tuple[int, int]:
    """The widest run in a row; ties go to the leftmost, which is the tab's own order."""
    best = runs[0]
    for run in runs[1:]:
        if run[1] - run[0] > best[1] - best[0]:
            best = run
    return best


def _handle_triangle(per_row: dict[int, list[tuple[int, int]]], seed_rows: list[int]) -> dict | None:
    """The triangle a band of seed rows belongs to, or ``None`` when they describe something else.

    ``seed_rows`` are the rows that carry a run at least ``QUICK_PANEL_HANDLE_SELECT_MIN_PX`` wide --
    only the triangle can produce those, because the tab's outline bar is 5-6 px (measured).  The
    seed is then **grown** along the base edge, because the triangle's own tips are narrower than the
    seed threshold: taking the seed rows alone truncates the shape and its width variation measures
    5 px instead of 11, which is the mistake the first version made and it rejected every real
    handle.  Growing stops when the run from the base edge is gone, which is the triangle's tip.

    A triangle has exactly one flat vertical edge -- its base -- and one that travels out to the apex
    and back.  That, plus unimodality and a minimum apex travel, is the whole test; it is what keeps
    this from being the generic "something is drawn here" detector this project measured and threw
    away.  It recognises **one named control's own shape**, in the strip the operator pointed at.
    """
    if len(seed_rows) < QUICK_PANEL_HANDLE_TRIANGLE_MIN_ROWS:
        return None
    seed_runs = [_widest(per_row[y]) for y in seed_rows]
    starts = [run[0] for run in seed_runs]
    ends = [run[1] for run in seed_runs]
    start_flat = (max(starts) - min(starts)) <= QUICK_PANEL_HANDLE_EDGE_FLAT_PX
    end_flat = (max(ends) - min(ends)) <= QUICK_PANEL_HANDLE_EDGE_FLAT_PX
    if start_flat == end_flat:
        return None
    base_x = sorted(starts)[len(starts) // 2] if start_flat else sorted(ends)[len(ends) // 2]
    on_base = 0 if start_flat else 1

    def matches(y: int) -> tuple[int, int] | None:
        for run in per_row.get(y, ()):
            if abs(run[on_base] - base_x) <= QUICK_PANEL_HANDLE_EDGE_FLAT_PX:
                return run
        return None

    top, bottom = seed_rows[0], seed_rows[-1]
    while top - 1 in per_row and matches(top - 1) is not None:
        top -= 1
    while bottom + 1 in per_row and matches(bottom + 1) is not None:
        bottom += 1
    profile: list[tuple[int, int, int]] = []
    for y in range(top, bottom + 1):
        run = matches(y)
        if run is not None:
            profile.append((y, run[0], run[1]))
    if len(profile) < QUICK_PANEL_HANDLE_TRIANGLE_MIN_ROWS:
        return None
    widths = [row[2] - row[1] + 1 for row in profile]
    travel = max(widths) - min(widths)
    if travel < QUICK_PANEL_HANDLE_TRIANGLE_MIN_PX + 1:
        return None
    peak = widths.index(max(widths))
    if peak == 0 or peak == len(widths) - 1:
        return None
    left = widths[:peak + 1]
    right = widths[peak:]
    if any(b < a for a, b in zip(left, left[1:])) or any(b > a for a, b in zip(right, right[1:])):
        return None
    if max(widths) < QUICK_PANEL_HANDLE_SELECT_MIN_PX:
        return None
    return {
        "direction": "RIGHT" if start_flat else "LEFT",
        "rows": len(profile),
        "width_px": max(widths),
        "x0": min(row[1] for row in profile),
        "x1": max(row[2] for row in profile),
        "y0": profile[0][0],
        "y1": profile[-1][0],
    }


def _handle_drawn_on_the_tab(array, triangle: dict) -> bool:
    """True when the triangle sits on the tab's own muted-blue fill rather than on white.

    See ``QUICK_PANEL_HANDLE_FILL_MIN_FRACTION``: this is the test that separates the real handle
    from the alliance page's white card, which otherwise passes the shape tests.
    """
    height, width = array.shape[0], array.shape[1]
    mid = (triangle["x0"] + triangle["x1"]) // 2
    left = max(0, mid - 2)
    right = min(width, mid + 3)
    patches = []
    span = QUICK_PANEL_HANDLE_FILL_PATCH_PX
    for top, bottom in (
        (triangle["y0"] - span, triangle["y0"] - 3),
        (triangle["y1"] + 3, triangle["y1"] + span),
    ):
        top, bottom = max(0, top), min(height, bottom)
        if bottom > top and right > left:
            patches.append(array[top:bottom, left:right].reshape(-1, 3))
    if not patches:
        return False
    import numpy as np  # noqa: PLC0415 - see the note in find_quick_panel_handle

    pixels = np.concatenate(patches)
    if not len(pixels):
        return False
    red, green, blue = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    fill = (red < 140) & (green > 70) & (green < 170) & (blue > 120) & (blue <= 215)
    return float(fill.mean()) >= QUICK_PANEL_HANDLE_FILL_MIN_FRACTION


def _handle_bar(bright, triangle: dict, y0: int, y1: int) -> tuple[int, int] | None:
    """The tab's white outline bar, which must sit just right of the triangle.

    Measured in both states: 5-6 px wide, 7-8 px from the triangle.  Requiring it is what stops a
    lone bright wedge elsewhere in the strip from being read as the handle -- and it is a property of
    this control (the tab's own outline), not a generic filter.
    """
    start = triangle["x1"] + 2
    stop = min(bright.shape[1], triangle["x1"] + QUICK_PANEL_HANDLE_BAR_MAX_GAP_PX + 1)
    for x in range(start, stop):
        column = bright[triangle["y0"]:triangle["y1"] + 1, x]
        if column.mean() < QUICK_PANEL_HANDLE_BAR_COVERAGE:
            continue
        end = x
        while (
            end + 1 < stop
            and bright[triangle["y0"]:triangle["y1"] + 1, end + 1].mean() >= QUICK_PANEL_HANDLE_BAR_COVERAGE
        ):
            end += 1
        if QUICK_PANEL_HANDLE_BAR_MIN_PX <= end - x + 1 <= QUICK_PANEL_HANDLE_BAR_MAX_PX:
            return x, end
    return None


def find_quick_panel_handle(
    image_path: str | Path,
    *,
    panel_open: bool | None = None,
) -> dict | None:
    """Where the 快捷面板's handle is drawn on **this** frame, or ``None``.

    Operator 2026-09-22: 我用红色圈起来的地方就是快捷面板把手，点进去就可以看到很多功能快捷入口和状态
    等信息.  That message is the missing half of what the panel reader needed.  Until it arrived the
    handle was only locatable while the panel was already open -- every anchor the reader had
    (section headers, rows) is drawn *by the panel* -- so the one state where the handle is actually
    needed was the state it could not be found in.

    This reads the handle the way it is drawn, not the way it was last seen: a near-white triangle
    with one flat edge whose other edge travels out to the apex and back, and the tab's near-white
    outline bar just to its right.  The pointing side names the state, because the triangle points the
    way the panel will move: right when the panel is closed (it will slide out to the right), left
    when it is open.

    Returns ``None`` when this frame draws no such thing, which is a real answer and a common one:
    measured, the handle is absent from a full-screen event page (``燃霜矿区``) and present on the city
    and world-map views.  A frame that does not draw it must not be told a position it does not have
    -- that is the difference between locating a control and remembering where one used to be.
    """
    import numpy as np  # noqa: PLC0415 - kept local so this module's import surface is unchanged

    try:
        with Image.open(image_path) as source:
            frame = source.convert('RGB')
            width, height = frame.size
        array = np.asarray(frame).astype(np.int16)
    except (OSError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    if panel_open is True:
        windows = [QUICK_PANEL_HANDLE_OPEN_X_NORM]
    elif panel_open is False:
        windows = [(0.0, QUICK_PANEL_HANDLE_STRIP_X_NORM)]
    else:
        windows = [(0.0, QUICK_PANEL_HANDLE_STRIP_X_NORM), QUICK_PANEL_HANDLE_OPEN_X_NORM]

    y0 = int(QUICK_PANEL_HANDLE_BAND_NORM[0] * height)
    y1 = int(QUICK_PANEL_HANDLE_BAND_NORM[1] * height)
    bright = array.min(axis=2) > QUICK_PANEL_HANDLE_BRIGHT_MIN

    for x0_norm, x1_norm in windows:
        x0, x1 = int(x0_norm * width), int(x1_norm * width)
        if x1 <= x0:
            continue
        per_row: dict[int, list[tuple[int, int]]] = {}
        for y in range(y0, y1):
            found = [
                (x0 + start, x0 + end)
                for start, end in _bright_runs(bright[y, x0:x1])
                if QUICK_PANEL_HANDLE_TRIANGLE_MIN_PX <= end - start + 1 <= QUICK_PANEL_HANDLE_TRIANGLE_MAX_PX
            ]
            if found:
                per_row[y] = found
        if not per_row:
            continue
        seeds = sorted(
            y for y, runs in per_row.items()
            if any(end - start + 1 >= QUICK_PANEL_HANDLE_SELECT_MIN_PX for start, end in runs)
        )
        bands: list[list[int]] = []
        current: list[int] = []
        for y in seeds:
            if current and y - current[-1] > 2:
                bands.append(current)
                current = []
            current.append(y)
        if current:
            bands.append(current)

        for band in bands:
            triangle = _handle_triangle(per_row, band)
            if triangle is None:
                continue
            if _handle_bar(bright, triangle, y0, y1) is None:
                continue
            if not _handle_drawn_on_the_tab(array, triangle):
                continue
            centre_x = (triangle["x0"] + triangle["x1"]) / 2.0
            centre_y = (triangle["y0"] + triangle["y1"]) / 2.0
            return {
                "state": "COLLAPSED" if triangle["direction"] == "RIGHT" else "EXPANDED",
                "triangle_direction": triangle["direction"],
                "point_norm": [round(centre_x / width, 4), round(centre_y / height, 4)],
                "box_norm": {
                    "x_norm": round(triangle["x0"] / width, 4),
                    "y_norm": round(triangle["y0"] / height, 4),
                    "w_norm": round((triangle["x1"] - triangle["x0"] + 1) / width, 4),
                    "h_norm": round((triangle["y1"] - triangle["y0"] + 1) / height, 4),
                },
                "basis": "HANDLE_TRIANGLE_SCAN",
                "measured_on": str(image_path),
                "evidence": {
                    "triangle_rows": triangle["rows"],
                    "triangle_width_px": triangle["width_px"],
                    "frame": [width, height],
                },
            }
    return None

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


#: The selected-building action bar, as a y-range like the tab strip above.
#:
#: Measured 2026-09-22 on the ten live frames that failed ``NAVIGATE_INFANTRY_CAMP``
#: between 16:24 and 23:47 GMT+8 (720x1280), every one of them reading:
#:
#:   详情   (236, 914-915)   conf 0.994 - 0.998
#:   升级   (360, 943-944)   conf 1.000
#:   训练   (483-487, 912-916)   conf 0.986 - 0.997
#:
#: Spread of 4 px over seven hours and ten frames, because the bar is a screen-space
#: overlay rather than part of the city.  The band is wider than those numbers need: it
#: is a filter for "is this label drawn in the bar", not a pin.
#: Where the bar draws its words -- and it draws them at TWO heights, which is why this band is not
#: the tight one it used to be.  Measured 2026-09-22 on the two live renderings of the same bar:
#:
#:   camp IDLE  详情 (0.328, 0.714)  conf 0.998   升级 (0.501, 0.737)  conf 1.000   训练 (0.672, 0.714) conf 0.994
#:   camp BUSY  详情 (0.269, 0.683)  conf 0.998   训练 (0.732, 0.685)  conf 0.996
#:              立即完成 (0.419, 0.734) conf 0.997   加速 (0.581, 0.735) conf 0.999
#:
#: A camp with a batch in training has no 升级 and gets a second sub-row (立即完成 / 加速), so the
#: client pushes 详情 and 训练 outward AND about 0.030 UP -- to y 0.683-0.685, which the previous band
#: (0.69, 0.76), measured only on the idle bar, rejected.  The consequence was not cosmetic:
#: ``training`` came back empty on three recorded steps (2026-09-22 16:42:30, 18:54:27 and the
#: ring tap at 18:43:51) whose own frames show the bar drawn, and the route judged the client to have
#: failed on a screen it had already reached correctly.
#:
#: The band is the union of both measured rows with room on each side, and the words it may accept are
#: still the whitelist below -- so widening it cannot make a control readable that was not one.
SELECTED_BUILDING_ACTION_BAND = (0.66, 0.78)

#: Where the client names the building it has selected.  盾兵营 measured at
#: (376-378, 545-548), conf 0.958 - 0.995, on the same ten frames.  The bar's layout does not move
#: this: 盾兵营 read at conf 0.994-0.995 at (0.510, 0.433) on the busy frames above, where the bar
#: itself sits 0.030 higher.
SELECTED_BUILDING_NAME_BAND = (0.39, 0.46)

#: The three controls the bar draws, in the client's own words.
#:
#: 立即完成 and 加速 are deliberately absent even though the busy bar draws them right beside 详情
#: and 训练 in the same band.  They are spend controls -- 立即完成 read "166" diamonds under it on the
#: measured frame -- and this whitelist is what turns a word into a point the executor may tap, so a
#: control that spends must not become readable by accident.  A reader that silently learned them
#: would hand the route a tap on a paid control the moment some goal asked the bar for anything.
BUILDING_ACTION_LABELS: tuple[str, ...] = ("详情", "升级", "训练")


def read_selected_building_actions(
    image_path,
    ocr,
    *,
    min_confidence: float = 0.85,
) -> dict:
    """What the client drew for the building it has selected, read from its own words.

    Why this exists.  The training route ends on this screen and the route could not see
    it: ``SemanticWorldVision._building_is_selected`` gates on three templates
    (``BTN_UPGRADE`` / ``BTN_TRAINING_MENU_LABEL`` / ``BTN_OPEN_TRAINING_FROM_CAMP``) and
    **all three miss this rendering**, so ``training`` came back empty, the verifier
    answered ``INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN``, the goal was deferred, and the
    barracks were never reached -- ten consecutive attempts, 16:24 to 23:47.

    The old render is a gold ring around the barracks and nothing else, which is what
    ``camp_ring.py`` was built from.  This one is the client's ordinary selected-building
    treatment: the scene dimmed, the building named above it, and 详情 / 升级 / 训练 drawn
    along the bottom.  Verified as a *different* render rather than a second reading of
    the same one: the two 训练 labels do not appear at all on the gold-ring frames.

    Returns what was actually read, never a default::

        {"actions": {"训练": (x_norm, y_norm), ...},   # only labels positively read
         "name": "盾兵营" or "",                        # the selected building's label
         "camp": "SHIELD_CAMP" or "",                   # that label as a camp id
         "name_norm": (x_norm, y_norm) or None}

    ``actions`` is empty when the bar is not drawn, and ``camp`` is empty for a selected
    building that is not a barracks -- the bar is drawn for any building, so presence
    alone must never be read as "the infantry camp is selected".
    """
    with Image.open(image_path) as source:
        frame_width, frame_height = source.size
    result = ocr.recognize(image_path)
    return read_building_action_tokens(
        result.tokens, (frame_width, frame_height), min_confidence=min_confidence
    )


def read_building_action_tokens(
    tokens,
    frame_size: tuple[int, int] | None,
    *,
    min_confidence: float = 0.85,
) -> dict:
    """The pure half of :func:`read_selected_building_actions`, over tokens and a size.

    Split out so the reading can be tested against boxes measured on real frames without
    an OCR backend in the loop -- ``RapidOCRBackend`` is optional at import time, and a
    reading that cannot be tested is a reading nobody can check.
    """
    empty = {"actions": {}, "name": "", "camp": "", "name_norm": None}
    if not frame_size:
        return empty
    width, height = int(frame_size[0]), int(frame_size[1])
    if width <= 0 or height <= 0:
        return empty

    action_lo, action_hi = SELECTED_BUILDING_ACTION_BAND
    name_lo, name_hi = SELECTED_BUILDING_NAME_BAND
    actions: dict[str, tuple[float, float]] = {}
    name = ""
    name_norm: tuple[float, float] | None = None

    for token in tokens:
        if token.confidence < min_confidence or not token.box:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        centre_x = (min(xs) + max(xs)) / 2.0 / width
        centre_y = (min(ys) + max(ys)) / 2.0 / height
        text = token.text.strip()
        if action_lo <= centre_y <= action_hi:
            if text in BUILDING_ACTION_LABELS and text not in actions:
                actions[text] = (round(centre_x, 4), round(centre_y, 4))
            continue
        if name_lo <= centre_y <= name_hi and text in LABEL_TO_CAMP and not name:
            name = text
            name_norm = (round(centre_x, 4), round(centre_y, 4))
    return {
        "actions": actions,
        "name": name,
        "camp": LABEL_TO_CAMP.get(name, ""),
        "name_norm": name_norm,
    }


def read_training_camp_tabs(
    image_path,
    ocr,
    *,
    band: tuple[float, float] = (0.95, 1.0),
    min_confidence: float = 0.85,
) -> dict[str, tuple[float, float]]:
    """The three barracks tabs on the training page: camp label -> its centre.

    The same reasoning as :func:`read_resource_tab_labels`: the client draws the names
    and the labels are what is stable, so reading them costs one pass and cannot drift
    out of step with a client reorder.  Measured 2026-09-22 on the three live training
    pages that exist (720x1280):

        盾兵营   (134, 1260)   conf 0.997
        矛兵营   (361, 1260)   conf 0.990
        射手营   (586, 1260)   conf 0.995

    All three drawn at once on every one of them -- which is exactly why presence alone
    cannot say which is *selected*, and why this returns their positions rather than a
    choice.  Choosing belongs to the caller that knows what it wants (``observe_camps``
    answers "which camp is open" from the page title instead).
    """
    with Image.open(image_path) as source:
        frame_width, frame_height = source.size
    top, bottom = band
    roi = {"x_norm": 0.0, "y_norm": top, "w_norm": 1.0, "h_norm": bottom - top}
    found: dict[str, tuple[float, float]] = {}
    for token in ocr.recognize(image_path, roi).tokens:
        if token.confidence < min_confidence or not token.box:
            continue
        label = token.text.strip()
        if label not in LABEL_TO_CAMP or label in found:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        # Crop-relative boxes: the band's own top is added back before normalising, the
        # same step ``read_resource_tab_labels`` documents, or every centre lands above
        # the tab it names.
        found[label] = (
            round((min(xs) + max(xs)) / 2.0 / frame_width, 4),
            round(((min(ys) + max(ys)) / 2.0 + top * frame_height) / frame_height, 4),
        )
    return found


#: The template that gates the reading above, and the reason it exists.
#:
#: ``tests/test_ocr.py::test_hybrid_is_template_first`` pins a contract this module keeps
#: on purpose: **a page the template layer fully resolves is not OCR'd**, because HOME is
#: the most common frame in the loop.  Reading the action bar on every HOME frame broke it
#: (backend calls 0 -> 1 on a plain city frame, measured), so the OCR pass is gated on a
#: template first -- and no *existing* template could serve, because on these frames every
#: registered control scores NO MATCH, ``BTN_UPGRADE`` included.
#:
#: So one was cut: the opaque white up-arrow of the bar's middle control, which is
#: identical (distance 0) on all twelve live action-bar frames and absent from ordinary
#: city frames.  It is a gate, never a tap target -- the 训练 label read off the frame is
#: the point, so a bar that moves still gets tapped where it actually is.
#:
#: It is also deliberately loose: it matches the same bar drawn for the 研究实验室, so the
#: reader below is what says "and it has a 训练 control on a barracks" (measured on that
#: frame: gate distance 0, reading refused).
CAMP_ACTION_BAR_GATE = "TARGET_CAMP_ACTION_BAR"


#: The client's own "tap anywhere" instructions, and the one thing each means.
#:
#: These are the client telling us the interaction, which is why obeying one is reading the
#: frame rather than guessing at it: the screen states that a tap anywhere dismisses it.
#: Measured 2026-09-17 on the mail-reward popup
#: (``dataset/truth_audit/power_route_20260917/probe_dismiss_mail_reward_20260917_044652.json``):
#: the phrase read at 0.998, one tap dismissed the popup, and the frame after it was the
#: MAIL page with ``popup = null``.  Kept as data because a new phrasing is knowledge, not a
#: code change -- the operator's rule that ordinary learning should arrive as data.
CLIENT_TAP_ANYWHERE_PHRASES: tuple[str, ...] = (
    "点击任意位置退出",
    "点击任意位置继续",
    "点击任意处退出",
    "点击任意处继续",
    "点击空白处退出",
    "点击空白处继续",
    "点击屏幕继续",
)


def read_tap_anywhere_instruction(image_path, ocr: OCRService) -> dict | None:
    """The client's own "tap anywhere" instruction, and where it drew it.

    ``None`` when this screen carries no such instruction, which is most of them and is the
    answer that keeps a caller from inventing a dismissal.  The point returned is the
    instruction's own box centre: that is a spot the client has just said is safe to tap,
    and it is read off *this* frame rather than remembered from another one.

    The phrase is matched on the token's text, not on the frame's whole OCR blob, because
    the caller needs the position as well as the fact -- a dismissal executed at a position
    nobody measured is the thing this function exists to avoid.
    """
    try:
        result = ocr.recognize(image_path)
    except (OSError, ValueError):
        return None
    size = read_frame_size(image_path)
    if not size:
        return None
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return None
    best: dict | None = None
    for token in result.tokens:
        text = (token.text or "").strip()
        if not text or not token.box:
            continue
        phrase = next((word for word in CLIENT_TAP_ANYWHERE_PHRASES if word in text), None)
        if phrase is None:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        centre = (
            round((min(xs) + max(xs)) / 2.0 / width, 4),
            round((min(ys) + max(ys)) / 2.0 / height, 4),
        )
        if not (0.0 <= centre[0] <= 1.0 and 0.0 <= centre[1] <= 1.0):
            continue
        candidate = {
            "phrase": phrase,
            "instruction": "TAP_ANYWHERE_TO_DISMISS",
            "center_norm": centre,
            "confidence": round(float(token.confidence or 0.0), 4),
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate
    return best


def find_printed_words(
    image_path,
    words: tuple[str, ...] | list[str],
    ocr: OCRService,
    *,
    band: dict[str, float] | None = None,
    allow_containment: bool = False,
) -> dict | None:
    """Locate a control by the word the client printed on it.

    This is the general answer to "the route names a control and no template exists for it":
    the client draws control names next to the controls, and reading one is a statement about
    *this* frame, so it cannot go stale the way a remembered coordinate can.

    **The match is exact by default, and that default is measured, not cautious.**  2026-09-22,
    on a MAP frame with the beast-search panel open: the 城镇 navigation cell is covered by the
    panel, the word ``城镇`` is nowhere on the bar, and a containment match still "found" it at
    (0.5062, 0.4945) -- inside ``我的城镇``, the town-hall label the client draws on the map
    itself.  A reader that accepts a substring would have answered with a *different* control's
    position and looked successful doing it.  Exactness is also what selects the right reading
    on a HOME frame, where the alliance cell's ``联盟`` (0.7444, 0.9820, conf 1.000) shares the
    screen with chat lines reading ``系统消息：…退出了联盟``.

    ``allow_containment`` exists for a caller that knows the client merges a name with a
    number; nothing uses it yet, and it is not the default for the reason above.

    ``band`` optionally narrows the search to a normalised region, for a control whose word also
    appears as a page title elsewhere on the same screen.  Highest confidence wins; ties keep
    reading order.  ``None`` means the word is not on this frame -- the honest answer, and the
    one a caller needs in order to know the control is not on screen at all.
    """
    wanted = [str(word).strip() for word in words if str(word or "").strip()]
    if not wanted:
        return None
    try:
        result = ocr.recognize(image_path)
    except (OSError, ValueError):
        return None
    size = read_frame_size(image_path)
    if not size:
        return None
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return None
    best: tuple[float, dict] | None = None
    for token in result.tokens:
        text = (token.text or "").strip()
        if not text or not token.box:
            continue
        word = next((candidate for candidate in wanted if candidate == text), None)
        exact = True
        if word is None:
            if not allow_containment:
                continue
            word = next((candidate for candidate in wanted if candidate in text), None)
            exact = False
        if word is None:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        centre = (
            (min(xs) + max(xs)) / 2.0 / width,
            (min(ys) + max(ys)) / 2.0 / height,
        )
        if not (0.0 <= centre[0] <= 1.0 and 0.0 <= centre[1] <= 1.0):
            continue
        if band is not None:
            inside_x = band["x_norm"] <= centre[0] <= band["x_norm"] + band["w_norm"]
            inside_y = band["y_norm"] <= centre[1] <= band["y_norm"] + band["h_norm"]
            if not (inside_x and inside_y):
                continue
        confidence = round(float(token.confidence or 0.0), 4)
        row = {
            "word": word,
            "exact": bool(exact),
            "center_norm": (round(centre[0], 4), round(centre[1], 4)),
            "confidence": confidence,
            # The token's own box, normalised.  Additive: every existing caller reads
            # ``word``/``center_norm``/``confidence`` and is unaffected.  The automatic UI
            # collector needs the box rather than the centre, because an element crop taken
            # from a centre needs a size and inventing one is what turns a measurement into a
            # guess -- the client drew this rectangle, and it is the only honest starting point
            # for "where is the control this word is printed on" (see ui_collection.py).
            "box_norm": {
                "x_norm": round(min(xs) / width, 4),
                "y_norm": round(min(ys) / height, 4),
                "w_norm": round((max(xs) - min(xs)) / width, 4),
                "h_norm": round((max(ys) - min(ys)) / height, 4),
            },
        }
        if best is None or confidence > best[0]:
            best = (confidence, row)
    return best[1] if best is not None else None


def read_frame_size(image_path) -> tuple[int, int] | None:
    """The frame's ``(width, height)`` in pixels, or ``None`` if it cannot be opened.

    Readers that judge *where* a token sits (rather than only what it says) need
    the frame height to turn a pixel ``y`` into a ``y_norm``.  Returning ``None``
    rather than raising keeps such a reader from turning a corrupt frame into a
    crash: a position test that cannot run simply does not run.
    """
    try:
        with Image.open(image_path) as source:
            width, height = source.size
    except (OSError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return int(width), int(height)


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


#: The client's two ways to answer a beast search.  Their difference is the whole
#: reason the beast route distinguishes the tabs, so it is read as words rather than
#: matched as sprites: the card that offers 攻击 can be fought solo, the one that
#: offers 集结 cannot.
BEAST_CARD_SOLO_ATTACK_LABEL = "攻击"
BEAST_CARD_RALLY_LABEL = "集结"
#: The result card's title is ``等级<N><name>`` -- a composite, measured 2026-09-21 as
#: ``等级10蔚牛`` (a one-glyph misread of 麝牛) at confidence 0.88.  The digit is what
#: separates it from a map nameplate, which never carries one.
BEAST_CARD_TITLE_PATTERN = re.compile(r"^等级\s*(\d{1,3})\s*(.+)$")


def read_beast_search_result_card(
    image_path,
    ocr,
    *,
    frame_size: tuple[int, int] | None = None,
    min_confidence: float = 0.75,
) -> dict:
    """Read the card the client draws over the panel after a beast search.

    Returns ``{}`` when this is not that card, and otherwise a dict describing what
    the client offered.  Why it exists rather than a template: measured live
    2026-09-21, the successful search produced a card that matches **none** of the
    reviewed card templates -- ``BTN_BEAST_CARD_ATTACK`` (cut from a world-map card)
    scored NO MATCH, and so did every ``TARGET_BEAST_*`` sprite -- while the card's
    own words read cleanly at 0.88-1.00.  The route only needs the words.

    The fields the caller acts on:

    ``solo_attack``
        the card carries 攻击 and does NOT carry 集结.  This is the user-facing rule
        that a rally target must never be attempted as a normal attack: the measured
        level-5 mammoth card offered 集结 with no 攻击, and the measured 等级10 麝牛
        card offered 攻击 with no 集结.  Keying on the words keeps the distinction
        working for species nobody has cut a sprite for, which is the whole point of
        searching by the client's own search rather than by species template.

    ``title_level`` / ``title_text``
        the ``等级<N><name>`` title the card prints, so the evidence names what was
        actually found rather than only that something was.

    ``attack_centre_norm``
        where the 攻击 control itself sits, as a normalised frame point.  This is the
        tap target the march needs, and it is read here rather than resolved from a
        control name for the same measured reason the rest of the card is: the
        position-pinned ``BTN_BEAST_CARD_ATTACK`` scored NO MATCH on exactly this
        card, so a route that tapped "the attack control" had no coordinate to tap.
        Only emitted when the control was found at a confidence above the threshold,
        so a miss is a miss and never a guessed point.

    ``{}`` is returned for a frame that is not this card (no title, or neither
    control word), so a bare map or the open panel cannot be mistaken for a result.
    """
    try:
        if frame_size is None:
            with Image.open(image_path) as opened:
                frame_size = opened.size
        tokens = tuple(ocr.recognize(image_path, None).tokens)
    except Exception:  # noqa: BLE001 - recognition must never take the frame with it
        return {}
    title_level: int | None = None
    title_text = ""
    title_box: tuple[float, float, float, float] | None = None
    has_attack = False
    has_rally = False
    attack_box: tuple[float, float, float, float] | None = None
    for token in tokens:
        if not token.box or token.confidence < min_confidence:
            continue
        text = str(token.text or "").strip().replace(" ", "")
        if not text:
            continue
        if BEAST_CARD_SOLO_ATTACK_LABEL == text:
            has_attack = True
            xs = [point[0] for point in token.box]
            ys = [point[1] for point in token.box]
            attack_box = (min(xs), min(ys), max(xs), max(ys))
            continue
        if BEAST_CARD_RALLY_LABEL == text:
            has_rally = True
            continue
        if title_level is None:
            match = BEAST_CARD_TITLE_PATTERN.match(text)
            if match is not None:
                title_level = int(match.group(1))
                title_text = match.group(2)
                xs = [point[0] for point in token.box]
                ys = [point[1] for point in token.box]
                title_box = (min(xs), min(ys), max(xs), max(ys))
    if title_level is None and not (has_attack or has_rally):
        return {}
    result: dict = {
        "title_level": title_level,
        "title_text": title_text,
        "has_attack": has_attack,
        "has_rally": has_rally,
        # Solo only when the attack word is offered and the rally word is not: a card
        # that showed both would be ambiguous, and this route must not guess.
        "solo_attack": bool(has_attack and not has_rally),
    }
    if attack_box is not None and frame_size is not None:
        width, height = frame_size
        result["attack_centre_norm"] = (
            round(((attack_box[0] + attack_box[2]) / 2.0) / width, 4),
            round(((attack_box[1] + attack_box[3]) / 2.0) / height, 4),
        )
    if title_box is not None and frame_size is not None:
        width, height = frame_size
        result["title_centre_norm"] = (
            round(((title_box[0] + title_box[2]) / 2.0) / width, 4),
            round(((title_box[1] + title_box[3]) / 2.0) / height, 4),
        )
    return result


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

    def _read_beast_card_words(self, image_path: Path, primary: WorldState) -> WorldState | None:
        """Attach the open beast card's own words, or ``None`` when this is not that frame.

        The card a tapped wilderness beast opens is the same layout the search result
        uses, and the client puts either 攻击 (ordinary attack) or 集结 (rally) at its
        bottom.  Which one it is has to come from the words, because the template that
        claims to describe this control does not match the card:

        * ``BTN_BEAST_CARD_ATTACK`` was cut from
          ``dataset/truth_audit/map_beast_search_20260918/key/go_20260918_014947_001_after_382_844.png``
          with its ROI at ``y 0.8187``, and on the live card the same control sits at
          ``y ~0.61`` -- the client moved it, so the template scores NO MATCH (measured
          2026-09-21 on all four frames of the run that opened it).
        * ``read_beast_search_result_card`` reads the same card correctly on the search
          path, because it reads words rather than positions.

        Measured cost of having no reader here: the labelled route tapped a **霜鳞避役**
        its map label named, a ``等级7`` card opened carrying only 集结 with
        推荐实力683,100,000, and the run recorded ``BEAST_TARGET_SELECTION_NOT_PROVEN``
        -- a correct refusal scored as a failure, which is exactly the kind of evidence
        that hides whether the route works.

        ``solo_attack`` therefore becomes measurable on ``Page.BEAST`` too, and the
        user's rule -- 集结 is not an ordinary attack -- is a guard the verifier can
        evaluate rather than a convention.

        ``None`` means "not a beast card" and leaves the template layer's state alone.
        """
        if primary.page is not Page.BEAST:
            return None
        if not (primary.beast.get("attack_card") or primary.beast.get("name")):
            return None
        card = read_beast_search_result_card(image_path, self.ocr, frame_size=None)
        if not card:
            return None
        return replace(primary, beast_search_result=card)

    def _quick_panel_is_drawn(self, image_path: Path) -> bool:
        """True when the 快捷面板's plate is drawn over the frame.

        A cheap pixel gate, so the OCR pass that reads the panel's rows only runs on
        frames where it can be there -- the same trade ``_building_is_selected`` makes for
        the building label, and what keeps "a page the template layer resolves costs no
        OCR" true.

        The test is the plate's own fill, not a template: the panel is a flat dark
        navy card with rounded corners, and nothing else on the city or map view paints
        that value across that much of the left strip.  Measured 2026-09-21 over the
        region ``QUICK_PANEL_PLATE_ROI``:

            panel open (live frame)                 0.674
            city view, panel closed                 0.038
            city view, panel closed (other frame)   0.035
            map/intel, panel closed                 0.007
            city view, panel closed (third frame)   0.0001

        The gap between 0.674 and 0.038 is wide enough that the threshold is not a
        fitted constant: anything between roughly 0.15 and 0.6 separates these frames.

        It answers "is the panel there", not "is it readable".  A ``True`` that leads to
        an unreadable panel costs one OCR pass and yields no reading, which is the
        honest outcome; a ``False`` costs nothing and leaves the state untouched.
        """
        rect = _roi_box(QUICK_PANEL_PLATE_ROI)
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGB")
                width, height = image.size
                box = (
                    round(rect[0] * width),
                    round(rect[1] * height),
                    round(rect[2] * width),
                    round(rect[3] * height),
                )
                if box[2] <= box[0] or box[3] <= box[1]:
                    return False
                crop = image.crop(box)
                pixels = crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata()
                pixels = list(pixels)
        except (OSError, ValueError):
            return False
        if not pixels:
            return False
        plate = sum(1 for pixel in pixels if _is_quick_panel_plate_pixel(pixel))
        return plate / len(pixels) >= QUICK_PANEL_PLATE_MIN_FRACTION

    def _read_selected_building(self, image_path: Path, primary: WorldState) -> WorldState | None:
        """Attach the selected building's action bar, or ``None`` when this is not that frame.

        This is the third rendering of "a building is selected" and the first one that is
        *read* rather than matched.  The other two are templates --

          * ``BTN_UPGRADE`` for a selected 仓库,
          * ``BTN_TRAINING_MENU_LABEL`` / ``BTN_OPEN_TRAINING_FROM_CAMP`` for the radial
            menu of a selected 盾兵营;

        -- and on the client of 2026-09-22 all three miss, while the frame shows the
        client's own 详情 / 升级 / 训练 bar at confidence 0.986-1.000.  The consequence was
        not cosmetic: ``training`` stayed empty, ``verify_infantry_camp_highlighted``
        answered ``INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN``, and every ``NAVIGATE_INFANTRY_CAMP``
        from 16:24 to 23:47 failed on a screen the route had already reached correctly.

        Two conditions, and both are load-bearing:

        * **the 训练 control is drawn** -- that is what makes this the camp's own bar and
          not some other overlay;
        * **the client named the building, and the name is a barracks** -- the bar is drawn
          for any selected building, so presence alone would let a selected 仓库 be
          reported as a selected camp.

        ``menu_open`` is what the reading sets, and it is the honest word for it: the
        client's menu for the selected building IS drawn.  ``navigation`` is deliberately
        left alone -- that key means the gold ring was seen, and this render has no ring,
        so setting it would be the same false-arrival this area has already been bitten by
        once.

        What it does NOT claim: that the queue is free.  ``queue_available`` is absent
        rather than True or False, because this screen does not say, and the route's own
        guard reads ``is False`` -- so unknown keeps it on its normal path instead of
        stopping it or authorising a spend.
        """
        if primary.page is not Page.HOME:
            return None
        # The cheap gate first, and it is load-bearing: nothing below this line may run on
        # a frame whose template layer already resolved the page, or every city frame in
        # the loop pays for an OCR pass.  ``TARGET_CAMP_ACTION_BAR`` is the bar's own
        # control, so a frame without a selected building never reaches the OCR call.
        semantic = getattr(self.template_vision, "semantic", None)
        if semantic is None or semantic.find(image_path, CAMP_ACTION_BAR_GATE) is None:
            return None
        reading = read_selected_building_actions(image_path, self.ocr)
        actions = reading.get("actions") or {}
        camp = str(reading.get("camp") or "")
        train_norm = actions.get("训练")
        if train_norm is None or not camp:
            return None
        training = dict(primary.training)
        training.update({
            "menu_open": True,
            "camp": camp,
            "camp_label": str(reading.get("name") or ""),
            "train_tap_norm": train_norm,
            "source": "ACTION_BAR",
        })
        return replace(primary, training=training)

    def _read_training_camp_tabs(self, image_path: Path, primary: WorldState) -> WorldState | None:
        """Where the three barracks tabs are drawn on this training page, or ``None``.

        This is the half that did not exist: the goal asked for another barracks and nothing
        could turn a tab's name into a pixel.  ``read_training_camp_tabs`` was written
        2026-09-21 and referenced by nothing.

        What this returns is **positions only**, and that boundary is the whole point: the
        client draws all three labels at once on every camp page (measured 2026-09-21 on all
        five reviewed frames), so a label being on screen proves nothing about which page this
        is.  Which camp is open comes from the title, in ``camp_open_label``; these are where to
        tap in order to reach a different one.  Both readings come off the same frame, so a tab
        that moves is followed rather than remembered.

        Measured 2026-09-22 on the live training page (720x1280): 盾兵营 (134,1260),
        矛兵营 (361,1260), 射手营 (586,1260), read at 0.990-0.997.  One narrow band along the
        bottom, so the cost is one small ROI pass and only on this page.
        """
        if primary.page is not Page.TRAINING:
            return None
        tabs = read_training_camp_tabs(image_path, self.ocr)
        if not tabs:
            return None
        training = dict(primary.training)
        training["camp_tab_norm"] = {label: list(point) for label, point in tabs.items()}
        return replace(primary, training=training)

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
        # The selected-building action bar is rendered on HOME, before the upgrade
        # dialog.  Read its "升级" label from this same screenshot so the entry
        # action can use a current-frame location rather than a remembered offset.
        if primary.page is Page.HOME:
            actions = read_building_action_tokens(tokens, read_frame_size(image_path))
            upgrade = actions.get("actions", {}).get("升级")
            if upgrade is not None:
                state["upgrade_tap_norm"] = list(upgrade)
            if actions.get("name"):
                state["selected_name"] = actions["name"]
                state["selected_name_norm"] = list(actions["name_norm"] or ())
        return replace(primary, building=state)

    def observe(self, image_path: Path) -> WorldState:
        """The frame's world, with the entry badges read onto it.

        Wrapped rather than edited in place: ``_observe_inner`` has many returns (one per page it
        recognises) and attaching the ledger at each of them is how a lower layer passes while the
        production entry point silently does not run -- a defect this module has already been bitten
        by twice.  A badge read can never take the observation down with it: the frames it needs are
        optional evidence, so a failure leaves ``red_dots`` empty rather than raising.
        """
        state = self._observe_inner(image_path)
        try:
            frame = image_path if isinstance(image_path, Path) else Path(image_path)
            ledger = read_all(state, frame, observed_at=_frame_stamp(frame))
            return replace(state, red_dots={name: badge.as_record() for name, badge in ledger.items()})
        except (OSError, ValueError, KeyError):
            return state

    def _observe_inner(self, image_path: Path) -> WorldState:
        primary = self.template_vision.observe(image_path)
        # The frame's pixel size, needed by the classifier to tell a page's own
        # wording from the wording of an overlay drawn on top of it (see
        # ``OCRPageClassifier.QUICK_PANEL_SECTIONS``).  A missing size only costs
        # those keywords, never the whole reading, so a failed read is not fatal.
        frame_size = read_frame_size(image_path)
        # Is the panel drawn, and -- when it is not -- where is its handle.  Read here, once, rather
        # than in the panel branch far below, because that branch is not reached on every frame: a
        # world-map frame with a building selected returns from the building branch first (measured
        # 2026-09-22 on ``20260922_184834_110558 step_010``, which draws the handle at
        # (0.0181, 0.4301) and reported no panel at all through that path).  A control that is only
        # read on some of the frames that draw it is the same defect this module has already been
        # bitten by twice -- a lower layer passing does not mean the production entry point runs.
        #
        # Both probes are pixels only, so a page the template layer resolved still spends no OCR.
        panel_drawn = self._quick_panel_is_drawn(image_path)
        if not panel_drawn:
            collapsed_handle = find_quick_panel_handle(image_path, panel_open=False)
            if collapsed_handle is not None:
                primary = replace(
                    primary,
                    quick_panel={
                        "open": False,
                        "state": "COLLAPSED",
                        "handle": collapsed_handle,
                    },
                )
        # The 快捷面板 is an overlay, so it is not tied to one page: it can be open over
        # the city, over the map, or over any page.  Its reading is attached below, in
        # the branch where the frame was OCR'd anyway.
        #
        # Measured 2026-09-21.  Missing this reading is what made the operator's
        # "为什么不训练士兵" answerable only by hand: the panel's 部队训练 rows (盾兵 /
        # 矛兵 / 射手, all 已完成) were on a frame the route read as `Page.RESEARCH`
        # with an empty `training`, so the route believed every queue was busy and
        # stopped instead of training.  Reading the panel gives the route the same
        # per-camp answer the training page would, without navigating to three pages.
        #
        # It is read from the frame's left strip rather than the whole frame.  Measured:
        # every token the panel draws sits between x_norm 0.10 and 0.34, while the rest
        # of the frame is the page underneath.  Reading only the strip is what keeps the
        # panel's own section headers from naming that page -- the defect this whole area
        # exists to fix -- because the strip carries none of the page-identifying words.
        quick_panel: dict = {}
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
            result = self.ocr.recognize(image_path)
            # The panel is read here, where the frame has already been recognised for the
            # page question, so it costs no extra OCR pass.  A page the template layer
            # resolves is left untouched, which is this module's long-standing contract.
            quick_panel = read_quick_panel(image_path, self.ocr, result=result)
            classified = self.classifier.classify(
                result, frame_size=frame_size
            )
            if classified.page is Page.TRAINING and classified.training:
                # Where the three tabs are drawn, read now: this branch RETURNS, so a fold
                # placed with the other per-page reads (further down, in the known-page chain)
                # would never run for a training frame -- the first version of this was written
                # there and produced nothing, while every test that called the classifier
                # directly looked fine.  Same lesson as the training branch above: a lower layer
                # passing does not mean the production entry point reaches it.
                tab_state = self._read_training_camp_tabs(image_path, classified)
                if tab_state is not None:
                    classified = tab_state
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
                return self._with_quick_panel(
                    replace(
                        classified,
                        camps=merge_camps(primary.camps, camps),
                        confidence=max(primary.confidence, classified.confidence),
                    ),
                    quick_panel,
                )
            if classified.page is Page.BUILDING and classified.building.get("upgrade_dialog_visible"):
                # Keep the navigation proof and the building identity separate.
                # The second read may resolve a catalogued identity, but an
                # unrecognized building remains UNKNOWN and cannot be upgraded.
                identified = self._read_building_identity(image_path, classified)
                if identified is not None:
                    classified = identified
            return self._with_quick_panel(classified, quick_panel)
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
            # The selected building's action bar, before the identity read below, because
            # this render is the one the template gate cannot see: a camp frame is read
            # here from the client's own words, and ``_read_building_identity`` would ask
            # its template gate about the same frame and answer "not that frame".
            selected_state = self._read_selected_building(image_path, primary)
            if selected_state is not None:
                return selected_state
            building_state = self._read_building_identity(image_path, primary)
            if building_state is not None:
                return building_state
            # The card a tapped wilderness beast opens, recognized by its own words.
            #
            # This has to come before the map branch below, and it has to exist at all,
            # because the template that described this card no longer matches it: the
            # client moved the control from y 0.8187 (where ``BTN_BEAST_CARD_ATTACK`` was
            # cut) to y ~0.61, so the frame reads ``MAP`` and the card's 攻击/集结 control
            # becomes invisible to every route that keys on the page.  Measured
            # 2026-09-21 on
            # ``live_runtime_step_001_after_refresh_1_20260921T113541458785.png``: the
            # card was on screen, fully readable, and the run recorded the labelled
            # selection as ``BEAST_TARGET_SELECTION_NOT_PROVEN``.
            #
            # It is gated on the frame NOT already being a known non-map page, so a
            # dialog or panel that happens to carry a 攻击 word cannot be re-labelled
            # as a beast card.  The card's title (``等级<N><name>``) is what makes the
            # reading specific: a bare map carries no such title.
            if primary.page in {Page.MAP, Page.RESOURCE_DETAIL}:
                card_words = read_beast_search_result_card(
                    image_path, self.ocr, frame_size=None
                )
                if card_words.get("title_level") and (
                    card_words.get("has_attack") or card_words.get("has_rally")
                ):
                    # ``beast_search_submitted`` goes along for the same reason the map
                    # branch sets it: the card IS the search's answer, and this branch now
                    # preempts that one on exactly the frames a search succeeded on.  The
                    # verifier reads this flag, so leaving it False would turn every
                    # successful search into BEAST_SEARCH_NOT_SUBMITTED -- which is the
                    # defect this whole path exists to fix, in a new place.
                    #
                    # The panel fields go along too, and they must: the card is drawn
                    # *over* the search panel, which stays open behind it (its 搜索 button
                    # and level slider are both still drawn -- measured on
                    # ``live_runtime_step_001_after_refresh_1_20260921T110723901682.png``).
                    # Reporting ``resource_search_open=False`` here would tell the route
                    # the panel had closed, and the search chain keys on that flag to
                    # decide whether it still owns the screen.
                    return replace(
                        primary,
                        page=Page.BEAST,
                        beast={"attack_card": True},
                        beast_search_submitted=bool(card_words.get("title_level")),
                        # The card is on top of whatever was underneath, so the page is
                        # BEAST while the panel state is whatever the frame still shows.
                        beast_search_result=card_words,
                    )
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
                # The client's beast search ran and left a target on the map.
                #
                # Measured 2026-09-21: the successful search draws a result card over the
                # panel whose layout matches NO reviewed template -- ``BTN_BEAST_CARD_ATTACK``
                # (cut from a world-map card) and every ``TARGET_BEAST_*`` sprite all scored
                # NO MATCH on
                # ``live_runtime_step_001_after_refresh_2_20260921T105832480183.png``, while
                # its words read at 0.88-1.00.  The card is therefore read from its own words,
                # and ``beast_search_submitted`` is that read.
                #
                # The pair this replaced was ``resource_beast_tab and beacon_beast``, and both
                # halves are broken on this very frame -- each an independent reason:
                #
                # * ``resource_beast_tab`` came from ``match("BTN_SEARCH_BEAST_TAB")``, the
                #   position-pinned template measured to score NO MATCH once the client moved
                #   野兽 into the leftmost slot.  The search chain was changed to read the
                #   tab's printed label for exactly this reason; leaving the verifier on the
                #   template kept the old defect alive behind the fix.  Confirmed NO MATCH on
                #   the result frame.
                # * ``beacon_beast`` came from ``beast_from_its_label``, which looks for a
                #   *map nameplate*; the result card's title is the composite ``等级10麝牛``
                #   and that reader returned ``{}``.
                #
                # So a search that visibly succeeded -- the card, its 攻击 control, its
                # recommended-power line -- was reported as not submitted, and the run stopped
                # one hop short of a target it had actually found.  The panel staying open is
                # still why "panel closed" is not the test.
                beast_search_result = (
                    read_beast_search_result_card(
                        image_path, self.ocr, frame_size=(frame_width, frame_height)
                    )
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
                    # Which tab the bracket anchors, monsters included.  Distinct from
                    # ``resource_selected`` (gatherable cells only, so a monster tab reads
                    # ``None``) and from ``resource_beast_tab_norm`` (where the label is
                    # *drawn*, which is true for every tab on a freshly opened panel).
                    # Measured 2026-09-21: the panel opens with 生肉 anchored while
                    # ``resource_beast_tab_norm`` is already non-``None``, which is exactly
                    # the pair of facts that made the route skip its tab switch.
                    #
                    # ``template_vision.semantic`` and not ``self.semantic``: the semantic
                    # layer hangs off the template vision on this composite (see
                    # ``_semantic_roi`` above), and reaching for the shorter name is what
                    # crashed the first live run of this change with
                    # ``AttributeError: 'HybridVision' object has no attribute 'semantic'``.
                    resource_selected_tab=(
                        self.template_vision.semantic.anchored_tab_kind(image_path)
                        if primary.resource_search_open else None
                    ),
                    beast_search_submitted=bool(beast_search_result.get("title_level")),
                    beast_search_result=beast_search_result,
                    # Only when the template path found nothing: that path is LIVE_VERIFIED and
                    # its values are not re-decided here.  The frame size goes along because the
                    # label read carries a tap point with it, and an ROI-scoped token box can
                    # only be mapped back to the frame with it.
                    beast=beacon_beast,
                )
            if primary.page is Page.BEAST and primary.beast.get("attack_card"):
                # Which control the open beast card offers, read from its own words.
                #
                # The template layer sees only ``attack_card``, and that name is a
                # misnomer it carries from the one card it was cut from: the client
                # draws the same layout for every huntable beast and puts either 攻击
                # (ordinary attack) or 集结 (rally) at the bottom.  Measured live
                # 2026-09-21 on
                # ``live_runtime_step_001_after_refresh_1_20260921T113541458785.png``:
                # the labelled route tapped a **霜鳞避役** the map label named, a
                # 等级7 card opened carrying only 集结 with 推荐实力683,100,000, and
                # the selection was recorded as ``BEAST_TARGET_SELECTION_NOT_PROVEN``
                # -- a correct refusal scored as a failure, because a template cannot
                # read a word.
                #
                # The words are what keep the user's rule measurable: 集结 is not an
                # ordinary attack, and this is where that is decided.
                card = read_beast_search_result_card(
                    image_path, self.ocr, frame_size=(frame_width, frame_height)
                )
                return replace(
                    primary,
                    beast_search_result=card,
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
                secondary = self.classifier.classify(
                    self.ocr.recognize(image_path), frame_size=frame_size
                )
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
                secondary = self.classifier.classify(
                    self.ocr.recognize(image_path), frame_size=frame_size
                )
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
            if primary.page is Page.RESEARCH:
                # A reviewed page template answers that the technology tree is open, but
                # not which nodes, levels, or detail controls are visible.  Read those
                # values from the same current screenshot so Goal/MAA can inspect the
                # actual tree instead of leaving an idle queue as an unstructured UNKNOWN.
                # Only OCR-derived node/detail facts are merged here; a stronger queue
                # state already supplied by the template reader keeps precedence.
                result = self.ocr.recognize(image_path)
                secondary = self.classifier.classify(result, frame_size=frame_size)
                if secondary.page is Page.RESEARCH:
                    research = dict(primary.research)
                    for key in (
                        "node_candidates", "selected_node", "selected_node_name",
                        "node_detail_visible", "research_control_norm", "node", "name",
                        "branch", "level_progress",
                    ):
                        if key in secondary.research:
                            research[key] = secondary.research[key]
                    if secondary.research.get("status") == "IN_PROGRESS":
                        research.update({
                            key: secondary.research[key]
                            for key in ("status", "queue_available", "timer")
                            if key in secondary.research
                        })
                    elif (
                        secondary.research.get("status") == "IDLE"
                        and research.get("queue_available") is not False
                    ):
                        research.update({
                            key: secondary.research[key]
                            for key in ("status", "queue_available")
                            if key in secondary.research
                        })
                    return replace(primary, research=research)
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
                secondary = self.classifier.classify(
                    self.ocr.recognize(image_path), frame_size=frame_size
                )
                if secondary.page is primary.page and secondary.training:
                    return replace(primary, training={**secondary.training, **primary.training, **({"timer": secondary.training["timer"]} if "timer" in secondary.training else {})})
            if primary.page is Page.RESEARCH and primary.research.get("status") == "IN_PROGRESS" and primary.research.get("timer") in {None, "VISIBLE"}:
                secondary = self.classifier.classify(
                    self.ocr.recognize(image_path), frame_size=frame_size
                )
                if secondary.page is primary.page and secondary.research:
                    merged = {**secondary.research, **primary.research}
                    if "timer" in secondary.research:
                        merged["timer"] = secondary.research["timer"]
                    return replace(primary, research=merged)
            # The 快捷面板 can be open over a page the template layer *did* name -- the
            # operator's own frame is the city view (HOME) with the panel over it.
            #
            # Gated on a pixel probe (``_quick_panel_is_drawn``) before any OCR is spent,
            # the same way ``_building_is_selected`` gates the building read below: the
            # panel is absent on most frames, and this module's contract is that a page
            # the template layer resolves costs no OCR at all.  When the gate says the
            # panel is not there, the frame stays exactly as cheap as it was.
            if panel_drawn:
                # The open panel's own reading overrides the collapsed handle attached above; the
                # two cannot both be true, and ``read_quick_panel`` is the measurement that settles it.
                try:
                    panel_size = read_frame_size(image_path)
                except (OSError, ValueError, AttributeError, TypeError):
                    panel_size = None
                quick_panel = read_quick_panel(
                    image_path,
                    self.ocr,
                    # The roi pass is kept (it is why this costs no extra OCR), but its boxes belong to
                    # the crop and the reader works in frame space -- see ``_tokens_in_frame_space``.
                    result=_tokens_in_frame_space(
                        self.ocr.recognize(image_path, QUICK_PANEL_ROI), QUICK_PANEL_ROI, panel_size
                    ),
                )
            return self._with_quick_panel(primary, quick_panel)
        # The template layer could not name the page.  The classifier is asked, and the
        # panel reading is attached to whatever it answers -- including UNKNOWN, because
        # the panel being open is what makes a frame usable even when the page under it
        # is not recognised.
        return self._with_quick_panel(
            self.classifier.classify(
                self.ocr.recognize(image_path), frame_size=frame_size
            ),
            quick_panel,
        )

    @staticmethod
    def _with_quick_panel(state: WorldState, quick_panel: dict) -> WorldState:
        """Attach the 快捷面板 reading, and merge what the goal layer reads out of it.

        The panel's 部队训练 rows describe all three barracks in one frame, which is
        more than the training page can say at once (it draws one camp per visit, #86),
        so where the panel has an answer it is merged in.  The panel is the *overlay*
        and the page is the thing under it, so a page that positively read a camp wins:
        the merge is ``{**panel_camps, **page_camps}``.

        The same rule now applies to the two other queue sections the panel draws, and it is
        measured rather than tidy-minded (operator directive 2026-09-23 §一.2/§二: 如果 WorldState 已有
        新鲜可信的状态，直接复用；快捷面板作为城内任务状态来源).  Across the 57 production frames on which
        the panel was open, the panel carried a 建筑队列 reading in **56** of them and a 科技研究
        reading in **57**, while ``WorldState.building`` and ``WorldState.research`` were **empty in
        all 57** -- so the state the run needed was read off the frame and then dropped, and the goal
        layer could not see it.  That is what sent the training and research goals down the
        加成总览 -> 实力详情 route to ask a question the panel had already answered: 20 such steps in the
        corpus, every one of them a FAILURE (``POWER_DETAILS_NOT_PROVEN``).

        Only the two queue sections are merged, and only into an *empty* field, so a page that really
        read the building or the lab still wins -- the panel is the overlay either way.  The panel's
        remaining sections (联盟捐献, 英雄招募, 我的奖励) have their own fields on the reading and no
        matching ``WorldState`` field yet, which is stated here instead of being half-wired.
        """
        if not quick_panel:
            return state
        camps = quick_panel.get("camps") or {}
        updates: dict[str, object] = {
            "quick_panel": quick_panel,
            "camps": merge_camps(camps, state.camps) if camps else state.camps,
        }
        building = quick_panel.get("building")
        if isinstance(building, dict) and building and not state.building:
            updates["building"] = dict(building)
        research = quick_panel.get("research")
        if isinstance(research, dict) and research and not state.research:
            updates["research"] = dict(research)
        return replace(state, **updates)
