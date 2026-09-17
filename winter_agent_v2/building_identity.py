"""Read a building's identity off the city frame, from pixels, without guessing.

Why this exists (CAP-B01, 2026-09-17)
-------------------------------------
``vision.py`` used to answer the building-upgrade control with

    building={"id": "STOREHOUSE", "level": 26, "target_level": 27, "upgradeable": True}

None of those three values was read from that frame, or from any frame.  They came
from ``dataset/raw/live_build_warehouse_upgrade_dialog.png`` -- and that dialog does
**not even show the current level**: it shows the *prerequisite* row ``大熔炉 等级 27``.
So ``level 26`` was an inference and ``id STOREHOUSE`` was a constant, and the operator's
rule is that identity must never be reverse-engineered.

What the current client actually draws, measured on
``dataset/raw/live_build_quest_navigation.png``: a selected building carries a floating
label and the quest banner names the target --

    '26'                       conf=0.999  norm=[0.396,0.416,0.447,0.437]
    '仓库'                     conf=0.999  norm=[0.487,0.417,0.557,0.437]
    '将仓库升到27级（26/27）'   conf=0.964  norm=[0.110,0.812,0.482,0.834]

so identity, current level and target level are all readable **without opening any
building panel** -- which matters, because no brain route can open one (that is why
BUILDING_UPGRADE has never had a live attempt).

Design rules, all of them load-bearing
--------------------------------------
* **Spatially associated, not merely present.**  ``26`` counts as a level only when it
  is a bare integer in the same text row as a known building name, immediately to its
  left, within a gap cap.  The frame also holds ``112.2万``, ``02:37:43``,
  ``50,000,000+10,000,000`` and ``（26/27）``; none of those may become a level.
* **Exact name match only.**  There is no "closest building" fallback: a wrong identity
  is worse than none, because the upgrade verifier compares the queued building against
  this value.
* **UNKNOWN when incomplete.**  A missing number, a missing name, a low-confidence read
  or a name that is not in the table all produce ``UNKNOWN`` rather than a guess.
* **target_level has two tiers, and which one was used is recorded.**  The quest banner
  is observed; ``level + 1`` is the game's rule and is only used when the banner is
  absent, flagged as derived.  If the banner's own current level contradicts the label,
  the banner is about a different building and its target is dropped.

Pure functions over OCR tokens: no engine, no I/O, no state.

Measured live, 2026-09-17 19:51 GMT+8 -- a 盾兵营 selected on the city, its menu open
(``dataset/truth_audit/power_route_20260917/build_live2_20260917_115113_01_after_tap_280_640.png``):

    '12'      conf=1.000  norm=[0.382,0.418,0.421,0.438]   <- level, left of the name
    '盾兵营'   conf=0.994  norm=[0.467,0.414,0.582,0.441]   <- building name
    '详情' conf=0.998 / '训练' conf=0.993 / '升级' conf=1.000  <- the action entries

The same frame also holds ``467``, ``27``, ``113.1万``, ``01:12:50``, ``32/32`` and
``通关探险第50关（0/1）``; none of them may become a level, and none of them does.  The
reader returned, through the production observation path::

    {"id": "UNKNOWN", "name": "盾兵营", "level": 12, "target_level": 13,
     "identity_confidence": 0.9937, "identity_source": "FLOATING_LABEL_OCR+LEVEL_PLUS_ONE"}

⚠ Open question recorded rather than guessed.  The table below maps 步兵营 -> INFANTRY_CAMP,
but the building whose menu offers 训练 labels itself **盾兵营** on screen (and per open
issue #24 the training tabs read 百战盾兵 / 刚毅矛兵 / 刚毅射手, so the shield troops are
"盾兵").  That the training camp and ``INFANTRY_CAMP`` are the same building is strongly
suggested by the frame -- the label and the 训练 entry are drawn together -- but it is not
proven, so 盾兵营 is deliberately absent and resolves to UNKNOWN.  One live confirmation
(enter 训练 from that menu and record which page/troop type appears) is all it takes to
add the mapping honestly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

UNKNOWN = "UNKNOWN"

# 中文建筑名 -> building_id.  Exact match only; every entry names its evidence.
BUILDING_IDS: dict[str, str] = {
    # Live: the upgrade dialog's title (live_build_warehouse_upgrade_dialog.png) and the
    # floating label on the city frame (live_build_quest_navigation.png), both OCR'd.
    "仓库": "STOREHOUSE",
    # Live: the 部队实力 training route focuses this building; template
    # BUILDING_INFANTRY_CAMP; PAGE_TRAINING_INFANTRY is drawn under it.
    "步兵营": "INFANTRY_CAMP",
    # Live: the 大熔炉 等级 27 prerequisite row in the upgrade dialog.  Matches the
    # external project's FURNACE_UPGRADE capability.
    "大熔炉": "FURNACE",
    # Live: template BUILDING_RESEARCH_CENTER, and NAVIGATE_RESEARCH_LAB focuses it.
    "科研所": "RESEARCH_CENTER",
    # Operator-supplied, NOT yet observed on a city frame.  Harmless while the lookup
    # is exact-match: an entry that never matches simply never fires.
    "射手营": "MARKSMAN_CAMP",
    "矛兵营": "LANCER_CAMP",
}

# A level is a bare small integer.  Anything with a unit, a separator, a sign, a clock
# or a slash is something else on this frame (resource cost, countdown, progress).
_LEVEL_RE = re.compile(r"^\d{1,3}$")
_NOT_A_LEVEL = re.compile(r"[万亿%:/+、,．.\-]|等级")

# Structural shape of a building name: a short run of Chinese characters.  Not a
# vocabulary -- see ``is_name_shaped`` for why this is safe without one.
_CHINESE_NAME_RE = re.compile(r"[\u4e00-\u9fa5]{2,6}")

# 「将仓库升到27级（26/27）」 and near variants.
_QUEST_TARGET_RE = re.compile(
    r"(?:将|把)?(?P<name>[\u4e00-\u9fa5]{2,8}?)升(?:到|至|级到)\s*(?P<target>\d{1,3})\s*级"
)
_QUEST_PROGRESS_RE = re.compile(r"[（(]\s*(?P<current>\d{1,3})\s*/\s*(?P<target>\d{1,3})\s*[）)]")

MIN_TOKEN_CONFIDENCE = 0.80
MAX_LEVEL_VALUE = 99
# Gap between the number's right edge and the name's left edge.  Measured 29 px on the
# live frame where both glyph rows are ~26 px tall, so 2x the name height is generous
# without reaching the next control (the 详情 button sits ~370 px below).
_GAP_FACTOR = 2.0
_MIN_VERTICAL_OVERLAP = 0.5


@dataclass(frozen=True)
class BuildingIdentity:
    """The unified output contract: exactly the six keys production consumes."""

    building_id: str
    name: str | None
    level: int | None
    target_level: int | None
    confidence: float
    source: str

    def as_state(self) -> dict[str, object]:
        return {
            "id": self.building_id,
            "name": self.name,
            "level": self.level,
            "target_level": self.target_level,
            "identity_confidence": self.confidence,
            "identity_source": self.source,
        }


def unknown(reason: str = "identity_not_read") -> BuildingIdentity:
    """The honest empty answer: a named reason, never a plausible default."""
    return BuildingIdentity(UNKNOWN, None, None, None, 0.0, reason.upper())


def box_bounds(box: Sequence[Sequence[float]]) -> tuple[float, float, float, float] | None:
    """``(x0, y0, x1, y1)`` from an OCR polygon, or ``None`` when there is no box."""
    if not box:
        return None
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    return min(xs), min(ys), max(xs), max(ys)


def _row_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Fraction of the shorter span that the two boxes share vertically."""
    top = max(a[1], b[1])
    bottom = min(a[3], b[3])
    if bottom <= top:
        return 0.0
    shorter = min(a[3] - a[1], b[3] - b[1])
    return (bottom - top) / shorter if shorter > 0 else 0.0


def is_a_level_candidate(text: str) -> bool:
    """True when a token could be a building level and nothing else."""
    stripped = text.strip()
    if _NOT_A_LEVEL.search(stripped):
        return False
    if not _LEVEL_RE.match(stripped):
        return False
    return int(stripped) <= MAX_LEVEL_VALUE


def find_name_token(tokens: Iterable, name_table: dict[str, str] | None = None):
    """The token whose whole text is a known building name, or ``None``.

    Used for frames that carry the name without a level next to it -- the upgrade
    dialog's title is exactly that case.
    """
    table = BUILDING_IDS if name_table is None else name_table
    best = None
    for token in tokens:
        text = token.text.strip()
        if text not in table:
            continue
        if token.confidence < MIN_TOKEN_CONFIDENCE:
            continue
        if box_bounds(token.box) is None:
            continue
        if best is None or token.confidence > best.confidence:
            best = token
    return best


def find_level_for(name_token, tokens: Iterable) -> int | None:
    """The integer immediately left of ``name_token`` in the same row.

    "Immediately left" is the whole discriminator: on the live frame the level sits
    ~29 px to the left of the name while every other number on screen (resource cost,
    countdown, quest progress) is either in another row or on the other side.
    """
    name_box = box_bounds(name_token.box)
    if name_box is None:
        return None
    height = name_box[3] - name_box[1]
    gap_cap = max(height * _GAP_FACTOR, 20.0)

    best: tuple[float, int] | None = None
    for token in tokens:
        if token is name_token or token.confidence < MIN_TOKEN_CONFIDENCE:
            continue
        if not is_a_level_candidate(token.text):
            continue
        box = box_bounds(token.box)
        if box is None:
            continue
        if box[2] > name_box[0]:
            # To the right of the name: not this label's number.
            continue
        gap = name_box[0] - box[2]
        if gap > gap_cap:
            continue
        if _row_overlap(box, name_box) < _MIN_VERTICAL_OVERLAP:
            continue
        distance = gap
        if best is None or distance < best[0]:
            best = (distance, int(token.text.strip()))
    return best[1] if best else None


def is_name_shaped(token) -> bool:
    """True for a token that *could* be a building name, independent of the table.

    Deliberately structural, not semantic: a short run of Chinese characters.  This is
    what lets an unlisted building be reported as ``name`` with ``id = UNKNOWN`` instead
    of being silently dropped -- and it is still not a fuzzy match, because the name is
    only accepted when a valid level sits immediately to its left, and the id only ever
    comes from an exact table lookup.
    """
    text = token.text.strip()
    if not 2 <= len(text) <= 6:
        return False
    if token.confidence < MIN_TOKEN_CONFIDENCE:
        return False
    if box_bounds(token.box) is None:
        return False
    return bool(_CHINESE_NAME_RE.fullmatch(text))


def find_label(tokens: Iterable) -> tuple[object | None, int | None]:
    """``(name_token, level)`` for the ``<level> <name>`` label, or ``(None, None)``.

    A token qualifies only when a valid level is spatially associated with it, which is
    what keeps 详情 / 升级 / 探险 and the rest of the chrome out of this.
    """
    token_list = list(tokens)
    named = find_name_token(token_list)
    if named is not None:
        level = find_level_for(named, token_list)
        if level is not None:
            return named, level

    candidates: list[tuple[object, int]] = []
    for token in token_list:
        if not is_name_shaped(token):
            continue
        level = find_level_for(token, token_list)
        if level is not None:
            candidates.append((token, level))
    if len(candidates) == 1:
        return candidates[0]
    # Zero candidates: nothing to read.  More than one: ambiguous -- the label is the
    # only one carrying a level and we cannot tell which, so refuse rather than pick.
    return None, None


def parse_quest_target(texts: Iterable[str]) -> tuple[str | None, int | None, int | None]:
    """``(name, current, target)`` from the quest banner, or ``(None, None, None)``.

    The parenthetical progress is used when the banner spells it out
    (``（26/27）``); otherwise only the target is known.
    """
    joined = " ".join(str(text).strip() for text in texts)
    match = _QUEST_TARGET_RE.search(joined)
    if not match:
        return None, None, None
    name = match.group("name")
    target = int(match.group("target"))
    current = None
    progress = _QUEST_PROGRESS_RE.search(joined)
    if progress and int(progress.group("target")) == target:
        current = int(progress.group("current"))
    return name, current, target


def read_building_identity(
    tokens: Iterable,
    *,
    quest_texts: Iterable[str] | None = None,
    name_table: dict[str, str] | None = None,
) -> BuildingIdentity:
    """Compose the unified identity from label tokens plus the quest banner.

    Returns :func:`unknown` with a named reason whenever anything is missing -- a wrong
    identity is worse than none, because the upgrade verifier compares the queued
    building against this value.

    ``quest_texts`` defaults to the token texts, because on the live frame the banner is
    itself a token; callers may pass a wider set when the banner is read from its own ROI.
    """
    table = BUILDING_IDS if name_table is None else name_table
    token_list = list(tokens)
    texts = list(quest_texts) if quest_texts is not None else [t.text for t in token_list]

    label_token, level = find_label(token_list)
    if label_token is None:
        # No ``<level> <name>`` pair.  A bare known name is still worth reporting -- the
        # upgrade dialog's title is exactly that -- but it carries no level, so it can
        # never satisfy the +1 the upgrade verifier needs.
        titled = find_name_token(token_list, table)
        if titled is None:
            return unknown("no_building_name_token")
        name = titled.text.strip()
        quest_name, _, quest_target = parse_quest_target(texts)
        if quest_name is not None and quest_name != name:
            quest_target = None
        return BuildingIdentity(table.get(name, UNKNOWN), name, None, quest_target,
                                titled.confidence, "LABEL_NAME_ONLY")

    name = label_token.text.strip()
    building_id = table.get(name, UNKNOWN)
    quest_name, quest_current, quest_target = parse_quest_target(texts)

    confidence = label_token.confidence
    source = "FLOATING_LABEL_OCR"

    if quest_target is not None and quest_name is not None and quest_name != name:
        # The banner names a different building than the label does: it is not about
        # this one, so its target is dropped rather than borrowed.
        quest_target = None

    if quest_target is not None and quest_current is not None and quest_current != level:
        # Same building by name, different current level: the two readings disagree, so
        # the observed target is not trustworthy and confidence drops with it.
        confidence = min(confidence, 0.5)
        quest_target = None

    if quest_target is not None:
        target_level = quest_target
        source = "FLOATING_LABEL_OCR+QUEST_BANNER"
    else:
        # Second tier: the game's own rule that an upgrade goes to the next level.  It
        # is a derivation, not a reading, so the source says so.
        target_level = level + 1
        source = "FLOATING_LABEL_OCR+LEVEL_PLUS_ONE"

    return BuildingIdentity(building_id, name, level, target_level, confidence, source)
