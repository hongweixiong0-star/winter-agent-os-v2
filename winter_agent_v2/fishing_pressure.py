"""FISHING POLICY V2 §3 / §14 / §15 — when fishing is allowed to take the device.

The problem this module exists to remove
----------------------------------------
``goal_library`` emits one ``EVENT_MINIMUM_GUARANTEE`` goal for whatever live event the
client is showing, and it takes that goal's ``remaining_seconds`` straight from the
countdown the client printed.  ``deadline_pressure`` then turns any countdown under 24h
into a priority boost -- ``+1000`` under a day, ``+2000`` under 12h, ``+4000`` under 6h,
``+10000`` under **2h**.  For most events that is exactly right: the window is closing and
the work has to happen inside it.

For the fishing tournament it is exactly what the operator forbade.  §3 says *do not switch
roles often for fishing*; §14 says *do not let the ordinary-points goal interrupt the
running Role Session*.  A fishing event that is open for two days would, under the raw
countdown, carry a rising ``+1000 … +10000`` for its entire length and take the device on
nearly every frame -- to go fishing *now*, for no reason other than that the event exists.

So the fishing event's deadline is not the event's countdown.  It is derived from the bait
budget, and it is **conditional**:

===================  ===========================================================
bait pressure        what the goal carries
===================  ===========================================================
``NORMAL``           ordinary.  No deadline, no bonus.  §3/§14: the current role
                     keeps the device and fishing happens after its batch.
``UNKNOWN``          ordinary, and honestly so: an unread bait counter cannot prove
                     urgency.  §2 requires reading it; this is not that reading.
``NO_BAIT``          ordinary.  There is nothing to spend, so there is nothing to
                     rush for -- a bait-less preemption would idle the whole run.
``CAP_FULL``         raised (§3 A): regeneration is being thrown away right now.
                     A synergy bonus, **not** a deadline -- the event is not closing.
``ENDGAME``          a real deadline (§15): the window is now shorter than the bait
                     left to spend in it, so the goal must outrank ordinary work.
===================  ===========================================================

Everything here is a pure function of data already read; nothing opens a device, a lease
or a file.  The store that *produces* the bait numbers is ``fishing_state.py``; the reader
is the runtime, which hands :func:`pressures_by_role_id` the loaded state once per frame.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

__all__ = [
    "BAIT_PRESSURES",
    "CAP_FULL",
    "CAP_FULL_SYNERGY_BONUS",
    "ENDGAME",
    "FISHING_EVENT_ID",
    "NO_BAIT",
    "NORMAL",
    "ORDINARY_PRESSURES",
    "UNKNOWN",
    "URGENT_PRESSURES",
    "event_goal_terms",
    "pressures_by_role_id",
    "role_bait_verdict",
    "signal_for_role",
]

#: The registry's id for the event this policy governs.  Matched case-insensitively.
FISHING_EVENT_ID = "FISHING_TOURNAMENT"

NORMAL = "NORMAL"
CAP_FULL = "CAP_FULL"
ENDGAME = "ENDGAME"
NO_BAIT = "NO_BAIT"
UNKNOWN = "UNKNOWN"

#: Every value this module can return, so a new one cannot be forgotten by a comparison.
BAIT_PRESSURES = (UNKNOWN, NO_BAIT, ENDGAME, CAP_FULL, NORMAL)
#: Pressures that leave the goal exactly as the generic event path would have left it.
ORDINARY_PRESSURES = (NORMAL, UNKNOWN, NO_BAIT)
#: Pressures that justify giving fishing a better claim on the device.
URGENT_PRESSURES = (CAP_FULL, ENDGAME)

#: §3 A's "raise the switch priority", expressed as a synergy bonus rather than a deadline.
#: Deliberately smaller than the ``reward_value + event_synergy`` (500 + 500) pair the goal
#: already carries, so a cap-full role outranks idle work without outranking a closing event.
CAP_FULL_SYNERGY_BONUS = 1500.0


def role_bait_verdict(role_state: Any, now: datetime, *,
                      seconds_per_run: float | None = None,
                      safety_margin_s: float | None = None) -> dict[str, Any]:
    """One role's bait verdict, plus the numbers behind it.

    ``role_state`` is a :class:`winter_agent_v2.fishing_state.RoleFishingState`; it is taken
    duck-typed so this module stays import-light and a caller cannot accidentally depend on
    the store's concrete class.
    """
    kwargs: dict[str, Any] = {"seconds_per_run": seconds_per_run}
    if safety_margin_s is not None:
        kwargs["safety_margin_s"] = safety_margin_s
    try:
        pressure = role_state.pressure(now, **kwargs)
        endgame = role_state.endgame(now, **kwargs)
    except (AttributeError, TypeError, ValueError):
        return {
            "pressure": UNKNOWN,
            "bait_current": None,
            "bait_cap": None,
            "is_full": None,
            "next_bait_at": None,
            "event_end_at": None,
            "points_total": None,
            "line_level": None,
            "hook_level": None,
            "sinker_level": None,
            "endgame": None,
            "reason": "STATE_UNREADABLE",
        }
    return {
        "pressure": getattr(pressure, "value", str(pressure)),
        "observed_at": getattr(role_state, "observed_at", None),
        "event_live_open": (getattr(role_state, "extra", {}) or {}).get("event_live_open"),
        "bait_current": getattr(role_state, "normal_bait_current", None),
        "bait_cap": getattr(role_state, "bait_cap", None),
        "is_full": bool(getattr(role_state, "is_full", False)),
        # Carried through because the goal provider needs them: "when may this role fish again"
        # is the counter's own printed instant, and "which gear do we have" is a live reading.
        # Both are read off the role state, never derived -- a guessed recovery instant is what
        # §2's "read the counter" rule exists to prevent.
        "next_bait_at": getattr(role_state, "next_bait_at", None),
        "event_end_at": getattr(role_state, "event_end_at", None),
        "points_total": getattr(role_state, "points_total", None),
        "line_level": getattr(role_state, "line_level", None),
        "hook_level": getattr(role_state, "hook_level", None),
        "sinker_level": getattr(role_state, "sinker_level", None),
        "endgame": endgame if isinstance(endgame, Mapping) else None,
        "reason": _pressure_reason(pressure, endgame),
    }


def pressures_by_role_id(state: Any, now: datetime, *,
                         seconds_per_run: float | None = None,
                         safety_margin_s: float | None = None) -> dict[str, dict[str, Any]]:
    """The whole store as ``{role_id: verdict}``, keyed the way the runtime names roles.

    The fishing state is filed under logical keys (``ROLE_A`` / ``ROLE_B``) while the
    runtime addresses roles by the account id it read off the client.  The mapping is taken
    from the store's own records rather than from a constant, so a role that has never been
    read contributes no entry and cannot be confused with another role.

    A role whose id is unknown is skipped on purpose: there is no key under which its
    verdict could be filed, and filing it under the wrong role would let one account's bait
    urgency steer the other account's device.
    """
    out: dict[str, dict[str, Any]] = {}
    roles = getattr(state, "roles", None)
    if not isinstance(roles, Mapping):
        return out
    for key in sorted(roles):
        role = roles[key]
        role_id = str(getattr(role, "role_id", "") or "").strip()
        if not role_id:
            continue
        per_role = seconds_per_run
        if per_role is None:
            # The cadence is per role -- one account's runs are not the other's -- and an
            # unmeasured cadence must stay unmeasured, because §15's endgame is only allowed
            # to fire against a duration somebody actually observed.
            try:
                per_role = state.seconds_per_run(key)
            except (AttributeError, TypeError, ValueError):
                per_role = None
        out[role_id] = {
            **role_bait_verdict(role, now, seconds_per_run=per_role,
                                safety_margin_s=safety_margin_s),
            "role_key": str(key),
        }
    return out


def signal_for_role(pressures: Mapping[str, Mapping[str, Any]] | None,
                    role_id: str) -> dict[str, Any] | None:
    """The verdict for one role id, or ``None`` when that role has no reading."""
    if not isinstance(pressures, Mapping):
        return None
    verdict = pressures.get(str(role_id or "").strip())
    return dict(verdict) if isinstance(verdict, Mapping) else None


def event_goal_terms(event_id: Any, verdict: Mapping[str, Any] | None) -> dict[str, Any]:
    """What the event goal should carry for the **current** role.

    Returns ``remaining_seconds`` and ``synergy_bonus`` ready to be handed to
    ``GoalState``.  ``applies`` is ``False`` for any event that is not this one, and for
    this one whenever no bait reading exists -- in both cases the caller keeps the
    generic behaviour it already had, so a missing reading can never *increase* urgency.
    """
    if str(event_id or "").strip().upper() != FISHING_EVENT_ID:
        return {"is_fishing": False, "applies": False, "remaining_seconds": None,
                "synergy_bonus": 0.0, "pressure": None,
                "reason": "NOT_THE_FISHING_EVENT"}
    if not isinstance(verdict, Mapping):
        return {"is_fishing": True, "applies": False, "remaining_seconds": None,
                "synergy_bonus": 0.0, "pressure": None,
                "reason": "NO_BAIT_READING_FOR_THIS_ROLE"}
    pressure = str(verdict.get("pressure") or UNKNOWN)
    if pressure == ENDGAME:
        endgame = verdict.get("endgame")
        remaining = None
        if isinstance(endgame, Mapping):
            remaining = _as_int(endgame.get("remaining_seconds"))
        return {"is_fishing": True, "applies": True, "remaining_seconds": remaining,
                "synergy_bonus": 0.0, "pressure": pressure,
                "reason": "ENDGAME_WINDOW_SHORTER_THAN_BAIT_LEFT"}
    if pressure == CAP_FULL:
        # A bonus, not a deadline: the event is not closing, the counter is full.  Saying
        # "deadline" here would also make the scheduler's hard-preempt fire, which §3 asks
        # be reserved for a genuinely closing window.
        return {"is_fishing": True, "applies": True, "remaining_seconds": None,
                "synergy_bonus": CAP_FULL_SYNERGY_BONUS, "pressure": pressure,
                "reason": "BAIT_AT_CAP_REGENERATION_IS_BEING_WASTED"}
    return {"is_fishing": True, "applies": True, "remaining_seconds": None,
            "synergy_bonus": 0.0, "pressure": pressure,
            "reason": "ORDINARY_FISHING_BATCHES_AFTER_THE_ROLE_SESSION"}


# --------------------------------------------------------------------------- helpers

def _pressure_reason(pressure: Any, endgame: Any) -> str:
    value = getattr(pressure, "value", str(pressure))
    if value == ENDGAME:
        if isinstance(endgame, Mapping):
            return str(endgame.get("reason") or "WINDOW_SHORTER_THAN_BAIT_LEFT")
        return "WINDOW_SHORTER_THAN_BAIT_LEFT"
    if value == CAP_FULL:
        return "BAIT_AT_CAP"
    if value == NO_BAIT:
        return "NO_BAIT_TO_SPEND"
    if value == NORMAL:
        return "BAIT_AVAILABLE_NO_PRESSURE"
    return "BAIT_STATE_UNKNOWN"


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
