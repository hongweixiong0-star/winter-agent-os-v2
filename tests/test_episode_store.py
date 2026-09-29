from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from winter_agent_v2.learning import Episode, EpisodeStore, ResourceLedger, ResourceSpend


def _episode(skill: str) -> Episode:
    return Episode(
        skill=skill,
        state_before={},
        action={},
        state_after={},
        result="SUCCESS",
        failure_type=None,
        duration=0.0,
        mode="PRODUCTION",
    )


def test_episode_append_does_not_read_or_rewrite_the_existing_ledger(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    path.write_text('{"skill":"OLD"}\n', encoding="utf-8")
    store = EpisodeStore(path)

    with (
        patch.object(Path, "read_text", side_effect=AssertionError("append read full ledger")),
        patch.object(Path, "write_text", side_effect=AssertionError("append rewrote full ledger")),
    ):
        store.append(_episode("NEW"))

    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    assert [row["skill"] for row in rows] == ["OLD", "NEW"]


def test_episode_retention_compacts_in_batches_and_keeps_the_newest_rows(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    store = EpisodeStore(path, limit=2)

    for index in range(3):
        store.append(_episode(f"STEP_{index}"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3  # bounded overflow

    store.append(_episode("STEP_3"))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["skill"] for row in rows] == ["STEP_2", "STEP_3"]


def test_next_runtime_instance_uses_the_size_checked_line_index(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    EpisodeStore(path).append(_episode("FIRST"))
    next_run = EpisodeStore(path)

    with patch.object(
        EpisodeStore,
        "_count_existing_lines",
        side_effect=AssertionError("valid line index should avoid a full ledger scan"),
    ):
        next_run.append(_episode("SECOND"))

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["skill"] for row in rows] == ["FIRST", "SECOND"]


def test_resource_ledger_uses_the_same_append_and_batched_retention(tmp_path: Path):
    path = tmp_path / "resource_ledger.jsonl"
    ledger = ResourceLedger(path, limit=2)

    for amount in range(4):
        ledger.append_spend(ResourceSpend(
            resource="meat",
            amount=amount,
            reason=f"step_{amount}",
            expected_value="test",
            before=10,
            after=10 - amount,
        ))

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["reason"] for row in rows] == ["step_2", "step_3"]
