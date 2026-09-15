from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Episode:
    """One production step, with the evidence needed to prove it happened.

    ``before_screenshot`` / ``after_screenshot`` are absolute paths.  They are
    what makes an episode auditable and what retention consults so a referenced
    frame is never pruned; without them "PRODUCTION evidence" was a claim with
    nothing behind it.  ``episode_id`` is unique per run, so the old
    ``step_001_before.png`` collision across episodes cannot come back.
    """

    skill: str
    state_before: dict[str, Any]
    action: dict[str, Any]
    state_after: dict[str, Any]
    result: str
    failure_type: str | None
    duration: float
    mode: str
    episode_id: str = ""
    goal_id: str = ""
    step_id: int = 0
    before_screenshot: str = ""
    after_screenshot: str = ""
    verifier_ok: bool | None = None
    recovery_result: str | None = None
    # Which backend actually executed this step ("MAA" / "ADB" / "" when nothing
    # was issued).  Recorded per episode so the MAA rollout is auditable from the
    # production stream instead of from a migration document.
    executor_backend: str = ""
    # The full call chain for this step: which channel produced the frames, who
    # recognised the target, who issued the input.  Never inferred from config -
    # an episode claiming MAA happened because MAA ran.
    capture_backend: str = ""
    recognition_backend: str = ""
    action_backend: str = ""
    executor_latency_ms: float | None = None
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EpisodeStore:
    def __init__(self, path: Path, *, limit: int = 10000) -> None:
        self.path = path
        self.limit = limit

    def append(self, episode: Episode) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        rows.append(json.dumps(
            asdict(episode),
            ensure_ascii=False,
            default=lambda value: value.value if hasattr(value, "value") else str(value),
        ))
        self.path.write_text("\n".join(rows[-self.limit:]) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ResourceSpend:
    resource: str
    amount: int | float | None
    reason: str
    expected_value: str
    before: int | float | None
    after: int | float | None


class ResourceLedger(EpisodeStore):
    def append_spend(self, spend: ResourceSpend) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        rows.append(json.dumps(asdict(spend), ensure_ascii=False))
        self.path.write_text("\n".join(rows[-self.limit:]) + "\n", encoding="utf-8")
