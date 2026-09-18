"""Knowledge Preload — read once, store once, reuse many times.

Why this exists
---------------
The operator's route change (2026-09-18): the main path for growing V2's capability
set is no longer "run until it fails, then develop from scratch".  It is

    Knowledge Preload -> Capability Preload -> Live Calibration -> LIVE_VERIFIED

with runtime gaps kept as the *catch-up* path (unknown content, UI drift, game
updates, wrong preloads, repeated real failures).

The route only works if knowledge is a **durable artifact**.  Knowledge that lives
in a development agent's context window is re-read next time, which is exactly the
waste the operator named: "说明书只需要认真读一次，知识必须保存下来".  So this
module owns one thing: a per-capability knowledge file under ``knowledge/preload/``
that carries the operator's full field list, where each value is stamped with where
it came from, how sure we are, and whether the real client has confirmed it.

What this module is NOT
-----------------------
Not a skill registry and not a lifecycle authority.  It stores *knowledge about the
game*; which skills exist is still ``winter_agent_v2/skills.py::v2_registry()``, the
capability lifecycle is still ``knowledge/game/capability_catalog.json`` +
``escalation_queue``, and the only writer of a capability's *proven* state remains a
production episode with a passing verifier.  ``tests/test_knowledge_preload.py``
pins that a knowledge record cannot carry a skill into LIVE_VERIFIED.

The four permanent rules, in the operator's words:

    PRELOAD BEFORE ENCOUNTER    prior work is cheap; a wall is expensive
    CALIBRATE ON REAL DEVICE    the real client is the only calibration authority
    LEARN FROM REAL FAILURE     runtime gaps catch what preload missed
    VERIFY BEFORE TRUST         knowledge is a belief until live evidence arrives
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------- trust states

# The operator's own ladder of how much a knowledge value may be trusted.
PRIOR = "PRIOR"                  # external / legacy: right for *their* client, maybe
UNVERIFIED = "UNVERIFIED"        # internal, but no live episode behind it
OBSERVED = "OBSERVED"            # seen on this client (frame / read-back)
CONFIRMED = "CONFIRMED"          # a live episode with a passing verifier proved it
CONFLICT = "CONFLICT"            # prior and live disagree and nobody has resolved it

TRUST_LADDER: tuple[str, ...] = (PRIOR, UNVERIFIED, OBSERVED, CONFIRMED)

# Lower is more trustworthy, so "which value wins" is a comparison and not a guess.
TRUST_RANK: dict[str, int] = {
    PRIOR: 0,
    UNVERIFIED: 1,
    OBSERVED: 2,
    CONFIRMED: 3,
    CONFLICT: -1,   # a conflict is not a lowly value, it is an unresolved question
}


def trusted_enough(status: str) -> bool:
    """May this knowledge carry a capability into preload without a live frame?"""
    return status in (OBSERVED, CONFIRMED)


# ------------------------------------------------------- acquisition rungs

# The operator's nine-rung order, top first.  Position IS the priority, and it is
# written down once.  Rungs 1-5 are LOCAL and must be exhausted before any network
# call: "如果信息已经足够：禁止重新联网研究."
LIVE_VERIFIED_ASSET = "LIVE_VERIFIED_ASSET"
INTERNAL_KNOWLEDGE = "INTERNAL_KNOWLEDGE"
EPISODE_EVIDENCE = "EPISODE_EVIDENCE"
LEGACY_VERIFIED_ASSET = "LEGACY_VERIFIED_ASSET"
FAILURE_PATTERN = "FAILURE_PATTERN"
EXTERNAL_MAP = "EXTERNAL_MAP"
OPEN_SOURCE_PROJECT = "OPEN_SOURCE_PROJECT"
GAME_WIKI = "GAME_WIKI"
SELF_EXPLORATION = "SELF_EXPLORATION"

ACQUISITION_ORDER: tuple[str, ...] = (
    LIVE_VERIFIED_ASSET,
    INTERNAL_KNOWLEDGE,
    EPISODE_EVIDENCE,
    LEGACY_VERIFIED_ASSET,
    FAILURE_PATTERN,
    EXTERNAL_MAP,
    OPEN_SOURCE_PROJECT,
    GAME_WIKI,
    SELF_EXPLORATION,
)

# Rungs 1-5 are on this machine, so consulting them is free and must come first.
LOCAL_RUNGS: frozenset[str] = frozenset(ACQUISITION_ORDER[:5])
# The rungs that reach outside the repository.  Only a named knowledge gap justifies
# them, and only for the specific questions the gap asks.
EXTERNAL_RUNGS: frozenset[str] = frozenset(ACQUISITION_ORDER[5:8])

ACQUISITION_ZH: dict[str, str] = {
    LIVE_VERIFIED_ASSET: "V2 当前 LIVE_VERIFIED 资产",
    INTERNAL_KNOWLEDGE: "当前内部 Knowledge",
    EPISODE_EVIDENCE: "历史 Episode / Screenshot / Evidence",
    LEGACY_VERIFIED_ASSET: "Legacy 已验证资产",
    FAILURE_PATTERN: "Failure Patterns",
    EXTERNAL_MAP: "external_capability_map",
    OPEN_SOURCE_PROJECT: "同游戏成熟开源项目",
    GAME_WIKI: "Wiki / 攻略 / 数据库",
    SELF_EXPLORATION: "真机未知探索（最后手段）",
}


def acquisition_rank(source_type: str) -> int:
    try:
        return ACQUISITION_ORDER.index(source_type) + 1
    except ValueError:
        return len(ACQUISITION_ORDER) + 1


def trust_for_source(source_type: str) -> str:
    """The most a claim from this rung may ever be trusted with.

    Deliberately a ceiling, not a promotion ladder: an answer is capped here and can
    only go higher through live evidence.  ``CONFIRMED`` is unreachable from any rung,
    which is what makes "an external guide can never mark a capability verified" a
    property of the code rather than a promise in a document.
    """
    if source_type == SELF_EXPLORATION:
        return OBSERVED          # the real device looked at it: seen, not yet proved
    if source_type in EXTERNAL_RUNGS:
        return PRIOR             # right for *their* client, maybe
    return UNVERIFIED            # in-repo: believed, no live episode behind it


# --------------------------------------------------------- the field contract

# The operator's field list, verbatim, plus the two bookkeeping fields.  A record is
# "sufficient" for preload only when the gate fields below are all present.
KNOWLEDGE_FIELDS: tuple[str, ...] = (
    "preconditions",
    "navigation",
    "page_semantics",
    "recognition",
    "actions",
    "success_state",
    "failure_states",
    "verifier_prior",
    "recovery_prior",
    "resource_rules",
    "risk",
    "client_specific_notes",
)

# The eight questions the Knowledge Sufficiency Gate asks (operator §七).  Note that
# `failure_states` is *not* in the gate: not knowing every failure mode must not
# block a first candidate, while not knowing what success looks like must.
GATE_FIELDS: tuple[str, ...] = (
    "preconditions",
    "navigation",
    "recognition",
    "actions",
    "success_state",
    "verifier_prior",
    "recovery_prior",
    "risk",
)

GATE_ZH: dict[str, str] = {
    "preconditions": "前置条件",
    "navigation": "导航路线",
    "recognition": "页面/目标识别",
    "actions": "动作",
    "success_state": "成功状态",
    "verifier_prior": "Verifier",
    "recovery_prior": "基础 Recovery",
    "risk": "风险",
}

DEFAULT_DIRECTORY = "knowledge/preload"


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().upper() == "UNKNOWN"
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _text(value: Any) -> str:
    """Render one field for a human, whichever shape the source had."""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value if not _blank(v))
    if isinstance(value, Mapping):
        return "; ".join(f"{k}={v}" for k, v in value.items() if not _blank(v))
    return "" if value is None else str(value)


# ------------------------------------------------------------- the record


@dataclass
class ResearchIngest:
    """What one ingest pass did, counted rather than assumed.

    Kept as a value so the controller can put the counts into its own state file: an
    executor that never writes anything must show up as ``accepted 0``, not as a
    silently quiet loop.
    """

    accepted: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    moved: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def line(self) -> str:
        parts: list[str] = []
        if self.accepted:
            parts.append(f"accepted {len(self.accepted)}")
        if self.rejected:
            parts.append(f"rejected {len(self.rejected)}")
        if self.notes:
            parts.append(f"kept-stronger {len(self.notes)}")
        return "[ingest] " + (", ".join(parts) if parts else "nothing to ingest")


@dataclass
class KnowledgeRecord:
    """One capability's durable knowledge, with provenance on every value.

    ``status`` is the *record's* trust level and ``field_status`` is per-field, so a
    record can be CONFIRMED overall while one field is still a WIKI prior -- which is
    the normal state after a good calibration and exactly what a later diff needs.
    """

    capability: str
    capability_id: str = ""
    game_version: str = ""
    observed_date: str = ""
    source: str = ""
    source_type: str = ""
    source_confidence: float = 0.0
    preconditions: str = ""
    navigation: str = ""
    page_semantics: str = ""
    recognition: str = ""
    actions: str = ""
    success_state: str = ""
    failure_states: str = ""
    verifier_prior: str = ""
    recovery_prior: str = ""
    resource_rules: str = ""
    risk: str = ""
    client_specific_notes: str = ""
    live_calibration_status: str = ""
    # bookkeeping
    status: str = PRIOR
    field_status: dict[str, str] = field(default_factory=dict)
    field_source: dict[str, str] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    # The question a research job was opened for.  Dedup is by
    # ``capability | question | source_type``, so re-reading the same manual is
    # impossible and a *new* question still gets researched.
    question: str = ""
    research_attempts: int = 0
    created_at: str = ""
    updated_at: str = ""
    # Evidence that produced the current status, so a claim is always traceable.
    evidence: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    # -- readers -----------------------------------------------------------

    def value(self, name: str) -> str:
        return _text(getattr(self, name, ""))

    @property
    def known_fields(self) -> tuple[str, ...]:
        return tuple(name for name in GATE_FIELDS if not _blank(self.value(name)))

    @property
    def missing(self) -> tuple[str, ...]:
        """Gate fields with no value.  Computed, never stored stale."""
        return tuple(name for name in GATE_FIELDS if _blank(self.value(name)))

    @property
    def sufficient(self) -> bool:
        enough, _ = sufficiency(self)
        return enough

    def field_trust(self, name: str) -> str:
        return self.field_status.get(name) or self.status

    def headline_status(self) -> str:
        """The record's own trust, derived -- never taken from its best field.

        Two guards, both of which were needed in practice:

        * a record is only as strong as its **shakiest known** field, so one confirmed
          field cannot certify seven doubtful ones;
        * a record with a **hole** can never be CONFIRMED at all.  Without this, a row
          with one CONFIRMED field and seven missing gate fields would read as CONFIRMED
          and ``select()`` would refuse to preload it forever -- the research that
          answered one question would have permanently un-scheduled the capability.
        """
        if not self.known_fields:
            return PRIOR
        weakest = self.weakest_field_trust()
        if self.missing and TRUST_RANK.get(weakest, 0) >= TRUST_RANK[CONFIRMED]:
            return OBSERVED
        return weakest

    def weakest_field_trust(self) -> str:
        """The trust of the *least* confirmed gate field.

        A record is only as good as its shakiest field, and preload decisions should
        be made on that number rather than on the record's headline status.
        """
        ranks = [TRUST_RANK.get(self.field_trust(name), 0) for name in self.known_fields]
        if not ranks:
            return PRIOR
        lowest = min(ranks)
        for status in TRUST_LADDER:
            if TRUST_RANK[status] == lowest:
                return status
        return PRIOR

    def as_json(self) -> dict[str, Any]:
        payload = {
            "capability": self.capability,
            "capability_id": self.capability_id,
            "game_version": self.game_version,
            "observed_date": self.observed_date,
            "source": self.source,
            "source_type": self.source_type,
            "source_confidence": round(self.source_confidence, 3),
            "status": self.status,
            "missing_fields": list(self.missing),
            "conflicts": list(self.conflicts),
            "live_calibration_status": self.live_calibration_status,
            "question": self.question,
            "research_attempts": self.research_attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "evidence": list(self.evidence),
            "notes": list(self.notes),
            "field_status": dict(self.field_status),
            "field_source": dict(self.field_source),
            "acquisition_rung": acquisition_rank(self.source_type),
        }
        for name in KNOWLEDGE_FIELDS:
            payload[name] = self.value(name)
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "KnowledgeRecord":
        known = {name for name in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        data = {k: v for k, v in payload.items() if k in known and k != "capability"}
        data.pop("missing_fields", None)   # derived on read; a stored copy can go stale
        data["conflicts"] = tuple(data.get("conflicts") or ())
        data["evidence"] = tuple(data.get("evidence") or ())
        data["notes"] = tuple(data.get("notes") or ())
        if not isinstance(data.get("field_status"), dict):
            data["field_status"] = {}
        if not isinstance(data.get("field_source"), dict):
            data["field_source"] = {}
        return cls(capability=str(payload.get("capability") or ""), **data)


def sufficiency(record: KnowledgeRecord) -> tuple[bool, tuple[str, ...]]:
    """The Knowledge Sufficiency Gate: enough to build a candidate, or what is missing.

    Enough means all eight gate fields have a value -- *not* that the values are
    correct.  Correctness is what Live Calibration is for, and requiring it here
    would make the gate unreachable and stall the loop the operator wants running.
    """
    missing = record.missing
    return (not missing, missing)


# ------------------------------------------------------------- the store


class KnowledgeStore:
    """One JSON file per capability under ``knowledge/preload/``.

    Same shape as the rest of ``knowledge/``: a human-readable file per subject plus
    a *derived* index.  The index is regenerated from the files, so it can never
    disagree with them -- the same rule ``capability_skill_map.json`` follows.
    """

    INDEX_NAME = "INDEX.json"

    def __init__(self, root: Path | str | None = None, *, directory: str = DEFAULT_DIRECTORY) -> None:
        base = Path(root) if root else Path(__file__).resolve().parents[1]
        self.root = base
        self.directory = base / directory

    # -- paths -------------------------------------------------------------

    @staticmethod
    def slug(capability: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", str(capability)).strip("_").upper() or "UNKNOWN"

    def path(self, capability: str) -> Path:
        return self.directory / f"{self.slug(capability)}.json"

    # -- reads -------------------------------------------------------------

    def load(self, capability: str) -> KnowledgeRecord | None:
        try:
            payload = json.loads(self.path(capability).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        return KnowledgeRecord.from_json(payload)

    def records(self) -> tuple[KnowledgeRecord, ...]:
        """Every knowledge file, newest first.  Unreadable files are skipped."""
        if not self.directory.is_dir():
            return ()
        out: list[KnowledgeRecord] = []
        for path in sorted(self.directory.glob("*.json")):
            if path.name == self.INDEX_NAME:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, Mapping) and payload.get("capability"):
                out.append(KnowledgeRecord.from_json(payload))
        out.sort(key=lambda r: str(r.updated_at), reverse=True)
        return tuple(out)

    # -- writes ------------------------------------------------------------

    def save(self, record: KnowledgeRecord, *, now: datetime | None = None) -> Path:
        moment = now or datetime.now(timezone.utc)
        record.updated_at = moment.isoformat()
        record.created_at = record.created_at or moment.isoformat()
        record.missing_fields = record.missing
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(record.capability)
        path.write_text(
            json.dumps(record.as_json(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return path

    def write_index(self, *, now: datetime | None = None) -> Path:
        """Regenerate the derived index.  Never hand-edited, never authoritative."""
        moment = now or datetime.now(timezone.utc)
        records = self.records()
        by_status: dict[str, int] = {}
        by_rung: dict[str, int] = {}
        rows = []
        for record in records:
            by_status[record.status] = by_status.get(record.status, 0) + 1
            rung = str(acquisition_rank(record.source_type))
            by_rung[rung] = by_rung.get(rung, 0) + 1
            rows.append({
                "capability": record.capability,
                "capability_id": record.capability_id,
                "status": record.status,
                "weakest_field": record.weakest_field_trust(),
                "source_type": record.source_type,
                "acquisition_rung": acquisition_rank(record.source_type),
                "sufficient": record.sufficient,
                "missing_fields": list(record.missing),
                "conflicts": list(record.conflicts),
                "live_calibration_status": record.live_calibration_status,
                "updated_at": record.updated_at,
            })
        payload = {
            "schema_version": "1.0",
            "generated_by": "winter_agent_v2.knowledge_preload.KnowledgeStore.write_index",
            "generated_at": moment.isoformat(),
            "note": (
                "derived from knowledge/preload/*.json -- not a skill registry and not a "
                "lifecycle authority; delete any row and it returns from the files"
            ),
            "acquired_vs_external": (
                "the point of this index is that acquisition_rung should drift toward 1-5 "
                "over time: external priors are a starting cost, not a permanent one"
            ),
            "summary": {
                "records": len(records),
                "by_status": by_status,
                "by_acquisition_rung": by_rung,
                "sufficient": sum(1 for r in records if r.sufficient),
                "with_conflicts": sum(1 for r in records if r.conflicts),
                "awaiting_calibration": sum(
                    1 for r in records if (r.live_calibration_status or "") in
                    ("QUEUED", "WAITING_FOR_LIVE_CALIBRATION")
                ),
            },
            "records": rows,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / self.INDEX_NAME
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    # -- dedup / freshness (operator §十) ---------------------------------

    def needs_research(
        self,
        capability: str,
        *,
        question: str,
        source_type: str,
        game_version: str = "",
    ) -> tuple[bool, str]:
        """``(needs_research, why)`` for one specific question about one capability.

        Re-reading a manual is the waste this exists to prevent.  A question is
        already answered when a record exists for it, from a source at least as good,
        at a trust level worth acting on, with no unresolved conflict -- unless
        something invalidated it: a new game version, a UI-change report, or live
        evidence that disagreed with the prior.
        """
        record = self.load(capability)
        if record is None:
            return True, "no knowledge record yet"
        if not record.question:
            return True, "the record carries no question yet, so nothing was asked"
        if record.question != question:
            return True, f"a different question is on file: {record.question}"
        if record.missing:
            # The question is on file but the field it asked about is still blank, so
            # nothing ever wrote an answer back.  Without this, the record looked
            # "answered" the moment its question was recorded, and the capabilities that
            # most needed research were exactly the ones permanently refused it --
            # KNOWLEDGE_BLOCKED instead of a job.
            return True, (
                f"the question is on file but {'、'.join(record.missing)} is still blank "
                f"(no answer was ever written back)"
            )
        if record.conflicts:
            return True, f"unresolved prior-vs-live conflict: {record.conflicts[0]}"
        if game_version and record.game_version and game_version != record.game_version:
            return True, f"game version moved {record.game_version} -> {game_version}"
        if TRUST_RANK.get(record.status, 0) < TRUST_RANK[UNVERIFIED]:
            return True, f"only a {record.status} answer is on file"
        if record.live_calibration_status in ("UI_CHANGED", "DEGRADED"):
            return True, f"live calibration reported {record.live_calibration_status}"
        return False, f"already answered at {record.status} from {record.source_type}"

    # -- targeted research: where the answer comes back (operator §五/§六) --

    @property
    def inbox(self) -> Path:
        return self.directory / "inbox"

    def pending_research(self) -> tuple[Path, ...]:
        """Answer files waiting to be folded into the knowledge base."""
        if not self.inbox.is_dir():
            return ()
        return tuple(sorted(p for p in self.inbox.glob("*.json") if p.is_file()))

    def ingest(self, *, now: datetime | None = None) -> "ResearchIngest":
        """Fold finished research into the durable knowledge, field by field.

        This is the half that was missing: the controller could *ask* a question --
        it could put a work order with the missing fields in it onto the one queue --
        but nothing ever put the answer back, so every loop re-researched the same
        capability and the knowledge base never grew.  Reading is only half of
        "READ ONCE".

        Rules that are enforced here rather than trusted:

        * an unknown **field** is rejected by name -- the gate reads exact field
          names, so a renamed field would otherwise sever the answer from the gate
          silently (the ``task_type`` lesson, one layer up);
        * an unknown **source_type** is rejected, because trust cannot be assigned
          without it and guessing the trust of a claim is how a prior becomes a fact;
        * an answer may **never** write ``CONFIRMED`` -- external sources land at
          ``PRIOR``, in-repo sources at ``UNVERIFIED``, and a real-device observation
          at ``OBSERVED``.  Only the reconciler, holding a live episode with a passing
          verifier, may confirm (``confirm_from_live``);
        * an answer may never *downgrade* a stronger existing value; the conflict is
          recorded in ``notes`` instead of being silently overwritten.
        """
        moment = now or datetime.now(timezone.utc)
        accepted: list[str] = []
        rejected: list[str] = []
        moved: list[str] = []
        notes: list[str] = []

        for path in self.pending_research():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                rejected.append(f"{path.name}: unreadable ({type(exc).__name__})")
                moved.append(self._file_away(path, "rejected"))
                continue
            if not isinstance(payload, Mapping):
                rejected.append(f"{path.name}: not a JSON object")
                moved.append(self._file_away(path, "rejected"))
                continue

            capability = str(payload.get("capability") or "").strip()
            if not capability:
                rejected.append(f"{path.name}: no capability named")
                moved.append(self._file_away(path, "rejected"))
                continue

            record = self.load(capability) or KnowledgeRecord(capability=capability)
            taken = 0
            for answer in payload.get("answers") or ():
                if not isinstance(answer, Mapping):
                    rejected.append(f"{capability}: an answer was not an object")
                    continue
                field_name = str(answer.get("field") or "").strip()
                if field_name not in KNOWLEDGE_FIELDS:
                    rejected.append(f"{capability}: unknown field '{field_name}'")
                    continue
                value = _text(answer.get("value"))
                if _blank(value):
                    rejected.append(f"{capability}.{field_name}: empty value")
                    continue
                source_type = str(answer.get("source_type") or "").strip()
                if source_type not in ACQUISITION_ORDER:
                    rejected.append(
                        f"{capability}.{field_name}: unknown source_type '{source_type}'"
                    )
                    continue

                trust = trust_for_source(source_type)
                current = record.value(field_name)
                current_trust = record.field_trust(field_name) if not _blank(current) else ""
                if current_trust and TRUST_RANK.get(current_trust, 0) > TRUST_RANK[trust]:
                    notes.append(
                        f"{capability}.{field_name}: kept the stronger {current_trust} value; "
                        f"the {trust} answer from {source_type} is recorded as a note"
                    )
                    record.notes = record.notes + (
                        f"{TRUST_LADDER[-1]} answer not applied to {field_name} "
                        f"({trust} < {current_trust}) from {answer.get('source') or source_type}: {value}",
                    )
                    taken += 1
                    continue

                setattr(record, field_name, value)
                record.field_status[field_name] = trust
                record.field_source[field_name] = _text(answer.get("source")) or source_type
                taken += 1
                accepted.append(f"{capability}.{field_name}")
                if not record.observed_date:
                    record.observed_date = _text(answer.get("observed_date"))
                if not record.source:
                    record.source = _text(answer.get("source")) or source_type
                    record.source_type = source_type
                    try:
                        record.source_confidence = max(
                            0.0, min(1.0, float(answer.get("source_confidence") or 0.0))
                        )
                    except (TypeError, ValueError):
                        record.source_confidence = 0.0

            # The record's headline status is *derived* from its fields, never raised by
            # the best one: a single well-sourced field must not certify the other seven.
            if taken:
                record.status = record.headline_status()
                record.notes = record.notes + (
                    f"research ingest {moment.isoformat()}: {taken} field(s) answered",
                )
                self.save(record, now=moment)
                moved.append(self._file_away(path, "done"))
            else:
                if not any(r.startswith(f"{capability}") for r in rejected):
                    rejected.append(f"{capability}: no usable answer in {path.name}")
                moved.append(self._file_away(path, "rejected"))

        if moved:
            self.write_index(now=moment)
        return ResearchIngest(
            accepted=tuple(accepted), rejected=tuple(rejected),
            moved=tuple(moved), notes=tuple(notes),
        )

    def _file_away(self, path: Path, bucket: str) -> str:
        """Move a consumed answer file aside for audit -- never delete research."""
        target = self.inbox / bucket
        target.mkdir(parents=True, exist_ok=True)
        destination = target / path.name
        counter = 1
        while destination.exists():
            destination = target / f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        try:
            path.replace(destination)
        except OSError:
            return ""
        return destination.as_posix()



# --------------------------------------------------- normalize / calibrate


def from_plan(
    plan: Any,
    *,
    source: str,
    source_type: str,
    source_confidence: float,
    capability_id: str = "",
    game_version: str = "",
    observed_date: str = "",
    question: str = "",
    now: datetime | None = None,
) -> KnowledgeRecord:
    """Turn a preload plan's seven fields into a durable knowledge record.

    Deliberately a one-way door: whatever a plan learned is stored as a **prior**,
    never as a confirmed fact, because nothing on this machine has seen the client.
    ``status`` is set from the acquisition rung instead of from the author's mood:
    a live-verified asset or an episode is ``UNVERIFIED`` (we believe it, we have not
    re-proved it for *this* capability), anything from outside is ``PRIOR``.
    """
    moment = now or datetime.now(timezone.utc)
    facet = {f.name: f for f in getattr(plan, "facets", ()) or ()}

    def value(name: str) -> str:
        got = facet.get(name)
        return got.value if got and got.known else ""

    record = KnowledgeRecord(
        capability=str(getattr(plan, "code", "") or getattr(plan, "capability_id", "")),
        capability_id=capability_id or str(getattr(plan, "capability_id", "")),
        game_version=game_version,
        observed_date=observed_date or moment.date().isoformat(),
        source=source,
        source_type=source_type,
        source_confidence=source_confidence,
        preconditions=value("Preconditions"),
        navigation=value("Navigation"),
        recognition=value("Recognition"),
        actions=value("Action"),
        # The plan's success condition is also the best statement of the success
        # *state*; see FIELD_TO_FACET for why they are one facet and two gate fields.
        success_state=value("Verifier"),
        verifier_prior=value("Verifier"),
        recovery_prior=value("Recovery"),
        risk=value("Risk"),
        question=question,
        status=UNVERIFIED if source_type in LOCAL_RUNGS else PRIOR,
    )
    # ``page_semantics`` and ``success_state`` are deliberately left empty: the plan's
    # facets carry how to *reach* and *act*, not which page model or success signal the
    # client has, and inventing them here would be the "spec looked complete by being
    # vague" failure.  They are what targeted research and live calibration fill in.
    record.notes = tuple(
        f"未注册语义（需要一帧真机页面）：{name}"
        for name in (getattr(plan, "missing_semantics", ()) or ())
    )
    for name in GATE_FIELDS:
        got = facet.get(FIELD_TO_FACET.get(name, ""))
        record.field_status[name] = (
            (UNVERIFIED if source_type in LOCAL_RUNGS else PRIOR) if got and got.known else PRIOR
        )
        record.field_source[name] = (got.source if got and got.known else "")
    record.failure_states = ""
    record.missing_fields = record.missing
    return record


# The plan's seven facets address the gate by these names; kept explicit so a rename
# cannot silently detach a field from the gate (the `task_type` lesson).  Note that
# ``success_state`` and ``verifier_prior`` both draw on the plan's ``Verifier`` facet:
# a success condition *is* the best available statement of the success state, and
# pretending otherwise would only make the gate say "unknown" for a field the project
# has actually measured.  ``page_semantics`` and ``failure_states`` are deliberately
# absent -- neither is in the gate, and neither can be guessed from a prior.
FIELD_TO_FACET: dict[str, str] = {
    "preconditions": "Preconditions",
    "navigation": "Navigation",
    "recognition": "Recognition",
    "actions": "Action",
    "success_state": "Verifier",
    "verifier_prior": "Verifier",
    "recovery_prior": "Recovery",
    "risk": "Risk",
}


@dataclass(frozen=True)
class Diff:
    """One field where the manual and the client disagree.  The output of calibration."""

    field: str
    prior: str
    observed: str
    note: str = ""

    def describe(self) -> str:
        return f"{self.field}: prior={self.prior or '-'} observed={self.observed or '-'}"


def prior_vs_live_diff(
    record: KnowledgeRecord,
    observed: Mapping[str, Any],
) -> tuple[Diff, ...]:
    """What the real client said differently.  Only the differences, never a wipe.

    The operator's rule after a failed calibration is explicit: "不要直接推翻全部先验",
    record what the manual thought and what the client actually is, then fix only the
    differences.  A prior and an observation agreeing is the common case and produces
    no diff -- which is what makes the surviving diffs worth reading.
    """
    diffs: list[Diff] = []
    for name in KNOWLEDGE_FIELDS:
        if name not in observed:
            continue
        prior = record.value(name)
        seen = _text(observed.get(name))
        if _blank(seen):
            continue
        if _blank(prior):
            diffs.append(Diff(name, prior, seen, "先验缺失，真机补齐"))
        elif prior.strip() != seen.strip():
            diffs.append(Diff(name, prior, seen, "先验与真机不一致，以真机为准"))
    return tuple(diffs)


def calibrate(
    record: KnowledgeRecord,
    diffs: Sequence[Diff],
    *,
    confirmed_fields: Iterable[str] = (),
    evidence: Iterable[str] = (),
    live_calibration_status: str = "",
    now: datetime | None = None,
) -> KnowledgeRecord:
    """Fold live calibration back into the knowledge, without inflating anything.

    * fields the client confirmed move to ``OBSERVED`` (a frame was read);
    * fields that differed are overwritten by the client's answer and marked
      ``OBSERVED``, with the old prior kept in ``notes`` -- the difference is the
      finding, so it must survive;
    * fields whose prior and observation disagreed are recorded as ``CONFLICT`` only
      when the client could *not* settle them (no frame, no verifier).
    """
    moment = now or datetime.now(timezone.utc)
    for diff in diffs:
        record.notes = record.notes + (
            f"PRIOR_VS_LIVE_DIFF {diff.field}: 说明书 {diff.prior or '(缺)'} -> 真机 {diff.observed}",
        )
        setattr(record, diff.field, diff.observed)
        record.field_status[diff.field] = OBSERVED
        record.field_source[diff.field] = "LIVE_CALIBRATION"
    for name in confirmed_fields:
        if name in KNOWLEDGE_FIELDS and not _blank(record.value(name)):
            record.field_status[name] = OBSERVED
    if live_calibration_status:
        record.live_calibration_status = live_calibration_status
    record.evidence = tuple(dict.fromkeys((*record.evidence, *[str(e) for e in evidence])))
    # The record's own status is the *weakest* gate field: a record is not better than
    # its shakiest value.
    record.status = CONFLICT if record.conflicts else record.weakest_field_trust()
    record.updated_at = moment.isoformat()
    record.missing_fields = record.missing
    return record


def confirm_from_live(
    record: KnowledgeRecord,
    *,
    evidence: Iterable[str] = (),
    now: datetime | None = None,
) -> KnowledgeRecord:
    """A production episode with a passing verifier proved it: the prior is now fact.

    Called by the completion hook, and only for a real live success.  An agent's
    summary, an offline test, or a replay must never reach this function -- the caller
    is the reconciler, which measures the episode stream.
    """
    moment = now or datetime.now(timezone.utc)
    for name in GATE_FIELDS:
        if not _blank(record.value(name)):
            record.field_status[name] = CONFIRMED
    record.status = CONFIRMED
    record.evidence = tuple(dict.fromkeys((*record.evidence, *[str(e) for e in evidence])))
    record.live_calibration_status = "CONFIRMED"
    record.updated_at = moment.isoformat()
    return record


def mark_conflict(
    record: KnowledgeRecord,
    field_name: str,
    *,
    prior: str,
    live: str,
    evidence: Iterable[str] = (),
    now: datetime | None = None,
) -> KnowledgeRecord:
    """Record an unresolved disagreement instead of silently preferring one side."""
    moment = now or datetime.now(timezone.utc)
    record.conflicts = tuple(dict.fromkeys((*record.conflicts, f"{field_name}: {prior} != {live}")))
    record.status = CONFLICT
    record.notes = record.notes + (f"CONFLICT {field_name}: 先验 {prior or '(缺)'} vs 真机 {live}",)
    record.evidence = tuple(dict.fromkeys((*record.evidence, *[str(e) for e in evidence])))
    record.updated_at = moment.isoformat()
    return record


# ---------------------------------------------------- local knowledge check


@dataclass(frozen=True)
class LocalCheck:
    """The result of walking the local rungs before any network call."""

    enough: bool
    rung: str
    missing: tuple[str, ...] = ()
    findings: tuple[tuple[str, str], ...] = ()
    network_allowed: bool = False
    why: str = ""

    def questions(self) -> tuple[str, ...]:
        """The specific questions a targeted research job must answer.

        One question per missing gate field, phrased as the operator phrased them
        ("入口在哪里 / 页面如何识别 / 按钮语义 / 操作顺序 / 成功状态 / 失败状态 /
        资源消耗"), so a research agent cannot quietly turn it into "collect
        everything about this game".
        """
        out = []
        for name in self.missing:
            out.append(f"{GATE_ZH.get(name, name)}：{_QUESTION.get(name, '是什么')}")
        return tuple(out)


_QUESTION: dict[str, str] = {
    "preconditions": "从哪里、在什么状态下可以开始",
    "navigation": "入口在哪里，需要哪几跳",
    "recognition": "页面与目标如何识别（文字/图标/颜色/位置）",
    "actions": "操作顺序是什么，点哪里、点什么语义",
    "success_state": "什么状态代表成功",
    "verifier_prior": "用什么可观测状态判定成功",
    "recovery_prior": "失败后怎么恢复",
    "risk": "风险等级与资源消耗规则",
}


def local_knowledge_check(
    plan: Any,
    record: KnowledgeRecord | None,
    *,
    cached_external: bool = False,
) -> LocalCheck:
    """Rungs 1-5 first: is what we already have enough to build a candidate?

    ``plan`` is the preload plan (already a projection over V2 code / episodes /
    legacy assets / the external map), so this is where the two layers meet: the plan
    says what the *ladder* found, the record says what has been stored, and the answer
    decides whether anything is allowed to touch the network.
    """
    findings: list[tuple[str, str]] = []
    classes = tuple(getattr(plan, "classes", ()) or ())
    has_plan_fields = any(f.known for f in getattr(plan, "facets", ()) or () if f.name != "Risk")
    if record is not None:
        findings.append((
            INTERNAL_KNOWLEDGE,
            f"{record.status} / rung {acquisition_rank(record.source_type)}",
        ))
    if has_plan_fields:
        findings.append((LIVE_VERIFIED_ASSET, "plan fields came from V2 code / evidence"))
    if (getattr(plan, "reuse", {}) or {}).get("episodes"):
        findings.append((EPISODE_EVIDENCE, f"{plan.reuse['episodes']} episode(s) with recorded_at"))
    if "LEGACY_ASSET_UNWIRED" in classes:
        findings.append((LEGACY_VERIFIED_ASSET, "an unwired legacy/internal asset exists"))
    if (getattr(plan, "external", {}) or {}).get("capability"):
        findings.append((EXTERNAL_MAP, str(plan.external.get("capability"))))
    if cached_external:
        findings.append((EXTERNAL_MAP, "cached external knowledge"))

    merged = KnowledgeRecord(capability="probe")
    if record is not None:
        for name in KNOWLEDGE_FIELDS:
            setattr(merged, name, record.value(name))
    facet = {f.name: f for f in getattr(plan, "facets", ()) or ()}
    for name, facet_name in FIELD_TO_FACET.items():
        if _blank(merged.value(name)) and facet_name in facet and facet[facet_name].known:
            setattr(merged, name, facet[facet_name].value)
    enough, missing = sufficiency(merged)

    rung = min((name for name, _ in findings), key=acquisition_rank, default=SELF_EXPLORATION)
    return LocalCheck(
        enough=enough,
        rung=rung,
        missing=missing,
        findings=tuple(findings),
        network_allowed=not enough,
        why=(
            "本地知识已经足够（第 1-5 级），禁止重新联网研究"
            if enough else
            "本地知识不足，只针对缺失字段做定向研究：" + "、".join(missing)
        ),
    )
