"""Which of the two modes owns the machine: Auto (the system plays) or Manual (WorkBuddy works).

Operator specification 2026-10-06, ``docs/MODE_SYSTEM.md``.  The spec's own words for the two
modes are:

    Auto   -- the system runs in the game; WorkBuddy stays off the machine.
    Manual -- the machine is entirely WorkBuddy's; Auto is paused.

Four properties the spec asks for and where each one is implemented here:

* **persistent** (§1) -- one durable record, ``learning/MODE_STATE.json``.  ``learning/`` is a
  junction into the data root, so both worktrees read the same file; there is no second copy.
* **atomic** (§7) -- a switch is one ``os.replace`` of a temp file written in the same
  directory.  A crash leaves the old record or the new one, never a half-switched machine.
* **compare-and-swap** (§7, "either fully switched or not switched") -- every transition states
  the mode it expects to find and refuses if the file disagrees.  Without that, the AUTO loop
  and an explicit command could both "win", which is precisely the state the spec forbids.
* **a record, not a lock** -- the search note
  (``.workbuddy-ai/handoff/MODE_SYSTEM_SEARCH_20261006.md``) found the same lesson twice: prefer
  an atomic write in the store that owns the data, and prefer a record with states
  (``pending/running/succeeded/failed``) over an ephemeral lock key, because the record keeps an
  audit trail and survives a crash.  So this module owns no lock.  ``device_lease.py`` remains
  the only mechanism that hands the device over; this says *who is entitled to ask for it*.

Two latching rules that are easy to get backwards (§4, §10):

* the user forcing a mode **locks out autonomous switching in the opposite direction**.  After
  "切 Manual" WorkBuddy must not return on its own even when its task is done; after "切 Auto" it
  must not go back even mid-task.  ``user_latch`` carries that, and it is cleared only by another
  explicit user command.
* with no user instruction at all the default is **Auto** (§11).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

#: Spec §1/§2/§3.  Exactly two, and never both at once.
MODE_AUTO = "AUTO"
MODE_MANUAL = "MANUAL"
MODES: tuple[str, ...] = (MODE_AUTO, MODE_MANUAL)

#: Who asked for the current mode (§4).  The distinction is what the latch keys off.
BY_USER = "USER"
BY_WORKBUDDY = "WORKBUDDY"
INITIATORS: tuple[str, ...] = (BY_USER, BY_WORKBUDDY)

#: Spec §5: at the expected duration WorkBuddy must pick one of these.  Neither is "keep going
#: quietly", which is why the decision is typed rather than a boolean.
DECISION_PAUSE_AND_RETURN = "PAUSE_AND_RETURN"
DECISION_EXTEND = "EXTEND"
DECISIONS: tuple[str, ...] = (DECISION_PAUSE_AND_RETURN, DECISION_EXTEND)

#: Spec §13: past ten times the estimate the console has to shout.
OVERDUE_MULTIPLIER = 10.0

#: The stop reason a runtime cycle carries when it yielded because the machine is Manual's
#: (§1/§2: in Manual the machine belongs entirely to WorkBuddy).
#:
#: It lives here, next to the two modes, because three modules must agree on this one string
#: and disagreed: the runtime emitted it, ``runtime_snapshot`` did not declare it so it fell
#: through to ``SYSTEM_FAILURE``, and the panel printed 「本轮被判定为系统故障：
#: manually_owned_by_workbuddy」.  Measured 2026-10-06 07:24 UTC on the real root: three
#: rows in ``learning/auto_uptime.jsonl``, all three ``healthy=false`` -- the operator's own
#: choice recorded as a fault three times out of three.
MANUAL_STOP_REASON = "manually_owned_by_workbuddy"

#: Spec §7 case 1: the four things that must be true before a Manual session that touched code
#: may hand the machine back.  "Not completed wrap-up means no switch back" is the spec's own
#: sentence, so these are checked rather than trusted.
WRAP_UP_STEPS: tuple[str, ...] = ("committed", "repinned", "production_check_only", "reported")

DEFAULT_PATH = Path("learning/MODE_STATE.json")

#: The panel writes its own pid here, and ``tools/panel_restart.py`` owns that file.  Read, never
#: written, from this module.
PANEL_PID_PATH = Path("learning/control_panel/panel.pid")

#: §9's 机器状态 has three truthful answers, not two.  See :func:`loop_liveness`.
LOOP_RUNNING = "RUNNING"
LOOP_STOPPED = "STOPPED"
LOOP_UNKNOWN = "UNKNOWN"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat()


def _parse(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class Transition:
    """One line of the audit trail (§7 asks for recovery, §13 for a crash log)."""

    at: str
    frm: str
    to: str
    initiator: str
    reason: str
    note: str = ""


@dataclass
class ModeState:
    mode: str = MODE_AUTO
    initiator: str = BY_USER
    #: True while the current mode was ordered by the user; blocks autonomous switching the
    #: other way (§4 triggers 1 and 2).
    user_latch: bool = False
    reason: str = ""
    #: §5: a decision threshold, not a forced return.
    expected_seconds: float | None = None
    completion_criteria: str = ""
    started_at: str = ""
    decision: str | None = None
    decided_at: str = ""
    extensions: int = 0
    #: §7 case 1 vs case 2.  Only a session that changed code owes the four wrap-up steps.
    code_changed: bool = False
    wrap_up: dict[str, bool] = field(default_factory=dict)
    manual_seconds_total: float = 0.0
    crash_reason: str = ""
    history: list[Transition] = field(default_factory=list)

    # -- derived ----------------------------------------------------------------

    def entered(self) -> datetime | None:
        return _parse(self.started_at)

    def elapsed_seconds(self, now: datetime | None = None) -> float:
        start = self.entered()
        if start is None:
            return 0.0
        return max(0.0, ((now or _now()) - start).total_seconds())

    def remaining_seconds(self, now: datetime | None = None) -> float | None:
        if self.expected_seconds is None:
            return None
        return self.expected_seconds - self.elapsed_seconds(now)

    def decision_due(self, now: datetime | None = None) -> bool:
        """§5: the estimate was reached and no decision has been recorded for it yet."""
        if self.mode != MODE_MANUAL or self.expected_seconds is None:
            return False
        if self.decision is not None:
            return False
        return self.elapsed_seconds(now) >= self.expected_seconds

    def overdue(self, now: datetime | None = None) -> bool:
        """§13: past ten times the estimate, the console must highlight this."""
        if self.mode != MODE_MANUAL or not self.expected_seconds:
            return False
        if self.decision is not None and self.decision != DECISION_EXTEND:
            return False
        return self.elapsed_seconds(now) >= self.expected_seconds * OVERDUE_MULTIPLIER

    def wrap_up_missing(self) -> tuple[str, ...]:
        return tuple(step for step in WRAP_UP_STEPS if not self.wrap_up.get(step))

    def wrap_up_complete(self) -> bool:
        return not self.wrap_up_missing()

    def needs_wrap_up(self) -> bool:
        """§13 step 2: a Manual session that changed code and never finished, found on restart."""
        return self.mode == MODE_MANUAL and self.code_changed and not self.wrap_up_complete()

    def manually_switched_by_user(self) -> bool:
        return self.mode == MODE_MANUAL and self.initiator == BY_USER

    # -- serialisation ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["history"] = [asdict(row) for row in self.history]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModeState":
        state = cls()
        for key, value in payload.items():
            if key == "history":
                rows = []
                for row in value or ():
                    if isinstance(row, Mapping):
                        rows.append(Transition(
                            at=str(row.get("at") or ""),
                            frm=str(row.get("frm") or ""),
                            to=str(row.get("to") or ""),
                            initiator=str(row.get("initiator") or ""),
                            reason=str(row.get("reason") or ""),
                            note=str(row.get("note") or ""),
                        ))
                state.history = rows
            elif hasattr(state, key):
                setattr(state, key, value)
        return state


class ModeRefused(Exception):
    """A transition that the specification forbids, or that lost the compare-and-swap."""


# -- persistence ---------------------------------------------------------------


def load(path: Path | str = DEFAULT_PATH) -> ModeState:
    """Read the record, or start a fresh one in Auto.

    §13: after a crash, ``restart reads the persisted mode``.  A file that will not parse is
    moved aside rather than overwritten, so the corrupt bytes are still there to look at, and
    the machine comes up in Auto -- §11's default when nothing says otherwise.
    """
    path = Path(path)
    if not path.is_file():
        return ModeState(mode=MODE_AUTO, initiator=BY_USER, started_at=_iso(),
                         reason="no mode record yet; defaulting to Auto (spec §11)")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        broken = path.with_suffix(path.suffix + ".corrupt")
        try:
            path.replace(broken)
        except OSError:
            pass
        state = ModeState(mode=MODE_AUTO, initiator=BY_USER, started_at=_iso())
        state.crash_reason = f"mode record unreadable ({error}); kept at {broken.name}"
        return state
    if not isinstance(payload, Mapping):
        state = ModeState(mode=MODE_AUTO, initiator=BY_USER, started_at=_iso())
        state.crash_reason = "mode record was not an object"
        return state
    state = ModeState.from_dict(payload)
    if state.mode not in MODES:
        state.crash_reason = f"unknown mode {state.mode!r}; defaulting to Auto"
        state.mode = MODE_AUTO
    return state


def save(state: ModeState, path: Path | str = DEFAULT_PATH) -> None:
    """One atomic replace.  §7: never a half-switched record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# -- transitions ---------------------------------------------------------------


def _record(state: ModeState, frm: str, to: str, initiator: str, reason: str, note: str = "") -> None:
    state.history.append(Transition(at=_iso(), frm=frm, to=to, initiator=initiator,
                                    reason=reason, note=note))
    # The trail is for recovery and for reading back "what happened", not an archive; keep it
    # bounded so the file stays small enough to read by eye.
    del state.history[:-200]


def switch(
    to: str,
    *,
    initiator: str,
    reason: str,
    expected_mode: str | None = None,
    expected_seconds: float | None = None,
    completion_criteria: str = "",
    code_changed: bool = False,
    force: bool = False,
    path: Path | str = DEFAULT_PATH,
) -> ModeState:
    """Move the machine from one mode to the other, or refuse.

    ``expected_mode`` is the compare-and-swap: the caller says which mode it believes the
    machine is in, and the switch is abandoned if the record disagrees.  That is what makes
    "either fully switched or not switched" true under a concurrent writer (§7).
    """
    if to not in MODES:
        raise ModeRefused(f"unknown mode {to!r}; expected one of {MODES}")
    if initiator not in INITIATORS:
        raise ModeRefused(f"unknown initiator {initiator!r}; expected one of {INITIATORS}")

    state = load(path)
    if expected_mode is not None and state.mode != expected_mode:
        raise ModeRefused(
            f"compare-and-swap lost: record says {state.mode}, caller expected {expected_mode}"
        )
    if state.mode == to:
        # Already in the requested mode -- but that is not automatically a no-op.
        #
        # 2026-10-06, found by test: "切 Auto" while the machine was already in Auto used to
        # return early, so the latch never armed and WorkBuddy could grab the machine on the
        # very next tick (§4 trigger 2 says it must not, and §10 ranks the user's instruction
        # first).  An explicit user command is therefore recorded even when the mode does not
        # change; a WorkBuddy assertion of the current mode still records nothing, and must not
        # clear a latch the user is holding.
        #
        # ``started_at`` deliberately stays put: otherwise repeating the command would restart
        # the occupancy clock and make §5's decision point unmeasurable.
        if initiator != BY_USER:
            return state
        state.initiator = BY_USER
        state.user_latch = True
        if reason:
            state.reason = reason
        if to == MODE_MANUAL:
            if expected_seconds is not None:
                state.expected_seconds = expected_seconds
            if completion_criteria:
                state.completion_criteria = completion_criteria
            if code_changed:
                state.code_changed = True
        _record(state, to, to, initiator, reason, note="re-affirmed by user")
        save(state, path)
        return state

    # §4/§10: a mode the user ordered stays until the user says otherwise.  Auto may not be
    # left by WorkBuddy's own judgement while that latch is held.
    if initiator == BY_WORKBUDDY and to == MODE_MANUAL and state.user_latch:
        raise ModeRefused(
            "the user put the machine in Auto (§4 trigger 2); WorkBuddy may not switch back on "
            "its own, even mid-task"
        )

    # §4 trigger 1 / §10, and the single most important rule in the specification:
    #     "用户强制切 Manual 后，WorkBuddy 不许自主回切——哪怕任务完成了"
    #
    # 2026-10-06, found by an end-to-end smoke run rather than by a test: this guard was missing,
    # so WorkBuddy could finish its own completion criteria and hand the machine back out of a
    # Manual the *user* had ordered.  The two Manuals are not the same situation and the
    # specification says so in two places:
    #   * user-ordered Manual  -> only the user may switch back; WorkBuddy waits, however done it
    #     thinks it is;
    #   * WorkBuddy-taken Manual (§4 trigger 3) -> it *must* return by itself, which is what the
    #     wrap-up gate below governs.
    # ``user_latch`` distinguishes them and `--by` is the declared speaker, so this is deliberately
    # not reachable from a WorkBuddy-initiated call.
    if to == MODE_AUTO and state.mode == MODE_MANUAL and initiator == BY_WORKBUDDY and state.user_latch:
        raise ModeRefused(
            "the user put the machine in Manual (§4 trigger 1); only the user may switch back, "
            "even when the task is finished (§10)"
        )

    # §7 gate.  This used to be two separate checks that both raised; they are gathered so that
    # one refusal names everything outstanding instead of revealing it one item per attempt.
    #
    # §10 orders the ladder as 用户强制指令 > 安全边界 > 模式一致性 > 自主判断 > 流程优化, and §7's
    # wrap-up gate is a *process* requirement -- so an order from the user can override it.  It
    # is not silently honoured, though: §12 forbids handing back a machine that still has
    # uncommitted code or a production that will not start, so an override is recorded in the
    # audit trail with exactly what was skipped.  ``force`` is that path; without it the caller
    # is told which steps remain, because they are all trivially completable.
    override_note = ""
    if to == MODE_AUTO and state.mode == MODE_MANUAL:
        missing = state.wrap_up_missing() if state.code_changed else ()
        pending = state.decision_due()
        if missing or pending:
            complaints = []
            if missing:
                complaints.append(
                    "wrap-up incomplete for a session that changed code (§7 case 1): "
                    + ", ".join(missing)
                )
            if pending:
                complaints.append(
                    "the expected duration was reached and no decision was recorded (§5): "
                    "record PAUSE_AND_RETURN or EXTEND first"
                )
            if not force:
                raise ModeRefused("；".join(complaints))
            override_note = "OVERRIDDEN BY USER: " + "; ".join(complaints)

    frm = state.mode
    if frm == MODE_MANUAL:
        state.manual_seconds_total += state.elapsed_seconds()
    _record(state, frm, to, initiator, reason, note=override_note)

    state.mode = to
    state.initiator = initiator
    state.reason = reason
    state.started_at = _iso()
    state.decision = None
    state.decided_at = ""
    state.user_latch = initiator == BY_USER

    if to == MODE_MANUAL:
        state.expected_seconds = expected_seconds
        state.completion_criteria = completion_criteria
        state.code_changed = bool(code_changed)
        state.wrap_up = {}
        state.extensions = 0
    else:
        state.expected_seconds = None
        state.completion_criteria = ""
        state.code_changed = False
        state.wrap_up = {}

    save(state, path)
    return state


def record_decision(
    decision: str,
    *,
    note: str = "",
    new_expected_seconds: float | None = None,
    path: Path | str = DEFAULT_PATH,
) -> ModeState:
    """§5's decision point.  Either pause-and-return, or extend with a new estimate."""
    if decision not in DECISIONS:
        raise ModeRefused(f"unknown decision {decision!r}; expected one of {DECISIONS}")
    state = load(path)
    if state.mode != MODE_MANUAL:
        raise ModeRefused("a decision point only exists in Manual")
    if decision == DECISION_EXTEND and new_expected_seconds is None:
        raise ModeRefused("an extension must state the new expected duration (§5 option B)")

    state.decision = decision
    state.decided_at = _iso()
    if decision == DECISION_EXTEND:
        state.extensions += 1
        state.expected_seconds = new_expected_seconds
        # A new estimate restarts the clock, so the next threshold is measurable.
        state.started_at = _iso()
        state.decision = None
    save(state, path)
    return state


def mark_wrap_up(step: str, done: bool = True, *, path: Path | str = DEFAULT_PATH) -> ModeState:
    """Tick one of §7 case 1's four steps."""
    if step not in WRAP_UP_STEPS:
        raise ModeRefused(f"unknown wrap-up step {step!r}; expected one of {WRAP_UP_STEPS}")
    state = load(path)
    state.wrap_up[step] = bool(done)
    save(state, path)
    return state


# -- console surface (§9) ------------------------------------------------------


def _human(seconds: float | None) -> str:
    if seconds is None:
        return "未知"
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


def loop_liveness(pid_path: Path | str = PANEL_PID_PATH) -> tuple[str, str]:
    """``(verdict, reason)`` for "is the AUTO loop actually up?", which §9's 机器状态 needs.

    The mode says who the machine *belongs to*; it says nothing about whether anything is running.
    Reporting a mode as though it were a live system is the bug this exists to stop: on
    2026-10-06 the record said AUTO and the console printed ``机器状态：系统运行中`` while the
    panel had been down for 53 minutes with zero workers.

    The pid is judged with the **same primitive the tool that owns the file uses** --
    ``tools/panel_restart.py`` imports ``winter_agent_v2.winproc`` for exactly this -- so this is
    not a second definition of "alive", it is the same question asked from the other side.

    Three answers, not two: with no record the honest answer is ``UNKNOWN``, because "nothing
    wrote a pid" and "the process is dead" lead to opposite decisions and a boolean would have to
    guess between them.
    """
    path = Path(pid_path)
    if not path.is_file():
        return LOOP_UNKNOWN, f"无面板记录（{path} 不存在）"
    try:
        recorded = int((path.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError) as error:
        return LOOP_UNKNOWN, f"面板记录无法解析：{error}"
    if recorded <= 0:
        return LOOP_STOPPED, "面板记录为空 pid"
    try:
        from . import winproc
        return (LOOP_RUNNING, f"面板进程 {recorded} 存活") if winproc.alive(recorded) \
            else (LOOP_STOPPED, f"面板进程 {recorded} 已不在")
    except Exception:  # noqa: BLE001 - a liveness probe must never take the console down
        return LOOP_UNKNOWN, f"无法判定面板进程 {recorded} 是否存活"


def console_fields(path: Path | str = DEFAULT_PATH, now: datetime | None = None,
                   pid_path: Path | str = PANEL_PID_PATH) -> dict[str, str]:
    """The seven lines §9 requires, derived from the record and the panel's own pid file."""
    state = load(path)
    moment = now or _now()
    liveness, why = loop_liveness(pid_path)
    if state.mode == MODE_MANUAL:
        machine = "WorkBuddy 开发中"
        back = state.completion_criteria or "（未登记完成标准）"
        if state.decision_due(moment):
            back = "已达预计时长，必须决策：暂停回切 或 申请延长（§5）"
    else:
        # 2026-10-06: this used to print 系统运行中 whenever the mode was AUTO.  It now says what
        # the panel's own pid file says, and names the disagreement instead of hiding it -- "the
        # mode is Auto" and "Auto is running" are two different facts and only one of them was
        # being checked.
        if liveness == LOOP_RUNNING:
            machine = "系统运行中"
        elif liveness == LOOP_STOPPED:
            machine = "系统未运行（AUTO 已停）"
        else:
            machine = "系统状态未知"
        back = "用户指令（§4 触发 2：WorkBuddy 不得自主切回 Manual）" if state.user_latch \
            else "无需回切：当前已是 Auto"

    remaining = state.remaining_seconds(moment)
    fields = {
        "当前模式": state.mode,
        "机器状态": machine,
        "切换发起方": state.initiator,
        "切换理由": state.reason or "（未登记）",
        "已持续": _human(state.elapsed_seconds(moment)),
        "预计剩余": _human(remaining) if remaining is not None else "（未登记预计时长）",
        "回切条件": back,
        "循环存活": f"{liveness}（{why}）",
    }
    if state.mode == MODE_AUTO and liveness != LOOP_RUNNING:
        fields["不一致"] = (
            f"模式是 Auto 但 AUTO 并未运行（{why}）。§7 的收尾只负责把模式交还，"
            "不负责把循环拉起来；要真跑需要显式启动面板。"
        )
    if state.overdue(moment):
        fields["警告"] = (
            f"Manual 已超过预计时长 {OVERDUE_MULTIPLIER:g} 倍（§13）—— 控制台须高亮；"
            "用户可强制切 Auto"
        )
    if state.needs_wrap_up():
        fields["收尾"] = "本轮改过代码且未收尾（§7 情况 1）：" + ", ".join(state.wrap_up_missing())
    if state.crash_reason:
        fields["恢复"] = state.crash_reason
    return fields


#: Everything the caller must supply to exercise §4 trigger 3's three conditions.
AUTONOMOUS_REFUSAL = (
    "\"I want to develop\" and \"I feel like doing something\" are not reasons (§4 trigger 3). "
    "Name the feature / page / path / skill / failure being verified, the expected duration, and "
    "what counts as done."
)


def autonomous_switch_check(
    *, reason: str, expected_seconds: float | None, completion_criteria: str
) -> tuple[bool, str]:
    """§4 trigger 3 conditions 1 and 2, as a check rather than a convention."""
    stripped = (reason or "").strip()
    if len(stripped) < 12:
        return False, AUTONOMOUS_REFUSAL
    if not (completion_criteria or "").strip():
        return False, "a switch must register its completion criteria (§4 condition 2)"
    if not expected_seconds or expected_seconds <= 0:
        return False, "a switch must register an expected duration (§4 condition 2)"
    vague = ("想开发", "该做点什么", "随便看看", "探索一下")
    if any(word in stripped for word in vague):
        return False, AUTONOMOUS_REFUSAL
    return True, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto/Manual machine-ownership mode (docs/MODE_SYSTEM.md)")
    parser.add_argument("--state", default=str(DEFAULT_PATH))
    parser.add_argument("--pid-path", default=str(PANEL_PID_PATH),
                        help="the panel's own pid file; §9's 机器状态 is read from it")
    parser.add_argument("--status", action="store_true", help="print the §9 console fields")
    parser.add_argument("--to-manual", action="store_true")
    parser.add_argument("--to-auto", action="store_true")
    parser.add_argument("--by", default=BY_WORKBUDDY, choices=list(INITIATORS))
    parser.add_argument("--reason", default="")
    parser.add_argument("--expected-minutes", type=float, default=None)
    parser.add_argument("--done-when", default="")
    parser.add_argument("--code-changed", action="store_true")
    parser.add_argument("--expect-mode", default=None, choices=list(MODES))
    parser.add_argument("--decide", default=None, choices=list(DECISIONS))
    parser.add_argument("--new-expected-minutes", type=float, default=None)
    parser.add_argument("--wrap-up", default=None, choices=list(WRAP_UP_STEPS))
    parser.add_argument("--force", action="store_true",
                        help="override the §7 wrap-up gate (recorded in the audit trail)")
    args = parser.parse_args(argv)

    path = Path(args.state)
    try:
        if args.status or not (args.to_manual or args.to_auto or args.decide or args.wrap_up):
            for key, value in console_fields(path, pid_path=args.pid_path).items():
                print(f"{key}：{value}")
            return 0
        if args.decide:
            state = record_decision(
                args.decide,
                new_expected_seconds=(args.new_expected_minutes or 0) * 60 or None,
                path=path,
            )
            print(f"决策已记录：{args.decide}；预计时长 {state.expected_seconds}s")
            return 0
        if args.wrap_up:
            state = mark_wrap_up(args.wrap_up, path=path)
            print(f"收尾步骤已完成：{args.wrap_up}；尚缺 {state.wrap_up_missing() or '无'}")
            return 0
        target = MODE_MANUAL if args.to_manual else MODE_AUTO
        seconds = args.expected_minutes * 60 if args.expected_minutes else None
        if target == MODE_MANUAL and args.by == BY_WORKBUDDY:
            ok, why = autonomous_switch_check(
                reason=args.reason, expected_seconds=seconds, completion_criteria=args.done_when
            )
            if not ok:
                print(f"拒绝自主切换：{why}", file=sys.stderr)
                return 2
        state = switch(
            target,
            initiator=args.by,
            reason=args.reason,
            expected_mode=args.expect_mode,
            expected_seconds=seconds,
            completion_criteria=args.done_when,
            code_changed=args.code_changed,
            force=args.force,
            path=path,
        )
        print(f"当前模式：{state.mode}（发起方 {state.initiator}）")
        return 0
    except ModeRefused as refused:
        print(f"拒绝切换：{refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
