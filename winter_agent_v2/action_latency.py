"""Low-overhead, append-only timing records for production actions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


PHASES = (
    "worker_start_ms", "scheduler_select_ms", "scheduler_tick_ms",
    "frame_capture_ms", "ocr_ms", "semantic_resolve_ms",
    "pipeline_resolve_ms", "maa_execute_ms", "post_action_wait_ms",
    "reobserve_ms", "verifier_ms", "episode_write_ms",
    "inter_step_wait_ms", "total_step_ms",
)


def append(path: Path, record: dict) -> None:
    """Write one measured action; diagnostics must never stop gameplay."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        row = {
            key: (round(float(record[key]), 3) if record.get(key) is not None else None)
            for key in PHASES
        }
        row.update({key: value for key, value in record.items() if key not in PHASES})
        row.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        pass
