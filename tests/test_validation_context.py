"""Validation context must persist on the row, and the version gate must precede the device.

Two things are being defended here.

**§2 -- the context must survive on the episode.**  Not "the caller meant validation": the
operator's §8 rule is that a validation episode may never be read as production reuse, and the
only place that distinction can live is the row itself.  A field that is set in memory and
never serialised would satisfy every in-process check and lose the fact on disk, so the
round-trip is what is tested.

**§3 -- the version gate must run before the first device action.**  Checked afterwards, the
options are to discard a real episode or to credit it to the wrong version, and the game has
already been clicked either way.  The ordering is asserted structurally because the ordering
*is* the guarantee.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.learning import Episode, EpisodeStore  # noqa: E402

RUN_LIVE = ROOT / "tools/run_live.py"
TRACE = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"


def _episode(**over) -> Episode:
    """A minimally valid episode, so each test varies only the field it is about."""
    base = dict(
        episode_id="ep-1", goal_id="MAIL", skill="OPEN_MAP",
        state_before={}, action="tap", state_after={},
        result="SUCCESS", failure_type="", duration=1.0, mode="AUTO",
        verifier_ok=True,
    )
    base.update(over)
    return Episode(**base)


def _round_trip(tmp_path: Path, episode: Episode) -> dict:
    store = EpisodeStore(tmp_path / "episodes.jsonl", limit=100)
    store.append(episode)
    rows = [json.loads(line) for line in
            (tmp_path / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, "the episode store wrote nothing"
    return rows[-1]


def test_a_plain_episode_is_production_and_carries_no_validation_context(tmp_path: Path):
    """The operator's counterexample 4: an ordinary AUTO step must not look like validation."""
    row = _round_trip(tmp_path, _episode())
    assert row["execution_mode"] == "PRODUCTION"
    assert row["trace_id"] == ""
    assert row["job_id"] == ""
    assert row["capability"] == ""
    assert row["expected_after_version"] == ""


def test_a_validation_episode_keeps_its_whole_context_on_disk(tmp_path: Path):
    """Counterexample 5: trace, job, capability and expected version all survive the write."""
    row = _round_trip(tmp_path, _episode(
        episode_id="ep-val-1", goal_id="BEAST_HUNT", goal_progress=True,
        repo_revision="b" * 40,
        execution_mode="DEVELOPMENT_VALIDATION", trace_id=TRACE, job_id="5b525aa4",
        capability="SPEND_STAMINA_ON_BEAST", expected_after_version="b" * 40,
    ))
    assert row["execution_mode"] == "DEVELOPMENT_VALIDATION"
    assert row["trace_id"] == TRACE
    assert row["job_id"] == "5b525aa4"
    assert row["capability"] == "SPEND_STAMINA_ON_BEAST"
    assert row["expected_after_version"] == "b" * 40
    # ...and the evidence the operator listed alongside it.
    for field in ("repo_revision", "verifier_ok", "goal_progress", "skill", "episode_id",
                  "before_screenshot", "after_screenshot"):
        assert field in row, field


def test_the_gate_reads_the_frozen_revision_and_refuses_before_the_runtime_exists():
    """Counterexample 7, structurally: expected != process must exit before any device action.

    ``LiveRuntime(...)`` is the first thing that can touch the game, so the comparison has to
    appear above it -- and it compares the *frozen* revision, never a fresh read.

    Anchored on the comparison rather than on the message string: the string sits *inside* the
    refusal below the ``if``, so searching for it would place the window one line too low and
    the assertion would pass for the wrong reason.
    """
    source = RUN_LIVE.read_text(encoding="utf-8")
    gate = source.find("if args.expected_after_version and args.expected_after_version != code_revision")
    build = source.find("result = LiveRuntime(")
    assert gate != -1, "the version comparison must exist"
    assert build != -1
    assert gate < build, "the version gate must precede LiveRuntime construction"
    window = source[gate:build]
    assert "VALIDATION_VERSION_MISMATCH" in window
    assert "return 4" in window, "a mismatch must end the cycle rather than continue"


def test_the_gate_is_skipped_when_no_version_is_examined():
    """An ordinary AUTO cycle passes no expected version, so the gate must not fire on it."""
    source = RUN_LIVE.read_text(encoding="utf-8")
    gate_line = [line for line in source.splitlines()
                 if "args.expected_after_version != code_revision" in line]
    assert gate_line, "the comparison must exist"
    assert gate_line[0].strip().startswith("if args.expected_after_version and"), (
        "an empty expected version must short-circuit: production cycles have none"
    )


def test_the_context_travels_as_arguments_and_reaches_the_runtime():
    """§2: explicit CLI, and the runtime receives it -- no environment variables."""
    source = RUN_LIVE.read_text(encoding="utf-8")
    for flag in ("--execution-mode", "--trace-id", "--job-id", "--capability",
                 "--expected-after-version"):
        assert flag in source, flag
    for keyword in ("execution_mode=args.execution_mode", "trace_id=args.trace_id",
                    "job_id=args.job_id", "capability=args.capability",
                    "expected_after_version=args.expected_after_version"):
        assert keyword in source, keyword
    assert "os.environ" not in source[source.find("--execution-mode"):
                                      source.find("result = LiveRuntime(")], (
        "the validation context must not travel through the environment"
    )


def test_a_mismatch_cannot_produce_live_tried_or_live_verified():
    """Counterexamples 8 and 9: this runner must not write either event at all.

    It reports what it did in its own output and leaves the ledger to the queue, which is the
    only place the gates for those rungs live -- so a validation run that never reached the
    device cannot have credited anything.
    """
    source = RUN_LIVE.read_text(encoding="utf-8")
    for event in ('"live_tried"', '"live_verified"', "'live_tried'", "'live_verified'"):
        assert event not in source, f"run_live must not append {event}; the queue owns that"
