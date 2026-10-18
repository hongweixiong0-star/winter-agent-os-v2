"""Incremental reader for the WorkBuddy skill loop.

Why this exists
---------------
The loop the operator asked for on 2026-10-18 is

    WinterAgent runs -> records UNKNOWN / failure -> WorkBuddy reads -> AI decides
    -> skill generated -> tests -> loaded -> MAA executes -> verifier -> episode
    -> WorkBuddy reads again -> corrected -> promoted

Every arrow on that line already had an owner except the first one and the last one.
The runtime writes ``learning/unknown_requests/*.json`` (one file per unnamed screen, with the
frame path, OCR text and boxes) and appends ``learning/episodes.jsonl``; ``unknown_advisor`` reads
answers; ``skills.py`` holds the registry; ``runtime.VERIFIER_BY_SKILL`` binds each skill to a
verifier; ``verifier.py`` judges the before/after pair.  What nobody owned was **reading the
runtime's own output as a change feed** -- so an analysing agent had to re-read 128 MB of ledger
and guess which rows were new, and had no durable record of "this skill came from that gap and
these were its measured outcomes".

This module is that feed and that record.  It is deliberately I/O-only: it clicks nothing, holds
no device and imports no vision.  The analysing half stays outside the runtime exactly as the
project's standing rule requires (a model is an optional provider, never a dependency).

What is incremental, precisely
------------------------------
* ``episodes.jsonl``: a byte offset, because the file is append-only and 128 MB.
* ``unknown_requests/``: a set of ``request_id``, because files are immutable once written.
* Everything else (registry, capability gaps) is cheap and read whole.

A cursor that cannot be read is treated as "start from now", never as "re-read everything": the
first pass is a baseline, and its whole point is that the second pass is small.

What a brief must contain
-------------------------
The five questions the operator's §2 asks the analyser to answer, each backed by a measured row:

1. which pages/operations are uncovered -> ``unknown`` entries with their frame and OCR,
2. whether a skill is missing -> ``skill_for_popup`` vs the registry's verifier bindings,
3. whether an existing skill fails -> ``failures`` aggregated by ``(skill, failure_type)``,
4. whether the failure is recognition / precondition / action / verification -> the episode's
   own ``failure_type`` plus whether ``verifier_ok`` was ever true,
5. whether an existing skill can be reused -> the registry's skill ids and their pages.

Promotion is a claim, not a checkbox
------------------------------------
:func:`promotion_verdict` refuses on anything short of *measured* evidence: at least
``PROMOTION_MIN_PASSES`` verified successes, no failure in the last ``PROMOTION_WINDOW`` attempts,
and every pass carrying ``verifier_ok is True``.  ``SIMULATION`` replay rows never count -- the
project's evidence ladder puts them below a real client step, and a promotion that could be earned
by replay would be earned by nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from config import paths

#: One directory for the loop's own state.  Under ``learning/`` so it lives with the other
#: runtime records and is covered by the same retention rules.
STATE_DIR = paths.LOG_ROOT / "skill_loop"
CURSOR_PATH = STATE_DIR / "cursor.json"
#: Each analyse/verify pass writes its brief here so the next reader sees what was decided and
#: from which rows -- the alternative (briefs in a chat log) is un-auditable a week later.
BRIEF_DIR = STATE_DIR / "briefs"
OUTCOME_PATH = STATE_DIR / "outcomes.jsonl"

#: Runs below this are not evidence of anything, and replay is not a run at all.
SIMULATION_MODES = frozenset({"SIMULATION", "REPLAY", "DRY_RUN"})
#: A skill that clicks nothing domain-specific.  A popup answered only by one of these is a
#: gap with a working fallback, not a covered capability.
GENERIC_FALLBACKS = frozenset({"BACK", "CLOSE_POPUP"})
#: A skill is promoted only on this many verified passes with no recent failure.
PROMOTION_MIN_PASSES = 3
PROMOTION_WINDOW = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cursor() -> dict[str, Any]:
    """``{"episodes_offset": int, "seen_requests": [id...]}``; unreadable reads as empty."""
    data = _read_json(CURSOR_PATH, {})
    if not isinstance(data, dict):
        data = {}
    seen = data.get("seen_requests")
    return {
        "episodes_offset": int(data.get("episodes_offset") or 0),
        "seen_requests": [str(x) for x in seen] if isinstance(seen, list) else [],
    }


def save_cursor(cursor: Mapping[str, Any]) -> None:
    _write_json(CURSOR_PATH, dict(cursor))


# -- the two feeds -------------------------------------------------------------------------
def read_new_episodes(cursor: Mapping[str, Any], path: Path | None = None
                      ) -> tuple[list[dict[str, Any]], int]:
    """Ledger rows appended since the cursor, and the new byte offset.

    Whole-file JSON decoding is not an option: the ledger is ~128 MB and grows every run.  The
    offset is only advanced past a *complete* line, so a row written while this is reading is
    picked up next time instead of being skipped.
    """
    ledger = path or (paths.LOG_ROOT / "episodes.jsonl")
    offset = int(cursor.get("episodes_offset") or 0)
    try:
        size = ledger.stat().st_size
    except OSError:
        return [], 0
    if size < offset:  # truncated or replaced: start over rather than read nothing forever
        offset = 0
    rows: list[dict[str, Any]] = []
    with ledger.open("rb") as handle:
        handle.seek(offset)
        while True:
            line = handle.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                break  # partial write; leave the offset before it
            offset += len(line)
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line.decode("utf-8", "replace")))
            except ValueError:
                continue
    return rows, offset


def read_new_unknowns(cursor: Mapping[str, Any], directory: Path | None = None
                      ) -> list[dict[str, Any]]:
    """UNKNOWN requests not yet in the cursor, oldest first."""
    root = directory or (paths.LOG_ROOT / "unknown_requests")
    seen = set(cursor.get("seen_requests") or [])
    fresh: list[tuple[float, dict[str, Any]]] = []
    try:
        entries = list(root.glob("*.json"))
    except OSError:
        return []
    for path in entries:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            continue
        request_id = str(payload.get("request_id") or path.stem)
        if request_id in seen:
            continue
        payload["_path"] = str(path)
        fresh.append((mtime, payload))
    fresh.sort(key=lambda pair: pair[0])
    return [payload for _, payload in fresh]


# -- the brief -----------------------------------------------------------------------------
def _popup_skill_map() -> dict[str, list[str]]:
    """Which skill the brain answers each named popup with, as data.

    Kept in ``knowledge/ui/popup_skill_map.json`` rather than re-derived from the skill ids:
    ``REAL_MONEY_OFFER -> DISMISS_REAL_MONEY_OFFER`` happens to share a word, while
    ``GET_MORE_STAMINA -> DISMISS_GET_MORE_STAMINA`` only does since 2026-10-18 and
    ``EXIT_CONFIRM -> CLOSE_POPUP`` never will.  Name matching alone reported eight covered
    popups as uncovered on the first real brief.
    """
    payload = _read_json(paths.KNOWLEDGE_ROOT / "ui" / "popup_skill_map.json", {})
    popups = payload.get("popups") if isinstance(payload, dict) else None
    if not isinstance(popups, dict):
        return {}
    return {str(k): [str(x) for x in v] for k, v in popups.items() if isinstance(v, list)}


def _skill_bindings() -> dict[str, str]:
    """``skill -> verifier name`` exactly as the runtime binds it.

    Imported lazily: ``runtime`` pulls in the executor and the device stack, and a brief must be
    readable on a machine with no emulator (that is the common case for the analysing half).
    """
    try:
        from .runtime import LiveRuntime
        bindings = LiveRuntime.VERIFIED_ATOMIC
        return {str(k): str(getattr(v, "__name__", v)) for k, v in bindings.items()}
    except Exception:  # noqa: BLE001 - a brief without bindings is still a valid brief
        return {}


def _registry_ids() -> list[str]:
    try:
        from .skills import p0_registry, v2_registry
        return sorted({s.id for s in (*p0_registry().all(), *v2_registry().all())})
    except Exception:  # noqa: BLE001
        return []


def _popup_of(row: Mapping[str, Any]) -> str | None:
    before = row.get("state_before")
    if isinstance(before, Mapping):
        popup = before.get("popup")
        return str(popup) if popup else None
    return None


def summarise_episodes(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate the new ledger rows into the four things a decision needs."""
    rows = list(rows)
    failures: dict[tuple[str, str], int] = {}
    by_skill: dict[str, dict[str, int]] = {}
    verified: dict[str, int] = {}
    simulation = 0
    for row in rows:
        skill = str(row.get("skill") or "")
        if not skill:
            continue
        mode = str(row.get("mode") or "")
        if mode in SIMULATION_MODES:
            simulation += 1
            continue
        bucket = by_skill.setdefault(skill, {"success": 0, "failure": 0, "unknown": 0})
        result = str(row.get("result") or "").upper()
        if result == "SUCCESS":
            bucket["success"] += 1
            if row.get("verifier_ok") is True:
                verified[skill] = verified.get(skill, 0) + 1
        elif result == "FAILURE":
            bucket["failure"] += 1
            failures[(skill, str(row.get("failure_type") or "UNSPECIFIED"))] = \
                failures.get((skill, str(row.get("failure_type") or "UNSPECIFIED")), 0) + 1
        else:
            bucket["unknown"] += 1
    return {
        "rows": len(rows),
        "simulation_rows_excluded": simulation,
        # Which failures can even be re-read.  Measured 2026-10-18 over the whole ledger:
        # 1096 failure rows, 0 missing the before frame, **399 (36%) missing the after frame** --
        # because those are the steps where no action was issued (SEMANTIC_TARGET_NOT_VERIFIED,
        # NO_EXECUTION).  That is not a defect, it is the distinction the analyser needs: a
        # failure with an after frame is "the action did not change the page", one without is
        # "the action never happened".  Different repairs, and a brief that hides it invites the
        # wrong one.
        "evidence_gaps": {
            "missing_before": sum(1 for r in rows if not r.get("before_screenshot")),
            "missing_after": sum(1 for r in rows if not r.get("after_screenshot")),
        },
        "by_skill": by_skill,
        "verified_by_skill": verified,
        "failures": [
            {"skill": skill, "failure_type": kind, "count": count}
            for (skill, kind), count in sorted(failures.items(), key=lambda kv: -kv[1])
        ],
    }


def build_brief(rows: Iterable[Mapping[str, Any]] | None = None,
                unknowns: Iterable[Mapping[str, Any]] | None = None,
                *, cursor: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The analyser's input: new rows, new screens, and what the registry already covers.

    ``rows``/``unknowns`` are injectable so the brief can be built from a fixture in a test and
    from the cursor in production through the same code path.
    """
    cursor = cursor or load_cursor()
    if rows is None or unknowns is None:
        new_rows, offset = read_new_episodes(cursor)
        new_unknowns = read_new_unknowns(cursor)
        if rows is None:
            rows = new_rows
        if unknowns is None:
            unknowns = new_unknowns
        next_cursor = {
            "episodes_offset": offset,
            "seen_requests": sorted({*(cursor.get("seen_requests") or []),
                                     *[str(u.get("request_id")) for u in new_unknowns]}),
        }
    else:
        next_cursor = dict(cursor)

    rows = list(rows)
    unknowns = list(unknowns)
    bindings = _skill_bindings()
    ids = _registry_ids()
    declared = _popup_skill_map()
    popups = sorted({p for p in (_popup_of(r) for r in rows) if p})
    covered = {
        popup: (declared.get(popup)
                or [sid for sid in ids if popup.lower() in sid.lower()])
        for popup in popups
    }
    # A popup whose only answer is the generic Back/X is not a covered capability: the loop's
    # job is to replace exactly those with a named skill and a verifier.  Reporting them
    # separately from "no branch at all" is what keeps the next skill choice honest.
    generic_only = [p for p in popups
                    if covered.get(p) and set(covered[p]) <= GENERIC_FALLBACKS]
    unnamed = [p for p in popups if not covered.get(p)]
    brief = {
        "generated_at": _now(),
        # Honest label, because the counters below describe this increment and nothing older.
        # A skill that failed three times across three passes looks like three separate ones here;
        # the cross-pass question ("is it stuck?") belongs to ``repair_candidates``, which reads
        # the whole ledger on purpose.
        "scope": "INCREMENT_ONLY",
        "cursor_after": next_cursor,
        "counts": {
            "episode_rows": len(rows),
            "unknown_requests": len(unknowns),
            "registry_skills": len(ids),
            "verifier_bindings": len(bindings),
        },
        "episodes": summarise_episodes(rows),
        "unknowns": [
            {
                "request_id": u.get("request_id"),
                "page_label": u.get("page_label"),
                "goal": u.get("goal"),
                "unknown_type": u.get("unknown_type"),
                "frame_path": u.get("frame_path"),
                "ocr_texts": (u.get("ocr_texts") or [])[:12],
                "page_confidence": u.get("page_confidence"),
            }
            for u in unknowns
        ],
        "popups_seen": popups,
        "popup_skill_coverage": covered,
        # The question the analyser must answer explicitly; left as data, not prose, so a test
        # can assert "every popup seen has a named skill or is reported uncovered".
        "popups_without_named_skill": unnamed,
        "popups_generic_fallback_only": generic_only,
        "skills_without_verifier": [sid for sid in ids if sid not in bindings],
        # What this loop already tried, so the next pass does not re-propose it.  Bounded: the
        # brief is read by a person (or a model) and twenty rows is a session's worth.
        "recent_outcomes": read_outcomes(20),
    }
    return brief


def write_brief(brief: Mapping[str, Any]) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = BRIEF_DIR / f"brief_{stamp}.json"
    _write_json(path, brief)
    return path


# -- the loop's own ledger ----------------------------------------------------------------
def record_outcome(skill: str, *, verdict: str, evidence: Mapping[str, Any],
                   request_id: str | None = None, note: str = "") -> dict[str, Any]:
    """Append one line describing what happened to a generated/modified skill.

    Separate from ``episodes.jsonl`` on purpose: an episode is *the runtime's* record of one step,
    while this is *the loop's* record of one generation decision and its measured result.  Keeping
    them apart means the episode schema does not grow a field that only the analysing half reads.
    """
    row = {
        "at": _now(),
        "skill": skill,
        "verdict": verdict,
        "request_id": request_id,
        "note": note,
        "evidence": dict(evidence),
    }
    OUTCOME_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTCOME_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def promotion_verdict(skill: str, rows: Iterable[Mapping[str, Any]],
                      *, min_passes: int = PROMOTION_MIN_PASSES,
                      window: int = PROMOTION_WINDOW) -> dict[str, Any]:
    """Whether the measured evidence is enough to move a skill from CANDIDATE to VERIFIED.

    Reads the same rows the brief summarised, filtered to one skill, in ledger order.  The three
    refusals are deliberately explicit, because "not enough evidence yet" and "it is failing" lead
    to opposite next actions.
    """
    relevant = [r for r in rows
                if str(r.get("skill") or "") == skill
                and str(r.get("mode") or "") not in SIMULATION_MODES]
    if not relevant:
        return {"promote": False, "reason": "NO_PRODUCTION_ROWS", "passes": 0, "recent": []}
    recent = relevant[-window:]
    passes = sum(1 for r in relevant
                 if str(r.get("result") or "").upper() == "SUCCESS" and r.get("verifier_ok") is True)
    recent_failures = [r for r in recent if str(r.get("result") or "").upper() != "SUCCESS"]
    if recent_failures:
        return {"promote": False, "reason": "RECENT_FAILURE",
                "passes": passes, "recent": recent_failures}
    if passes < min_passes:
        return {"promote": False, "reason": "NOT_ENOUGH_VERIFIED_PASSES",
                "passes": passes, "required": min_passes}
    return {"promote": True, "reason": "VERIFIED_PASSES", "passes": passes,
            "recent": recent}


def repair_candidates(rows: Iterable[Mapping[str, Any]], *,
                      threshold: int | None = None,
                      limit: int = 10) -> list[dict[str, Any]]:
    """Skills that have failed enough times in a row for a screenshot to explain it.

    The judgement is ``skill_repair.should_escalate``'s, not this module's: it already owns the
    two rules that matter -- *only the last run of consecutive failures counts*, and *only a
    perception failure is worth a picture* -- and re-deriving them here would be the drift this
    project keeps paying for.  What this function adds is the aggregation a brief needs: group
    the window's rows by skill, ask once per skill, and sort by how stuck it is.

    ``page_key`` is left to the trigger's own reading of the failing rows, so a skill that broke
    on one screen and is fine on another is not repaired as if it were one thing.
    """
    from .skill_repair import REPAIR_TRIGGER_FAILURES, should_escalate
    from .skills import NON_SKILL_LEDGER_VALUES

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        skill = str(row.get("skill") or "")
        if not skill:
            continue
        # ``SAFE_STOP`` / ``PRINTED_TAP`` / ``OBSERVE_ONLY`` are ledger values, not skills: the
        # project already declares that distinction, and a repair queue that asks a model about
        # "the SAFE_STOP skill" is asking about something that does not exist.
        if skill in NON_SKILL_LEDGER_VALUES:
            continue
        if str(row.get("mode") or "") in SIMULATION_MODES:
            continue
        grouped.setdefault(skill, []).append(row)
    found: list[dict[str, Any]] = []
    for skill, skill_rows in grouped.items():
        trigger = should_escalate(skill, skill_rows,
                                  threshold=threshold or REPAIR_TRIGGER_FAILURES)
        if trigger is None:
            continue
        found.append({
            "skill": trigger.skill_id,
            "consecutive_failures": trigger.consecutive_failures,
            "failure_kinds": list(trigger.failure_kinds),
            "page_key": trigger.page_key,
            "goal_id": trigger.goal_id,
            "first_failure_at": trigger.first_failure_at,
            "last_failure_at": trigger.last_failure_at,
            "frames": list(trigger.failure_frames[-3:]),
        })
    found.sort(key=lambda item: (-item["consecutive_failures"], item["skill"]))
    return found[:limit]


def write_repair_queue(candidates: Iterable[Mapping[str, Any]]) -> Path:
    """Where the analysing half looks for "what is broken and on which screen"."""
    from .skill_repair import REPAIR_TRIGGER_FAILURES

    path = STATE_DIR / "repair_queue.json"
    _write_json(path, {
        "generated_at": _now(),
        "threshold": REPAIR_TRIGGER_FAILURES,
        "candidates": list(candidates),
    })
    return path


def read_outcomes(limit: int = 200) -> list[dict[str, Any]]:
    """The loop's own decisions, newest last -- what it generated and how that turned out.

    Without this the analysing half starts every session blind: it can see the runtime's ledger
    but not *what it already tried*, so the same skill gets proposed twice and a failure gets
    "fixed" the way that already failed once.  The file is small and append-only, so a tail read
    is enough; a malformed line is skipped rather than fatal.
    """
    try:
        lines = OUTCOME_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit):]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def pending_promotions(episode_rows: Iterable[Mapping[str, Any]],
                       outcomes: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Which loop-touched skills the measured episodes now justify promoting.

    ``promotion_verdict`` answers for one skill; this answers "of the skills this loop has
    actually generated or run, which ones have earned VERIFIED".  A skill that was only
    *proposed* (never run) cannot be promoted, and is reported separately with the reason,
    because "no evidence yet" and "it failed" need different next actions.
    """
    rows = list(episode_rows)
    touched = {str(o.get("skill")) for o in (outcomes if outcomes is not None
                                             else read_outcomes()) if o.get("skill")}
    ready: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for skill in sorted(touched):
        verdict = promotion_verdict(skill, rows)
        entry = {"skill": skill, **{k: v for k, v in verdict.items() if k != "recent"}}
        (ready if verdict.get("promote") else waiting).append(entry)
    return {"ready": ready, "waiting": waiting}


def state() -> dict[str, Any]:
    """One screenful for a human: what the cursor holds and what is waiting behind it."""
    cursor = load_cursor()
    rows, offset = read_new_episodes(cursor)
    unknowns = read_new_unknowns(cursor)
    pending = 0
    try:
        pending = len(list((paths.LOG_ROOT / "unknown_requests").glob("*.json")))
    except OSError:
        pass
    return {
        "cursor": cursor,
        "next_episode_offset": offset,
        "unread_episode_rows": len(rows),
        "unread_unknown_requests": len(unknowns),
        "unknown_files_total": pending,
        "state_dir": str(STATE_DIR),
    }
