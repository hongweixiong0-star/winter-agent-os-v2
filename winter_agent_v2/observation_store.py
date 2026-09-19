"""When was each panel last read, and what did it say?  One file, no new machinery.

The operator's §四/§五, which the goal engine could not answer before: a reading taken once
was gone by the next run, so every run either re-opened every panel or -- as it actually
behaved -- opened none and reported them all as 未读取.

This is a *state file plus pure helpers*, not a scheduler: ``GoalLibrary`` reads it to decide
whether a routine still needs a visit, and the runtime writes one record after a run that
actually observed the page.  Same shape as ``resource_rotation.json`` and
``stamina_supply.json``, and deliberately nothing more.

What it buys, in the operator's terms:

* §五 "已获得且未过期的观察结果可以复用" -- a fresh reading is re-emitted with its own state, so
  a panel read five minutes ago can still be acted on without opening it again.
* §五 "过期结果必须重新观察" -- a stale reading becomes a visit ticket again.
* §五 "不能每一轮都打开所有页面" -- that is what the TTL is for.
* §四 ``last_checked_at`` / ``next_check_at`` -- carried per domain, so the question "when
  should this be looked at again" has an answer that outlives the process.

The TTLs below are **initial values**, chosen from how the panel behaves rather than measured
from run timings, and they are the thing to tune once there are real observations to look at.
They are named per domain rather than global because the reasons differ: a mail badge can
appear at any moment, a training queue cannot finish faster than its own timer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "learning/observation_state.json"

#: How long a reading stays usable, in seconds.  Ordered by how fast the answer can change:
#: the alliance help queue turns over in minutes, a research queue in hours.
DEFAULT_TTL_SECONDS: dict[str, int] = {
    "alliance": 10 * 60,
    "mail": 15 * 60,
    "daily": 30 * 60,
    "exploration": 60 * 60,
    "training": 15 * 60,
    "research": 30 * 60,
    "building": 30 * 60,
    "intel": 20 * 60,
    # The HUD gauge, short because it moves: measured 2026-09-19 it fell 10-15 per intel mission
    # and regenerated about 1 per minute, so a ten-minute-old reading can be ~10 out.  It is only
    # used when the current frame cannot read the gauge at all, and the goal carries `reused` so
    # the difference is visible -- a stale number must never be presented as a fresh one.
    "stamina": 10 * 60,
}
FALLBACK_TTL_SECONDS = 30 * 60


def ttl_seconds(domain: str) -> int:
    return int(DEFAULT_TTL_SECONDS.get(str(domain), FALLBACK_TTL_SECONDS))


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Observation:
    """One domain's last reading, and when it was taken."""

    domain: str
    reading: Mapping[str, Any]
    checked_at: datetime

    def age_seconds(self, now: datetime) -> float:
        return (now - self.checked_at).total_seconds()

    def next_check_at(self, now: datetime | None = None) -> str:
        return (self.checked_at + timedelta(seconds=ttl_seconds(self.domain))).isoformat()


def load(path: Path | str | None = None) -> dict[str, Observation]:
    """Every recorded observation, newest state per domain.  Never raises.

    An unreadable file is an empty store, which makes every routine due -- the safe direction:
    the cost is one wasted visit, against never looking at a panel again.
    """
    source = Path(path) if path is not None else STATE_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    records = payload.get("domains") if isinstance(payload, Mapping) else None
    if not isinstance(records, Mapping):
        return {}

    out: dict[str, Observation] = {}
    for domain, body in records.items():
        if not isinstance(body, Mapping):
            continue
        checked = _moment(body.get("checked_at"))
        if checked is None:
            continue
        reading = body.get("reading")
        out[str(domain)] = Observation(
            domain=str(domain),
            reading=dict(reading) if isinstance(reading, Mapping) else {},
            checked_at=checked,
        )
    return out


def as_discovery_input(
    observations: Mapping[str, Observation] | None,
    now: datetime | None = None,
) -> dict[str, Mapping[str, Any]]:
    """What ``GoalLibrary.discover`` needs: fresh readings only, keyed by domain.

    Freshness is filtered here rather than in the goal engine so the engine stays a pure
    function of "what is known", and the policy of how long something stays known lives in
    the one place that also holds the TTLs.
    """
    moment = now or datetime.now(timezone.utc)
    out: dict[str, Mapping[str, Any]] = {}
    for domain, observation in (observations or {}).items():
        if observation.age_seconds(moment) <= ttl_seconds(domain):
            out[domain] = observation.reading
    return out


def as_observation_input(
    observations: Mapping[str, Observation] | None,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """The richer form the engine needs to decide *whether* to go and look.

    ``as_discovery_input`` answers "what do we already know"; this also answers "how long since
    we last knew it", and the second question is what makes a sweep actually happen.  Measured
    2026-09-19 with the static values: the stamina goal priced at 2450 and gathering at 70, both
    above every routine's discovery value, so ``best()`` chose them on every run and **no panel
    was ever swept** -- the state existed and was never selected.

    So an overdue routine gets a bounded, age-scaled value: enough to outrank ordinary routine
    work once it is genuinely due, never enough to outrank a real claim (a claimable routine is
    worth 250, intel rewards 500, the stamina goal 2450).  The bound is what keeps this a
    bounded sweep rather than a reason to open every panel every run.
    """
    moment = now or datetime.now(timezone.utc)
    out: dict[str, dict[str, Any]] = {}
    for domain, observation in (observations or {}).items():
        age_minutes = observation.age_seconds(moment) / 60.0
        ttl_minutes = max(1.0, ttl_seconds(domain) / 60.0)
        out[str(domain)] = {
            "reading": dict(observation.reading),
            "age_minutes": round(age_minutes, 1),
            "overdue": age_minutes > ttl_minutes,
            "overdue_ratio": round(max(0.0, age_minutes / ttl_minutes), 3),
        }
    return out


def record(
    domain: str,
    reading: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    path: Path | str | None = None,
) -> None:
    """Write one domain's reading.  Never raises: an observation must not fail a run.

    An empty reading is still recorded, and that is deliberate: "we looked and the panel said
    nothing" is information -- without it the domain looks never-visited and gets opened again
    on the very next run.
    """
    source = Path(path) if path is not None else STATE_PATH
    moment = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {}
    domains = payload.get("domains")
    domains = dict(domains) if isinstance(domains, Mapping) else {}
    domains[str(domain)] = {
        "checked_at": moment.isoformat(),
        "reading": dict(reading or {}),
    }
    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            json.dumps({"schema_version": "1.0", "domains": domains},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError:
        pass
