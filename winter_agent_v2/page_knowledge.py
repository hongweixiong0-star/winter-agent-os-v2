"""Unknown-page knowledge: name what a screen is, and remember what leaving it looks like.

Why this exists (operator directive 2026-09-22, "未知页面自主探索与页面知识自动入库")

The element collector answers "what is this control".  It cannot answer "what is this
*screen*", and the two are different questions: a page the page model cannot name has no
elements registered, so every control on it is invisible to the whole registry at once.  The
directive's lead sentence is exactly that gap -- the collector must cover unknown pages, not
only unknown buttons on known pages.

The evidence is this project's own episode stream.  Of the steps whose *after* frame came back
``Page.UNKNOWN``, the largest single class is 31 failures of ``EXPLORATION_IDLE_CLAIM``: tapping
the exploration panel's idle button opens 挂机收益 -- a dialog OCR reads cleanly (title 挂机收益
0.998, 领取 0.995, ✕ 0.776) and that the page model has no rule for.  The goal was to claim the
reward, the reward was on screen, and the run could neither name the screen nor tap it.

What it is and is not
---------------------
A **state file plus pure helpers**, the same shape as ``ui_collection`` / ``observation_store``:
it observes nothing, decides nothing, clicks nothing, owns no device.  There is no second
Brain, Scheduler or Executor, and no second clicker -- the runtime hands it the frames it
already captured, and the *same* ordinary-control path executes whatever it records.

Two records, two vocabularies
-----------------------------
* a **page candidate** (``knowledge/perception/pages/<id>/``) -- the screen itself: its frame,
  its candidate title, its visible controls with boxes, what it was entered from, and the
  candidate semantics.  A page is *not* verified by a button on it working.
* a **transition** (``knowledge/ui/page_transitions.json``) -- what one real step did:
  ``before page -> control -> action -> after page``, with the verifier's own verdict.  This is
  the navigation knowledge the directive's §五 asks to keep, and it is what makes the second
  visit cheaper than the first.

Why transitions are keyed on the *title* as well as the page label
------------------------------------------------------------------
Every unknown screen carries the label ``UNKNOWN``, so a ledger keyed on the label alone would
let 挂机收益's 领取 answer for a different unnamed screen's 领取.  For an unknown page the key is
``(UNKNOWN, <title candidate>)``; for a named page the title is empty and the key is just the
label, which is what a named page's key already is everywhere else in this project.  The same
reasoning applies to the page candidate's own id.
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

from .ui_collection import (
    PLAIN_ACTION_WORDS,
    STATUS_CANDIDATE,
    STATUS_DISCOVERED,
    STATUS_FAILED,
    STATUS_VERIFIED,
    STATUSES,
    phash_digest,
)

#: Where page candidates live.  Outside ``dataset/raw`` for the same reason element candidates
#: are: that tree is pruned by the retention pass, and "the frame this page was learned from"
#: has to outlive it.
PAGE_ROOT = Path("knowledge/perception/pages")
INDEX_NAME = "INDEX.json"

#: The navigation knowledge the directive's §五 asks to keep.  Deliberately a hand-appendable
#: JSON file and not ``knowledge/ui/navigation_matrix.json``: that one is *derived* (regenerated
#: by ``tools/ui_navigation_matrix.py`` from the skill registry), so anything learned into it
#: would be erased by the next regeneration.
TRANSITIONS_PATH = Path("knowledge/ui/page_transitions.json")
TRANSITIONS_SCHEMA = "1.0"

#: The one dictionary the project already keeps, read here only to answer "does the client's own
#: word for this screen match something the project has already named".  Nothing is written back.
UI_DICTIONARY_PATH = Path("knowledge/ui/semantic_dictionary.json")

#: Recognition provenance for a page (operator §二/§五).  AI inference is its own value and never
#: masquerades as a measurement -- ``ACTION_RESULT`` is what a real step proved.
PAGE_METHOD_OCR = "OCR_TITLE"
PAGE_METHOD_ACTION = "ACTION_RESULT"
PAGE_METHOD_AI = "AI_INFERENCE"

#: The band a page title is allowed to come from.  Measured on the live 挂机收益 frame: the title
#: sits at cy 0.233 with height 40 px, and the frame's *largest* text is the 领取 button (47 px)
#: at cy 0.723 -- so "biggest text on the screen" would name the dialog after its own button, and
#: the upper-half restriction is what stops that.  Same reading on the battle overlay frame:
#: 对战 (139 px, cy 0.215) is the salient word there and the page is not named after 自动 (0.675).
TITLE_BAND_CY = 0.62

#: A title candidate must be at least this confident and this tall.  Below it the honest answer is
#: "this screen has no readable title", which is a state the caller records rather than fills in.
MIN_TITLE_CONFIDENCE = 0.90
MIN_TITLE_HEIGHT_PX = 24

#: Words that mark a control as the way *out* of a screen.  The client also draws its close as a
#: bare ✕, which OCR reads as ``X`` at 0.776 on the measured frame -- hence the lower floor below
#: and the glyph list, and hence ``kind`` is recorded rather than acted on.
BACK_WORDS: tuple[str, ...] = ("返回", "返回主城", "退出", "关闭", "离开", "返回城镇")
CLOSE_GLYPHS: tuple[str, ...] = ("X", "x", "×", "✕", "╳", "⨯")
MIN_GLYPH_CONFIDENCE = 0.70

#: The client's words for the things a reward panel usually carries.  Used only to fill
#: ``candidate_page_semantics`` -- a *candidate* name that a real step may later confirm or
#: delete.  Nothing executes on the strength of this table.
SEMANTIC_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("REWARD_PANEL", ("收益", "奖励", "领取", "获得", "礼包内容", "签到")),
    ("RESOURCE_PANEL", ("产量", "采集", "资源", "木材", "铁矿", "粮食", "石料")),
    ("TROOP_PANEL", ("部队", "士兵", "兵力", "等级", "属性")),
    ("EVENT_PANEL", ("活动", "限时", "任务", "进度")),
    ("SHOP_PANEL", ("商店", "兑换", "购买", "特惠")),
    ("BATTLE_OVERLAY", ("对战", "战斗", "胜利", "失败", "战报")),
    ("ALLIANCE_PANEL", ("联盟", "成员", "捐献", "礼物")),
)

#: An upper bound on what one page record carries, so a dense screen cannot make one record
#: larger than the whole rest of the directory.
MAX_CONTROLS_PER_PAGE = 16
MAX_TEXTS_PER_PAGE = 24

#: Storage bound, the same policy as the element collector (operator §九): hypotheses are pruned
#: oldest-first, and nothing a real step verified is ever pruned by this module.
MAX_PAGES = 200
MAX_TRANSITIONS = 400

#: How many answers one page record keeps.  A screen asked about for a year would otherwise grow
#: without bound; the most recent answers are the ones a reader can still act on.
MAX_ADVICE_PER_PAGE = 4

#: The key every unknown screen shares.  Named here so the ledger and the candidate store cannot
#: disagree about which screens are "the same screen".
UNKNOWN_LABEL = "UNKNOWN"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _box_norm(token: Any, frame_size: tuple[int, int]) -> dict[str, float]:
    xs = [float(point[0]) for point in token.box]
    ys = [float(point[1]) for point in token.box]
    width, height = int(frame_size[0]), int(frame_size[1])
    return {
        "x_norm": round(min(xs) / width, 4),
        "y_norm": round(min(ys) / height, 4),
        "w_norm": round((max(xs) - min(xs)) / width, 4),
        "h_norm": round((max(ys) - min(ys)) / height, 4),
    }


def _token_geometry(token: Any, frame_size: tuple[int, int]) -> tuple[float, float, float]:
    """``(height_px, centre_y_norm, centre_x_norm)`` for one token."""
    ys = [float(point[1]) for point in token.box]
    xs = [float(point[0]) for point in token.box]
    height = max(ys) - min(ys)
    width, frame_height = int(frame_size[0]), int(frame_size[1])
    return height, (min(ys) + max(ys)) / 2 / frame_height, (min(xs) + max(xs)) / 2 / width


#: Cached by file state, the same way the runtime caches its own dictionary read: an edit to the
#: dictionary has to take effect without a code change.
_DICTIONARY: tuple[float, dict[str, tuple[str, ...]]] = (0.0, {})


def dictionary_word_pages() -> dict[str, tuple[str, ...]]:
    """``{client word: the pages the project already places it on}`` from the semantic dictionary.

    Read rather than duplicated: the page-name hints below (`suggest_page_semantics`) are only
    allowed to use knowledge this repository already keeps, never a fresh hand-written table.
    """
    global _DICTIONARY
    try:
        stamp = UI_DICTIONARY_PATH.stat().st_mtime
    except OSError:
        return {}
    if stamp != _DICTIONARY[0]:
        table: dict[str, list[str]] = {}
        try:
            payload = json.loads(UI_DICTIONARY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _DICTIONARY[1]
        for record in payload.get("records") or ():
            if not isinstance(record, Mapping):
                continue
            pages = tuple(str(page) for page in (record.get("pages") or ()))
            for word in record.get("ocr") or ():
                text = str(word or "").strip()
                if not text or not pages:
                    continue
                table.setdefault(text, [])
                for page in pages:
                    if page not in table[text]:
                        table[text].append(page)
        _DICTIONARY = (stamp, {word: tuple(pages) for word, pages in table.items()})
    return _DICTIONARY[1]


def read_title_candidate(
    frame_path: Path | str, ocr: Any, frame_size: tuple[int, int] | None = None
) -> dict[str, Any] | None:
    """The client's own largest word in the title band, or ``None`` when the screen has none.

    ``None`` is a real answer and the caller records it as such: an unnamed screen whose title is
    unreadable is exactly the screen that needs its picture and its controls kept, and inventing
    a title for it would make two different screens look identical to the ledger.
    """
    from .ocr import read_frame_size

    frame_path = Path(frame_path)
    size = frame_size or read_frame_size(frame_path)
    if not size:
        return None
    try:
        result = ocr.recognize(frame_path)
    except (OSError, ValueError):
        return None
    best: dict[str, Any] | None = None
    for token in result.tokens:
        text = (token.text or "").strip()
        if not text or not token.box:
            continue
        confidence = float(token.confidence or 0.0)
        if confidence < MIN_TITLE_CONFIDENCE:
            continue
        height, cy, cx = _token_geometry(token, size)
        if cy > TITLE_BAND_CY or height < MIN_TITLE_HEIGHT_PX:
            continue
        # A whitelisted action word is a button, not a title, wherever it is drawn.  Measured:
        # 领取 is the tallest text on the 挂机收益 frame; without this it would name the dialog.
        if text in PLAIN_ACTION_WORDS:
            continue
        row = {
            "text": text,
            "confidence": round(confidence, 4),
            "height_px": round(height, 1),
            "center_norm": (round(cx, 4), round(cy, 4)),
            "box_norm": _box_norm(token, size),
        }
        if best is None or (row["height_px"], row["confidence"]) > (best["height_px"], best["confidence"]):
            best = row
    return best


def visible_controls(
    tokens: Iterable[Any], frame_size: tuple[int, int], *, limit: int = MAX_CONTROLS_PER_PAGE
) -> list[dict[str, Any]]:
    """The client's own words for what can be operated on this frame, with their boxes.

    Four kinds, and the kind is the point (operator §二.4 "当前页面可见的按钮、页签和操作提示"):

    * ``ACTION`` -- a word this project may already act on without a registered skill
      (``PLAIN_ACTION_WORDS``), i.e. a candidate for a goal-advancing tap;
    * ``BACK`` -- the client's own way out (返回/关闭/退出...), the entry the directive's §六 wants
      used before anything is guessed;
    * ``CLOSE_GLYPH`` -- the bare ✕ the client draws; recorded, never chosen automatically,
      because one glyph is not a measured control and its position is what a tap would need;
    * ``TAB`` -- a page-switch label (the 兵营 tabs are the measured example: they all carry 营).
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for token in tokens:
        text = (token.text or "").strip()
        if not text or not token.box:
            continue
        confidence = float(token.confidence or 0.0)
        if text in CLOSE_GLYPHS:
            kind = "CLOSE_GLYPH"
            if confidence < MIN_GLYPH_CONFIDENCE:
                continue
        elif text in BACK_WORDS:
            kind = "BACK"
            if confidence < MIN_TITLE_CONFIDENCE:
                continue
        elif text in PLAIN_ACTION_WORDS:
            kind = "ACTION"
            if confidence < MIN_TITLE_CONFIDENCE:
                continue
        elif len(text) <= 4 and text.endswith(("营", "页", "签")):
            kind = "TAB"
            if confidence < MIN_TITLE_CONFIDENCE:
                continue
        else:
            continue
        key = (kind, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "text": text,
                "kind": kind,
                "confidence": round(confidence, 4),
                "box_norm": _box_norm(token, frame_size),
            }
        )
        if len(out) >= limit:
            break
    return out


def suggest_page_semantics(title: str, texts: Iterable[str]) -> tuple[str, ...]:
    """Candidate page meanings, strongest evidence first, and never a claim of verification.

    Two sources, both traceable (operator §五 "标注来源必须可追溯"):

    * the project's own semantic dictionary, when the client's title is a word the dictionary
      already places on a page -- that is reuse of existing knowledge rather than a new guess;
    * the client's visible vocabulary, matched against ``SEMANTIC_HINTS`` -- a *candidate*, kept
      in ``candidate_page_semantics`` and never promoted to the page's identity by this function.

    Nothing here can return a value that outranks a real step's verdict: the record's
    ``recognition_method`` stays ``OCR_TITLE`` until an action result exists.
    """
    suggestions: list[str] = []
    title = str(title or "").strip()
    if title:
        for page in dictionary_word_pages().get(title, ()):
            name = f"DICTIONARY_PAGE:{page}"
            if name not in suggestions:
                suggestions.append(name)
    joined = " ".join(str(text or "") for text in texts)
    for name, cues in SEMANTIC_HINTS:
        if any(cue in joined for cue in cues) and name not in suggestions:
            suggestions.append(name)
    return tuple(suggestions[:4])


def page_key(page_label: str, title: str = "") -> str:
    """The key one screen is remembered under: its label, plus its title when unnamed.

    ``UNKNOWN`` is every unnamed screen's label, so the title is what keeps two of them apart --
    the directive's §九 rule ("不同页面下的同形图标必须保留独立语义记录") applied to pages.
    """
    label = str(page_label or "").strip() or UNKNOWN_LABEL
    name = str(title or "").strip()
    if label == UNKNOWN_LABEL and name:
        return f"{label}::{name}"
    return label


def page_candidate_id(key: str, digest: str) -> str:
    """A page candidate's identity: its key plus a perceptual digest of the frame."""
    stem = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")[:40] or "page"
    material = f"{key}|{digest}".encode("utf-8")
    return f"{stem}__{hashlib.sha256(material).hexdigest()[:10]}"


def frame_digest(frame_path: Path | str, *, size: int = 16) -> str | None:
    """A perceptual digest of a whole frame, or ``None`` when the frame cannot be read."""
    try:
        with Image.open(frame_path) as image:
            return phash_digest(image, size=size)
    except (OSError, ValueError):
        return None


@dataclass
class PageCandidate:
    """One unnamed screen's record.  Field names follow the directive's §四 list."""

    page_candidate_id: str
    page_label: str
    page_key: str
    title: str = ""
    title_confidence: float | None = None
    candidate_page_semantics: tuple[str, ...] = ()
    ocr_texts: tuple[str, ...] = ()
    controls: tuple[dict[str, Any], ...] = ()
    entry_page: str = ""
    entry_trigger: str = ""
    goal: str = ""
    world_state: dict[str, Any] = field(default_factory=dict)
    source_frame: str = ""
    source_episode: str = ""
    page_image_path: str = ""
    recognition_method: str = PAGE_METHOD_OCR
    #: What an on-demand analysis said about this screen (operator 2026-09-22 §五), kept as its
    #: own field so it can never be read as a measurement.  ``candidate_page_semantics`` stays what
    #: OCR read; this is what a reasoner *proposed*, and ``verification_status`` still moves only
    #: when a real step's verifier passes.
    ai_advice: tuple[dict[str, Any], ...] = ()
    verification_status: str = STATUS_DISCOVERED
    confidence: float = 0.0
    attempt_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    created_at: str = ""
    last_seen_at: str = ""
    notes: str = ""

    def as_metadata(self) -> dict[str, Any]:
        return asdict(self)


class PageCandidateStore:
    """The page-candidate directory and its index, as a state file plus pure helpers."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else PAGE_ROOT
        self.index_path = self.root / INDEX_NAME
        self._records: dict[str, PageCandidate] = self._load()

    def _load(self) -> dict[str, PageCandidate]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[str, PageCandidate] = {}
        for row in payload.get("pages") or ():
            if not isinstance(row, Mapping):
                continue
            try:
                data = dict(row)
                data["candidate_page_semantics"] = tuple(data.get("candidate_page_semantics") or ())
                data["ocr_texts"] = tuple(data.get("ocr_texts") or ())
                data["controls"] = tuple(data.get("controls") or ())
                data["ai_advice"] = tuple(data.get("ai_advice") or ())
                page = PageCandidate(
                    **{k: v for k, v in data.items() if k in PageCandidate.__dataclass_fields__}
                )
            except (TypeError, ValueError):
                continue
            # A record whose own picture is gone is not knowledge any more -- and keeping it is
            # actively harmful, not merely untidy.  Measured 2026-09-22: a store index survived
            # its ``<id>/`` directory (the directory had been removed while a live cycle still
            # held the record), and every later cycle then re-saved the resurrected record and
            # skipped re-capturing the screen -- ``_stage_unknown_page`` sees a record for that
            # key and folds the sighting into it instead of staging.  So the index grew a row
            # whose evidence nobody could open, for as long as the key kept being met.
            #
            # Dropping it here is the honest answer: the screen is unnamed again, and the next
            # sighting writes a new record with a fresh picture.  Only a *set* path is checked --
            # a record that was never given an image (a refusal) is not affected.
            image = str(page.page_image_path or "")
            if image and not Path(image).exists():
                continue
            out[page.page_candidate_id] = page
        return out

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "written_at": _now(),
            "count": len(self._records),
            "counts_by_status": self.counts(),
            "pages": [asdict(record) for record in self._records.values()],
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for record in self._records.values():
            counts[record.verification_status] = counts.get(record.verification_status, 0) + 1
        return counts

    def all(self) -> list[PageCandidate]:
        return list(self._records.values())

    def get(self, key: str) -> PageCandidate | None:
        return self._records.get(key)

    def find_key(self, key: str) -> PageCandidate | None:
        """The record already held for one screen key, if any -- the §六 "do not start over" read."""
        for record in self._records.values():
            if record.page_key == key:
                return record
        return None

    def stage(
        self,
        *,
        frame_path: Path | str,
        page_label: str,
        title: str = "",
        title_confidence: float | None = None,
        candidate_page_semantics: Sequence[str] = (),
        ocr_texts: Sequence[str] = (),
        controls: Sequence[Mapping[str, Any]] = (),
        entry_page: str = "",
        entry_trigger: str = "",
        goal: str = "",
        world_state: Mapping[str, Any] | None = None,
        episode: str = "",
        recognition_method: str = PAGE_METHOD_OCR,
        ai_advice: Sequence[Mapping[str, Any]] = (),
        notes: str = "",
    ) -> PageCandidate | None:
        """Write one screen's frame and metadata; return it, or ``None`` when it cannot be read.

        The frame is *copied* into the candidate's own directory rather than referenced
        (``source_frame`` still records where it came from): ``dataset/raw`` is pruned by the
        retention pass, and a page record whose only picture has been deleted cannot answer the
        next visit's question.
        """
        frame_path = Path(frame_path)
        digest = frame_digest(frame_path)
        if digest is None:
            return None
        key = page_key(page_label, title)
        identity = page_candidate_id(key, digest)
        record = self._records.get(identity)
        directory = self.root / identity
        directory.mkdir(parents=True, exist_ok=True)
        page_image = directory / "page.png"
        if not (record and record.page_image_path and Path(record.page_image_path).exists()):
            try:
                with Image.open(frame_path) as source:
                    source.convert("RGB").save(page_image)
            except (OSError, ValueError):
                return None
        record = record or PageCandidate(
            page_candidate_id=identity, page_label=str(page_label or UNKNOWN_LABEL), page_key=key
        )
        record.page_image_path = str(page_image.as_posix())
        record.source_frame = str(frame_path.as_posix())
        record.source_episode = episode or record.source_episode
        record.title = title or record.title
        record.title_confidence = (
            round(float(title_confidence), 4) if title_confidence is not None else record.title_confidence
        )
        record.candidate_page_semantics = tuple(
            dict.fromkeys(tuple(record.candidate_page_semantics) + tuple(candidate_page_semantics))
        )
        record.ocr_texts = tuple(
            dict.fromkeys(tuple(record.ocr_texts) + tuple(ocr_texts))
        )[:MAX_TEXTS_PER_PAGE]
        record.controls = tuple(dict.fromkeys(
            tuple(str(item.get("kind", "")) + "|" + str(item.get("text", "")) for item in record.controls)
            + tuple(str(item.get("kind", "")) + "|" + str(item.get("text", "")) for item in controls)
        ))
        record.controls = tuple(
            {**item} for item in tuple(record.controls or ()) if isinstance(item, Mapping)
        ) if False else _merge_controls(record.controls, controls)
        record.entry_page = entry_page or record.entry_page
        record.entry_trigger = entry_trigger or record.entry_trigger
        record.goal = goal or record.goal
        if world_state:
            record.world_state = dict(world_state)
        record.recognition_method = recognition_method or record.recognition_method
        if ai_advice:
            record.ai_advice = _merge_advice(record.ai_advice, ai_advice)
        record.confidence = round(
            float(title_confidence or record.confidence or 0.0), 4
        )
        record.created_at = record.created_at or _now()
        record.last_seen_at = _now()
        try:
            import yaml

            (directory / "metadata.yaml").write_text(
                yaml.safe_dump(record.as_metadata(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 - a missing metadata file must not fail a run
            pass
        self._records[identity] = record
        return record

    def record_attempt(self, *, key: str, verified: bool, observed_effect: str = "") -> PageCandidate | None:
        """Fold one real step's outcome into the page it happened on.

        The page's own status moves only on an action result -- ``VERIFIED`` when a step on this
        screen passed its verifier, ``FAILED`` when one ran its course without doing what it
        declared.  A control on the page working does not verify the page's *semantics*, which is
        why ``candidate_page_semantics`` is left exactly as the OCR read it (operator §四: "页面与
        元素分别管理验证状态").
        """
        record = self.find_key(key)
        if record is None:
            return None
        record.attempt_count += 1
        if verified:
            record.success_count += 1
            record.verification_status = STATUS_VERIFIED
            record.recognition_method = PAGE_METHOD_ACTION
        else:
            record.failure_count += 1
            if record.verification_status != STATUS_VERIFIED:
                record.verification_status = STATUS_FAILED
        if observed_effect:
            record.notes = f"observed_effect={observed_effect}"
        record.last_seen_at = _now()
        return record

    def prune(self, *, limit: int = MAX_PAGES) -> list[str]:
        """Drop the oldest unproven records past the cap; never a verified one."""
        if len(self._records) <= limit:
            return []
        prunable = [
            record
            for record in self._records.values()
            if record.verification_status in (STATUS_DISCOVERED, STATUS_FAILED)
        ]
        prunable.sort(key=lambda item: item.last_seen_at or item.created_at or "")
        removed: list[str] = []
        for record in prunable[: max(0, len(self._records) - limit)]:
            self._records.pop(record.page_candidate_id, None)
            removed.append(record.page_candidate_id)
        return removed


def _merge_controls(
    existing: Sequence[Any], incoming: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    """Keep one entry per ``(kind, text)``, newest position winning, bounded."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in tuple(existing) + tuple(incoming):
        if not isinstance(item, Mapping):
            continue
        key = (str(item.get("kind", "")), str(item.get("text", "")))
        if not key[1]:
            continue
        merged[key] = dict(item)
    return tuple(list(merged.values())[:MAX_CONTROLS_PER_PAGE])


def _merge_advice(
    existing: Sequence[Any], incoming: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    """One entry per ``request_id``, newest winning: the same question answered twice is one
    answer, and the later one is the one the reasoner most recently stood behind."""
    merged: dict[str, dict[str, Any]] = {}
    for item in tuple(existing) + tuple(incoming):
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("request_id") or "")
        if not key:
            continue
        merged[key] = dict(item)
    return tuple(list(merged.values())[-MAX_ADVICE_PER_PAGE:])


@dataclass
class Transition:
    """One measured ``before page -> control -> action -> after page``."""

    key: str
    before_page: str
    control: str
    skill: str = ""
    action: str = ""
    after_page: str = ""
    verified: bool = False
    goal: str = ""
    observed_change: str = ""
    expected_effect: str = ""
    count: int = 0
    success_count: int = 0
    failure_count: int = 0
    first_at: str = ""
    last_at: str = ""

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class TransitionLedger:
    """The learned navigation, as a file plus pure reads.

    Nothing in it is trusted as a *control*: the point of a transition is not "tap here", it is
    "this control, on this screen, led there" -- so the reuse it enables is about which word to
    prefer and which word not to retry, and the position is still measured off the live frame
    every time (operator §六: a coordinate is never the only basis for a tap).
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else TRANSITIONS_PATH
        self._rows: dict[str, Transition] = self._load()

    def _load(self) -> dict[str, Transition]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[str, Transition] = {}
        for row in payload.get("transitions") or ():
            if not isinstance(row, Mapping):
                continue
            try:
                transition = Transition(
                    **{k: v for k, v in dict(row).items() if k in Transition.__dataclass_fields__}
                )
            except (TypeError, ValueError):
                continue
            out[transition.key] = transition
        return out

    def save(self) -> None:
        rows = sorted(self._rows.values(), key=lambda item: item.last_at or item.first_at or "")
        if len(rows) > MAX_TRANSITIONS:
            # Verified transitions are what reuse depends on, so they are the last to go.
            keep_verified = [row for row in rows if row.verified]
            keep_other = [row for row in rows if not row.verified]
            rows = (keep_verified + keep_other[-max(0, MAX_TRANSITIONS - len(keep_verified)):])[-MAX_TRANSITIONS:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": TRANSITIONS_SCHEMA,
                    "written_at": _now(),
                    "count": len(rows),
                    "transitions": [row.as_row() for row in rows],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    def record(
        self,
        *,
        before_page: str,
        before_title: str = "",
        control: str,
        after_page: str = "",
        after_title: str = "",
        verified: bool = False,
        skill: str = "",
        action: str = "",
        goal: str = "",
        observed_change: str = "",
        expected_effect: str = "",
    ) -> Transition | None:
        """Fold one executed step into the ledger, merging with what the same tuple already says."""
        name = str(control or "").strip()
        if not name:
            return None
        key = "|".join(
            (
                page_key(before_page, before_title),
                name,
                str(skill or ""),
                page_key(after_page, after_title) if after_page else "",
            )
        )
        row = self._rows.get(key)
        row = row or Transition(
            key=key,
            before_page=page_key(before_page, before_title),
            control=name,
            skill=str(skill or ""),
            action=str(action or ""),
            after_page=page_key(after_page, after_title) if after_page else "",
            first_at=_now(),
        )
        row.count += 1
        row.verified = row.verified or bool(verified)
        if verified:
            row.success_count += 1
        else:
            row.failure_count += 1
        row.goal = str(goal or "") or row.goal
        row.observed_change = str(observed_change or "") or row.observed_change
        row.expected_effect = str(expected_effect or "") or row.expected_effect
        row.last_at = _now()
        self._rows[key] = row
        return row

    def rows_for(self, before_page: str, before_title: str = "") -> list[Transition]:
        key = page_key(before_page, before_title)
        return [row for row in self._rows.values() if row.before_page == key]

    def preferred_controls(self, before_page: str, before_title: str = "") -> list[str]:
        """Controls that a real step proved leave this screen, most-proven first."""
        rows = [row for row in self.rows_for(before_page, before_title) if row.verified]
        rows.sort(key=lambda item: (item.success_count, item.last_at or ""), reverse=True)
        return [row.control for row in rows]

    def failed_controls(self, before_page: str, before_title: str = "") -> list[str]:
        """Controls whose every recorded attempt on this screen did nothing that could be seen."""
        return [
            row.control
            for row in self.rows_for(before_page, before_title)
            if not row.verified and row.failure_count > 0
        ]

    def counts(self) -> dict[str, int]:
        return {
            "total": len(self._rows),
            "verified": sum(1 for row in self._rows.values() if row.verified),
        }


def word_from_control(control: str) -> str:
    """The client's word behind a control label (``ORDINARY_CONTROL[领取]`` -> ``领取``)."""
    match = re.search(r"\[(.*?)\]", str(control or ""))
    return match.group(1) if match else ""


def ocr_texts(tokens: Iterable[Any], *, limit: int = MAX_TEXTS_PER_PAGE) -> tuple[str, ...]:
    """The client's readable words on this frame, highest confidence first, bounded."""
    rows = [
        (round(float(token.confidence or 0.0), 4), (token.text or "").strip())
        for token in tokens
        if (token.text or "").strip()
    ]
    rows.sort(reverse=True)
    return tuple(text for _confidence, text in rows[:limit])
