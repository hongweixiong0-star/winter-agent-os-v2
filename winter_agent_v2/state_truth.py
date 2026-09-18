"""Truth Source Audit — every displayed state names its source, or says it does not know.

Why this exists
---------------
The operator reported a GUI cell that read ``current_role = xhw`` while the real client
was logged in as a different role.  The cause was not a stale cache: the panel printed a
**string literal** (``tools/control_panel.py``: ``text="xhw"``), next to another literal
(``● 在线``) that claimed the device was online no matter what it was doing.  A constant
that looks like an observation is worse than no value at all, because it cannot be told
apart from a measured one.

So the rule this module enforces is the operator's own ladder, and it is enforced by
`TruthAudit` refusing to return a value without a provenance record:

```
LIVE OBSERVED
  > fresh verified runtime state
  > persisted last-known state
  > expected / requested state
```

A cached or persisted value is allowed to *help recovery*.  It is not allowed to
impersonate a currently-observed one.  Anything past its freshness budget must read
``STALE`` / ``UNKNOWN`` / ``CONFLICT`` — never a confident-looking old number.

Deliberately **not** a second WorldState.  This is a read-only projection over artifacts
that already exist (runtime snapshot, episode stream, executor ledger, escalation ledger,
device lease, role probe, capability catalog).  It stores nothing; delete it and every
question is answerable again from the same files.  Same shape as ``capability_gate``.

The five questions each state must answer (operator, 2026-09-18):

1. what is the truth source?
2. when was it last confirmed?
3. what is the evidence?
4. which role / session / episode / version does it belong to?
5. is it expired right now?
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------- provenance status

LIVE_OBSERVED = "LIVE_OBSERVED"        # read off the device, with a frame behind it
FRESH_RUNTIME = "FRESH_RUNTIME"        # the running process wrote it just now
PERSISTED = "PERSISTED"                # last known value, older than its budget
REQUESTED = "REQUESTED"                # what we asked for -- not evidence it happened
CATALOG_DERIVED = "CATALOG_DERIVED"    # derived from a maintained artifact, not a fresh read
ASSUMED = "ASSUMED"                    # a literal or a default: must be eliminated
UNKNOWN = "UNKNOWN"
STALE = "STALE"
CONFLICT = "CONFLICT"

# Worst-last, so a sort or a max() reads as "how much can this be trusted".
# ``ASSUMED`` sits below ``PERSISTED`` on purpose: an old measurement is a fact about the
# past, a literal is a claim about nothing.
STATUS_RANK: dict[str, int] = {
    CONFLICT: -1,      # not a low score -- an unresolved question, like TRUST_RANK[CONFLICT]
    UNKNOWN: 0,
    ASSUMED: 1,
    REQUESTED: 2,
    CATALOG_DERIVED: 3,
    STALE: 4,
    PERSISTED: 5,
    FRESH_RUNTIME: 6,
    LIVE_OBSERVED: 7,
}

STATUS_ZH: dict[str, str] = {
    LIVE_OBSERVED: "真机观测",
    FRESH_RUNTIME: "运行时新鲜",
    PERSISTED: "持久化（上次已知）",
    REQUESTED: "已请求（未证实）",
    CATALOG_DERIVED: "总表推导（非真机）",
    ASSUMED: "假定值（必须消除）",
    UNKNOWN: "未知",
    STALE: "已过期",
    CONFLICT: "冲突",
}

# A value that needs a frame behind it goes stale faster than one the runtime republishes.
FRESH_RUNTIME_SECONDS = 120.0
LIVE_OBSERVED_SECONDS = 6 * 3600.0
PERSISTED_SECONDS = 7 * 24 * 3600.0


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _probe_stamp(text: str) -> str:
    """``20260916_184004`` -> an ISO stamp.  Shaped by the probe that writes it.

    The underscore matters: an earlier version tested ``isdigit()`` over the whole
    string and therefore silently produced no timestamp at all, which read as "this
    observation has no date" instead of "this observation is two days old".
    """
    digits = re.sub(r"\D", "", text or "")
    if len(digits) != 14:
        return ""
    return (f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}T"
            f"{digits[8:10]}:{digits[10:12]}:{digits[12:14]}+00:00")


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _tail_jsonl(path: Path, count: int) -> tuple[Mapping[str, Any], ...]:
    """The last ``count`` well-formed rows.  Skips a half-written trailing line."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    rows: list[Mapping[str, Any]] = []
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(payload)
        if len(rows) >= count:
            break
    rows.reverse()
    return tuple(rows)


# ------------------------------------------------------------------ the value object


@dataclass
class TruthValue:
    """One state, with everything needed to judge whether to believe it."""

    name: str
    value: str = ""
    status: str = UNKNOWN
    source: str = ""
    observed_at: str = ""
    age_seconds: float | None = None
    role_id: str = ""
    episode: str = ""
    version: str = ""
    evidence: tuple[str, ...] = ()
    verification: str = ""      # "", PASS, FAIL, UNVERIFIED
    note: str = ""
    # Where the same fact was also seen, so a disagreement is visible instead of resolved
    # by whoever read last.
    seen: tuple[tuple[str, str], ...] = ()

    @property
    def stale(self) -> bool:
        return self.status in (STALE, UNKNOWN, CONFLICT, ASSUMED)

    @property
    def display(self) -> str:
        """What a window may print.  A value never travels without its qualifier."""
        if self.status in (UNKNOWN, ASSUMED):
            return f"{UNKNOWN}（{STATUS_ZH.get(self.status, self.status)}）"
        if self.status == STALE:
            return f"{self.value or UNKNOWN} · 已过期"
        if self.status == CONFLICT:
            return f"{self.value or UNKNOWN} · 冲突"
        return self.value or UNKNOWN

    def as_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "status_zh": STATUS_ZH.get(self.status, self.status),
            "source": self.source,
            "observed_at": self.observed_at,
            "age_seconds": None if self.age_seconds is None else round(self.age_seconds, 1),
            "role_id": self.role_id,
            "episode": self.episode,
            "version": self.version,
            "evidence": list(self.evidence),
            "verification": self.verification,
            "note": self.note,
            "seen_elsewhere": [f"{where}={what}" for where, what in self.seen],
        }


@dataclass
class Conflict:
    """Two artifacts disagree about the same fact, and nobody may silently pick one."""

    name: str
    readings: tuple[tuple[str, str], ...]
    note: str = ""

    def describe(self) -> str:
        joined = " vs ".join(f"{where}={what}" for where, what in self.readings)
        return f"STATE_CONFLICT {self.name}: {joined}" + (f" ({self.note})" if self.note else "")


@dataclass
class TruthReport:
    values: tuple[TruthValue, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    role_id: str = ""
    role_status: str = UNKNOWN
    head: str = ""
    generated_at: str = ""

    def by_name(self, name: str) -> TruthValue | None:
        for value in self.values:
            if value.name == name:
                return value
        return None

    def conflicts_for(self, name: str) -> tuple[Conflict, ...]:
        return tuple(c for c in self.conflicts if c.name == name)

    def worst(self) -> tuple[TruthValue, ...]:
        """Everything that must not be shown as if it were a current fact."""
        return tuple(v for v in self.values if v.stale)

    def line(self) -> str:
        stale = len(self.worst())
        return (
            f"[truth] {len(self.values)} states · {stale} not current"
            f" · {len(self.conflicts)} conflict(s)"
            f" · role {self.role_id or UNKNOWN} ({STATUS_ZH.get(self.role_status, self.role_status)})"
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "head": self.head,
            "role_id": self.role_id,
            "role_status": self.role_status,
            "states": [v.as_row() for v in self.values],
            "conflicts": [
                {"name": c.name, "readings": [f"{w}={v}" for w, v in c.readings], "note": c.note}
                for c in self.conflicts
            ],
        }


# ------------------------------------------------------------------------ the audit


ROLE_PROBE_DIR = "dataset/truth_audit/role_identity_20260916"
ROLE_ARTIFACT = "learning/role_identity.json"
SNAPSHOT = "learning/runtime_snapshot.json"
EPISODES = "learning/episodes.jsonl"
EXECUTOR_LEDGER = "learning/executor_backend.jsonl"
ESCALATIONS = "learning/workbuddy_escalations.jsonl"
DEVICE_LEASE = "learning/DEVICE_LEASE.json"
BACKEND_ROUTING = "knowledge/execution/backend_routing.json"
TOOL_REGISTRY = "knowledge/tooling/tool_registry.json"
EVENT_STATE = "learning/event_goal_state.json"
PUMP = "learning/control_panel/pump.json"


class TruthAudit:
    """Read-only projection: every key state, with provenance and a freshness verdict."""

    def __init__(self, root: Path | str, *, now: datetime | None = None) -> None:
        self.root = Path(root)
        self.now = now or datetime.now(timezone.utc)
        self._snapshot = _read_json(self.root / SNAPSHOT)
        self._episodes = _tail_jsonl(self.root / EPISODES, 3)
        self._all_episodes_cache: tuple[Mapping[str, Any], ...] | None = None
        self._executor = _tail_jsonl(self.root / EXECUTOR_LEDGER, 2)
        self._pump = _read_json(self.root / PUMP)
        self._conflicts: list[Conflict] = []

    @property
    def _all_episodes(self) -> tuple[Mapping[str, Any], ...]:
        """The whole episode stream, read at most once per audit.

        Lazy because it is four megabytes and most states do not need it: the panel asks
        this question on a slower cadence than it asks for the page, and paying for the
        whole stream on every refresh would make the window stutter for a number nobody
        looks at that often.
        """
        if self._all_episodes_cache is None:
            self._all_episodes_cache = _tail_jsonl(self.root / EPISODES, 5000)
        return self._all_episodes_cache

    # -- primitives --------------------------------------------------------

    def _age(self, stamp: str) -> float | None:
        moment = _moment(stamp)
        if moment is None:
            return None
        return (self.now - moment).total_seconds()

    def _grade(self, *, live: bool, age: float | None) -> str:
        if age is None:
            return PERSISTED
        if live and age <= LIVE_OBSERVED_SECONDS:
            return LIVE_OBSERVED
        if age <= FRESH_RUNTIME_SECONDS:
            return FRESH_RUNTIME
        if age <= PERSISTED_SECONDS:
            return PERSISTED
        return STALE

    def _stamp(self, source: str, stamp: str, *, live: bool = False) -> tuple[str, float | None]:
        """A provenance stamp plus the status its age earns.  Never a bare value."""
        age = self._age(stamp)
        return self._grade(live=live, age=age), age

    def _episode_stamp(self, episode_id: str, recorded_at: str) -> tuple[str, float | None]:
        return self._stamp(f"episode {episode_id}", recorded_at, live=True)

    def _snapshot_stamp(self) -> tuple[str, float | None]:
        return self._stamp(SNAPSHOT, str(self._snapshot.get("updated_at") or ""))

    def _head(self) -> str:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(self.root),
                capture_output=True, text=True, timeout=15,
            )
            return (out.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    # -- the role, which everything else must be scoped by ----------------

    def role(self) -> TruthValue:
        """Which role the client is logged in as -- or an honest admission that we do not know.

        The operator's product definition makes this a *precondition* for every other
        metric, because the corpus was already built from two accounts with different
        power and different march slots.  So it gets the strictest treatment here: the
        only acceptable sources are a vision read of the 领主档案 panel (``LIVE_OBSERVED``,
        with the frame on disk) or a persisted copy of one (``PERSISTED``/``STALE``).
        A configured name, a panel literal or a default are all ``ASSUMED``, and the
        display must say so.
        """
        artifact = _read_json(self.root / ROLE_ARTIFACT)
        probe = _read_json(self.root / ROLE_PROBE_DIR / "probe.json")
        frame = self.root / ROLE_PROBE_DIR / "profile_panel_live_20260916T184004.png"

        evidence: list[str] = []
        source = ""
        observed_at = ""
        role_id = ""
        role_name = ""
        verification = ""

        if artifact.get("role_id"):
            source = ROLE_ARTIFACT
            observed_at = str(artifact.get("observed_at") or "")
            role_id = str(artifact.get("role_id") or "")
            role_name = str(artifact.get("role_name") or "")
            verification = str(artifact.get("verification") or "VISION_READ")
            evidence = [str(p) for p in (artifact.get("evidence") or ())][:3]
        elif probe:
            # The archived probe is a real observation with a real frame; it is simply old.
            source = f"{ROLE_PROBE_DIR}/probe.json"
            observed_at = _probe_stamp(str(probe.get("stamp") or ""))
            for token in probe.get("candidate_identity_tokens") or ():
                text = str((token or {}).get("text") or "")
                if text.startswith("账号："):
                    role_id = text.split("：", 1)[1].strip()
                elif text.startswith("[") and "]" in text:
                    role_name = text.split("]", 1)[1].strip()
                elif text and not role_name and "领主档案" not in text and "：" not in text:
                    role_name = text
            verification = "VISION_READ"
            if frame.exists():
                evidence = [frame.as_posix()]

        if not role_id and not role_name:
            return TruthValue(
                name="current_role", value="", status=UNKNOWN,
                source="(no observation on file)",
                note=("没有任何角色观测记录；GUI 不得用配置名或默认值代替 —— "
                      "这正是「界面显示 xhw、真机不是 xhw」那类缺陷的来源"),
                verification="",
            )

        status, age = self._stamp(source, observed_at, live=bool(artifact.get("observed_at")))
        if artifact.get("observed_at") and status != LIVE_OBSERVED:
            status = STALE if age is not None and age > PERSISTED_SECONDS else PERSISTED
        note = ""
        if status in (PERSISTED, STALE):
            note = (
                "这是**上一次已知**的角色，不是当前真机确认值；"
                "任何 role-scoped 状态都必须按此标注，不得当作当前事实。"
            )
        return TruthValue(
            name="current_role",
            value=f"{role_name}（账号 {role_id}）" if role_name else f"账号 {role_id}",
            status=status, source=source, observed_at=observed_at, age_seconds=age,
            role_id=role_id, evidence=tuple(evidence), verification=verification, note=note,
        )

    # -- runtime states ----------------------------------------------------

    def current_page(self) -> TruthValue:
        page = str(self._snapshot.get("page") or "")
        status, age = self._snapshot_stamp()
        seen: list[tuple[str, str]] = []
        for episode in reversed(self._episodes):
            after = (episode.get("state_after") or {})
            if isinstance(after, Mapping) and after.get("page"):
                seen.append((f"episode {episode.get('episode_id')}", str(after["page"])))
                if page and str(after["page"]) != page:
                    self._conflicts.append(Conflict(
                        "current_page",
                        ((SNAPSHOT, page), (f"episode {episode.get('episode_id')}", str(after["page"]))),
                        "运行时快照与最近一条生产 episode 的 state_after 不一致",
                    ))
                break
        return TruthValue(
            name="current_page", value=page, status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            episode=str((self._episodes[-1] or {}).get("episode_id") or "") if self._episodes else "",
            evidence=(), verification="", seen=tuple(seen),
        )

    def current_goal(self) -> TruthValue:
        goal = str(self._snapshot.get("current_goal") or "")
        status, age = self._snapshot_stamp()
        seen: list[tuple[str, str]] = []
        for episode in reversed(self._episodes):
            if episode.get("goal_id"):
                seen.append((f"episode {episode.get('episode_id')}", str(episode["goal_id"])))
                if goal and str(episode["goal_id"]) != goal:
                    self._conflicts.append(Conflict(
                        "current_goal",
                        ((SNAPSHOT, goal), (f"episode {episode.get('episode_id')}", str(episode["goal_id"]))),
                        "快照与最近 episode 的 goal_id 不一致",
                    ))
                break
        return TruthValue(
            name="current_goal", value=goal, status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            seen=tuple(seen),
        )

    def current_skill(self) -> TruthValue:
        skill = str(self._snapshot.get("current_skill") or "")
        status, age = self._snapshot_stamp()
        seen: list[tuple[str, str]] = []
        for episode in reversed(self._episodes):
            if episode.get("skill"):
                seen.append((f"episode {episode.get('episode_id')}", str(episode["skill"])))
                break
        return TruthValue(
            name="current_skill", value=skill, status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            episode=str((self._episodes[-1] or {}).get("episode_id") or "") if self._episodes else "",
            seen=tuple(seen),
        )

    def auto_state(self) -> TruthValue:
        state = str(self._snapshot.get("agent_state") or "")
        status, age = self._snapshot_stamp()
        return TruthValue(
            name="auto_state", value=f"{state}（{self._snapshot.get('mode') or '-'}）",
            status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            verification=str(self._snapshot.get("verifier") or ""),
            note="面板进程是否还在，是另一个问题（见 panel_heartbeat）",
        )

    def panel_heartbeat(self) -> TruthValue:
        stamp = str(self._pump.get("written_at") or "")
        status, age = self._stamp(PUMP, stamp)
        alive = status in (FRESH_RUNTIME, LIVE_OBSERVED)
        return TruthValue(
            name="panel_heartbeat",
            value=f"pid {self._pump.get('process') or '?'}",
            status=status if alive else STALE, source=PUMP, observed_at=stamp, age_seconds=age,
            note="看门狗据此判断面板是否真的在运行",
        )

    def march_capacity(self) -> TruthValue:
        used = self._snapshot.get("march_used")
        maximum = self._snapshot.get("march_max")
        status, age = self._snapshot_stamp()
        if used is None and maximum is None:
            return TruthValue(
                name="march_capacity", value="", status=UNKNOWN, source=SNAPSHOT,
                observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
                note="快照里没有行军占用/容量",
            )
        role = self.role()
        note = ""
        if role.status != LIVE_OBSERVED:
            # The marching capacity is a property of the *account*: the audited corpus
            # already contains 6 slots for one account and 2 for another.  A number whose
            # role is only "last known" is therefore not scoped to the current role, and
            # saying so is the whole point -- the operator's case was exactly a value that
            # belonged to one account being shown while another was logged in.
            note = (
                f"未按当前角色确认：角色状态为「{STATUS_ZH.get(role.status, role.status)}」；"
                f"容量可能属于另一个账号（上次已知 {role.value or '未知'}）"
            )
        # A number that cannot be true is a conflict, not a reading.  Found live: the
        # snapshot reported ``march_used=21`` against ``march_max=3`` and the window drew
        # it without complaint, which is exactly "displayed state disconnected from the
        # client" -- the failure mode this audit exists to surface.
        try:
            used_int, max_int = int(used), int(maximum)
        except (TypeError, ValueError):
            used_int = max_int = None
        if used_int is not None and max_int is not None and max_int > 0 and used_int > max_int:
            self._conflicts.append(Conflict(
                "march_capacity",
                ((SNAPSHOT, f"{used_int}/{max_int}"),
                 ("invariant", f"行军占用不可能超过容量 {max_int}")),
                "占用大于容量：这两个数不是同一时刻/同一角色的读数",
            ))
            return TruthValue(
                name="march_capacity", value=f"{used_int}/{max_int}", status=CONFLICT,
                source=SNAPSHOT, observed_at=str(self._snapshot.get("updated_at") or ""),
                age_seconds=age, role_id=role.role_id,
                note=(note + "；" if note else "")
                     + f"占用 {used_int} 超过容量 {max_int}，不是可信读数",
            )
        return TruthValue(
            name="march_capacity", value=f"{used}/{maximum}" if maximum is not None else str(used),
            status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            role_id=role.role_id, note=note,
        )

    def resources(self) -> TruthValue:
        for episode in reversed(self._episodes):
            after = episode.get("state_after") or {}
            if isinstance(after, Mapping) and after.get("resources"):
                status, age = self._episode_stamp(
                    str(episode.get("episode_id") or ""), str(episode.get("recorded_at") or "")
                )
                resources = after["resources"]
                return TruthValue(
                    name="resources",
                    value=", ".join(f"{k}={v}" for k, v in list(resources.items())[:5]),
                    status=status, source=f"episode {episode.get('episode_id')} state_after",
                    observed_at=str(episode.get("recorded_at") or ""), age_seconds=age,
                    episode=str(episode.get("episode_id") or ""),
                    role_id=self.role().role_id,
                    evidence=tuple(
                        p for p in (episode.get("after_screenshot"),) if isinstance(p, str)
                    ),
                )
        return TruthValue(
            name="resources", value="", status=UNKNOWN, source=EPISODES,
            note=("最近 3 条 episode 的 state_after 里没有资源读数 —— "
                  "「没读到」不是「没有资源」，不得显示为 0"),
        )

    def queues(self) -> TruthValue:
        queues = self._snapshot.get("queues") or {}
        status, age = self._snapshot_stamp()
        if not isinstance(queues, Mapping) or not any(queues.values()):
            return TruthValue(
                name="queues", value="", status=UNKNOWN, source=SNAPSHOT,
                observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
                note=("快照里建筑/科研/训练/情报/联盟/活动队列都是空的 —— "
                      "空是「没读到」，不是「没有任务」"),
            )
        filled = {k: v for k, v in queues.items() if v}
        return TruthValue(
            name="queues", value=", ".join(f"{k}={v}" for k, v in list(filled.items())[:4]),
            status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
        )

    def feature_unlock(self) -> TruthValue:
        catalog = self.root / "knowledge/game/capability_catalog.json"
        payload = _read_json(catalog)
        capabilities = payload.get("capabilities") or ()
        if not capabilities:
            return TruthValue(name="feature_unlock", value="", status=UNKNOWN, source=str(catalog))
        observed = sum(
            1 for row in capabilities
            if str((row or {}).get("current_role_available")) == "OBSERVED_AVAILABLE"
        )
        return TruthValue(
            name="feature_unlock",
            value=f"{observed}/{len(capabilities)} 项标记为当前角色可用",
            status=CATALOG_DERIVED, source="knowledge/game/capability_catalog.json",
            observed_at=str(payload.get("generated_at") or ""),
            age_seconds=self._age(str(payload.get("generated_at") or "")),
            note=("总表推导，不是真机解锁检查；且未绑定角色 —— 换角色后必须重新推导"),
        )

    def event_state(self) -> TruthValue:
        payload = _read_json(self.root / EVENT_STATE)
        if not payload:
            return TruthValue(
                name="event_state", value="", status=UNKNOWN, source=EVENT_STATE,
                note="没有活动状态文件；「没有活动」与「没读到活动」必须区分",
            )
        stamp = str(payload.get("updated_at") or payload.get("recorded_at") or "")
        status, age = self._stamp(EVENT_STATE, stamp)
        return TruthValue(
            name="event_state",
            value=", ".join(f"{k}={v}" for k, v in list(payload.items())[:4]),
            status=status, source=EVENT_STATE, observed_at=stamp, age_seconds=age,
        )

    # -- execution, evidence and version ----------------------------------

    def executor_backend(self) -> TruthValue:
        if not self._executor:
            return TruthValue(
                name="executor_backend", value="", status=UNKNOWN, source=EXECUTOR_LEDGER,
                note="没有执行器台账行",
            )
        row = self._executor[-1]
        stamp = str(row.get("recorded_at") or row.get("at") or "")
        status, age = self._stamp(EXECUTOR_LEDGER, stamp, live=True)
        used = row.get("used_backend") or row.get("backend") or row.get("executor_backend") or ""
        capture = row.get("capture_backend") or ""
        return TruthValue(
            name="executor_backend",
            value=f"{used}" + (f" / 截图 {capture}" if capture else ""),
            status=status, source=EXECUTOR_LEDGER, observed_at=stamp, age_seconds=age,
            note="这是**实际用过**的后端，不是配置里写的偏好",
        )

    def version_active(self) -> TruthValue:
        head = self._head()
        for episode in reversed(self._episodes):
            revision = str(episode.get("repo_revision") or "")
            if not revision:
                continue
            status, age = self._episode_stamp(
                str(episode.get("episode_id") or ""), str(episode.get("recorded_at") or "")
            )
            running = revision.split("+")[0]
            conflict = bool(head) and not (head.startswith(running) or running.startswith(head[:7]))
            if conflict:
                # Not a defect by itself -- it is exactly VERSION_ACTIVATION_PENDING -- but
                # it must be *visible*, because a live episode produced by the old tree
                # must never be credited to the new one.
                self._conflicts.append(Conflict(
                    "version_active",
                    (("git HEAD", head[:7]), (f"episode {episode.get('episode_id')}", running[:7])),
                    "生产仍在跑旧树；新版本的 episode 尚未产生",
                ))
            return TruthValue(
                name="version_active", value=running[:7] or revision,
                status=CONFLICT if conflict else status,
                source=f"episode {episode.get('episode_id')} repo_revision",
                observed_at=str(episode.get("recorded_at") or ""), age_seconds=age,
                version=revision, episode=str(episode.get("episode_id") or ""),
                note=f"HEAD={head[:7]}" if head else "",
            )
        return TruthValue(
            name="version_active", value=head[:7], status=REQUESTED, source="git HEAD",
            version=head, note="没有带 repo_revision 的 episode：新版本是否已生效无法证明",
        )

    def verifier(self) -> TruthValue:
        for episode in reversed(self._episodes):
            if "verifier_ok" not in episode:
                continue
            ok = episode.get("verifier_ok")
            status, age = self._episode_stamp(
                str(episode.get("episode_id") or ""), str(episode.get("recorded_at") or "")
            )
            return TruthValue(
                name="verifier",
                value=f"{'PASS' if ok else 'FAIL'} · skill={episode.get('skill')}"
                      f" · goal={episode.get('goal_id')}",
                status=status, source=f"episode {episode.get('episode_id')} verifier_ok",
                observed_at=str(episode.get("recorded_at") or ""), age_seconds=age,
                episode=str(episode.get("episode_id") or ""),
                verification="PASS" if ok else "FAIL",
                note=("单条 episode 的 verifier 结果；只有它属于**当前生效版本**时才可用来判定能力"),
            )
        return TruthValue(
            name="verifier", value="", status=UNKNOWN, source=EPISODES,
            note="没有带 verifier_ok 的 episode",
        )

    def workbuddy_jobs(self) -> TruthValue:
        from .escalation_queue import EscalationLedger, fold

        try:
            snapshot = fold(EscalationLedger(self.root / ESCALATIONS).events())
        except Exception as exc:  # noqa: BLE001
            return TruthValue(
                name="workbuddy_jobs", value="", status=UNKNOWN, source=ESCALATIONS,
                note=f"台账不可读：{type(exc).__name__}",
            )
        records = list(snapshot.records.values())
        if not records:
            # An empty ledger and a missing ledger are the same thing here: nothing has
            # been filed, which is a fact about the queue but not a freshness claim.
            return TruthValue(
                name="workbuddy_jobs", value="", status=UNKNOWN, source=ESCALATIONS,
                note="台账为空：还没有任何升级记录，不得显示成「队列正常」",
            )
        counts: dict[str, int] = {}
        for record in records:
            counts[record.state] = counts.get(record.state, 0) + 1
        new = counts.get("NEW", 0) + counts.get("QUEUED", 0)
        working = [r for r in records if r.state in ("WORKING", "SUBMITTED")]
        value = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        note = ""
        if new and not working:
            # The exact GUI lie the operator caught once before: "排队中" over an empty
            # pipeline, or worse, a queue that says nothing while records sit unconsumed.
            note = f"{new} 条仍未被消费（NEW/QUEUED）——不得显示成「开发中」"
        stamp = datetime.fromtimestamp(
            (self.root / ESCALATIONS).stat().st_mtime, tz=timezone.utc
        ).isoformat()
        return TruthValue(
            name="workbuddy_jobs", value=value, status=FRESH_RUNTIME, source=ESCALATIONS,
            observed_at=stamp, age_seconds=self._age(stamp), note=note,
        )

    def device_lease(self) -> TruthValue:
        payload = _read_json(self.root / DEVICE_LEASE)
        if not payload:
            return TruthValue(
                name="device_lease", value="idle", status=CATALOG_DERIVED, source=DEVICE_LEASE,
                note=("没有租约文件 = 游戏端持有设备（在唯一那把锁上定义），这是正常情况；"
                      "但它是一个由文件存在性推出的读数，不是新鲜观测"),
            )
        released = bool(payload.get("released_at"))
        return TruthValue(
            name="device_lease",
            value=f"{payload.get('owner')}" + ("（已归还）" if released else "（持有中）"),
            status=FRESH_RUNTIME if released else LIVE_OBSERVED, source=DEVICE_LEASE,
            observed_at=str(payload.get("released_at") or payload.get("acquired_at") or ""),
            age_seconds=self._age(str(payload.get("released_at") or payload.get("acquired_at") or "")),
            note=f"trace={payload.get('trace_id') or '-'} job={payload.get('job_id') or '-'}",
        )

    def episode_role_scope(self) -> TruthValue:
        """Are the episodes we draw conclusions from actually scoped to this role?

        This is the operator's role-isolation question, made answerable.  The corpus was
        already pooled from two accounts with different power and different march slots, so
        a metric computed across episodes is an average of two different players unless the
        episodes carry a role.  The field was added to the schema on 2026-09-18; every
        episode written before that is permanently unscoped, and saying so is the honest
        reading -- not a gap to be filled in by guessing.
        """
        role = self.role()
        total = len(self._all_episodes)
        scoped = [e for e in self._all_episodes if e.get("role_id")]
        mine = [e for e in scoped if str(e.get("role_id")) == role.role_id] if role.role_id else []
        foreign = [e for e in scoped
                   if role.role_id and str(e.get("role_id")) != role.role_id]
        note = (f"{len(scoped)}/{total} 条 episode 带角色；"
                f"{len(mine)} 条属于上次已知角色 {role.value or '未知'}")
        if foreign and self._recent(foreign):
            self._conflicts.append(Conflict(
                "episode_role_scope",
                (("current_role", role.role_id or "UNKNOWN"),
                 ("recent episodes", ", ".join(sorted({str(e.get("role_id")) for e in foreign})[:3]))),
                "有别的角色的 episode 混在同一份语料里 —— 任何跨 episode 的统计都必须是分角色的",
            ))
            return TruthValue(
                name="episode_role_scope", value=f"{len(scoped)}/{total}",
                status=CONFLICT, source=EPISODES, role_id=role.role_id,
                note=note + "；发现非当前角色的 episode",
            )
        if not scoped:
            return TruthValue(
                name="episode_role_scope", value=f"0/{total}", status=UNKNOWN,
                source=EPISODES, role_id=role.role_id,
                note=note + "；**全部未按角色限定** —— 跨 episode 统计不得当作单角色结论",
            )
        status, age = self._episode_stamp(
            str(scoped[-1].get("episode_id") or ""), str(scoped[-1].get("recorded_at") or "")
        )
        return TruthValue(
            name="episode_role_scope", value=f"{len(scoped)}/{total}", status=status,
            source=EPISODES, observed_at=str(scoped[-1].get("recorded_at") or ""),
            age_seconds=age, role_id=role.role_id, note=note,
        )

    def _recent(self, episodes: Sequence[Mapping[str, Any]], within: int = 200) -> bool:
        """Are any of these among the most recent rows?  Old history is not a live conflict."""
        recent_ids = {e.get("episode_id") for e in self._all_episodes[-within:]}
        return any(e.get("episode_id") in recent_ids for e in episodes)

    def capability_lifecycle(self) -> TruthValue:
        catalog = _read_json(self.root / "knowledge/game/capability_catalog.json")
        rows = catalog.get("capabilities") or ()
        if not rows:
            return TruthValue(
                name="capability_lifecycle", value="", status=UNKNOWN,
                source="knowledge/game/capability_catalog.json",
                note="能力总表不可读：生命周期状态未知",
            )
        counts: dict[str, int] = {}
        verified_with_episode = 0
        for row in rows:
            lifecycle = str((row or {}).get("lifecycle") or "?")
            counts[lifecycle] = counts.get(lifecycle, 0) + 1
            if lifecycle == "LIVE_VERIFIED" and int((row or {}).get("live_attempts") or 0) > 0:
                verified_with_episode += 1
        return TruthValue(
            name="capability_lifecycle",
            value=" · ".join(f"{k} {v}" for k, v in sorted(counts.items())),
            status=CATALOG_DERIVED, source="knowledge/game/capability_catalog.json",
            note=(f"LIVE_VERIFIED {counts.get('LIVE_VERIFIED', 0)} 项中 "
                  f"{verified_with_episode} 项带有真机尝试记录；其余是总表状态，不是本轮证据"),
        )

    # -- the report --------------------------------------------------------

    def report(self) -> TruthReport:
        role = self.role()
        values = (
            role,
            self.current_page(), self.current_goal(), self.current_skill(),
            self.auto_state(), self.panel_heartbeat(),
            self.march_capacity(), self.resources(), self.queues(),
            self.feature_unlock(), self.event_state(),
            self.executor_backend(), self.version_active(), self.verifier(),
            self.workbuddy_jobs(), self.device_lease(), self.capability_lifecycle(),
            self.episode_role_scope(),
        )
        return TruthReport(
            values=values, conflicts=tuple(self._conflicts), role_id=role.role_id,
            role_status=role.status, head=self._head(),
            generated_at=self.now.isoformat(),
        )


def record_role(
    root: Path | str,
    identity: Any,
    *,
    evidence: Sequence[str] = (),
    observed_at: datetime | None = None,
    verification: str = "VISION_READ",
) -> Path:
    """Persist one read of the 领主档案 panel.

    The other half of the role chain.  The vision reader existed and was verified against
    an archived frame (``tools/cq_role_identity_verify.py``), but nothing ever wrote its
    answer anywhere -- so the window had no choice but to print a literal.  This is the
    only function that writes the artifact, and it refuses to write a read with no frame
    behind it: an identity without evidence is the thing that caused the original defect.

    ``observed_at`` is when the **frame** was captured, not when this ran.  A replay of an
    old frame stamped with ``now()`` would make an old observation look current -- the same
    error in the opposite direction, and the reason ``verification`` distinguishes a live
    read from a replay.
    """
    if not getattr(identity, "role_id", ""):
        raise ValueError("refusing to persist a role identity with no role_id")
    if not evidence:
        raise ValueError(
            "refusing to persist a role identity with no evidence frame: an identity "
            "without a frame is indistinguishable from a hardcoded one"
        )
    moment = observed_at or datetime.now(timezone.utc)
    path = Path(root) / ROLE_ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(identity.to_dict() if hasattr(identity, "to_dict") else identity)
    payload.update({
        "observed_at": moment.isoformat(),
        "evidence": list(evidence),
        "verification": verification,
        "written_by": "state_truth.record_role",
    })
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def audited_names() -> tuple[str, ...]:
    """The state names this projection answers for.  One list, so a test can hold it."""
    return (
        "current_role", "current_page", "current_goal", "current_skill",
        "auto_state", "panel_heartbeat", "march_capacity", "resources", "queues",
        "feature_unlock", "event_state", "executor_backend", "version_active",
        "verifier", "workbuddy_jobs", "device_lease", "capability_lifecycle",
        "episode_role_scope",
    )


def scannable_state_names(source: str) -> tuple[str, ...]:
    """State names a *source file* may be allowed to carry as a literal.

    Used by the invariant test: a GUI that hard-codes a ``name="value"`` cell for one of
    these is claiming an observation it never made.  Kept here rather than in the test so
    the list cannot drift away from :func:`audited_names`.
    """
    return tuple(name for name in audited_names() if name in source)
