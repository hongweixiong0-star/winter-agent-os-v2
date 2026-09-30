"""Role-scoped task completion projection over the existing Goal and Episode streams.

This is a materialized view for operators, not another source of goals or a scheduler.
Live status comes from GoalStateStore; proven actions and complete-goal transitions come
from the production Episode stream. Missing observations stay explicit instead of being
counted as completed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping


GAME_TIMEZONE = "Asia/Shanghai"
_GAME_TZ = timezone(timedelta(hours=8), name=GAME_TIMEZONE)
TASK_TYPES: tuple[str, ...] = (
    "DAILY", "INTEL", "MAIL", "REWARD", "ALLIANCE", "ALLIANCE_DONATION",
    "TRAINING", "RESEARCH", "BUILDING", "GATHER", "STAMINA", "BEAST",
    "ICEFIELD_BEAST", "ARENA", "ACTIVITY_CLAIM", "FREE_REWARD",
    "ALLIANCE_MOBILIZATION", "BEAR", "FISHING", "OTHER_CURRENT_EVENTS",
)

# These definitions intentionally describe the evidence available in V2's real runtime
# records. L3/L4/L5 are populated only by production Episodes; a click or offline test
# cannot manufacture game-side completion evidence.
EVIDENCE_DEFINITIONS = {
    "DISCOVER": "the role-scoped Goal appeared in a fresh Goal discovery snapshot",
    "L1": "the existing control-experience ledger has a verifier-proven single-step action for this Goal",
    "L2": "the discovered Goal has an available Skill and a configured production route",
    "L3": "a production Episode recorded an issued action for the Goal",
    "L4": "a production Episode passed its step Verifier for the Goal",
    "L5": "a production Episode recorded the Goal in completed_goal_ids",
}

_EXACT_TASK_TYPES: dict[str, tuple[str, ...]] = {
    "DAILY_ACTIVITY_TARGET": ("DAILY",),
    "CLEAR_INTEL": ("INTEL",),
    "MAIL_ROUTINE": ("MAIL",),
    "ALLIANCE_ROUTINE": ("ALLIANCE",),
    "ALLIANCE_DONATION": ("ALLIANCE", "ALLIANCE_DONATION"),
    "DISCOVER_BEAR_RALLY_LIST": ("ALLIANCE", "BEAR"),
    "PARTICIPATE_BEAR": ("BEAR", "ALLIANCE"),
    "SCHEDULED_BEAR_HUNT": ("BEAR", "ACTIVITY_CLAIM", "OTHER_CURRENT_EVENTS"),
    "USE_FREE_ARENA_ATTEMPTS": ("ARENA",),
    "KEEP_TRAINING_PRODUCTIVE": ("TRAINING",),
    "SHIELD_CAMP_TRAINING": ("TRAINING",),
    "LANCER_CAMP_TRAINING": ("TRAINING",),
    "MARKSMAN_CAMP_TRAINING": ("TRAINING",),
    "KEEP_RESEARCH_PRODUCTIVE": ("RESEARCH",),
    "KEEP_BUILDING_PRODUCTIVE": ("BUILDING",),
    "KEEP_MARCHES_PRODUCTIVE": ("GATHER",),
    "GATHER_RESOURCE": ("GATHER",),
    "AVOID_STAMINA_WASTE": ("STAMINA",),
    "ALLIANCE_TIMED_EVENTS": ("ALLIANCE", "ACTIVITY_CLAIM"),
    "CLAIM_FREE_REWARDS": ("REWARD", "FREE_REWARD"),
    "MY_REWARDS": ("REWARD", "FREE_REWARD"),
    "CLAIM_EXPLORATION_IDLE": ("REWARD", "FREE_REWARD"),
    "EVENT_MINIMUM_GUARANTEE": ("ACTIVITY_CLAIM",),
    "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K": (
        "ALLIANCE_MOBILIZATION", "TRAINING",
    ),
    "ALLIANCE_MOBILIZATION_ICEFIELD_BEAST": (
        "ALLIANCE_MOBILIZATION", "ICEFIELD_BEAST",
    ),
    "ALLIANCE_MOBILIZATION_LARGE_GATHER": (
        "ALLIANCE_MOBILIZATION", "GATHER",
    ),
    "ALLIANCE_MOBILIZATION_BEAST": ("ALLIANCE_MOBILIZATION", "BEAST"),
}


def task_types_for_goal(goal_id: object) -> tuple[str, ...]:
    value = str(goal_id or "").strip().upper()
    if "FISHING" in value:
        return ("FISHING",)
    if not value:
        return ()
    exact = _EXACT_TASK_TYPES.get(value)
    if exact:
        return exact
    if value.startswith("DAILY_TRAIN_"):
        return ("DAILY", "TRAINING")
    if value.startswith("DAILY_RESEARCH"):
        return ("DAILY", "RESEARCH")
    if value.startswith("DAILY_BUILD"):
        return ("DAILY", "BUILDING")
    if value.startswith("DAILY_GATHER_"):
        return ("DAILY", "GATHER")
    if value.startswith("DAILY_INTEL"):
        return ("DAILY", "INTEL")
    if value.startswith("DAILY_ALLIANCE_CONTRIBUTE"):
        return ("DAILY", "ALLIANCE", "ALLIANCE_DONATION")
    if value.startswith("ALLIANCE_MOBILIZATION"):
        return ("ALLIANCE_MOBILIZATION", "ALLIANCE")
    if value.startswith("SCHEDULED_"):
        if "ALLIANCE_MOBILIZATION" in value:
            return ("ALLIANCE_MOBILIZATION", "ACTIVITY_CLAIM", "OTHER_CURRENT_EVENTS")
        if "ICEFIELD_BEAST" in value:
            return ("ICEFIELD_BEAST", "ACTIVITY_CLAIM", "OTHER_CURRENT_EVENTS")
        if "BEAR" in value:
            return ("BEAR", "ACTIVITY_CLAIM", "OTHER_CURRENT_EVENTS")
        if "ALLIANCE_MOBILIZATION" in value:
            return ("ALLIANCE_MOBILIZATION", "ACTIVITY_CLAIM", "OTHER_CURRENT_EVENTS")
        return ("ACTIVITY_CLAIM", "OTHER_CURRENT_EVENTS")
    if "ICEFIELD_BEAST" in value:
        return ("ICEFIELD_BEAST",)
    if "ARENA" in value:
        return ("ARENA",)
    if "BEAST" in value or value.endswith("_HUNT"):
        return ("BEAST",)
    if "STAMINA" in value or value.startswith("USE_STAMINA"):
        return ("STAMINA",)
    if value.startswith("FREE_REWARD") or value.startswith("CLAIM_FREE_"):
        return ("REWARD", "FREE_REWARD")
    return ("OTHER_CURRENT_EVENTS",) if value.startswith("EVENT_") else ()


def _parse_stamp(value: object, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            parsed = fallback or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _game_day(value: object) -> str:
    # China Standard Time is UTC+08:00 year round. Using the explicit offset avoids
    # depending on the optional Windows IANA timezone database in the production venv.
    return _parse_stamp(value).astimezone(_GAME_TZ).date().isoformat()


def _empty_level() -> dict[str, Any]:
    return {"proven": False, "count": 0, "last_at": None, "evidence_refs": []}


def _empty_task_history() -> dict[str, Any]:
    return {
        "DISCOVER": _empty_level(), "L1": _empty_level(), "L2": _empty_level(),
        "L3": _empty_level(), "L4": _empty_level(), "L5": _empty_level(),
        "last_success": None, "last_step_success": None, "last_failure": None,
        "last_goal_completion": None, "current_blocker": None,
        "processed_episode_steps": [],
    }


def _empty_daily_task(task_type: str, observed_at: str, reason: str) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "status": "NOT_DISCOVERED",
        "goal_ids": [],
        "goal_states": [],
        "reason_code": "NOT_DISCOVERED",
        "current_blocker": reason,
        "next_action_at": None,
        "updated_at": observed_at,
    }


def _reason_code(goal: Mapping[str, Any]) -> tuple[str | None, str | None]:
    status = str(goal.get("status") or "UNKNOWN").upper()
    evidence = goal.get("evidence") if isinstance(goal.get("evidence"), Mapping) else {}
    retry = goal.get("retry_after")
    seconds = goal.get("remaining_seconds")
    condition = str(evidence.get("condition") or "").lower()
    raw = " ".join(str(evidence.get(key) or "") for key in (
        "blocker", "reason", "required_observation", "condition", "execution_readiness",
    )).lower()
    if status == "SCHEDULED_NOT_OPEN" or "not_open" in raw or "waiting_window" in raw:
        return "EVENT_NOT_OPEN", str(evidence.get("blocker") or evidence.get("note") or "event window has not opened")
    if status == "EXPIRED":
        return None, "event occurrence expired"
    if status == "BLOCKED" and (retry or seconds is not None or condition in {
        "queue_busy", "camp_queue_busy", "cooldown", "timer",
    }):
        return "WAITING_FOR_TIMER", str(evidence.get("condition") or retry or seconds or "waiting for a game timer")
    if status == "BLOCKED":
        if any(token in raw for token in ("resource", "insufficient", "not enough", "资源不足")):
            return "RESOURCE_BLOCKED", str(evidence.get("blocker") or evidence.get("reason") or "resource condition")
        if any(token in raw for token in ("risk", "policy", "forbidden", "payment", "付费")):
            return "RISK_BLOCKED", str(evidence.get("blocker") or evidence.get("reason") or "blocked by existing policy")
        if any(token in raw for token in ("capability", "missing", "unregistered", "skill", "observation")):
            return "CAPABILITY_GAP", str(evidence.get("blocker") or evidence.get("required_observation") or "required runtime capability is not observed")
        if any(token in raw for token in ("attempt", "exhaust")):
            return "ATTEMPTS_EXHAUSTED", str(evidence.get("blocker") or "available attempts exhausted")
        return "ENVIRONMENT_BLOCKED", str(evidence.get("blocker") or evidence.get("reason") or "blocked by current game or runtime state")
    if status == "UNKNOWN":
        if any(token in raw for token in ("missing", "observation", "capability", "not registered")):
            return "CAPABILITY_GAP", str(evidence.get("blocker") or evidence.get("required_observation") or "required observation is missing")
        return "ENVIRONMENT_BLOCKED", str(evidence.get("blocker") or evidence.get("note") or "current availability has not been observed")
    if status == "SCHEDULED_NOT_OPEN":
        return "EVENT_NOT_OPEN", "event window has not opened"
    return None, None


def _goal_board_row(goal: Mapping[str, Any], observed_at: str) -> dict[str, Any]:
    source_status = str(goal.get("status") or "UNKNOWN").upper()
    blocker_code, blocker = _reason_code(goal)
    if source_status in {"READY", "DISCOVERED"}:
        status = "READY"
    elif source_status == "IN_PROGRESS":
        status = "RUNNING"
    elif source_status == "COMPLETE":
        status = "COMPLETE"
    elif source_status == "EXPIRED":
        status = "EXPIRED"
    elif source_status == "SCHEDULED_NOT_OPEN":
        status = "WAITING"
    elif source_status == "BLOCKED":
        status = "WAITING" if blocker_code in {"WAITING_FOR_TIMER", "EVENT_NOT_OPEN"} else "BLOCKED"
    else:
        status = "BLOCKED"
    evidence = goal.get("evidence") if isinstance(goal.get("evidence"), Mapping) else {}
    next_action_at = goal.get("retry_after") or evidence.get("next_action_at") or evidence.get("wait_until")
    reading = evidence.get("reading") if isinstance(evidence.get("reading"), Mapping) else {}
    if not next_action_at:
        next_action_at = reading.get("expected_finish_at") or reading.get("timer")
    return {
        "goal_id": str(goal.get("goal_id") or ""),
        "status": status,
        "source_status": source_status,
        "completion": goal.get("completion"),
        "distance": goal.get("distance"),
        "reason_code": blocker_code,
        "current_blocker": blocker,
        "next_action_at": next_action_at,
        "available_skills": list(goal.get("available_skills") or ()),
        "updated_at": str(observed_at or ""),
    }


def _aggregate_status(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "NOT_DISCOVERED"
    statuses = {str(row.get("status") or "BLOCKED") for row in rows}
    for candidate in ("READY", "RUNNING", "WAITING", "BLOCKED"):
        if candidate in statuses:
            return candidate
    if statuses == {"COMPLETE"}:
        return "COMPLETE"
    if statuses == {"EXPIRED"}:
        return "EXPIRED"
    if "COMPLETE" in statuses:
        return "COMPLETE"
    return "BLOCKED"


def _l1_goal_evidence(path: Path) -> dict[str, list[str]]:
    """Read proven single-step L1 records from the existing shared control ledger."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    controls = payload.get("controls") if isinstance(payload, Mapping) else None
    if not isinstance(controls, Mapping):
        return {}
    evidence: dict[str, list[str]] = {}
    for control_key, record in controls.items():
        if not isinstance(record, Mapping) or str(record.get("level") or "").upper() != "L1":
            continue
        # L1 is registered only after the step verifier proves a real effect. Keep
        # the saved expectation/effect pair as the minimum evidence contract.
        if not str(record.get("expected_effect") or "").strip():
            continue
        if not str(record.get("observed_effect") or "").strip():
            continue
        if str(record.get("last_result") or "").upper() in {"", "NO_OP", "UNKNOWN"}:
            continue
        goal_ids: set[str] = set()
        goal_help = record.get("goal_help")
        if isinstance(goal_help, Mapping):
            goal_ids.update(str(goal).strip() for goal in goal_help if str(goal).strip())
        conditions = record.get("conditions") if isinstance(record.get("conditions"), Mapping) else {}
        condition_goal = str(conditions.get("goal") or "").strip()
        if condition_goal:
            goal_ids.add(condition_goal)
        for goal_id in goal_ids:
            evidence.setdefault(goal_id, []).append(str(control_key))
    return evidence


def _new_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "timezone": GAME_TIMEZONE,
        "updated_at": None,
        "level_definitions": dict(EVIDENCE_DEFINITIONS),
        "roles": {},
        "ROLE_A_REMAINING_TODAY": {"role_id": None, "tasks": []},
        "ROLE_B_REMAINING_TODAY": {"role_id": None, "tasks": []},
    }


def _ensure_day(role: dict[str, Any], role_id: str, role_key: str, day: str, stamp: str) -> None:
    if role.get("game_date") == day and isinstance(role.get("daily_board"), dict):
        role["role_id"] = role_id
        if role_key:
            role["role_key"] = role_key
        return
    role["role_id"] = role_id
    role["role_key"] = role_key or str(role.get("role_key") or role_id)
    role["game_date"] = day
    role["daily_board"] = {
        "game_date": day,
        "timezone": GAME_TIMEZONE,
        "generated_at": stamp,
        "last_observed_at": None,
        "tasks": {
            task_type: _empty_daily_task(
                task_type, stamp, "no role-scoped Goal observation for this task type today",
            )
            for task_type in TASK_TYPES
        },
        "completion_events_today": {},
        "summary": {
            "completed": 0, "observed": 0, "pending": 0, "not_discovered": len(TASK_TYPES),
            "expired": 0, "observed_completion_rate": None,
        },
        "refresh_required": True,
    }
    role.setdefault("tasks", {})


def _refresh_aliases(payload: dict[str, Any], now: datetime) -> None:
    by_key: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for role_id, role in (payload.get("roles") or {}).items():
        board = role.get("daily_board") if isinstance(role, Mapping) else None
        if not isinstance(board, Mapping) or board.get("game_date") != now.astimezone(_GAME_TZ).date().isoformat():
            continue
        tasks = board.get("tasks") if isinstance(board.get("tasks"), Mapping) else {}
        remaining = [
            {"task_type": key, "status": row.get("status"),
             "reason_code": row.get("reason_code"), "current_blocker": row.get("current_blocker"),
             "next_action_at": row.get("next_action_at")}
            for key, row in tasks.items()
            if isinstance(row, Mapping) and row.get("status") not in {"COMPLETE", "EXPIRED"}
        ]
        role_key = str(role.get("role_key") or "")
        if role_key:
            by_key[role_key] = (str(role_id), remaining)
    for key in ("ROLE_A", "ROLE_B"):
        role_id, tasks = by_key.get(key, (None, []))
        payload[f"{key}_REMAINING_TODAY"] = {"role_id": role_id, "tasks": tasks}


class TaskCompletionStore:
    """Atomic writer for a role-scoped daily board and cumulative evidence matrix."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            return _new_payload()
        value.setdefault("roles", {})
        value["level_definitions"] = dict(EVIDENCE_DEFINITIONS)
        return value

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _refresh_aliases(payload, datetime.now(timezone.utc))
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _observe_payload(
        payload: dict[str, Any], *, role_id: str, role_key: str,
        goals: Iterable[Mapping[str, Any]], observed_at: object,
        l1_goal_evidence: Mapping[str, list[str]] | None = None,
    ) -> None:
        role_id = str(role_id or "").strip()
        if not role_id:
            return
        stamp = _parse_stamp(observed_at).isoformat()
        day = _game_day(stamp)
        roles = payload.setdefault("roles", {})
        role = roles.setdefault(role_id, {"role_id": role_id, "role_key": role_key or role_id, "tasks": {}})
        _ensure_day(role, role_id, role_key, day, stamp)
        raw_goals = [dict(item) for item in goals if isinstance(item, Mapping) and item.get("goal_id")]
        grouped: dict[str, list[dict[str, Any]]] = {task_type: [] for task_type in TASK_TYPES}
        # Import lazily so the Goal Library stays the source of routes, not this report.
        try:
            from .goal_library import route_for
        except ImportError:  # pragma: no cover - defensive for command-line projection use
            route_for = lambda _: None
        task_history = role.setdefault("tasks", {})
        for goal in raw_goals:
            goal_id = str(goal["goal_id"])
            row = _goal_board_row(goal, stamp)
            for task_type in task_types_for_goal(goal_id):
                if task_type in grouped:
                    grouped[task_type].append(row)
            history = task_history.setdefault(goal_id, _empty_task_history())
            discover = history["DISCOVER"]
            discover.update(proven=True, count=max(1, int(discover.get("count") or 0)), last_at=stamp)
            skills = [str(item) for item in goal.get("available_skills") or () if str(item)]
            l1_refs = list((l1_goal_evidence or {}).get(goal_id, ()))
            if l1_refs:
                history["L1"].update(
                    proven=True, count=max(1, int(history["L1"].get("count") or 0)),
                    last_at=stamp, evidence_refs=l1_refs[:20],
                )
            if skills and route_for(goal_id):
                history["L2"].update(proven=True, count=max(1, int(history["L2"].get("count") or 0)),
                                     last_at=stamp, evidence_refs=[str(route_for(goal_id))])
            normalized = row["status"]
            history["current_blocker"] = (
                {"status": normalized, "reason_code": row["reason_code"],
                 "detail": row["current_blocker"], "observed_at": stamp}
                if normalized in {"BLOCKED", "WAITING", "NOT_DISCOVERED"} else None
            )
        board = role["daily_board"]
        task_rows: dict[str, dict[str, Any]] = {}
        for task_type in TASK_TYPES:
            members = grouped[task_type]
            if not members:
                previous = board["tasks"].get(task_type)
                # A same-day verified completion remains visible until a current
                # observation discovers new work. Other absent rows are explicit gaps.
                if isinstance(previous, Mapping) and previous.get("status") == "COMPLETE":
                    task_rows[task_type] = dict(previous)
                else:
                    task_rows[task_type] = _empty_daily_task(
                        task_type, stamp, "no matching role-scoped Goal in the latest discovery snapshot",
                    )
                continue
            status = _aggregate_status(members)
            pending = [item for item in members if item["status"] not in {"COMPLETE", "EXPIRED"}]
            # A runnable cast and an unobserved reward can coexist. Display the
            # reason belonging to the aggregate state, not another subgoal's blocker.
            matching = [item for item in pending if item["status"] == status]
            representative = next((item for item in matching if item.get("current_blocker")), None)
            if representative is None:
                representative = next((item for item in matching if item.get("next_action_at")), None)
            task_rows[task_type] = {
                "task_type": task_type,
                "status": status,
                "goal_ids": list(dict.fromkeys(item["goal_id"] for item in members)),
                "goal_states": members,
                "reason_code": representative.get("reason_code") if representative else None,
                "current_blocker": representative.get("current_blocker") if representative else None,
                "next_action_at": representative.get("next_action_at") if representative else None,
                "updated_at": stamp,
            }
        previous_tasks = board.get("tasks") if isinstance(board.get("tasks"), Mapping) else {}
        completion_events = board.get("completion_events_today")
        completion_events = completion_events if isinstance(completion_events, Mapping) else {}
        for task_type, row in task_rows.items():
            previous = previous_tasks.get(task_type) if isinstance(previous_tasks, Mapping) else None
            row["completion_events_today"] = len(completion_events.get(task_type, ()))
            if isinstance(previous, Mapping) and previous.get("last_goal_completion"):
                row["last_goal_completion"] = previous["last_goal_completion"]
            if isinstance(previous, Mapping) and previous.get("PRODUCTIVE_CYCLE_VERIFIED"):
                row["PRODUCTIVE_CYCLE_VERIFIED"] = True
                row["productive_cycle_evidence"] = previous.get("productive_cycle_evidence")
        observed_rows = [row for row in task_rows.values() if row["status"] != "NOT_DISCOVERED"]
        completed = sum(row["status"] == "COMPLETE" for row in observed_rows)
        expired = sum(row["status"] == "EXPIRED" for row in observed_rows)
        pending_count = sum(row["status"] not in {"COMPLETE", "EXPIRED"} for row in task_rows.values())
        denominator = len(observed_rows) - expired
        board.update({
            "generated_at": stamp,
            "last_observed_at": stamp,
            "tasks": task_rows,
            "summary": {
                "completed": completed,
                "observed": len(observed_rows),
                "pending": pending_count,
                "not_discovered": sum(row["status"] == "NOT_DISCOVERED" for row in task_rows.values()),
                "expired": expired,
                "observed_completion_rate": round(completed / denominator, 4) if denominator else None,
            },
            "refresh_required": False,
        })

    def observe_role(
        self, *, role_id: str, goals: Iterable[Any], observed_at: object = None,
        role_key: str = "",
    ) -> None:
        rows = []
        for goal in goals:
            if isinstance(goal, Mapping):
                rows.append(dict(goal))
            elif hasattr(goal, "goal_id"):
                status = getattr(goal, "status", "UNKNOWN")
                rows.append({
                    "goal_id": str(goal.goal_id),
                    "status": str(getattr(status, "value", status)),
                    "completion": getattr(goal, "completion", None),
                    "remaining_seconds": getattr(goal, "remaining_seconds", None),
                    "available_skills": list(getattr(goal, "available_skills", ()) or ()),
                    "retry_after": getattr(goal, "retry_after", None),
                    "evidence": dict(getattr(goal, "evidence", {}) or {}),
                    "distance": getattr(goal, "distance", None),
                })
        payload = self._load()
        l1_goal_evidence = _l1_goal_evidence(self.path.parent / "control_experience.json")
        self._observe_payload(
            payload, role_id=role_id, role_key=role_key, goals=rows,
            observed_at=observed_at or datetime.now(timezone.utc),
            l1_goal_evidence=l1_goal_evidence,
        )
        self._save(payload)

    @staticmethod
    def _record_episode_payload(payload: dict[str, Any], episode: Mapping[str, Any]) -> None:
        mode = str(episode.get("execution_mode") or episode.get("mode") or "PRODUCTION").upper()
        role_id = str(episode.get("role_id") or "").strip()
        if mode != "PRODUCTION" or not role_id:
            return
        stamp = _parse_stamp(episode.get("recorded_at") or episode.get("timestamp"))
        stamp_text = stamp.isoformat()
        day = _game_day(stamp)
        role = payload.setdefault("roles", {}).setdefault(
            role_id, {"role_id": role_id, "role_key": str(episode.get("role_key") or role_id), "tasks": {}},
        )
        _ensure_day(role, role_id, str(role.get("role_key") or ""), day, stamp_text)
        ids = [str(episode.get("goal_id") or "").strip()]
        ids.extend(str(item).strip() for item in episode.get("attached_goal_ids") or () if str(item).strip())
        ids.extend(str(item).strip() for item in episode.get("completed_goal_ids") or () if str(item).strip())
        ids.extend(str(item).strip() for item in (episode.get("goal_progress_by_id") or {}) if str(item).strip())
        goal_ids = list(dict.fromkeys(item for item in ids if item))
        if not goal_ids:
            return
        result = str(episode.get("result") or "").upper()
        verifier_ok = episode.get("verifier_ok") is True
        action = episode.get("action") if isinstance(episode.get("action"), Mapping) else {}
        attempted = bool(action.get("kind") and (episode.get("executor_backend") or episode.get("action_backend") or result == "SUCCESS"))
        progress = episode.get("goal_progress_by_id") if isinstance(episode.get("goal_progress_by_id"), Mapping) else {}
        completed_ids = {str(item) for item in episode.get("completed_goal_ids") or ()}
        selected_goal_id = str(episode.get("goal_id") or "").strip()
        episode_id = str(episode.get("episode_id") or "")
        references = [episode_id] if episode_id else []
        board = role["daily_board"]
        task_history = role.setdefault("tasks", {})
        episode_marker = f"{episode_id}:{episode.get('step_id', '')}" if episode_id else ""
        for goal_id in goal_ids:
            history = task_history.setdefault(goal_id, _empty_task_history())
            processed = history.setdefault("processed_episode_steps", [])
            if episode_marker and episode_marker in processed:
                continue
            if attempted:
                level = history["L3"]
                level.update(proven=True, count=int(level.get("count") or 0) + 1, last_at=stamp_text)
                level["evidence_refs"] = list(dict.fromkeys([*level.get("evidence_refs", []), *references]))[-10:]
            goal_step_proven = (
                verifier_ok and (
                    goal_id == selected_goal_id
                    or progress.get(goal_id) is True
                    or goal_id in completed_ids
                )
            )
            if goal_step_proven:
                level = history["L4"]
                level.update(proven=True, count=int(level.get("count") or 0) + 1, last_at=stamp_text)
                level["evidence_refs"] = list(dict.fromkeys([*level.get("evidence_refs", []), *references]))[-10:]
                history["last_step_success"] = {
                    "at": stamp_text, "episode_id": episode_id, "skill": episode.get("skill"),
                    "scope": "STEP_VERIFIED",
                }
                productive = {"TRAIN_TROOPS": "TRAINING", "START_RESEARCH": "RESEARCH",
                              "RESEARCH": "RESEARCH", "BUILDING_UPGRADE": "BUILDING",
                              "DISPATCH_MARCH": "GATHER"}.get(str(episode.get("skill") or ""))
                if productive and productive in task_types_for_goal(goal_id):
                    row = board["tasks"].setdefault(productive, _empty_daily_task(productive, stamp_text, ""))
                    row["PRODUCTIVE_CYCLE_VERIFIED"] = True
                    row["productive_cycle_evidence"] = history["last_step_success"]
            if result == "FAILURE":
                history["last_failure"] = {
                    "at": stamp_text, "episode_id": episode_id, "skill": episode.get("skill"),
                    "reason": str(episode.get("failure_type") or "production step failed"),
                }
            if verifier_ok and goal_id in completed_ids:
                level = history["L5"]
                level.update(proven=True, count=int(level.get("count") or 0) + 1, last_at=stamp_text)
                level["evidence_refs"] = list(dict.fromkeys([*level.get("evidence_refs", []), *references]))[-10:]
                completion = {"at": stamp_text, "episode_id": episode_id, "source": "completed_goal_ids"}
                history["last_success"] = completion
                history["last_goal_completion"] = completion
                for task_type in task_types_for_goal(goal_id):
                    row = board["tasks"].setdefault(
                        task_type, _empty_daily_task(task_type, stamp_text, "awaiting fresh Goal observation"),
                    )
                    events = board.setdefault("completion_events_today", {}).setdefault(task_type, [])
                    if episode_marker and episode_marker not in events:
                        events.append(episode_marker)
                    row["last_goal_completion"] = completion
            progress_value = progress.get(goal_id)
            if progress_value is True and verifier_ok:
                # Goal progress is recorded separately from L5 completion.
                history.setdefault("verified_progress_events", []).append({
                    "at": stamp_text, "episode_id": episode_id,
                })
                history["verified_progress_events"] = history["verified_progress_events"][-20:]
            if goal_step_proven:
                for task_type in task_types_for_goal(goal_id):
                    row = board["tasks"].get(task_type)
                    if isinstance(row, dict):
                        row["completion_events_today"] = len(
                            board.setdefault("completion_events_today", {}).get(task_type, []),
                        )
            if episode_marker:
                processed.append(episode_marker)
                history["processed_episode_steps"] = processed[-300:]

    def record_episode(self, episode: Any) -> None:
        if hasattr(episode, "__dataclass_fields__"):
            from dataclasses import asdict
            row = asdict(episode)
        elif isinstance(episode, Mapping):
            row = dict(episode)
        else:
            return
        payload = self._load()
        self._record_episode_payload(payload, row)
        self._save(payload)

    @classmethod
    def rebuild_from_root(cls, root: Path | str) -> dict[str, Any]:
        """One-time historical materialization; called by an explicit maintenance tool only."""
        root = Path(root)
        learning = root / "learning"
        try:
            goal_payload = json.loads((learning / "goal_state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            goal_payload = {}
        try:
            inventory = json.loads((root / "knowledge/roles/role_inventory.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            inventory = {}
        role_keys = {
            str(item.get("role_id")): str(item.get("role_key") or "")
            for item in inventory.get("roles", [])
            if isinstance(item, Mapping) and item.get("role_id")
        } if isinstance(inventory, Mapping) else {}
        payload = _new_payload()
        for role_id, snapshot in (goal_payload.get("roles") or {}).items() if isinstance(goal_payload, Mapping) else ():
            if isinstance(snapshot, Mapping):
                cls._observe_payload(
                    payload, role_id=str(role_id), role_key=role_keys.get(str(role_id), ""),
                    goals=snapshot.get("goals", ()),
                    observed_at=snapshot.get("observed_at") or datetime.now(timezone.utc),
                    l1_goal_evidence=_l1_goal_evidence(learning / "control_experience.json"),
                )
        episodes = learning / "episodes.jsonl"
        scanned = 0
        try:
            with episodes.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        episode = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(episode, Mapping):
                        cls._record_episode_payload(payload, episode)
                        scanned += 1
        except OSError:
            pass
        cls(learning / "task_completion_matrix.json")._save(payload)
        return {"episodes_scanned": scanned, "roles": len(payload["roles"]),
                "path": str(learning / "task_completion_matrix.json")}
