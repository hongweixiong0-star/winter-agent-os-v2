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

#: The ordinary actions this project may act on without a registered skill, in the client's own
#: words.  **One definition, two readers**: ``runtime._ordinary_control_candidate`` uses it to
#: decide what it may tap, and ``find_plain_controls`` below uses it to decide what is worth
#: collecting.  A second copy would let the collector gather words the executor refuses (or miss
#: the ones it taps), which is exactly the drift a shared constant prevents.
PLAIN_ACTION_WORDS: tuple[str, ...] = (
    "领取",
    "免费领取",
    "签到",
    "前往",
    "去完成",
    "打开",
    "帮助",
)

#: Words that *end* an interaction instead of committing one, so they need no goal to justify
#: them.  Stated once here because the tap path (the interactivity gate below) and the collection
#: scan both read it, and two copies would drift into disagreeing about what counts as an exit.
SAFE_EXIT_WORDS: tuple[str, ...] = ("返回", "关闭", "取消", "退出", "跳过")

#: Substrings that make a piece of text a *label* rather than a control: they name a value, a
#: count or a status the client draws beside one.  Taken from the vocabulary this project's own
#: frames keep producing (``原始时间``, ``剩余``, ``距离``, ``等级``) -- a caption that gets tapped
#: is a wasted step, so this gate is about precision, not recall.
NON_CONTROL_MARKERS: tuple[str, ...] = (
    "时间",
    "剩余",
    "距离",
    "等级",
    "战力",
    "数量",
    "消耗",
    "获得",
    "加成",
    "上限",
    "次数",
    "进度",
    "排名",
    "分数",
    "积分",
    "产量",
    "速度",
    "容量",
    "耐久",
    "说明",
    "提示",
    "条件",
    "需求",
    "总计",
    "当前",
    "已满",
    "已领",
    "已达",
)

#: What a goal looks for on a screen, as substrings of the client's own words.  This is the
#: "候选元素与目标相关" half of the directive's §3: a control whose words belong to the goal being
#: pursued is worth one bounded try; a control that belongs to nothing is not chased.  The keys are
#: substrings of the goal ids this project really runs (``KEEP_TRAINING_PRODUCTIVE``,
#: ``AVOID_STAMINA_WASTE``, ``CLEAR_INTEL``, ...), so a new goal whose name contains one of them
#: inherits the hints instead of needing a new table.
GOAL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TRAIN", ("训练", "兵营", "士兵", "部队")),
    ("TROOP", ("训练", "兵营", "士兵")),
    ("CAMP", ("训练", "兵营", "士兵")),
    ("RESEARCH", ("研究", "科技", "学院")),
    ("INTEL", ("情报", "线索", "调查", "前往")),
    ("BEAST", ("野怪", "讨伐", "搜索", "前往")),
    ("STAMINA", ("体力", "补给", "领取")),
    ("RESOURCE", ("采集", "资源", "搜索", "前往")),
    ("GATHER", ("采集", "资源", "前往")),
    ("MAIL", ("邮件", "领取", "前往")),
    ("ALLIANCE", ("联盟", "帮助", "捐献", "领取")),
    ("DAILY", ("每日", "任务", "活跃", "领取")),
    ("ACTIVITY", ("活动中心", "参与", "报名")),
    ("EXPLORATION", ("探索", "挂机", "领取")),
    ("MARCH", ("行军", "部队", "前往")),
    ("HOME", ("主城", "返回", "关闭")),
    ("DISCOVERY", ("前往", "打开", "查看")),
)

#: Text shapes that are *not* a control's label, measured on this project's own frames.  Every
#: entry killed a real false positive: ``系统消息：`` / ``退出了联盟`` (a system toast), ``-12.7`` /
#: ``166`` (a value), ``Q#4298（644,4`` (OCR debris on an overlay), ``统帅4`` (a tier caption).
#: The client's own button labels are Chinese words with no punctuation and no digits, so both are
#: required to be absent -- precision is the whole job of this gate, and a skipped control costs
#: one unexplored screen while a tapped caption costs a wasted step on the live game.
CONTROL_TEXT_REJECT = tuple("：:#（）()[]【】《》<>,.、/\\-—+%\"'“”·!！?？")
CONTROL_MIN_CJK_CHARS = 2

#: Longest label a control in this client carries, in Chinese characters.  Measured: every control
#: in the sampled frames is at most six (``增加行军队列``), while the whole sentences that are *not*
#: controls are longer (``您的部队已经返回`` = 8, ``仅搜索资源为满的资源点`` = 11, ``天子退出了联盟`` = 7).
#: A client that prints a sentence is telling the player something, not offering a button.
CONTROL_MAX_CJK_CHARS = 6

#: Geometry of a control's *label*, measured on 720x1280 captures.  A caption is smaller than the
#: floor and a page title is larger than the ceiling; a wide-and-short box is a button's own text
#: while a tall-and-narrow one is a column heading or a tab stack.
CONTROL_MIN_TEXT_PX = 18
CONTROL_MAX_TEXT_PX = 130
CONTROL_MIN_ASPECT = 1.0
CONTROL_MAX_ASPECT = 14.0
CONTROL_MAX_AREA_NORM = 0.05
CONTROL_TOP_MARGIN_NORM = 0.02


def goal_relevant(text: str, goal: str) -> bool:
    """Does this control's own wording belong to the goal being pursued? (directive §3)

    Two ways to qualify, and both are the client's evidence rather than a preference: the words
    name something the goal's hints name, or they are one of the exit words that end an
    interaction under any goal.  An empty goal has no hints, so nothing qualifies -- "有 Goal 明确"
    is a precondition of the whole mechanism, not an optional extra.
    """
    word = str(text or "").strip()
    if not word:
        return False
    if word in SAFE_EXIT_WORDS:
        return True
    if len(word) < 2:
        return False
    wanted = str(goal or "").strip().upper()
    if not wanted:
        return False
    for key, hints in GOAL_HINTS:
        if key not in wanted:
            continue
        if any(hint and (hint in word or word in hint) for hint in hints):
            return True
    return False


def interactive_controls(
    frame_path: Path | str,
    ocr,
    *,
    skip_words: Iterable[str] = (),
    goal: str = "",
    hints: Iterable[str] = (),
    limit: int = 8,
) -> list[dict]:
    """Text boxes on this frame that *look* like a control nobody has recorded (directive §2).

    The tap path's other source is exact match against ``PLAIN_ACTION_WORDS`` -- the client's own
    words, but only the seven somebody wrote down.  This is the general case the directive asks
    for: an element is judged from what the existing vision gives, not from a list.

        * the frame's own OCR boxes (``token.box``, the client's own text bounds);
        * their geometry -- a label-sized, wide-and-short box in the frame's usable area;
        * the text itself -- not a value, a countdown, a caption or OCR debris
          (``NON_CONTROL_MARKERS``, ``DYNAMIC_TEXT``, ``CONTROL_TEXT_REJECT``, digits, and a floor
          of ``CONTROL_MIN_CJK_CHARS`` Chinese characters);
        * the page context, through ``skip_words``: a word the semantic dictionary already
          declares is a control the project knows, and re-deriving it here would be a second,
          worse definition of it.

    ``score`` ranks what is left: confidence plus a bonus for the label-height band, the
    button-shaped aspect, the lower two thirds of the screen, and -- decisively -- for wording
    that matches the goal being pursued.  A row is returned with the box it was measured on, so a
    caller can tap it *and* file it as a candidate, and ``goal_relevant`` says whether the
    directive's relevance condition holds for it.

    Nothing here clicks, decides or remembers; it is the evidence, not the act.  An empty list is
    a real answer ("this frame shows no unrecorded control") and not a failure.
    """
    skip = {str(word).strip() for word in skip_words if str(word or "").strip()}
    frame_path = Path(frame_path)
    try:
        result = ocr.recognize(frame_path)
    except (OSError, ValueError):
        return []
    from .ocr import read_frame_size

    size = read_frame_size(frame_path)
    if not size:
        return []
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return []
    rows: list[dict] = []
    for token in result.tokens:
        word = (token.text or "").strip()
        confidence = float(token.confidence or 0.0)
        if not word or not token.box or confidence < MIN_SCAN_CONFIDENCE:
            continue
        if word in skip or DYNAMIC_TEXT.search(word):
            continue
        if any(marker in word for marker in NON_CONTROL_MARKERS):
            continue
        if any(char in word for char in CONTROL_TEXT_REJECT):
            continue
        if any(char.isdigit() for char in word):
            continue
        if sum(1 for char in word if "\u4e00" <= char <= "\u9fff") < CONTROL_MIN_CJK_CHARS:
            continue
        if sum(1 for char in word if "\u4e00" <= char <= "\u9fff") > CONTROL_MAX_CJK_CHARS:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        box_w = max(xs) - min(xs)
        box_h = max(ys) - min(ys)
        if box_h < CONTROL_MIN_TEXT_PX or box_h > CONTROL_MAX_TEXT_PX:
            continue
        if box_w <= 0 or box_h <= 0:
            continue
        aspect = box_w / box_h
        if aspect < CONTROL_MIN_ASPECT or aspect > CONTROL_MAX_ASPECT:
            continue
        x_norm = min(xs) / width
        y_norm = min(ys) / height
        w_norm = box_w / width
        h_norm = box_h / height
        if y_norm < CONTROL_TOP_MARGIN_NORM:
            continue
        if w_norm * h_norm > CONTROL_MAX_AREA_NORM:
            continue
        # ``hints`` is the goal's vocabulary as the *semantic dictionary* declares it (each
        # record's ``related_goals``): a word the project has already tied to this goal counts as
        # relevant even when the built-in table has no entry for it, which is how the dictionary
        # widens the judgement without a code change.
        extra = {str(item).strip() for item in hints if str(item or "").strip()}
        relevant = goal_relevant(word, goal) or any(
            token in word or word in token for token in extra if len(word) >= 2 and len(token) >= 2
        )
        centre_y = y_norm + h_norm / 2
        score = confidence
        if CONTROL_MIN_TEXT_PX * 1.2 <= box_h <= 72:
            score += 0.30
        if 1.4 <= aspect <= 7:
            score += 0.20
        if 0.30 <= centre_y <= 0.95:
            score += 0.15
        if relevant:
            score += 0.25
        rows.append(
            {
                "word": word,
                "confidence": round(confidence, 4),
                "box_norm": {
                    "x_norm": round(x_norm, 4),
                    "y_norm": round(y_norm, 4),
                    "w_norm": round(w_norm, 4),
                    "h_norm": round(h_norm, 4),
                },
                "score": round(score, 4),
                "goal_relevant": relevant,
                "basis": "OCR_BOX",
            }
        )
    rows.sort(key=lambda item: (-item["score"], -item["box_norm"]["y_norm"], item["word"]))
    return rows[:limit]

#: Safety valve on the per-run scan, not a ration.  The scan used to be rationed (two frames, then
#: every fourth), and three production cycles collected nothing while frames that carried an
#: unregistered control went by unscanned -- so the bound was re-derived from a measurement
#: instead: one cold OCR pass over a 720x1280 frame costs 0.31 s on average (0.95 s worst of 8
#: frames), a frame another layer already read costs 0.000 s through ``OCRService``'s cache, and a
#: production step is 20-40 s apart.  Scanning every step is therefore about 1% of a step, and the
#: cap exists only so a pathological frame cannot make collection the expensive part of a cycle.
MAX_SCANS_PER_RUN = 40

#: Scan every step.  Kept as a named constant because the *reason* it is 1 matters: coverage is
#: how many of the run's frames can offer a new control, and no sampling stride survived contact
#: with the data (the frames that qualified sat at steps 22-24 of one run and at 1/6/9 of others).
UI_SCAN_EVERY_STEP = 1

#: Minimum OCR confidence for a word to become a candidate.  The same bar ``find_printed_words``
#: uses for the tap path: a word that is not read well enough to tap is not read well enough to
#: remember either.
MIN_SCAN_CONFIDENCE = 0.9


def find_plain_controls(
    frame_path: Path | str,
    ocr,
    *,
    skip_words: Iterable[str] = (),
    words: Sequence[str] = PLAIN_ACTION_WORDS,
) -> list[dict]:
    """The ordinary action words on this frame that the project has never recorded.

    This is operator §二.3/§十 ("OCR 识别到新的按钮文字、页面入口或操作提示") and it is the
    collector's positive source: the failure-context cases only fire when something already went
    wrong, while this one fires whenever the client draws an ordinary action somebody has not
    written down yet -- a 领取 on a new panel, a 前往 the route has never taken.

    ``skip_words`` is what keeps it from re-collecting knowledge the project already has: the
    caller passes every word the semantic dictionary declares (whatever control they belong to)
    so a known control is never re-staged under a new name.  Exact match, like the tap path --
    a substring would collect ``我的城镇`` as ``城镇``.

    Returns ``[{"word", "box_norm", "confidence"}]``, highest confidence first per word, and an
    empty list when the frame is unreadable or names nothing new.
    """
    wanted = [str(word).strip() for word in words if str(word or "").strip()]
    if not wanted:
        return []
    skip = {str(word).strip() for word in skip_words if str(word or "").strip()}
    wanted = [word for word in wanted if word not in skip]
    if not wanted:
        return []
    frame_path = Path(frame_path)
    try:
        result = ocr.recognize(frame_path)
    except (OSError, ValueError):
        return []
    from .ocr import read_frame_size

    size = read_frame_size(frame_path)
    if not size:
        return []
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return []
    best: dict[str, dict] = {}
    for token in result.tokens:
        text = (token.text or "").strip()
        confidence = float(token.confidence or 0.0)
        if not text or not token.box or confidence < MIN_SCAN_CONFIDENCE:
            continue
        if text not in wanted:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        row = {
            "word": text,
            "confidence": round(confidence, 4),
            "box_norm": {
                "x_norm": round(min(xs) / width, 4),
                "y_norm": round(min(ys) / height, 4),
                "w_norm": round((max(xs) - min(xs)) / width, 4),
                "h_norm": round((max(ys) - min(ys)) / height, 4),
            },
        }
        if text not in best or row["confidence"] > best[text]["confidence"]:
            best[text] = row
    return sorted(best.values(), key=lambda item: item["confidence"], reverse=True)


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


# ---------------------------------------------------------- what a point may be justified by

#: The bases a point may be justified by.  All of them are taken from the **current** frame:
#: the text this frame's OCR read, the templates this project has already collected and can find
#: *here*, and a region derived from one of those text boxes by a declared offset.  A point
#: matching none of them is a coordinate nobody measured, which is what the directive forbids a
#: reasoner to supply.
BASIS_OCR_BOX = "OCR_BOX"
BASIS_TEMPLATE = "TEMPLATE"
BASIS_ANCHOR = "ANCHORED_TO_TEXT"
GROUNDING_BASES: tuple[str, ...] = (BASIS_OCR_BOX, BASIS_TEMPLATE, BASIS_ANCHOR)

#: The same bar MAA's own matcher defaults to, used when a template from the candidate library or
#: the experience ledger is matched against the current frame.
MIN_TEMPLATE_SCORE = 0.7

#: The least internal contrast (grayscale standard deviation) a template, or the region it matched,
#: must have before the match means anything.
#:
#: Normalised cross-correlation is ill-conditioned on a flat patch, and this project has a flat
#: patch on file: measured 2026-09-22, the first live dispatch's template for ``ORDINARY_CONTROL[退出]``
#: has std **2.22** -- it was cropped from a blurred transition frame -- and it "matched" another
#: transition frame at score **0.9943** in a window whose std was 2.23.  A region like that would
#: have justified a tap on a screen with nothing drawn on it.  Every crop measured from a real UI
#: screen sits at 39.5-62.1, so the bar is not close to any of them.
MIN_TEMPLATE_CONTRAST = 8.0

#: Bounds on a region *derived* from a text box.  The offset is declared rather than measured, so
#: it is the weakest of the three bases and is fenced accordingly: a region bigger than 35% of the
#: frame is a panel rather than a control, and an offset further than 20% is not "next to" the
#: anchor it names.  Both are what separates "the icon above 说明" from "somewhere else entirely".
ANCHOR_MAX_SIZE_NORM: tuple[float, float] = (0.35, 0.35)
ANCHOR_MAX_OFFSET_NORM = 0.20


def _match_ccoeff_anywhere(
    image_path: Path,
    template_path: Path,
    roi_norm: Mapping[str, float],
    *,
    margin: int = 40,
):
    """``matchers.match_ccoeff`` imported at call time, so cv2 stays off this module's import path."""
    from .matchers import match_ccoeff

    return match_ccoeff(image_path, template_path, dict(roi_norm), margin=margin)


def _contrast(image: "Image.Image") -> float:
    """Grayscale standard deviation of an image: how much there is here to recognise."""
    try:
        import numpy as np

        return float(np.asarray(image.convert("L"), dtype=np.float32).std())
    except Exception:  # noqa: BLE001 - a picture that cannot be measured is not evidence
        return 0.0


def _crop_cache(source: Path, roi: Mapping[str, float], directory: Path) -> Path | None:
    """A crop of ``roi`` inside ``source``, cached on disk under its own digest.

    ``match_ccoeff`` takes a template *file*, so an experience record's region -- which lives inside
    the frame it was measured on -- has to become one crop.  The digest in the name makes it
    idempotent, so a screen visited twenty times pays for the crop once, and the directory is the
    candidate store's own, which is where this project already keeps element crops.
    """
    box = _norm_box(roi)
    if box is None:
        return None
    material = f"{source}|{box['x_norm']},{box['y_norm']},{box['w_norm']},{box['h_norm']}"
    name = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16] + ".png"
    target = Path(directory) / name
    if target.exists():
        return target
    try:
        with Image.open(source) as image:
            width, height = image.size
            crop = image.crop((
                round(box["x_norm"] * width),
                round(box["y_norm"] * height),
                round((box["x_norm"] + box["w_norm"]) * width),
                round((box["y_norm"] + box["h_norm"]) * height),
            ))
            target.parent.mkdir(parents=True, exist_ok=True)
            crop.save(target)
    except (OSError, ValueError):
        return None
    return target


def template_regions(
    frame_path: Path | str,
    templates: Iterable[Mapping[str, Any]],
    *,
    margin: int = 40,
    min_score: float = MIN_TEMPLATE_SCORE,
    min_contrast: float = MIN_TEMPLATE_CONTRAST,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Where this project's own collected templates are drawn on the **current** frame.

    Directive §三's third and fourth sources: 当前页面适用的已有模板 and 已有控件经验与当前视觉匹配
    结果.  Both are the same mechanism -- a crop this project already holds, found on the frame in
    front of it -- and both go through ``matchers.match_ccoeff``, the normalised cross-correlation
    the vision layer already uses, rather than a second matcher written here.  That is also the
    answer to "how is a textless icon located": this project's way of locating one has always been
    a registered crop plus a matcher, never a pixel heuristic.

    Each entry names a ``template_path`` (a crop on disk) and the ``roi_norm`` its registration was
    measured at.  The match reports the bounds it *found*, not the registration, for the same reason
    the vision layer does: a tap has to land where the control is now.

    Two contrast gates stand in front of the score, and they are not decoration -- see
    ``MIN_TEMPLATE_CONTRAST``: a crop with nothing in it, and a matched window with nothing in it,
    both produce high scores on flat pictures and neither identifies anything.
    """
    frame_path = Path(frame_path)
    out: list[dict[str, Any]] = []
    try:
        with Image.open(frame_path) as image:
            width, height = image.size
            frame_image = image.convert("L")
    except (OSError, ValueError):
        return out
    if width <= 0 or height <= 0:
        return out
    for entry in templates:
        if len(out) >= limit:
            break
        template_path = Path(str(entry.get("template_path") or ""))
        roi = entry.get("roi_norm")
        if not template_path.exists() or not isinstance(roi, Mapping):
            continue
        try:
            with Image.open(template_path) as template_image:
                if _contrast(template_image) < min_contrast:
                    continue
        except (OSError, ValueError):
            continue
        try:
            found = _match_ccoeff_anywhere(frame_path, template_path, roi, margin=margin)
        except Exception:  # noqa: BLE001 - one unusable template must not lose the others
            continue
        if found is None or float(found.score) < float(min_score):
            continue
        bx, by, bw, bh = found.bounds
        if bw <= 0 or bh <= 0:
            continue
        if _contrast(frame_image.crop((bx, by, bx + bw, by + bh))) < min_contrast:
            continue
        out.append(
            {
                "text": "",
                "box_norm": {
                    "x_norm": round(bx / width, 4),
                    "y_norm": round(by / height, 4),
                    "w_norm": round(bw / width, 4),
                    "h_norm": round(bh / height, 4),
                },
                "basis": BASIS_TEMPLATE,
                "score": round(float(found.score), 4),
                "detail": {
                    "template_path": str(template_path),
                    "semantic": str(entry.get("semantic") or ""),
                    "source": str(entry.get("source") or ""),
                    "scale": float(found.scale),
                },
            }
        )
    return out


def template_entries_from_candidates(
    candidates: Iterable[Any],
    *,
    page: str = "",
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Candidate records that can act as a template *on this page*: a crop, and where it was seen.

    The page filter is the directive's own (§四/§九 elsewhere): the same-looking icon on two pages
    is two different controls, so a template collected on MAP is not evidence about EVENT.
    """
    wanted = str(page or "").strip()
    out: list[dict[str, Any]] = []
    for record in candidates:
        if len(out) >= limit:
            break
        record_page = str(getattr(record, "page", "") or "")
        if wanted and record_page and record_page != wanted:
            continue
        image_path = Path(str(getattr(record, "image_path", "") or ""))
        bbox = getattr(record, "bbox", None)
        if not image_path.exists() or not isinstance(bbox, Mapping) or not bbox:
            continue
        roi = _norm_box(bbox)
        if roi is None:
            continue
        out.append(
            {
                "template_path": str(image_path),
                "roi_norm": roi,
                "semantic": str(getattr(record, "semantic_id", "") or ""),
                "source": "CANDIDATE",
            }
        )
    return out


def template_entries_from_experience(
    experiences: Iterable[Any],
    *,
    page: str = "",
    limit: int = 4,
    cache_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Ledger records whose own measured crop can be found on this frame (§三's fourth source).

    An L1 registration carries the frame it was measured on and the box inside it, which together
    *are* a template -- the region the project proved was a control.  The crop is materialised on
    demand (``_crop_cache``) because the matcher takes a file, and it is cached by digest so a
    screen visited repeatedly does not re-cut the same region.

    A correction worth stating: this used to hand the matcher the *source frame* as the template,
    which would have searched for a whole 720x1280 screenshot inside a 40 px window of another one.
    Nothing could ever have matched, so the source was quietly useless -- found by running it, not
    by reading it.
    """
    wanted = str(page or "").strip()
    directory = Path(cache_dir) if cache_dir else TEMPLATE_DIR / "experience_crops"
    out: list[dict[str, Any]] = []
    for record in experiences:
        if len(out) >= limit:
            break
        record_page = str(getattr(record, "page", "") or "")
        if wanted and record_page and record_page != wanted:
            continue
        features = getattr(record, "visual_features", None)
        if not isinstance(features, Mapping):
            continue
        box = features.get("box_norm")
        frame = Path(str(features.get("read_from_frame") or ""))
        roi = _norm_box(box) if isinstance(box, Mapping) else None
        if roi is None or not frame.exists():
            continue
        crop = _crop_cache(frame, roi, directory)
        if crop is None:
            continue
        out.append(
            {
                "template_path": str(crop),
                "roi_norm": roi,
                "semantic": str(getattr(record, "control", "") or ""),
                "source": "EXPERIENCE",
            }
        )
    return out


def anchored_region(
    anchor: Mapping[str, Any],
    regions: Iterable[Mapping[str, Any]],
    *,
    limit: int = 40,
) -> dict[str, Any] | None:
    """The region a reasoner derived from a text box this frame really drew, or ``None``.

    This is the third basis of §三, and it exists because two real cases have no other evidence.
    The 燃霜矿区 event page has four textless icons (说明/奖励/指南/历史排名) that each sit directly
    above their own label, and the quick panel's rows each have a blue arrow at the row's right
    edge.  A template only covers such an element *after* somebody has collected it; an OCR box
    covers the label and not the icon.  What a person says is "the icon above 说明", and that is
    exactly what this resolves: an anchor text, plus the offset of the element's centre from the
    anchor's centre.

    What keeps it honest is that the anchor is **measured** and the offset is **bounded**.  The
    anchor text has to be among the words this frame's OCR read -- a text the frame does not draw
    resolves to nothing -- and the derived region is refused when it is larger than a control or
    further from its anchor than "next to" can mean (``ANCHOR_MAX_SIZE_NORM``,
    ``ANCHOR_MAX_OFFSET_NORM``).  The basis is recorded as ANCHORED_TO_TEXT rather than as a
    measurement, so the weaker evidence never masquerades as the stronger.

    What it does **not** guarantee, measured on the real 燃霜矿区 frame while writing this: the
    offset is the reasoner's, so this basis promises a bounded neighbourhood of a word the frame
    drew and *not* that something is drawn in that neighbourhood.  An offset of -0.056 above 奖励
    lands in the gap between two rows of icons and resolves just as happily as the -0.030 that
    lands squarely on the gift; this module cannot tell the two apart (see the note below on why a
    pixel test for it was written and removed).  The bound on the damage is the step's own verifier:
    a tap on empty background changes nothing, the step fails honestly, and no L1 action is
    registered from it.  That is why the offset is the reasoner's to declare and not this module's
    to guess.
    """
    text = str(anchor.get("text") or "").strip()
    if not text:
        return None
    source: dict[str, Any] | None = None
    for region in regions:
        candidate_text = str(region.get("text") or "").strip()
        if not candidate_text:
            continue
        if candidate_text == text or text in candidate_text:
            source = dict(region)
            break
        if limit <= 0:
            break
        limit -= 1
    if source is None:
        return None
    box = _norm_box(source.get("box_norm"))
    if box is None:
        return None
    try:
        dx = float(anchor.get("dx_norm") or 0.0)
        dy = float(anchor.get("dy_norm") or 0.0)
    except (TypeError, ValueError):
        return None
    if abs(dx) > ANCHOR_MAX_OFFSET_NORM or abs(dy) > ANCHOR_MAX_OFFSET_NORM:
        return None
    try:
        w = float(anchor["w_norm"]) if anchor.get("w_norm") is not None else box["w_norm"]
        h = float(anchor["h_norm"]) if anchor.get("h_norm") is not None else box["h_norm"]
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    if w > ANCHOR_MAX_SIZE_NORM[0] or h > ANCHOR_MAX_SIZE_NORM[1]:
        return None
    centre_x = box["x_norm"] + box["w_norm"] / 2 + dx
    centre_y = box["y_norm"] + box["h_norm"] / 2 + dy
    x_norm = centre_x - w / 2
    y_norm = centre_y - h / 2
    if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
        return None
    w = min(w, 1.0 - x_norm)
    h = min(h, 1.0 - y_norm)
    if w <= 0 or h <= 0:
        return None
    return {
        "text": "",
        "box_norm": {
            "x_norm": round(x_norm, 4),
            "y_norm": round(y_norm, 4),
            "w_norm": round(w, 4),
            "h_norm": round(h, 4),
        },
        "basis": BASIS_ANCHOR,
        "score": 0.0,
        "detail": {
            "anchor_text": str(source.get("text") or ""),
            "anchor_box": box,
            "offset": [round(dx, 4), round(dy, 4)],
        },
    }


def grounding_regions(
    frame_path: Path | str,
    ocr,
    *,
    skip_words: Iterable[str] = (),
    limit: int = 200,
) -> list[dict[str, Any]]:
    """The text regions of this frame, as the basis every other source is checked against.

    One call, one answer to "what words did this frame actually draw".  Template regions are
    produced by :func:`template_regions` and anchored regions by :func:`anchored_region`; both are
    appended by the caller, which is what keeps this function free of any knowledge about where
    templates live or what a reasoner asked for.
    """
    frame_path = Path(frame_path)
    try:
        from .ocr import read_frame_size
    except ImportError:  # pragma: no cover
        return []
    try:
        size = read_frame_size(frame_path)
    except (OSError, ValueError):
        return []
    if not size or int(size[0]) <= 0 or int(size[1]) <= 0:
        return []
    width, height = int(size[0]), int(size[1])
    skip = {str(word).strip() for word in skip_words if str(word or "").strip()}
    regions: list[dict[str, Any]] = []
    try:
        result = ocr.recognize(frame_path)
    except (OSError, ValueError, AttributeError):
        result = None
    if result is None:
        return regions
    for token in result.tokens:
        text = (token.text or "").strip()
        if not text or not token.box or text in skip:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        w_px = max(xs) - min(xs)
        h_px = max(ys) - min(ys)
        if w_px <= 0 or h_px <= 0:
            continue
        regions.append(
            {
                "text": text,
                "box_norm": {
                    "x_norm": round(min(xs) / width, 4),
                    "y_norm": round(min(ys) / height, 4),
                    "w_norm": round(w_px / width, 4),
                    "h_norm": round(h_px / height, 4),
                },
                "basis": BASIS_OCR_BOX,
                "score": round(float(token.confidence or 0.0), 4),
                "detail": {},
            }
        )
        if len(regions) >= limit:
            break
    return regions


#: Why there is no fourth basis here.  Directive §三 lists 当前帧视觉元素 bbox, and a pixel-level
#: detector for it was written, measured on the real frames, and **removed** because its own
#: measurements refused it:
#:
#:   * on the 燃霜矿区 event page, a 9%-window blob test reported an "element" at 138 of 289 grid
#:     points -- the volcanic artwork behind the panel is as textured as the icons in front of it;
#:   * the gates that were meant to separate them (surround spread, contour circularity, fill of the
#:     component's own box) measured the two populations as *overlapping*: surround spread 22.8-84.0
#:     for real icons against 26.6-85.6 for artwork, and every large component's contour is clipped
#:     by its own window, which makes circularity 0.0 for both;
#: * a flat-surface test at 12-50% windows overlapped as well (icons 0.11-0.65, artwork 0.14-0.39).
#:
#: So the honest statement is that this module can measure *text* and it can match *crops*, and it
#: cannot tell a textless control from a picture.  A textless control is therefore located the way
#: this project has always located one -- a registered template found on the frame (§三's third and
#: fourth sources, both shipped here) or a region anchored to a text box the frame really drew
#: (``anchored_region``) -- and never by a guess about pixels.  MAA's own ColorMatch / FeatureMatch
#: recognitions are the engine-side way to find a textless element and are named in the delivery
#: notes as the next step, not claimed here as done.


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


# 

# ---------------------------------------------------------------------------------------------
# Element identities, and the icon+label control (operator directive 2026-09-25)
#
# The break this section fixes, measured on the city HUD: the client draws an activity icon with
# its name printed **underneath**.  The element table was built from OCR text boxes, so the label
# box became the element and the tap landed on the text instead of on the control above it
# (``SEMANTIC_TARGET_IS_A_LABEL_NOT_A_CONTROL``).  The model had chosen the right semantic; the
# geometry was wrong, and the geometry is this module's job.
#
# Constitution B §25.1 gives the four identities, and §25.2 requires a state to be derived from
# elements **and their relations**.  An icon and the label under it are exactly such a relation, so
# the control is *one* element with *one* semantic id -- not two boxes and a guess.
#
# What the gate measures, and why it is not a colour test
# ------------------------------------------------------
# The first version of this gate asked whether the band above a label was "vivid", i.e. saturated.
# Measured on 80 real frames it *failed on its own positive*: the 登录好礼 control is a white-and-blue
# calendar, so `sat_delta` came out at -0.01 while a red gift icon scored +0.31.  Colourfulness is a
# property of one icon, not of controls.  Two other framings were rejected the same way:
#
#   * raw edge strength -- the band scored *below* the terrain beside it (edge_ratio 0.68), because
#     map artwork is textured everywhere and a flat icon interior is smooth;
#   * an absolute whole-frame blob test -- this module already records why that failed (the volcanic
#     artwork behind a panel is as textured as the icons; 138 of 289 grid points reported).
#
# What is left is the shape relation, which is what a control actually is: **a compact block that
# differs from the background of its own label's row, is centred on the label, and sits directly
# above it.**  Everything is measured against the label's own surroundings on the *same* frame, so
# terrain, lighting and artwork cancel out; and "compact + centred + adjacent" is precisely what
# separates an icon from a town name's terrain.
#
# What is measured and what is knowledge
# --------------------------------------
# The clickable region is always measured on the **current** frame (constitution A §24).  The
# registry stores the *relation* -- "this printed word names a control, and the control is a compact
# block directly above it" -- plus the identity.  A stored offset would be the forbidden thing; a
# stored relation is what §24.4 allows long-term knowledge to keep.
# ---------------------------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: §25.1's four identities.  ``TEXT_LABEL`` is what the client printed; ``ICON`` is artwork with no
#: words; ``INTERACTIVE_CONTROL`` is a drawn control carrying its own words (a 领取 button);
#: ``COMPOSITE_CONTROL`` is an icon whose meaning is its label -- the case this section adds.
ELEMENT_TEXT_LABEL = "TEXT_LABEL"
ELEMENT_ICON = "ICON"
ELEMENT_INTERACTIVE_CONTROL = "INTERACTIVE_CONTROL"
ELEMENT_COMPOSITE_CONTROL = "COMPOSITE_CONTROL"

#: Only these may be offered to a planner as a ``CLICK_ELEMENT`` target.  A ``TEXT_LABEL`` is
#: information -- a town name, a resource count -- and offering it as a button is the failure this
#: section exists to prevent.
EXECUTABLE_ELEMENT_KINDS = frozenset({ELEMENT_INTERACTIVE_CONTROL, ELEMENT_COMPOSITE_CONTROL})

#: Two more bases, so a reader can tell how a point was justified.
#: ``TEMPLATE_LABEL`` is the strongest: this project's own crop was found on this frame *and* the
#: label that names it is here.  ``ANCHORED_TO_TEXT_VERIFIED`` is the upgrade of ``BASIS_ANCHOR``:
#: the bounded neighbourhood an anchor declares was additionally *measured* to contain a compact
#: drawn block, which is exactly what the original basis could not promise (see its own note on the
#: 燃霜矿区 gap between two rows of icons).
BASIS_TEMPLATE_LABEL = "TEMPLATE_LABEL"
BASIS_VERIFIED_ANCHOR = "ANCHORED_TO_TEXT_VERIFIED"

#: Where the label→control relation is kept between runs.
ICON_CONTROL_REGISTRY = Path("knowledge/ui/icon_label_controls.json")

#: The band searched above a label: this many label-heights tall (capped), padded sideways by this
#: fraction of the label's width.  A bound, not a position -- it names the control's own row.
BAND_HEIGHT_RATIO = 1.6
BAND_HEIGHT_MAX_NORM = 0.075
BAND_WIDTH_PAD_RATIO = 0.18
BAND_MIN_SIDE_PX = 14

#: --- the gate -------------------------------------------------------------------------------
#:
#: ``MARGIN_FRACTION`` picks the band's own left/right margins as the background reference: they are
#: the same rows as the block, so lighting and terrain are shared.
MARGIN_FRACTION = 0.14
#: A pixel belongs to the block when its colour is this far from that reference, as a fraction of
#: the largest possible RGB distance.  The threshold is relative (median + a share of the range) with
#: an absolute floor, so a flat band cannot manufacture a block out of its own noise.
CONTROL_DIST_FLOOR = 0.10
CONTROL_DIST_RELATIVE = 0.45
#: The block's own shape, all measured against the label it belongs to.
CONTROL_PROFILE_FLOOR = 0.25          # a column/row joins the block at a quarter of its peak
CONTROL_MIN_BLOCK_FILL = 0.40         # a solid block, not scattered texture
CONTROL_MIN_WIDTH_RATIO = 0.30        # of the label's width
CONTROL_MAX_WIDTH_RATIO = 2.20        # of the label's width -- wider means terrain, not a control
CONTROL_MAX_CENTER_OFFSET = 0.60      # of the label's width, block centre vs label centre
CONTROL_MAX_GAP_RATIO = 1.40          # of the label's height, block bottom to label top
CONTROL_BOX_MAX_AREA_NORM = 0.045     # of the frame
#: How much of the recovered block may sit on words some other label printed.  A control is
#: artwork; ``_overlaps_text`` records the countdown row this refuses.
TEXT_OVERLAP_MAX = 0.25


def band_above_label(
    box_norm: Mapping[str, float], frame: tuple[int, int]
) -> tuple[int, int, int, int] | None:
    """The pixel rect above a label box, bounded to the control's own row (see the constants)."""
    try:
        width, height = int(frame[0]), int(frame[1])
        x = float(box_norm["x_norm"])
        y = float(box_norm["y_norm"])
        w = float(box_norm["w_norm"])
        h = float(box_norm["h_norm"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return None
    pad = w * BAND_WIDTH_PAD_RATIO
    band_h_norm = min(max(h * BAND_HEIGHT_RATIO, 0.028), BAND_HEIGHT_MAX_NORM)
    left = int(round(max(0.0, x - pad) * width))
    right = int(round(min(1.0, x + w + pad) * width))
    top = int(round(max(0.0, y - band_h_norm) * height))
    bottom = int(round(max(0.0, y - 0.002) * height))
    if right - left < BAND_MIN_SIDE_PX or bottom - top < BAND_MIN_SIDE_PX:
        return None
    return left, top, right, bottom


def region_structure(image: "Image.Image", rect: Sequence[int]) -> dict[str, float]:
    """Four descriptive terms for a region -- recorded as evidence, never used as the gate.

    ``edge``, ``sat``, ``vivid`` and ``contrast``.  They travel in the element's ``detail`` so a
    later reader (and the calibration probe) can see *why* a band was accepted or refused, and they
    are deliberately **not** what decides: this module's own measurement showed a saturation gate
    refusing its own positive.
    """
    try:
        import numpy as np
        from PIL import ImageFilter

        left, top, right, bottom = (int(value) for value in rect)
        if right - left < 1 or bottom - top < 1:
            return {"edge": 0.0, "sat": 0.0, "vivid": 0.0, "contrast": 0.0}
        patch = image.crop((left, top, right, bottom)).convert("RGB")
        gray = np.asarray(patch.convert("L"), dtype=np.float32)
        edge = np.asarray(patch.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
        rgb = np.asarray(patch, dtype=np.float32) / 255.0
        biggest = rgb.max(axis=2)
        smallest = rgb.min(axis=2)
        with np.errstate(divide="ignore", invalid="ignore"):
            sat = np.where(biggest > 0.0, (biggest - smallest) / np.maximum(biggest, 1e-6), 0.0)
        return {
            "edge": round(float(edge.mean()) / 255.0, 4),
            "sat": round(float(sat.mean()), 4),
            "vivid": round(float((sat > 0.66).mean()), 4),
            "contrast": round(float(gray.std()) / 255.0, 4),
        }
    except Exception:  # noqa: BLE001 - a picture that cannot be measured is not evidence
        return {"edge": 0.0, "sat": 0.0, "vivid": 0.0, "contrast": 0.0}


def _longest_run(profile: Any, floor: float) -> tuple[int, int]:
    """The longest contiguous run of ``profile`` at or above ``floor``, as ``(lo, hi)``."""
    values = [float(value) for value in profile]
    best = (0, 0)
    start: int | None = None
    for index, value in enumerate(values):
        if value >= floor and start is None:
            start = index
        elif value < floor and start is not None:
            if index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    if start is not None and len(values) - start > best[1] - best[0]:
        best = (start, len(values))
    return best


def _row_background(
    image: "Image.Image", span: tuple[int, int], label_row: tuple[int, int] | None
) -> "Any":
    """The dominant colour of the label's own row beside its text, used as the band's reference."""
    import numpy as np

    left, right = int(span[0]), int(span[1])
    if label_row is None:
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)
    top, bottom = int(label_row[0]), int(label_row[1])
    top = max(0, min(top, image.size[1] - 1))
    bottom = max(top + 1, min(bottom, image.size[1]))
    strip = np.asarray(image.crop((left, top, right, bottom)).convert("RGB"), dtype=np.float32)
    if strip.size == 0:
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)
    width = strip.shape[1]
    margin = max(2, int(width * MARGIN_FRACTION))
    sides = np.concatenate([strip[:, :margin], strip[:, width - margin:]], axis=1).reshape(-1, 3)
    return np.median(sides, axis=0)


def _overlaps_text(box_norm: Mapping[str, float], text_boxes: Iterable[Mapping[str, Any]]) -> str:
    """A printed word the block sits on, other than the label that named it, or ``""``.

    This refuses "text above text".  Measured: a countdown row (``13:03:32``) has its own HUD title
    printed directly above it, so the block recovered from that band *was* the title -- a perfectly
    compact block, and not a control.  A control is artwork; if the region a tap would land on is
    something OCR read as words, it is a label and it is refused.
    """
    x, y = float(box_norm["x_norm"]), float(box_norm["y_norm"])
    w, h = float(box_norm["w_norm"]), float(box_norm["h_norm"])
    area = max(w * h, 1e-9)
    for other in text_boxes:
        ox, oy = float(other.get("x_norm", 0.0)), float(other.get("y_norm", 0.0))
        ow, oh = float(other.get("w_norm", 0.0)), float(other.get("h_norm", 0.0))
        overlap_w = max(0.0, min(x + w, ox + ow) - max(x, ox))
        overlap_h = max(0.0, min(y + h, oy + oh) - max(y, oy))
        if overlap_w * overlap_h / area > TEXT_OVERLAP_MAX:
            return str(other.get("text") or "")
    return ""


def _block_in_band(
    image: "Image.Image",
    rect: Sequence[int],
    *,
    label_row: tuple[int, int] | None = None,
) -> tuple[dict[str, float], dict[str, Any]] | None:
    """The compact block that differs from its own row's background, or ``None``.

    Returns the block as ``(box_norm, detail)``.  The background reference is the band's own left
    and right margins -- same rows, same lighting -- so the comparison cannot be fooled by the map
    behind it, which is what sank both the saturation gate and the whole-frame blob test.
    """
    try:
        import numpy as np

        left, top, right, bottom = (int(value) for value in rect)
        width, height = right - left, bottom - top
        if width < BAND_MIN_SIDE_PX or height < BAND_MIN_SIDE_PX:
            return None
        patch = np.asarray(image.crop((left, top, right, bottom)).convert("RGB"), dtype=np.float32)
        # The background reference is the **label's own row**, not this band's margins, and the
        # difference is not cosmetic -- it was why the first version missed its own positives.
        # Measured on the 登录好礼 control: the icon is *wider* than the label under it, so a margin
        # taken inside the band lands on the icon itself, the reference becomes the icon's colour,
        # and only the outline and the digits differ from it -- the recovered block came out
        # narrower than its own label (25 of 80 frames refused BLOCK_NARROWER_THAN_A_CONTROL).
        # The row a control sits directly above cannot contain the control, shares its lighting, and
        # is exactly the comparison a person makes when they say "the icon above the word".
        reference = _row_background(image, (left, right), label_row)
        distance = np.linalg.norm(patch - reference, axis=2) / (255.0 * 3.0 ** 0.5)
        median = float(np.median(distance))
        peak = float(np.percentile(distance, 99.0))
        threshold = max(CONTROL_DIST_FLOOR, median + CONTROL_DIST_RELATIVE * (peak - median))
        mask = distance >= threshold
        if not bool(mask.any()):
            return None
        cols = mask.mean(axis=0)
        rows = mask.mean(axis=1)
        col_lo, col_hi = _longest_run(cols, CONTROL_PROFILE_FLOOR * float(cols.max()))
        row_lo, row_hi = _longest_run(rows, CONTROL_PROFILE_FLOOR * float(rows.max()))
        if col_hi - col_lo < 2 or row_hi - row_lo < 2:
            return None
        block = mask[row_lo:row_hi, col_lo:col_hi]
        fill = float(block.mean()) if block.size else 0.0
        frame_w, frame_h = image.size
        box_norm = {
            "x_norm": round((left + col_lo) / frame_w, 4),
            "y_norm": round((top + row_lo) / frame_h, 4),
            "w_norm": round((col_hi - col_lo) / frame_w, 4),
            "h_norm": round((row_hi - row_lo) / frame_h, 4),
        }
        detail = {
            "block_px": [left + col_lo, top + row_lo, left + col_hi, top + row_hi],
            "band_px": [left, top, right, bottom],
            "threshold": round(threshold, 4),
            "distance_median": round(median, 4),
            "distance_p99": round(peak, 4),
            "block_fill": round(fill, 4),
            "band": region_structure(image, rect),
        }
        return box_norm, detail
    except Exception:  # noqa: BLE001
        return None


def control_block_above_label(
    frame_path: Path | str,
    label_box: Mapping[str, float],
    *,
    label: str = "",
    frame: tuple[int, int] | None = None,
    image: "Image.Image | None" = None,
    text_boxes: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """The measured clickable region of the control named by a printed label, or ``None``.

    ``None`` is a real answer and the important one: a town name, a resource count and a caption all
    have terrain above them, and each of those must stay a ``TEXT_LABEL`` rather than become a
    button.  The refusals are the mechanism -- without them a bounded offset would be a plausible
    guess dressed up as a measurement, which is what the previous round's failure actually was.

    Every requirement is a relation between the block and the label it belongs to (compact, about
    the label's width, centred on it, just above it).  None of them is a position on the screen.
    """
    from .ocr import read_frame_size

    frame_path = Path(frame_path)
    size = frame if frame else read_frame_size(frame_path)
    if not size:
        return None
    rect = band_above_label(label_box, size)
    if rect is None:
        return None
    opened = image
    owns = False
    try:
        if opened is None:
            with Image.open(frame_path) as handle:
                opened = handle.convert("RGB")
            owns = True
        label_row = (
            int(round(float(label_box["y_norm"]) * int(size[1]))),
            int(round((float(label_box["y_norm"]) + float(label_box["h_norm"])) * int(size[1]))),
        )
        found = _block_in_band(opened, rect, label_row=label_row)
        if found is None:
            return None
        box_norm, detail = found
        overlapping = _overlaps_text(box_norm, text_boxes)
        frame_w, frame_h = int(size[0]), int(size[1])
        label_w = float(label_box["w_norm"]) * frame_w
        label_h = float(label_box["h_norm"]) * frame_h
        label_cx = (float(label_box["x_norm"]) + float(label_box["w_norm"]) / 2) * frame_w
        label_top = float(label_box["y_norm"]) * frame_h
        block_w = box_norm["w_norm"] * frame_w
        block_h = box_norm["h_norm"] * frame_h
        block_cx = (box_norm["x_norm"] + box_norm["w_norm"] / 2) * frame_w
        block_bottom = (box_norm["y_norm"] + box_norm["h_norm"]) * frame_h
        checks = {
            "fill": detail["block_fill"],
            "width_ratio": block_w / max(label_w, 1e-6),
            "center_offset_ratio": abs(block_cx - label_cx) / max(label_w, 1e-6),
            "gap_ratio": max(0.0, label_top - block_bottom) / max(label_h, 1e-6),
            "area_norm": box_norm["w_norm"] * box_norm["h_norm"],
            "min_side_px": min(block_w, block_h),
        }
        refusals: list[str] = []
        if checks["min_side_px"] < MIN_ELEMENT_SIDE_PX:
            refusals.append("BLOCK_TOO_SMALL")
        if checks["fill"] < CONTROL_MIN_BLOCK_FILL:
            refusals.append("BLOCK_NOT_SOLID")
        if checks["width_ratio"] < CONTROL_MIN_WIDTH_RATIO:
            refusals.append("BLOCK_NARROWER_THAN_A_CONTROL")
        if checks["width_ratio"] > CONTROL_MAX_WIDTH_RATIO:
            refusals.append("BLOCK_WIDER_THAN_A_CONTROL")
        if checks["center_offset_ratio"] > CONTROL_MAX_CENTER_OFFSET:
            refusals.append("BLOCK_NOT_CENTRED_ON_LABEL")
        if checks["gap_ratio"] > CONTROL_MAX_GAP_RATIO:
            refusals.append("BLOCK_NOT_ADJACENT_TO_LABEL")
        if checks["area_norm"] > CONTROL_BOX_MAX_AREA_NORM:
            refusals.append("BLOCK_TOO_LARGE_TO_BE_A_CONTROL")
        if overlapping:
            refusals.append(f"BLOCK_IS_PRINTED_TEXT:{overlapping}")
        detail["checks"] = {key: round(float(value), 4) for key, value in checks.items()}
        if refusals:
            detail["refused"] = refusals
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    finally:
        if owns and opened is not None:
            try:
                opened.close()
            except Exception:  # noqa: BLE001
                pass
    return {
        "box_norm": box_norm,
        "icon_box_norm": box_norm,
        "label_box_norm": {
            key: round(float(label_box[key]), 4)
            for key in ("x_norm", "y_norm", "w_norm", "h_norm")
            if key in label_box
        },
        "basis": BASIS_VERIFIED_ANCHOR,
        "confidence": round(
            min(1.0, 0.5 + 0.5 * min(1.0, detail["checks"]["fill"] / max(CONTROL_MIN_BLOCK_FILL, 1e-6))),
            4,
        ),
        "detail": detail,
    }


#: How the search window above a label is derived from the label's own box: this many label-widths
#: either side, and this many label-heights above.  A **search region**, never a click target --
#: §24.3 allows a bounded area to make recognition cheap and forbids treating that area as the
#: thing to click.  The tap comes from where the matcher finds the crop, which is why this window
#: may be generous.
SEARCH_SIDE_RATIO = 0.35
SEARCH_ABOVE_RATIO = 3.2


def search_region_above_label(
    box_norm: Mapping[str, float], frame: tuple[int, int]
) -> dict[str, float] | None:
    """The bounded window above a label in which this project looks for its control's crop."""
    try:
        width, height = int(frame[0]), int(frame[1])
        x = float(box_norm["x_norm"])
        y = float(box_norm["y_norm"])
        w = float(box_norm["w_norm"])
        h = float(box_norm["h_norm"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return None
    left = max(0.0, x - w * SEARCH_SIDE_RATIO)
    right = min(1.0, x + w + w * SEARCH_SIDE_RATIO)
    top = max(0.0, y - h * SEARCH_ABOVE_RATIO)
    bottom = min(1.0, y + h)
    if right - left <= 0 or bottom - top <= 0:
        return None
    return {
        "x_norm": round(left, 4),
        "y_norm": round(top, 4),
        "w_norm": round(right - left, 4),
        "h_norm": round(bottom - top, 4),
    }


def registered_icon_region(
    frame_path: Path | str,
    label_box: Mapping[str, float],
    *,
    template_path: Path | str,
    frame: tuple[int, int] | None = None,
    min_score: float = MIN_TEMPLATE_SCORE,
    min_contrast: float = MIN_TEMPLATE_CONTRAST,
) -> dict[str, Any] | None:
    """Where this project's own crop for a control is drawn on the **current** frame, or ``None``.

    This is the project's documented way to locate an icon -- "a registered crop plus a matcher,
    never a pixel heuristic" (see the note above ``template_regions``) -- and it is what replaced the
    geometric gate for registered controls.  Why it had to: the gate was calibrated against 136 real
    positives and 1832 real negatives and **could not separate them** (37% of positives accepted,
    39% of negatives accepted; the full measurement is in
    ``dataset/truth_audit/icon_label_controls/samples.json`` and the calibration tool prints it).
    A gate like that would have produced buttons out of terrain.

    What the matcher guarantees and the geometry did not: the template is a crop of the real control
    taken from a real frame, so a match *is* the control, and `cv2.TM_CCOEFF_NORMED` plus a contrast
    floor is this project's already-used calibration.  The stored artifact is a **picture**, not a
    coordinate -- the position still comes from matching the frame in front of the run.
    """
    from .ocr import read_frame_size

    frame_path = Path(frame_path)
    size = frame if frame else read_frame_size(frame_path)
    if not size:
        return None
    template = Path(template_path)
    if not template.is_file():
        return None
    try:
        with Image.open(template) as handle:
            if _contrast(handle) < min_contrast:
                # A crop with nothing in it scores high on flat pictures and identifies nothing.
                return None
    except (OSError, ValueError):
        return None
    roi = search_region_above_label(label_box, size)
    if roi is None:
        return None
    try:
        found = _match_ccoeff_anywhere(frame_path, template, roi)
    except Exception:  # noqa: BLE001 - an unusable template must not fail a step
        return None
    if found is None or float(found.score) < float(min_score):
        return None
    bx, by, bw, bh = found.bounds
    frame_w, frame_h = int(size[0]), int(size[1])
    if bw <= 0 or bh <= 0:
        return None
    box_norm = {
        "x_norm": round(bx / frame_w, 4),
        "y_norm": round(by / frame_h, 4),
        "w_norm": round(bw / frame_w, 4),
        "h_norm": round(bh / frame_h, 4),
    }
    return {
        "box_norm": box_norm,
        "icon_box_norm": box_norm,
        "label_box_norm": {
            key: round(float(label_box[key]), 4)
            for key in ("x_norm", "y_norm", "w_norm", "h_norm")
            if key in label_box
        },
        "basis": BASIS_TEMPLATE_LABEL,
        "confidence": round(float(found.score), 4),
        "detail": {
            "matched_by": "TEMPLATE",
            "template_path": str(template),
            "score": round(float(found.score), 4),
            "search_roi_norm": roi,
            "matched_px": [int(bx), int(by), int(bw), int(bh)],
        },
    }


def load_control_registry(root: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """The labels known to name a control that sits directly above them, by printed word.

    **Identity and relation, never a coordinate.**  Each record says which printed word names a
    control, which semantic id it gets, which pages it is drawn on, and where the control sits *in
    relation to* the label.  The tap position is measured on the frame in front of the run, every
    run -- §24.2 forbids the alternative, and §24.4 is explicit that long-term knowledge may hold
    relations but not click targets.
    """
    base = Path(root) if root else PROJECT_ROOT
    path = base / ICON_CONTROL_REGISTRY
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    controls = payload.get("controls")
    if not isinstance(controls, Mapping):
        return {}
    return {
        str(label): dict(record)
        for label, record in controls.items()
        if isinstance(record, Mapping)
    }


def composite_controls(
    frame_path: Path | str,
    ocr,
    *,
    page: str = "",
    skip_words: Iterable[str] = (),
    registry: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Every icon+label control this frame draws, one element per printed function name.

    Only labels the record knows are considered, which keeps the gate from becoming a general
    "guess a button" search: a name has to be on record as one that names a control, and then the
    *geometry* is measured here.  A label the record does not list is still reported by
    ``build_element_table`` -- as a ``TEXT_LABEL``, which is what a town name is.
    """
    from .ocr import read_frame_size

    frame_path = Path(frame_path)
    size = read_frame_size(frame_path)
    if not size:
        return []
    known = dict(registry) if registry is not None else load_control_registry()
    if not known:
        return []
    skip = {str(word).strip() for word in skip_words if str(word or "").strip()}
    out: list[dict[str, Any]] = []
    try:
        with Image.open(frame_path) as handle:
            image = handle.convert("RGB")
    except (OSError, ValueError):
        return []
    try:
        regions = grounding_regions(frame_path, ocr)
        text_boxes = [
            {"text": str(r.get("text") or ""), **dict(r.get("box_norm") or {})} for r in regions
        ]
        for region in regions:
            text = str(region.get("text") or "").strip()
            if not text or text in skip:
                continue
            record = known.get(text)
            if record is None:
                continue
            pages = record.get("pages")
            if isinstance(pages, (list, tuple)) and pages and page and page not in pages:
                continue
            label_box = dict(region.get("box_norm") or {})
            others = [box for box in text_boxes if box.get("text") != text]
            # A registered crop is the strongest evidence and is tried first: a match *is* the
            # control.  Only when the record carries no template does the measured-block gate run,
            # and that path is explicitly marked on the element so a reader can tell the two apart.
            measured = None
            template_path = record.get("template_path")
            if template_path:
                resolved = Path(str(template_path))
                if not resolved.is_absolute():
                    resolved = Path(PROJECT_ROOT) / resolved
                measured = registered_icon_region(
                    frame_path, label_box, template_path=resolved, frame=size
                )
            if measured is None and record.get("allow_measured_block", False):
                measured = control_block_above_label(
                    frame_path, label_box, label=text, frame=size, image=image, text_boxes=others
                )
            if measured is None:
                continue
            out.append({
                "label": text,
                "text": text,
                "semantic": str(record.get("semantic") or f"CONTROL[{text}]"),
                "kind": ELEMENT_COMPOSITE_CONTROL,
                "box_norm": measured["box_norm"],
                "icon_box_norm": measured["icon_box_norm"],
                "label_box_norm": measured["label_box_norm"],
                "basis": measured["basis"],
                "confidence": measured["confidence"],
                "detail": measured["detail"],
                "source": str(record.get("source") or "REGISTRY"),
            })
            if len(out) >= limit:
                break
    finally:
        image.close()
    return out


def build_element_table(
    frame_path: Path | str,
    ocr,
    *,
    page: str = "",
    skip_words: Iterable[str] = (),
    registry: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """This frame's elements, typed, with the region a tap must use.

    One function for both consumers, deliberately: the planner chooses an ``id`` from this table and
    the executor resolves that same ``id`` against the *same* table, so "the model and the executor
    use one frame" is a property of the code rather than a hope.  A table built twice could drift,
    and a drift here is a tap on a stale position.

    Ordering is significant: composite controls come **first**, so a caller that grounds an answer by
    the label's own words resolves them to the control's region rather than to the label's text box.
    That ordering is the fix for ``SEMANTIC_TARGET_IS_A_LABEL_NOT_A_CONTROL``.
    """
    frame_path = Path(frame_path)
    from .ocr import read_frame_size

    if not read_frame_size(frame_path):
        return []
    skip = {str(word).strip() for word in skip_words if str(word or "").strip()}
    entries: list[dict[str, Any]] = []
    for control in composite_controls(
        frame_path, ocr, page=page, skip_words=skip, registry=registry
    ):
        entries.append({
            "id": "",
            "kind": ELEMENT_COMPOSITE_CONTROL,
            "text": control["text"],
            "semantic": control["semantic"],
            "box_norm": control["box_norm"],
            "icon_box_norm": control.get("icon_box_norm"),
            "label_box_norm": control.get("label_box_norm"),
            "basis": control["basis"],
            "confidence": control["confidence"],
            "detail": control.get("detail") or {},
            "executable": True,
            "expected": "",
        })
    control_labels = {entry["text"] for entry in entries}
    for region in grounding_regions(frame_path, ocr, skip_words=skip):
        text = str(region.get("text") or "").strip()
        if not text:
            continue
        entries.append({
            "id": "",
            "kind": ELEMENT_TEXT_LABEL,
            "text": text,
            "semantic": f"TEXT[{text}]",
            "box_norm": dict(region.get("box_norm") or {}),
            "icon_box_norm": None,
            "label_box_norm": None,
            "basis": str(region.get("basis") or BASIS_OCR_BOX),
            "confidence": float(region.get("score") or 0.0),
            "detail": dict(region.get("detail") or {}),
            # A printed word is information.  It is executable only when this frame also measured a
            # control for it, which is exactly what ``control_labels`` records.
            "executable": text in control_labels,
            "expected": "",
        })
    for index, entry in enumerate(entries[:limit]):
        entry["id"] = f"E{index + 1}"
    return entries[:limit]
