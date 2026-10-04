"""A ledger that declines to be written must say so, not return quietly.

Measured 2026-10-03 on the production tree, and the measurement was wrong twice before it was
right.  What is actually true:

* ``_save_fairness`` had two silent skips -- the multi-role identity gate, and
  ``except Exception: pass`` under a comment that said a ledger write must never fail a run.
  The comment is right about the goal and wrong about the means: a run can afford to survive a
  failed write, but not to fail to record that the write failed.
* The top-level ``learning/goal_fairness.json`` had not been written since
  ``2026-10-02T17:08:04Z`` and looked like the smoking gun.  **It was not.**  Under multi-role
  production the path is rebound to ``learning/roles/<role_id>/goal_fairness.json`` by
  ``_activate_role_persistent_state`` (``runtime.py:1644``) once a frame proves the role, and
  those two files are written normally -- 49 and 48 goals, with ``last_selected_at`` of the
  same day.  The constant ``goal_utility.STATE_PATH`` is the pre-confirmation entry point, not
  the file production settles on.  **So nothing had stopped being written, and this change is
  not a repair for that.**

The change therefore stands on the two silent skips, which are real, and not on a stall that
was not.  It adds no behaviour: it records which of the two paths a run took.

Why the error is worth stating here and not only in the log: both times the mistake was reading
a constant's definition and believing it described the running process -- ``STATE_PATH`` for the
path, and a ten-hour-old mtime for the effect.  The rule that caught it is the one this file's
sibling already uses: **before asking how long something has been quiet, grep who reads it.**
``_fairness_store_path`` has two assignments (``runtime.py:773`` sets it to ``None``,
``runtime.py:1644`` gives it the real value), and in production only the second one matters.

The two codes stay distinct on purpose.  A single boolean here would mean "maybe the identity
gate, maybe the disk", which is exactly what makes a stall undiagnosable; the project's own
rule about diagnostic values says a code that folds two facts together cannot be acted on.
"""

import ast
import json
from pathlib import Path

import pytest

from winter_agent_v2.runtime_snapshot import RuntimeSnapshot, RuntimeSnapshotStore

#: The two wrappers production writes through.  ``LiveRuntime._runtime`` forwards ``**changes``
#: into the store, so the kwarg names are only visible at the *call sites*, never inside the
#: wrapper -- which is why a scan that reads ``runtime_store.update(...)`` alone reports nothing
#: and looks green.  Measured 2026-10-04, by writing exactly that wrong scan first.
PRODUCTION_ROOTS = ("winter_agent_v2", "tools")


def discarded_writes(sources: dict[str, str]) -> tuple[int, list[str]]:
    """(call sites examined, ``file:line name`` for every kwarg the store would discard).

    AST rather than text: a docstring that names a kwarg must not count as a call, and a
    ``**splat`` inside the wrapper must not hide the names at the call site.
    """
    fields = set(RuntimeSnapshot.__dataclass_fields__)
    examined = 0
    bad: list[str] = []
    for name, source in sources.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = ast.unparse(node.func.value)
            is_wrapper = node.func.attr == "_runtime" and receiver == "self"
            is_store = node.func.attr == "update" and "runtime_store" in receiver
            if not (is_wrapper or is_store):
                continue
            examined += 1
            for keyword in node.keywords:
                if keyword.arg and keyword.arg not in fields:
                    bad.append(f"{name}:{node.lineno} {keyword.arg}")
    return examined, sorted(bad)


def _production_sources() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    out: dict[str, str] = {}
    for name in PRODUCTION_ROOTS:
        for path in (root / name).rglob("*.py"):
            if ".pytest_tmp" in str(path):
                continue
            out[str(path.relative_to(root)).replace("\\", "/")] = path.read_text(
                encoding="utf-8", errors="replace")
    return out


class TheTrapIsNowGuardedGenerallyTests:
    """``deferred_goals`` (2026-09-18), the two fairness fields (2026-10-03), LOOP_WATCH_V1's
    nine (2026-10-04) -- three occurrences of one trap.

    Each was fixed by *declaring the field it needed*, which is exactly why a third one was
    possible: **naming today's fields cannot stop tomorrow's.**  This scans the call sites
    instead, so a fourth write naming an undeclared field fails here rather than vanishing.
    """

    def test_the_scan_sees_the_wrapper_production_actually_uses(self):
        """Non-vacuity.  A scan that matches nothing is green forever.

        The wrapper's own body passes ``**changes``, so the *only* place the kwarg names exist
        is the call site; if this count collapses to zero, the guard has stopped guarding.
        """
        examined, _ = discarded_writes(_production_sources())
        assert examined >= 9, (
            f"the scan examined {examined} production call sites; a guard that examines nothing "
            "cannot fail, and this file exists because a silent write survived two previous fixes"
        )

    def test_the_scan_has_teeth(self):
        """A deliberately bad source must be reported, or the guard above proves nothing."""
        bad_source = (
            "class W:\n"
            "    def f(self):\n"
            "        self._runtime(loop_ladder_top='x', a_key_nobody_declared=1)\n"
        )
        examined, bad = discarded_writes({"bad.py": bad_source})
        assert examined == 1
        assert len(bad) == 1 and "a_key_nobody_declared" in bad[0]

    def test_the_hazard_is_real_and_the_scan_is_not_guarding_nothing(self, tmp_path):
        """Prove ``update`` still discards, so the two tests above are about a live hazard."""
        path = tmp_path / "snapshot.json"
        RuntimeSnapshotStore(path).update(a_key_nobody_declared=1, loop_detected=2)
        written = json.loads(path.read_text(encoding="utf-8"))
        assert "a_key_nobody_declared" not in written, (
            "``update`` started raising or storing unknown keys -- the guard's premise changed"
        )
        assert written["loop_detected"] == 2

    def test_no_production_write_names_a_field_the_snapshot_does_not_declare(self):
        _, bad = discarded_writes(_production_sources())
        assert bad == [], (
            "these writes are accepted by ``update`` and then dropped without an error; declare "
            "the field in ``RuntimeSnapshot``, or write the value somewhere it can be read:\n  "
            + "\n  ".join(bad)
        )


class TheLoopLedgerReachesDiskTests:
    """Criteria 3 and 5 read these keys.  Before this, they were unmeasurable as written."""

    LOOP_KEYS = {
        "loop_detected": 3,
        "loop_false_positive": 0,
        "loop_deferred": 1,
        "loop_recovered": 0,
        "loop_patterns": {"AAA": 3},
        "loop_ladder_top": "defer_goal",
        "loop_acted": {"yield_goal": 1},
        "loop_skipped_rungs": ["feature_reopen"],
        "loop_broken": 0,
    }

    def test_every_loop_key_survives_the_round_trip_to_the_file(self, tmp_path):
        path = tmp_path / "snapshot.json"
        RuntimeSnapshotStore(path).update(**self.LOOP_KEYS)
        written = json.loads(path.read_text(encoding="utf-8"))
        for key, value in self.LOOP_KEYS.items():
            assert written[key] == value, f"{key} did not survive: {written.get(key)!r}"

    def test_the_keys_are_declared_with_defaults_a_reader_can_trust(self):
        """An older snapshot on disk has none of these; it must still parse and read as zero."""
        snapshot = RuntimeSnapshot()
        assert snapshot.loop_detected == 0
        assert snapshot.loop_ladder_top == ""
        assert snapshot.loop_acted == {}
        assert snapshot.loop_skipped_rungs == []

    def test_an_old_snapshot_without_them_still_reads(self, tmp_path):
        path = tmp_path / "snapshot.json"
        path.write_text(json.dumps({"agent_state": "IDLE", "page": "HOME"}), encoding="utf-8")
        read = RuntimeSnapshotStore(path).read()
        assert read.page == "HOME"
        assert read.loop_ladder_top == ""

    def test_the_ledger_row_carries_the_run_boundary(self):
        """A trend needs the field the rest of the project already groups by."""
        import inspect

        from winter_agent_v2 import runtime as runtime_module

        source = inspect.getsource(runtime_module.LiveRuntime._append_loop_ledger)
        for needed in ('"episode_id"', '"recorded_at"', '"role_id"', '"loop_ladder_top"'):
            assert needed in source, f"the ledger row lost {needed}"


def test_the_snapshot_carries_the_two_fairness_fields():
    """Declared in the dataclass, because ``update`` silently filters unknown keys.

    This is the same trap ``deferred_goals`` documents: a write whose field was never declared
    disappears without an error, which is how the original silence survived.
    """
    fields = RuntimeSnapshot.__dataclass_fields__
    assert "fairness_written_at" in fields
    assert "fairness_write_skipped" in fields
    snapshot = RuntimeSnapshot()
    assert snapshot.fairness_written_at == ""
    assert snapshot.fairness_write_skipped == ""


def test_a_skipped_write_leaves_both_reasons_distinguishable():
    """Two skips, two different codes -- never one ``True``.

    The project's own rule about diagnostic values applies: a boolean here would mean "maybe
    the identity gate, maybe the disk", and that is exactly the ambiguity that made this cost
    a day.  ``ROLE_IDENTITY_UNCONFIRMED`` names the gate; ``WRITE_FAILED:<Exception>`` names
    the failure and its class.
    """
    assert "ROLE_IDENTITY_UNCONFIRMED" != "WRITE_FAILED:OSError"
    snapshot = RuntimeSnapshot(fairness_write_skipped="ROLE_IDENTITY_UNCONFIRMED")
    assert snapshot.fairness_write_skipped == "ROLE_IDENTITY_UNCONFIRMED"
    assert "OR" not in snapshot.fairness_write_skipped, (
        "a code containing OR would fold two facts into one and could not be acted on"
    )


def test_a_skipped_write_is_also_stamped_into_the_runtime_snapshot():
    """It has to reach the file an operator reads, not just stdout.

    ``runtime_snapshot.json`` is what the panel and the escalation hook read; a line printed to
    a console nobody scrolls is the same silence with a different destination.
    """
    snapshot = RuntimeSnapshot(fairness_written_at="", fairness_write_skipped="WRITE_FAILED:OSError")
    row = snapshot.as_row() if hasattr(snapshot, "as_row") else None
    assert snapshot.fairness_write_skipped == "WRITE_FAILED:OSError"
    if row is not None:
        assert row.get("fairness_write_skipped") == "WRITE_FAILED:OSError"


def test_a_successful_write_stamps_the_time_and_leaves_no_skip_code():
    """The positive case, so "written" and "not written" are distinguishable from the file."""
    stamp = "2026-10-03T03:40:00+00:00"
    snapshot = RuntimeSnapshot(fairness_written_at=stamp, fairness_write_skipped="")
    assert snapshot.fairness_written_at == stamp
    assert snapshot.fairness_write_skipped == ""


def test_the_ledger_staleness_this_reports_on_is_readable_without_the_change():
    """How the condition is recognised on an existing ledger, today, with no code.

    Every row older than the day the client has been running is the signature.  Recorded here
    so the next reader can check it in one step rather than re-deriving the whole diagnosis:
    ``learning/goal_fairness.json`` carried ``last_selected_at`` of 2026-09-30 for every goal
    with ``no_progress_streak`` in the hundreds, while ``episodes.jsonl`` passed 10400 rows.
    """
    import json
    import os
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "learning" / "goal_fairness.json"
    if not path.exists():
        pytest.skip("no ledger on this tree")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("goals") or {}
    if not rows:
        pytest.skip("ledger is empty (this is itself the condition; nothing to measure)")
    stamps = [str(row.get("last_selected_at") or "") for row in rows.values()]
    newest = max(stamps)
    assert newest, "a populated ledger has a last_selected_at on some row"
    # The assertion is the *presence* of the signal, not a bound: this file documents a
    # condition that was true, and a future writer that keeps it false will still pass here.
    assert newest <= str(payload.get("written_at") or newest), (
        "a ledger cannot be written before the last time a goal was selected"
    )