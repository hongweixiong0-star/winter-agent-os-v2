"""The acceptance instrument, checked before it is trusted to check anything.

Section 33 asks for five verdicts, and four of them are properties of *code* -- so the tool that
prints them calls the code and parses the import graph.  The fifth, ``KNOWN_MODEL_CALLS = 0``, is a
property of a *run*, and it is the one that can be got wrong without anybody noticing: a tool that
reads a store nobody has written since the last pin, finds no rows, and prints ``0`` has said
"the model made no wrong call" when the truth is "nobody drove the model".  Those are opposite
findings and the same digit.

So this file tests the instrument, not the contract:

* it reads the numbers where they actually live (``row["metrics"]``, not the top level -- the funnel
  row nests them, and a top-level read silently returns ``None`` for every one, which formats as a
  plausible-looking blank rather than as an error);
* an empty window reads ``unmeasured`` and cannot read ``0``;
* it does not write, including through ``learning_funnel.refresh``, which persists the funnel when
  called and would have made a read-only report into a write against a production worktree handed
  to ``--root``;
* the three chains print the directive's own refusal codes rather than a summary of them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import ui_venus_contract_acceptance as acc

from winter_agent_v2 import ui_venus_contract as contract
from winter_agent_v2 import ui_venus_offline as offline
from winter_agent_v2 import ui_venus_online as online
from winter_agent_v2 import ui_venus_repair as repair


def _write_lines(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def _stamp(minutes_ago: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _planner_row(*, page_key: str, source: str = "LOCAL_GUI_MODEL") -> dict:
    """A planner call, in the shape ``local_planner`` really writes.

    ``decision`` is what separates a plan from a settlement in this one file, and a row without it
    is not counted as a call -- so a fixture that omitted it would prove nothing about the count.
    """
    return {
        "recorded_at": _stamp(), "source": source, "page_key": page_key,
        "goal": "DAILY_ROUTINE", "decision": "EXECUTE", "action_type": "CLICK_ELEMENT",
        "target_element_id": "E1", "reason": "the only actionable control on this screen",
    }


def _online_row(*, admitted: bool, stage: str = "", code: str = "", detail: str = "") -> dict:
    return {
        "recorded_at": _stamp(), "admitted": admitted, "trace_id": "t1", "page_key": "UNKNOWN_A",
        "verdict": {"ok": admitted, "code": code, "stage": stage, "detail": detail},
    }


class TheFunnelIsReadWhereTheNumbersAreTests(unittest.TestCase):
    """``row["metrics"]`` -- the top level holds ``funnel``/``metrics``/``console``/``sources``."""

    def test_a_top_level_read_would_have_found_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = acc.check_funnel(Path(tmp))
        self.assertNotIn("error", report)
        # The values exist, which is the whole point: a read of the top level returns None for each
        # of them and the tool would print "KNOWN_MODEL_CALLS None" as though the store were broken.
        self.assertIsNotNone(report["UNKNOWN_MODEL_CALLS"])
        self.assertIsNotNone(report["KNOWN_MODEL_CALLS"])
        self.assertIn("CONTRACT_ONLINE_ROWS", report["contract_ledgers"])

    def test_the_counts_that_live_in_metrics_are_the_ones_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lines(root / "learning" / "local_planner_steps.jsonl", [
                _planner_row(page_key="UNKNOWN_A"),
                _planner_row(page_key="UNKNOWN_B", source="LOCAL_QWEN"),
                _planner_row(page_key="HOME"),
            ])
            report = acc.check_funnel(root)
        self.assertEqual(report["UNKNOWN_MODEL_CALLS"], 3)
        self.assertEqual(report["KNOWN_MODEL_CALLS"], 1)

    def test_the_three_contract_ledgers_are_counted_by_this_modes_own_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lines(root / online.ONLINE_LEDGER_PATH, [
                _online_row(admitted=True, code="", detail="grounded: ok"),
                _online_row(admitted=False, stage="ELEMENT_EXISTENCE",
                            code="PLAN_TARGET_NOT_ON_THIS_FRAME"),
                _online_row(admitted=False, stage="GROUNDING", code="UNKNOWN_GROUNDING_FAILED"),
            ])
            _write_lines(root / repair.REPAIR_LEDGER_PATH, [{"kind": "PACKET", "ok": True}])
            _write_lines(root / offline.OFFLINE_LEDGER_PATH, [{"kind": "CANDIDATE", "ok": True}])
            report = acc.check_funnel(root)
            ledgers = report["contract_ledgers"]
        self.assertEqual(ledgers["CONTRACT_ONLINE_ROWS"], 3)
        self.assertEqual(ledgers["CONTRACT_ONLINE_ADMITTED"], 1)
        self.assertEqual(ledgers["CONTRACT_ONLINE_REFUSED"], 2)
        self.assertEqual(ledgers["CONTRACT_ONLINE_REFUSAL_FAMILIES"], {"TARGET": 1, "GROUNDING": 1})
        self.assertEqual(ledgers["CONTRACT_REPAIR_ROWS"], 1)
        self.assertEqual(ledgers["CONTRACT_OFFLINE_ROWS"], 1)


class AnEmptyWindowIsNotAZeroTests(unittest.TestCase):
    """§26's discipline: ``0`` wrong calls and no calls at all are the same digit, opposite facts."""

    def test_no_planner_call_in_the_window_reads_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = acc.check_funnel(Path(tmp))
        self.assertEqual(report["UNKNOWN_MODEL_CALLS_IN_WINDOW"], 0)
        self.assertIsInstance(report["KNOWN_MODEL_CALLS_IN_WINDOW"], str)
        self.assertTrue(report["KNOWN_MODEL_CALLS_IN_WINDOW"].startswith("unmeasured"))
        # ... and it still says what the all-time number is, so the reader can tell the store is
        # populated and the window is simply older than its last run.
        self.assertIn("all-time 0", report["KNOWN_MODEL_CALLS_IN_WINDOW"])

    def test_the_model_having_been_called_zero_wrong_times_reads_as_a_real_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lines(root / "learning" / "local_planner_steps.jsonl", [
                _planner_row(page_key="UNKNOWN_A"),
                _planner_row(page_key="UNKNOWN_B"),
            ])
            report = acc.check_funnel(root)
        # Two calls happened in the window and neither was on a named page: that *is* measurable,
        # and the answer is 0 -- an int, not the "unmeasured" sentence.
        self.assertEqual(report["UNKNOWN_MODEL_CALLS_IN_WINDOW"], 2)
        self.assertEqual(report["KNOWN_MODEL_CALLS_IN_WINDOW"], 0)

    def test_a_row_from_an_older_window_is_not_counted_as_this_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = _planner_row(page_key="HOME")
            stale["recorded_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            _write_lines(root / "learning" / "local_planner_steps.jsonl", [stale])
            report = acc.check_funnel(root)
        self.assertEqual(report["KNOWN_MODEL_CALLS"], 1)      # all time
        self.assertIn("unmeasured", str(report["KNOWN_MODEL_CALLS_IN_WINDOW"]))

    def test_the_window_it_reports_is_the_window_it_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = acc.check_funnel(Path(tmp), window_days=3)
        window = report["window"]
        self.assertEqual(window["window_days"], 3)
        since = datetime.fromisoformat(window["since"])
        now = datetime.fromisoformat(window["now"])
        self.assertAlmostEqual((now - since).total_seconds(), 3 * 86400, delta=5)


class TheInstrumentDoesNotWriteTests(unittest.TestCase):
    """The docstring says "nothing here writes".  ``refresh`` would have broken that promise."""

    def test_reading_the_funnel_leaves_no_file_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir()
            _write_lines(root / "learning" / "local_planner_steps.jsonl",
                         [_planner_row(page_key="UNKNOWN_A")])
            before = sorted(p.as_posix() for p in root.rglob("*"))
            acc.check_funnel(root)
            after = sorted(p.as_posix() for p in root.rglob("*"))
        self.assertEqual(before, after)

    def test_it_does_not_go_through_refresh(self):
        """A monkeypatched ``refresh`` must not be reachable from the read path."""
        from winter_agent_v2 import learning_funnel as lf

        called: list[object] = []
        original = lf.refresh

        def _trap(*args, **kwargs):
            called.append((args, kwargs))
            return original(*args, **kwargs)

        lf.refresh = _trap
        try:
            with tempfile.TemporaryDirectory() as tmp:
                acc.check_funnel(Path(tmp))
        finally:
            lf.refresh = original
        self.assertEqual(called, [])

    def test_a_root_it_cannot_read_is_reported_rather_than_raised(self):
        report = acc.check_funnel(Path(tempfile.gettempdir()) / "no-such-root-for-this-test")
        # Either the fold accepts a missing tree and reports empty counts, or it fails and the tool
        # says so.  What it may not do is take the report down with it.
        self.assertTrue("error" in report or "UNKNOWN_MODEL_CALLS" in report)


class TheCodeGuaranteesTests(unittest.TestCase):
    """§33's four ``false`` verdicts, re-derived here rather than quoted from the tool's output."""

    def test_the_contract_cannot_reach_the_device_or_the_loop(self):
        graph = acc.check_import_graph()
        self.assertEqual(graph["findings"], [])
        self.assertFalse(graph["MODEL_DIRECT_DEVICE_CONTROL"])

    def test_a_previous_frames_region_never_grounds(self):
        _, reason = online.local_ground(
            (0.5, 0.5, 0.1, 0.1),
            regions=[{"x_norm": 0.45, "y_norm": 0.45, "w_norm": 0.2, "h_norm": 0.2}],
            frame_now=contract.FrameIdentity("f2", "sha256:bb"),
            frame_then=contract.FrameIdentity("f1", "sha256:aa"))
        self.assertEqual(reason, online.GROUNDING_STALE_FRAME)
        self.assertFalse(online.VisualHistory(previous_key_frame="f1", purpose="compare")
                         .as_wire()["grounding_allowed"])

    def test_there_is_no_offline_channel_for_a_box_at_all(self):
        # The online mode exempts ``candidate_bbox_norm`` because it is its untrusted proposal
        # channel.  Offline has no such channel, so the same key is a finding here -- including
        # when it is smuggled into the open ``payload`` block.
        self.assertEqual(
            offline.find_any_geometry({"payload": {"candidate_bbox_norm": [0.1, 0.2, 0.3, 0.4]}}),
            "payload.candidate_bbox_norm")

    def test_stable_and_real_money_are_properties_with_no_setter(self):
        self.assertFalse(repair.may_overwrite_stable())
        self.assertFalse(contract.RiskEnvelope().real_money_allowed)


class TheSixTypesTests(unittest.TestCase):
    def test_every_directive_type_exists_with_its_four_parts(self):
        report = acc.check_six_types()
        self.assertTrue(report["complete"])
        self.assertEqual(
            [row["directive"] for row in report["rows"]],
            ["UIVenusContextPacketV1", "UIVenusSemanticActionV1", "UIVenusSkillRepairPacketV1",
             "UIVenusRepairCandidateV1", "OfflineUIVenusLearningPacketV1",
             "OfflineLearningCandidateV1"])

    def test_each_schema_is_named_exactly_as_the_directive_names_it(self):
        for row in acc.check_six_types()["rows"]:
            self.assertTrue(row["schema_is_the_directives_name"],
                            f"{row['directive']} carries schema {row['schema']!r}")

    def test_the_three_modes_have_three_distinct_ledgers(self):
        paths = {str(online.ONLINE_LEDGER_PATH), str(repair.REPAIR_LEDGER_PATH),
                 str(offline.OFFLINE_LEDGER_PATH)}
        self.assertEqual(len(paths), 3)


class TheThreeChainsTests(unittest.TestCase):
    """§33's three chains, by the codes they produce rather than by a summary of them."""

    def setUp(self):
        self.chains = acc.check_three_chains()

    def test_online_admits_a_click_on_a_control_this_frame_has(self):
        admitted = self.chains["ONLINE"]["admitted"]
        self.assertEqual(admitted["code"], "")
        self.assertEqual(admitted["stage"], "")

    def test_online_refuses_a_hallucinated_element_at_the_existence_stage(self):
        refused = self.chains["ONLINE"]["refused_a_hallucinated_element"]
        self.assertEqual(refused["code"], contract.PLAN_TARGET_NOT_ON_THIS_FRAME)
        self.assertEqual(refused["stage"], "ELEMENT_EXISTENCE")

    def test_repair_refuses_to_overwrite_stable(self):
        repair_chain = self.chains["SKILL_REPAIR"]
        self.assertEqual(repair_chain["known_skill_maturity"], "STABLE")
        self.assertEqual(repair_chain["overwrite_refused_with"], "REPAIR_WOULD_TOUCH_PRODUCTION")
        self.assertFalse(repair_chain["may_overwrite_stable"])

    def test_offline_refuses_an_execute_decision(self):
        offline_chain = self.chains["OFFLINE"]
        self.assertEqual(offline_chain["episodes_in_packet"], ["ep_001"])
        self.assertEqual(offline_chain["an_EXECUTE_answer_refused_with"],
                         "OFFLINE_DECISION_EXECUTE_FORBIDDEN")


class TheReportItselfTests(unittest.TestCase):
    def test_the_report_runs_and_says_what_it_cannot_prove(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = acc.main(["--root", tmp, "--json"])
        self.assertEqual(code, 0)

    def test_main_reports_the_window_it_measured_over(self):
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                acc.main(["--root", tmp, "--window-days", "2"])
        text = buffer.getvalue()
        self.assertIn("window", text)
        self.assertIn("unmeasured", text)
        self.assertIn("KNOWN_MODEL_CALLS", text)


if __name__ == "__main__":
    unittest.main()
