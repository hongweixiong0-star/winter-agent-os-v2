"""Low-overhead, append-only timing records for production actions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 2
PHASES = (
    "capture_ms", "ocr_ms", "parse_ms", "decision_ms", "maa_ms",
    "settle_ms", "reobserve_ms", "verifier_ms", "episode_write_ms",
    "total_step_ms",
)
LEGACY_PHASES = frozenset({
    "frame_capture_ms", "scheduler_select_ms", "maa_execute_ms", "post_action_wait_ms",
})


def append(path: Path, record: dict) -> None:
    """Write one measured action; diagnostics must never stop gameplay."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        settle_parts = (record.get("settle_first_wait_ms"), record.get("settle_retry_wait_ms"))
        aliases = {
            "capture_ms": "frame_capture_ms",
            "decision_ms": "scheduler_select_ms",
            "maa_ms": "maa_execute_ms",
            "settle_ms": "post_action_wait_ms",
        }
        row = {"schema_version": SCHEMA_VERSION}
        for key in PHASES:
            value = record.get(key)
            if value is None and key in aliases:
                value = record.get(aliases[key])
            if key == "settle_ms" and value is None and any(part is not None for part in settle_parts):
                value = sum(float(part or 0.0) for part in settle_parts)
            row[key] = round(float(value), 3) if value is not None else None
        row.update({key: value for key, value in record.items()
                    if key not in PHASES and key not in LEGACY_PHASES})
        row.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        pass
