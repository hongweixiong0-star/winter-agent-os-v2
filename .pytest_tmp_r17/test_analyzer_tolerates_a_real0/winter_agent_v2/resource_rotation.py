from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .operations_policy import BASE_RESOURCES, choose_resource_balanced

# How long a resource stays excluded after the game reported "no matching target
# near your town".  Long enough to stop the rotation from livelocking on it,
# short enough that it is retried in the same session once nodes reappear.
DEFAULT_UNAVAILABLE_TTL_SECONDS = 1800


class ResourceRotationStore:
    """Small persistent policy state for one universal gather workflow.

    Two pieces of state, both learned from the client:

    * ``dispatched`` — how many marches have actually been sent per resource, so
      the rotation is balanced rather than driven by whatever is leftmost.
    * ``unavailable`` — when the *game* last reported that a resource had no
      eligible node in range.  Previously the only way the rotation advanced was
      a successful dispatch, so a resource with no nodes nearby was selected
      forever: the goal could never progress and every cycle re-searched the same
      empty query.  Measured live on 2026-09-14: MEAT found a node and completed
      the whole chain, WOOD returned ``RESOURCE_NOT_FOUND`` at every level from 1
      to 8, and the rotation kept asking for WOOD.
    """

    def __init__(self, path: Path, *, unavailable_ttl_seconds: int = DEFAULT_UNAVAILABLE_TTL_SECONDS) -> None:
        self.path = path
        self.unavailable_ttl_seconds = max(0, int(unavailable_ttl_seconds))

    def _read(self) -> tuple[dict[str, int], dict[str, str]]:
        """Read the state file defensively.

        A malformed or partially written file must never break the gather goal:
        this state is an optimisation, not a source of truth.  ``int()`` on a
        non-numeric value raised here before, which turned cosmetic file damage
        into a hard failure of the whole workflow.
        """
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {name: 0 for name in BASE_RESOURCES}, {}
        if not isinstance(payload, dict):
            return {name: 0 for name in BASE_RESOURCES}, {}
        raw_counts = payload.get("dispatched", {})
        raw_counts = raw_counts if isinstance(raw_counts, dict) else {}
        counts: dict[str, int] = {}
        for name in BASE_RESOURCES:
            try:
                counts[name] = max(0, int(raw_counts.get(name, 0)))
            except (TypeError, ValueError):
                counts[name] = 0
        raw_unavailable = payload.get("unavailable", {})
        raw_unavailable = raw_unavailable if isinstance(raw_unavailable, dict) else {}
        unavailable = {
            str(name): str(stamp)
            for name, stamp in raw_unavailable.items()
            if name in BASE_RESOURCES and isinstance(stamp, str)
        }
        return counts, unavailable

    def _cooling(self, unavailable: dict[str, str], now: datetime | None = None) -> list[str]:
        """Resources whose last "no node in range" report is still fresh."""
        current = now or datetime.now(timezone.utc)
        if self.unavailable_ttl_seconds <= 0:
            return []
        cutoff = current - timedelta(seconds=self.unavailable_ttl_seconds)
        cooling: list[str] = []
        for name, stamp in unavailable.items():
            try:
                reported = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if reported.tzinfo is None:
                reported = reported.replace(tzinfo=timezone.utc)
            if reported > cutoff:
                cooling.append(name)
        return cooling

    def target(self, stock: dict[str, int | None] | None = None) -> str:
        counts, unavailable = self._read()
        decision = choose_resource_balanced(
            stock or {}, counts, exclude=self._cooling(unavailable)
        )
        return str(decision.parameters["resource"])

    def unavailable(self, resource: str) -> None:
        """Record that the client reported no eligible node for ``resource``."""
        if resource not in BASE_RESOURCES:
            return
        counts, unavailable = self._read()
        unavailable[resource] = datetime.now(timezone.utc).isoformat()
        self._write(counts, unavailable)

    def completed(self, resource: str) -> None:
        """Record a real dispatch and clear that resource's cooling state."""
        counts, unavailable = self._read()
        if resource in counts:
            counts[resource] += 1
        unavailable.pop(resource, None)
        self._write(counts, unavailable)

    def _write(self, counts: dict[str, int], unavailable: dict[str, str]) -> None:
        payload = {
            "dispatched": counts,
            "next": str(choose_resource_balanced({}, counts, exclude=self._cooling(unavailable)).parameters["resource"]),
            "unavailable": unavailable,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
