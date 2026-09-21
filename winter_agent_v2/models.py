from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Page(str, Enum):
    HOME = "HOME"
    MAP = "MAP"
    LOADING = "LOADING"
    MAINTENANCE = "MAINTENANCE"
    RESOURCE_DETAIL = "RESOURCE_DETAIL"
    MARCH = "MARCH"
    MARCH_QUEUE = "MARCH_QUEUE"
    BUILDING = "BUILDING"
    RESEARCH = "RESEARCH"
    TRAINING = "TRAINING"
    INTEL = "INTEL"
    BEAST = "BEAST"
    DAILY = "DAILY"
    ALLIANCE = "ALLIANCE"
    MAIL = "MAIL"
    EXPLORATION = "EXPLORATION"
    HERO = "HERO"
    EVENT = "EVENT"
    POPUP = "POPUP"
    UNKNOWN = "UNKNOWN"


class MarchState(str, Enum):
    IDLE = "IDLE"
    MARCHING = "MARCHING"
    GATHERING = "GATHERING"
    RETURNING = "RETURNING"
    UNKNOWN = "UNKNOWN"


class SkillState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    STABLE = "STABLE"
    BLOCKED = "BLOCKED"


class LatencyClass(str, Enum):
    NORMAL = "NORMAL"
    FAST = "FAST"
    REALTIME = "REALTIME"


class IntelState(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLAIMABLE = "CLAIMABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WorldState:
    page: Page = Page.UNKNOWN
    popup: str | None = None
    resources: dict[str, int | None] = field(default_factory=dict)
    marches: tuple[MarchState, ...] = ()
    march_used: int | None = None
    march_max: int | None = None
    normal_march_slots: int | None = None
    normal_idle_slots: int | None = None
    bear_rally_special_slot: bool | None = None
    bear_rally_special_available: bool | None = None
    building: dict[str, Any] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)
    training: dict[str, Any] = field(default_factory=dict)
    #: Per-barracks training state, keyed by ``SHIELD_CAMP`` / ``LANCER_CAMP`` /
    #: ``MARKSMAN_CAMP``.  Distinct from ``training`` above, which is the single
    #: "whatever training page was last open" reading and cannot answer "which camp is
    #: busy" -- the gap that let one running barracks mark the whole goal COMPLETE
    #: (open issue #86).  ``camp_training`` explains the model and the measurements.
    camps: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, Any] = field(default_factory=dict)
    alliance: dict[str, Any] = field(default_factory=dict)
    intel: dict[str, Any] = field(default_factory=dict)
    beast: dict[str, Any] = field(default_factory=dict)
    daily: dict[str, Any] = field(default_factory=dict)
    mail: dict[str, Any] = field(default_factory=dict)
    exploration: dict[str, Any] = field(default_factory=dict)
    stamina: dict[str, Any] = field(default_factory=dict)
    hospital: dict[str, Any] = field(default_factory=dict)
    defense: dict[str, Any] = field(default_factory=dict)
    rewards: dict[str, Any] = field(default_factory=dict)
    account_stage: dict[str, Any] = field(default_factory=dict)
    resource_bank: dict[str, Any] = field(default_factory=dict)
    queues: dict[str, Any] = field(default_factory=dict)
    rally: dict[str, Any] = field(default_factory=dict)
    hero_troop: dict[str, Any] = field(default_factory=dict)
    attempts: dict[str, Any] = field(default_factory=dict)
    battlefield: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)
    resource_target: str | None = None
    resource_search_open: bool = False
    resource_search_exhausted: bool = False
    resource_selected: str | None = None
    resource_level: int | None = None
    resource_available: bool | None = None
    # The search panel's beast tab.  Two readers, and they do not always agree:
    #
    # * the template layer sets it from the reviewed ``BTN_SEARCH_BEAST_TAB`` control;
    # * the OCR fusion layer overwrites it from the client's own printed tab labels,
    #   which is the durable reading because the strip's order drifts between client
    #   versions (measured 2026-09-21: 野兽 moved into the leftmost slot where the
    #   template expected 冰原巨兽, so all three beast-search templates scored NO MATCH
    #   on the live frame).  See ``ocr.RESOURCE_TAB_LABEL_TO_KIND``.
    #
    # Separate from ``resource_selected`` on purpose: the strip classifier only
    # identifies the four gatherable cells (MEAT/WOOD/COAL/IRON) against reviewed
    # templates, so a monster tab reads back as ``None`` there even when it is drawn.
    resource_beast_tab: bool = False
    #: The tab kinds positively read off the strip this frame, e.g.
    #: ``("BEAST", "COAL", "GIANT_BEAST", "MEAT", "WOOD")``.  Recorded so "the panel is open
    #: but a different tab is selected" is answerable from the state rather than inferred.
    resource_tab_kinds: tuple[str, ...] = ()
    #: Where the client drew the 野兽 (ordinary beast) tab, or ``None`` when it is not on
    #: screen.  This is the tab whose cards offer a solo 攻击; the route must prefer it.
    resource_beast_tab_norm: tuple[float, float] | None = None
    #: Where the client drew the 冰原巨兽 (giant beast) tab.  Its cards are rally targets --
    #: the measured level-5 mammoth offered only 集结 -- so a solo-kill route must not treat
    #: it as equivalent to ``BEAST``, which is what the user-facing rule requires.
    resource_giant_beast_tab_norm: tuple[float, float] | None = None
    #: Which tab of the strip the selection bracket currently anchors, monster tabs included,
    #: e.g. ``"BEAST"`` / ``"GIANT_BEAST"`` / ``"MEAT"``, or ``None`` when the strip could not
    #: be located or no tab is marked.
    #:
    #: This is the fact that distinguishes "the tab is drawn" from "the tab is selected", and
    #: the beast route needs the second.  Measured 2026-09-21: a freshly opened panel draws all
    #: five tabs, so ``resource_beast_tab_norm`` is already non-``None`` while the client has
    #: **生肉** anchored; a gate keyed on the label's presence therefore submitted the search
    #: without switching tabs and the 搜索 tap landed on a gatherable node behind the panel.
    #: ``resource_selected`` cannot stand in for this either, because it is limited to the four
    #: gatherable cells and reports ``None`` for a monster tab.
    resource_selected_tab: str | None = None
    # Set when the search panel is open on the beast tab AND the client has drawn
    # its result card on top of it -- the state ``beast5_found.png`` records after
    # 搜索 is tapped.  The panel does not close on success, which is why a
    # "panel is gone" test would never pass.
    beast_search_submitted: bool = False
    #: What the client's beast-search result card offered, read from its own words.
    #:
    #: ``solo_attack`` is the load-bearing field: True when the card carries 攻击 and does
    #: NOT carry 集结.  This is how the route honours the rule that a rally target must not
    #: be attempted as a normal attack -- the measured level-5 mammoth card offered 集结 and
    #: no 攻击, while the measured 等级10 麝牛 card (live 2026-09-21) offered 攻击 and no
    #: 集结.  Read from words rather than a sprite so it holds for species nobody has cut a
    #: template for, which is exactly what the client's own search returns.
    #:
    #: Measured on the successful-search frame
    #: ``live_runtime_step_001_after_refresh_2_20260921T105832480183.png``:
    #: ``{'title_level': 10, 'title_text': '蔚牛', 'has_attack': True, 'has_rally': False,
    #: 'solo_attack': True}``.  Empty when the frame is not that card.
    beast_search_result: dict = field(default_factory=dict)
    #: The 快捷面板, opened by the left-edge triangle, read as its own surface.
    #:
    #: The panel is an overlay: it is drawn on top of whichever page is underneath
    #: (measured 2026-09-21, open over the city view), so it is not a ``Page`` and
    #: must not name one.  What makes it worth reading is that it prints, in one
    #: frame, the state of three queues the route otherwise has to navigate to
    #: separately -- 建筑队列, 部队训练, 科技研究 -- and in particular the per-barracks
    #: training state for all three camps at once (盾兵 / 矛兵 / 射手 each with its own
    #: 已完成 / 训练中), which the training page only reveals one camp at a time.
    #:
    #: Shape: ``{"open": True, "building": {...}, "camps": {...}, "research": {...}}``,
    #: where ``camps`` uses the same ``SHIELD_CAMP`` / ``LANCER_CAMP`` /
    #: ``MARKSMAN_CAMP`` keys as ``WorldState.camps`` so one per-camp model serves both.
    #: ``open`` is the only key always present; each section is added only when its own
    #: rows were positively read, so a section that could not be read is absent rather
    #: than reported idle.  See ``ocr.read_quick_panel``.
    quick_panel: dict = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def known(self) -> bool:
        return self.page is not Page.UNKNOWN

    @property
    def idle_marches(self) -> int | None:
        if self.normal_idle_slots is not None:
            return self.normal_idle_slots
        if self.march_used is None or self.march_max is None:
            return None
        return max(0, self.march_max - self.march_used)

    @property
    def has_free_march_slot(self) -> bool | None:
        """Whether at least one normal march slot is free, or ``None`` if unknowable.

        The start condition must not depend on a capacity the client will not draw.
        Measured 2026-09-16: the march counter only exists while a march is out.  With
        nothing out, ``MARCH_COUNT_ROI`` returns no tokens at all, so ``march_used``
        reads 0 while ``march_max`` stays unreadable -- and every ``idle_marches``
        computation returns ``None``.  ``CHECK_MARCH`` cannot repair that by looking
        again: nothing is going to change.  Live 2026-09-16T11:09-11:16, three
        ``GATHER_RESOURCE`` runs burned all eight actions each on CHECK_MARCH for
        exactly this reason.

        It does not have to be repaired, because a lower bound is enough to start:
        if nothing is out at all, at least one slot is free -- an account that can
        march has at least one slot.  That claims nothing about the capacity, and it
        is self-correcting: dispatching a march makes the counter appear, so the real
        pair is read on the very next frame (live 2026-09-16T04:15:47, ``max``
        ``None -> 2``).

        The distinction matters for honest reporting.  ``idle_marches`` states a
        count and is only knowable while a march is out; this states the weak fact
        the dispatch decision actually needs, and it is knowable in both states.
        """
        if self.idle_marches is not None:
            return self.idle_marches > 0
        if self.march_used == 0:
            return True
        return None

    @property
    def effective_normal_march_slots(self) -> int | None:
        return self.normal_march_slots if self.normal_march_slots is not None else self.march_max

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoleIdentity:
    """Which role the client is logged in as, quoted from the 领主档案 panel.

    The operator's product definition (2026-09-16) makes this a precondition:
    "它登录到哪个角色 → 识别当前角色 → 读取当前角色的发展状态".  The project had no
    role concept at all, and the corpus was already built from two different
    accounts -- one showing 70,206,322 power and 6 march slots on 2026-09-14,
    the other showing 542,443 power and 2 march slots on 2026-09-16 -- so every
    metric that pooled them was un-scoped.

    Every field is a string the client drew.  Nothing here is derived from a
    furnace-level table, per "实际客户端观测 > 推测规则": a level may only ever
    supply a prior, never a fact.

    ``role_id`` is the account number the panel prints (``账号：1171757165``) and
    is the stable key to scope state by.  ``role_name`` is what the player sees,
    with any alliance tag kept separately rather than baked into the name.
    ``power_text`` stays text on purpose: the panel rounds (``54.2万`` against a
    HUD reading of 542,443), so turning it into an int would claim precision the
    client never showed.
    """

    role_id: str
    role_name: str
    alliance_tag: str | None = None
    kingdom: str | None = None
    power_text: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    skill: str
    reason: str
    confidence: float
    expected_result: str


@dataclass(frozen=True)
class Action:
    kind: str
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    executed: bool
    dry_run: bool
    action: Action
    error: str | None = None
    # Which UI-automation backend actually issued this action ("MAA" / "ADB").
    # Required by the operator's rule that a production episode must show
    # ``executor_backend = MAA`` before MAA can be called "接入".  Empty means the
    # action never reached a backend (policy refusal, dry run).
    backend: str = ""
    # The full call chain for this one action, so an episode can state which
    # channel produced the frame, who recognised the target, and who clicked -
    # recorded from what ran, never from what the config asked for.
    capture_backend: str = ""
    recognition_backend: str = ""
    latency_ms: float | None = None
    # Where a TAP_SEMANTIC actually landed, in device pixels.  Added 2026-09-20 after a tap resolved
    # a target, verified as "did not open it", and the question "so where did it land?" turned out to
    # be unanswerable from the episode: the resolved point was computed and then discarded.  For a
    # project whose rule is that a claim must be provable from its artifacts, a tap that did nothing
    # has to carry where it went.  None for actions that have no point (BACK, OBSERVE, refusals).
    tap_point: tuple[int, int] | None = None


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
