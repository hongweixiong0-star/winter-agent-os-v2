"""Three barracks, three independent readings, three independent decisions.

Why this exists (open issues #86 / #87, operator P0 2026-09-21)
---------------------------------------------------------------
The game has three training barracks and the client draws them as three tabs on one
training page.  The agent had exactly **one** ``world.training`` reading, and
``_append_queue_goal`` decided ``KEEP_TRAINING_PRODUCTIVE`` from that single value::

    busy = state.get("queue_available") is False or state.get("status") == "IN_PROGRESS"
    GoalStatus.COMPLETE if busy else GoalStatus.READY

So a busy shield camp marked **the whole training goal COMPLETE**, and the other two
barracks were never even looked at.  The operator's rule is explicit:

    "某个兵营正在训练、入口暂时不可用或识别失败，不得直接宣布整个训练 Goal 完成，
     也不得阻止检查另外两个兵营。"

What the client actually draws, measured on a live frame
(``dataset/truth_audit/training_three_barracks_20260921/key/
03_training_page_infantry_002515_250_20260921T015321.png``, 2026-09-21T01:53:21Z):

* the page title is the **troop** name -- ``英勇盾兵`` -- not the camp name;
* the three camp tabs sit at the bottom, y_norm ~0.928, x_norm ~0.03 / 0.345 / 0.66,
  labelled ``盾兵营`` / ``矛兵营`` / ``射手营``;
* the **selected** tab draws its label darker on a light tile while the other two draw
  lighter on blue -- which is exactly why ``TAB_TRAINING_LANCER`` and
  ``TAB_TRAINING_MARKSMAN`` are byte-identical (d=2): both were cut from *unselected*
  tiles, so even a match could not tell them apart.

The OCR of that same frame reads all three names at conf 1.00 / 0.99 / 1.00, which is
what makes this module possible **without re-cutting a single template**: the camp is
decided by which name is drawn as selected, not by a template layer that is dead.

Design rules, all of them load-bearing
--------------------------------------
* **A camp is only read when the page is open.**  ``observe_camps`` is called with the
  page it was read from; a frame that is not the training page returns no camps at all.
  Reading a camp off a frame that does not show it is how ``tier: 10`` got invented.
* **Absent is UNKNOWN, never IDLE.**  A camp that was not on screen is ``UNKNOWN`` --
  not "idle" and not "busy".  Two of the three camps have **zero frames in the entire
  live corpus**, so "we have never looked" is the honest answer and it stays that way
  until the tab is actually opened.
* **A queue that is not drawn is not an empty queue.**  ``AVAILABLE`` (trainable) is
  claimed only from a positive reading -- a visible 训练 action with no countdown.  No
  reading yields ``UNKNOWN``, which the scheduler treats as "still worth a look".
* **One camp's answer never stands in for another's.**  There is no aggregate "the
  training queue" value: ``summarise_camps`` counts the three separately, and a campless
  legacy ``world.training`` reading is reported as its own ``LEGACY_PAGE`` entry rather
  than being silently attributed to INFANTRY.

Pure functions over already-read text: no engine, no OCR call, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

#: The three barracks, in the left-to-right order the client draws their tabs.
CAMP_ORDER: tuple[str, ...] = ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP")

#: ``troop_type`` (what vision writes today) -> camp id.  ``SHIELD`` is the operator's
#: name for what the page title calls 盾兵 and what the older code called ``INFANTRY``.
TROOP_TO_CAMP: dict[str, str] = {
    "INFANTRY": "SHIELD_CAMP",
    "SHIELD": "SHIELD_CAMP",
    "LANCER": "LANCER_CAMP",
    "MARKSMAN": "MARKSMAN_CAMP",
}

#: Camp id -> the Chinese label the client draws on that camp's tab.
CAMP_LABELS: dict[str, str] = {
    "SHIELD_CAMP": "盾兵营",
    "LANCER_CAMP": "矛兵营",
    "MARKSMAN_CAMP": "射手营",
}

#: Reverse of :data:`CAMP_LABELS`, for reading a tab off a frame.
LABEL_TO_CAMP: dict[str, str] = {label: camp for camp, label in CAMP_LABELS.items()}

#: Per-camp status words, and what each one means for the goal.  These are the words the
#: client itself draws (``训练中`` for busy, ``正在训练N位...`` for the batch line); the
#: table exists so a status the page did not draw cannot become a status the goal acts on.
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CampReading:
    """One barracks: what was read about it, and what was *not* read is ``None``.

    Every field is optional on purpose.  ``None`` means "this frame did not show it" and
    is carried through to the goal as work still to do, rather than defaulted into a
    value that reads like knowledge.
    """

    camp: str
    status: str = STATUS_UNKNOWN
    troop_type: str | None = None
    #: True only when the frame positively shows this camp's queue is running.
    training: bool | None = None
    #: True only when the frame positively shows an empty trainable queue.
    queue_available: bool | None = None
    batch_count: int | None = None
    timer: str | None = None
    #: True when this camp's tab is the selected one on the page.
    selected: bool = False
    #: How the camp was decided: ``TAB_LABEL`` (name drawn as selected) or
    #: ``PAGE_IS_THIS_CAMP`` (page open on it, title names the troop).
    source: str = ""
    confidence: float = 0.0

    @property
    def observed(self) -> bool:
        return self.status != STATUS_UNKNOWN

    @property
    def busy(self) -> bool | None:
        """Whether this camp's queue is running, or ``None`` when not read.

        A camp is busy when either signal says so, and ``None`` when neither was read --
        which is distinct from ``False`` (read, and it is free).
        """
        if self.training is True or self.status == STATUS_IN_PROGRESS:
            return True
        if self.queue_available is True or self.status == STATUS_AVAILABLE:
            return False
        return None

    def to_state(self) -> dict[str, Any]:
        """The dict the goal layer and the panel both read.  Keys are stable."""
        return {
            "camp": self.camp,
            "label": CAMP_LABELS.get(self.camp, self.camp),
            "status": self.status,
            "troop_type": self.troop_type,
            "training": self.training,
            "queue_available": self.queue_available,
            "batch_count": self.batch_count,
            "timer": self.timer,
            "selected": self.selected,
            "source": self.source,
            "confidence": self.confidence,
            "observed": self.observed,
            "busy": self.busy,
        }


def _timer_seconds(timer: str | None) -> int | None:
    if not timer:
        return None
    parts = timer.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return None


def camp_from_selected_label(texts: Iterable[str]) -> str | None:
    """Which camp's tab is selected, decided from the drawn labels.

    The client draws all three camp names at once, so presence alone decides nothing.
    This returns the camp whose label is present, and it is the caller's job to have
    passed only the labels that were drawn *as selected* (see
    :func:`observe_camps`).  Two labels present is ambiguous and returns ``None`` --
    guessing between 盾兵营 and 矛兵营 would be the same class of error as inventing a
    tier from an old screenshot.
    """
    found = [LABEL_TO_CAMP[text] for text in texts if text in LABEL_TO_CAMP]
    unique = sorted(set(found))
    return unique[0] if len(unique) == 1 else None


def observe_camps(
    *,
    page_is_training: bool,
    selected_camp: str | None = None,
    training: Mapping[str, Any] | None = None,
    tab_selected: Mapping[str, bool] | None = None,
) -> dict[str, dict[str, Any]]:
    """Read the camps this training-page frame answers for.

    The camp is decided by the page's own ``troop_type`` -- which the client draws as the
    page title (英勇盾兵 / 刚毅矛兵 / 刚毅射手) and which OCR reads off it -- and only falls
    back to ``selected_camp`` when the page did not name its troop.  That order is deliberate:
    the title is drawn once, for the open camp, while all three tab labels are drawn at the
    same time, so a tab-based guess has to distinguish three identical-looking labels and the
    title does not.  Measured 2026-09-21: the tab-highlight pixel test that would do that
    distinguishing was not reliable enough to be worth a wrong answer (see
    ``OCRPageClassifier.classify``).

    ``training`` is the page's own reading -- its countdown, batch count and status belong to
    whichever camp is open, and only to that camp.

    Returns a dict keyed by camp id containing **only** the camps this frame said something
    about.  A camp absent from the result has not been read, which the goal layer must treat
    as work (go and look), never as an idle queue.
    """
    if not page_is_training:
        # Not the training page: it shows no camp, so it says nothing about any camp.
        # Returning the tab map here would let a stale page invent a queue state.
        return {}

    reading = dict(training or {})
    status_word = str(reading.get("status") or "").strip().upper()
    batch = reading.get("batch_count")
    timer = reading.get("timer")
    troop_type = reading.get("troop_type")
    if isinstance(troop_type, str):
        troop_type = troop_type.strip().upper() or None

    # The title wins; the selected tab is the fallback for a frame that drew tabs but whose
    # title was not read.  No default camp.
    camp = TROOP_TO_CAMP.get(troop_type) if troop_type else None
    source = "PAGE_IS_THIS_CAMP"
    if camp is None and selected_camp:
        camp = selected_camp
        source = "TAB_LABEL"
    if camp is None:
        return {}

    running = status_word == STATUS_IN_PROGRESS or bool(timer)
    trainable = status_word == STATUS_AVAILABLE
    if running:
        status = STATUS_IN_PROGRESS
    elif trainable:
        status = STATUS_AVAILABLE
    elif status_word in {STATUS_IN_PROGRESS, STATUS_AVAILABLE}:
        status = status_word
    else:
        status = STATUS_UNKNOWN

    reading_obj = CampReading(
        camp=camp,
        status=status,
        troop_type=troop_type,
        training=True if running else (False if trainable else None),
        queue_available=False if running else (True if trainable else None),
        batch_count=batch if isinstance(batch, int) else None,
        timer=timer if isinstance(timer, str) else None,
        selected=bool((tab_selected or {}).get(camp)) or selected_camp == camp,
        source=source,
        confidence=float(reading.get("confidence") or 0.0),
    )

    out = {camp: reading_obj.to_state()}
    # A frame that named the other two tabs but could not read them still tells us they
    # exist and were not opened.  Recording them as UNKNOWN would be an entry that looks
    # like a reading, so they are simply left out and the goal layer's per-camp table
    # supplies DISCOVERED for anything it has never seen.
    return out


def merge_camps(
    previous: Mapping[str, Any] | None,
    fresh: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Fold a fresh per-camp reading into the running per-camp state.

    Only the camps present in ``fresh`` are touched: looking at one barracks must not
    erase what the last look at another learned.  A camp already known and not re-read
    keeps its reading (the goal layer separately ages it with the observation store's
    TTL, exactly like every other page reading).
    """
    merged: dict[str, dict[str, Any]] = {}
    for camp, state in (previous or {}).items():
        if isinstance(state, Mapping) and camp in CAMP_ORDER:
            merged[camp] = dict(state)
    for camp, state in (fresh or {}).items():
        if camp in CAMP_ORDER and isinstance(state, Mapping):
            merged[camp] = dict(state)
    return merged


def summarise_camps(camps: Mapping[str, Any] | None) -> dict[str, Any]:
    """The three answers, counted separately -- never collapsed into one.

    ``trainable`` lists camps with a positively-read free queue; ``busy`` lists camps
    positively running; ``unread`` lists camps with no reading at all.  The caller
    decides what to do, but it can no longer say "the training queue is busy" without
    saying *which* queue, and an unread camp stays visible as work.
    """
    states = {camp: dict(camps.get(camp) or {}) for camp in CAMP_ORDER} if camps else {}
    trainable: list[str] = []
    busy: list[str] = []
    unread: list[str] = []
    for camp in CAMP_ORDER:
        state = states.get(camp) or {}
        busy_flag = state.get("busy")
        if not state or state.get("observed") is not True:
            unread.append(camp)
        elif busy_flag is False:
            trainable.append(camp)
        elif busy_flag is True:
            busy.append(camp)
        else:
            unread.append(camp)
    return {
        "camps": states,
        "trainable": trainable,
        "busy": busy,
        "unread": unread,
        "all_accounted_for": not unread,
    }
