from __future__ import annotations

import json
from pathlib import Path

from .operations_policy import BASE_RESOURCES, choose_resource_balanced


class ResourceRotationStore:
    """Small persistent policy state for one universal gather workflow."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, int]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return {name: int(payload.get("dispatched", {}).get(name, 0)) for name in BASE_RESOURCES}
        except (OSError, ValueError, TypeError):
            return {name: 0 for name in BASE_RESOURCES}

    def target(self, stock: dict[str, int | None] | None = None) -> str:
        return str(choose_resource_balanced(stock or {}, self._read()).parameters["resource"])

    def completed(self, resource: str) -> None:
        counts = self._read()
        if resource not in counts:
            return
        counts[resource] += 1
        next_resource = str(choose_resource_balanced({}, counts).parameters["resource"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"dispatched": counts, "next": next_resource}, ensure_ascii=False, indent=2), encoding="utf-8")
