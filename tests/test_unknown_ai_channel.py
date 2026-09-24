"""The UNKNOWN question channel: answered automatically, grounded on the frame, judged per candidate.

Operator directive 2026-09-22 ("UNKNOWN AI 求助通道补齐").  Before this round the runtime half of the
channel was automatic and the answering half was a person at a terminal: the gateway was up and jobs
really ran (99 of them in ``learning/workbuddy_escalations.jsonl``), but nothing in the project ever
turned a question in ``learning/unknown_requests/`` into work.  Calling ``--list``/``--show``/
``--answer`` automatic AI reasoning would have been false.

What these tests pin, and each is one item of the directive:

一  a pending question becomes exactly one dispatched job, with a bounded, idempotent, audited
    consumer -- and nothing on the AUTO's step path can ever call it (the AUTO does not wait);
二  all three action shapes are answerable: a registered skill, a learned L1 action, and a
    temporary ordinary candidate that needs no registration, template or prior verification;
三  a point may be justified by text this frame read, by a template this project collected found on
    this frame, or by a bounded offset from a text box -- and by nothing else;
四  an answer made for another screen or another goal is filed as knowledge and re-asked, never
    acted on;
五  a page that offers purchases stays analysable: the risk decision is made on the candidate
    itself, so 关闭 on such a page is allowed and the purchase is refused.

The frame-level cases run on the real captured 燃霜矿区 event page (720x1280) -- the exact frame the
live AUTO asked about -- so what is exercised is the wire in ``runtime._advised_control`` and not a
helper in isolation.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import page_knowledge, ui_collection, unknown_advisor, unknown_dispatch  # noqa: E402
from winter_agent_v2.models import Action, Decision, ExecutionResult, Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The real frame the live AUTO filed its first unanswered question about (goal DAILY, page read as
#: UNKNOWN with the title 燃霜矿区).  Its own OCR read the four right-hand labels 说明/奖励/指南/历史排名
#: -- each of which has a wordless icon directly above it, which is the anchor case of item 三.
EVENT_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_163010_905874/"
    "20260922_163010_905874_step_002_before_20260922T083049654040.png"
)

#: Measured on that frame with the production OCR (the live request's own ``ocr_boxes``).
EXPLAIN_BOX = {
    "text": "说明",
    "confidence": 0.9995,
    "x_norm": 0.8528,
    "y_norm": 0.2242,
    "w_norm": 0.0597,
    "h_norm": 0.0203,
}
DONE_BOX = {
    "text": "已完成本期挑战",
    "confidence": 0.9966,
    "x_norm": 0.3375,
    "y_norm": 0.8914,
    "w_norm": 0.3236,
    "h_norm": 0.0281,
}

#: The wordless icon above 说明, as an offset from the label's own centre.  Measured on the frame by
#: cropping and looking: 说明's centre is at y 0.234, its clipboard icon's centre at y 0.205, so the
#: offset is -0.030.  (A first guess of -0.056 was written here and it lands in the gap *between*
#: two rows of icons -- see ``ui_collection.anchored_region``: the offset is declared, not measured,
#: so it has to be looked at rather than reasoned about.)
ICON_ABOVE_EXPLAIN = {"text": "说明", "dy_norm": -0.030, "w_norm": 0.06, "h_norm": 0.035}


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _runtime(root: Path, *, ocr=None, goal="DAILY") -> LiveRuntime:
    """The resolver called the way the live loop calls it, without a device.

    Same shape as ``tests/test_unknown_advisor.py``: an object built without ``__init__``, because
    what is under test is one method's decision and not the runtime's construction.
    """
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime.registry = v2_registry()
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._l1_context = None
    runtime._last_known_label = "EVENT"
    runtime._last_advice = None
    runtime._last_attempt_summary = {}
    runtime._advisor = unknown_advisor.UnknownAdvisor(root=root / "requests")
    runtime._transitions = None
    runtime._ui_pages = page_knowledge.PageCandidateStore(root=root / "pages")
    runtime._ui_candidates = ui_collection.UiCandidateStore(
        root=root / "candidates", manifest=root / "manifest.json"
    )
    runtime.brain = SimpleNamespace(current_goal=goal, goal_id="")
    return runtime


def _answer(request_id: str, **overrides) -> dict:
    payload = {
        "unknown_type": "CONTROL",
        "candidate_semantics": ["这个屏幕上的普通控件"],
        "proposed_action": "ORDINARY_CONTROL[关闭]",
        "expected_result": "the panel closes",
        "uncertainty": "medium",
    }
    payload.update(overrides)
    return payload


class _StubBridge:
    """The gateway bridge's two methods, over a script the test controls."""

    def __init__(self, *, available=True, statuses=None):
        self.available = available
        self.statuses = dict(statuses or {})
        self.submitted = []
        self.cancelled = []
        self._next = 0

    def is_available(self):
        return SimpleNamespace(available=self.available, reason="OK" if self.available else "DOWN")

    def submit_prompt(self, prompt, *, name="", model=None, effort=None, channel="", extra=None):
        self._next += 1
        job_id = f"job{self._next:02d}"
        self.submitted.append(
            {"prompt": prompt, "name": name, "model": model, "channel": channel, "extra": extra}
        )
        return SimpleNamespace(job_id=job_id, state="working", name=name, cwd=str(ROOT), raw={})

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        return True

    def status(self, job_id):
        entry = self.statuses.get(job_id)
        if entry is None:
            from winter_agent_v2.workbuddy_bridge import JobLost

            raise JobLost(f"{job_id} is gone")
        return SimpleNamespace(
            verdict=entry.get("verdict", "RUNNING"),
            terminal=entry.get("terminal", False),
            gateway_state=entry.get("state", "working"),
            # The two clocks the abandon rule reads.  Without them the rule cannot fire, which is how
            # the first version of this stub silently made the timebox untestable.
            started_at=entry.get("started_at"),
            progress_at=entry.get("progress_at"),
            # The gateway's own sentence about the job.  It is the only positive evidence that a
            # worker never started, so the stub has to be able to carry it (2026-09-24).
            detail=entry.get("detail", ""),
            result="",
        )


def _seed_question(root: Path, *, key: str, goal: str, frame: Path) -> unknown_advisor.UnknownRequest:
    request = unknown_advisor.build_request(
        unknown_type=unknown_advisor.UNKNOWN_CONTROL,
        page_label="UNKNOWN",
        page_key="UNKNOWN::燃霜矿区",
        frame_path=frame,
        goal=goal,
        ocr_texts=(EXPLAIN_BOX["text"],),
        ocr_boxes=(EXPLAIN_BOX,),
        situation="UNKNOWN#燃霜矿区",
    )
    advisor = unknown_advisor.UnknownAdvisor(root=root)
    advisor.ask(request, force=True)
    return request


class DispatchTests(unittest.TestCase):
    """Item 一: a pending question becomes exactly one job, within bounds, and never blocks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = _seed_question(
            self.root, key="q", goal="DAILY", frame=EVENT_FRAME
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _dispatcher(self, bridge=None, **kwargs):
        return unknown_dispatch.UnknownDispatcher(
            root=self.root,
            advisor=unknown_advisor.UnknownAdvisor(root=self.root),
            bridge=bridge if bridge is not None else _StubBridge(),
            **kwargs,
        )

    def test_a_pending_question_becomes_exactly_one_job(self):
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        report = dispatcher.dispatch(limit=1)
        self.assertEqual(len(report["submitted"]), 1)
        self.assertEqual(report["submitted"][0]["request_id"], self.request.request_id)
        self.assertEqual(len(bridge.submitted), 1, "one question, one job")
        self.assertEqual(bridge.submitted[0]["channel"], unknown_dispatch.CHANNEL)
        # The ledger is the evidence that this is automatic, so it has to say which frame.
        rows = [row for row in dispatcher.rows() if row["event"] == "submitted"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_id"], self.request.request_id)
        self.assertEqual(rows[0]["job_id"], "job01")
        self.assertEqual(rows[0]["frame_digest"], self.request.frame_digest)

    def test_the_same_question_is_never_asked_twice(self):
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=5)
        dispatcher.dispatch(limit=5)
        dispatcher.dispatch(limit=5)
        self.assertEqual(len(bridge.submitted), 1, "a second pass must find nothing to submit")
        records = dispatcher.records()
        self.assertEqual(records[self.request.request_id].attempts, 1)

    def test_the_channel_is_bounded(self):
        """In-flight limit, attempt cap and cooldown -- three bounds, each checkable."""
        bridge = _StubBridge()
        # A different *screen*: ``request_id`` is (screen, question), so asking twice about the same
        # one is the same question by construction -- which is what makes the dedupe correct.
        second = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL,
            page_label="UNKNOWN",
            page_key="UNKNOWN::挂机收益",
            frame_path=EVENT_FRAME,
            goal="DAILY",
        )
        unknown_advisor.UnknownAdvisor(root=self.root).ask(second, force=True)
        self.assertNotEqual(second.request_id, self.request.request_id)
        dispatcher = self._dispatcher(bridge, max_in_flight=1)
        first = dispatcher.dispatch(limit=5)
        self.assertEqual(len(first["submitted"]), 1, "the in-flight limit holds at one")
        self.assertTrue(first["skipped"], "and the question it did not submit says so")
        submitted_id = first["submitted"][0]["request_id"]
        waiting_id = first["skipped"][0]["request_id"]
        self.assertNotEqual(submitted_id, waiting_id)

        # A job that is terminal without an answer may be retried -- but only up to the cap.
        bridge.statuses["job01"] = {"verdict": "STOPPED", "terminal": True, "state": "stopped"}
        dispatcher.reconcile()
        self.assertNotIn(
            submitted_id,
            [item[0].request_id for item in dispatcher.candidates()],
            "a failed attempt waits out its cooldown before it is retried",
        )
        impatient = self._dispatcher(bridge, cooldown=0.0)
        retried = impatient.dispatch(limit=1)
        self.assertEqual(
            retried["submitted"][0]["request_id"],
            submitted_id,
            "the question whose job produced nothing is the one retried",
        )
        impatient._append({
            "event": "reconciled",
            "request_id": submitted_id,
            "job_id": "job02",
            "state": "STOPPED",
        })
        capped = self._dispatcher(bridge, cooldown=0.0)
        owed = [item[0].request_id for item in capped.candidates()]
        self.assertNotIn(submitted_id, owed, "two attempts is the cap")
        self.assertIn(waiting_id, owed, "and the question nobody has asked about yet is still owed")

    def test_a_job_whose_answer_arrived_is_never_abandoned_and_never_cancelled(self):
        """The measured case: work that is on disk is done, whatever the transport says.

        Measured 2026-09-22, job ``13ffdac6`` wrote ``answers/unknown__control__b6546e80.json`` at
        10:12:39Z and the ledger recorded it at 10:37:49Z as ``ABANDONED -- no result after 45
        minutes``, then cancelled it.  A background session that has finished its work still reads
        ``working`` until the gateway reaps it, so an age clock alone turns a job that produced into
        a job that produced nothing.
        """
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=1)
        answers = dispatcher.advisor.root / unknown_advisor.ANSWERS_DIR
        answers.mkdir(parents=True, exist_ok=True)
        (answers / f"{self.request.request_id}.json").write_text(
            json.dumps(_answer(self.request.request_id), ensure_ascii=False), encoding="utf-8"
        )
        bridge.statuses["job01"] = {
            "verdict": "RUNNING", "terminal": False, "state": "working",
            "started_at": int((datetime.now(timezone.utc) - timedelta(hours=3)).timestamp() * 1000),
        }
        report = dispatcher.reconcile()
        self.assertEqual(report["done"], 1)
        self.assertEqual(report["abandoned"], 0)
        self.assertEqual(bridge.cancelled, [], "a job that produced is not stopped")
        row = [r for r in dispatcher.rows() if r["event"] == "reconciled"][-1]
        self.assertEqual(row["state"], "ANSWERED")
        self.assertIn("the answer is on disk", row["note"])

    def test_a_stuck_job_that_produced_nothing_is_still_abandoned(self):
        """The bound is unchanged -- the artefact decides, not the hope."""
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=1)
        bridge.statuses["job01"] = {
            "verdict": "RUNNING", "terminal": False, "state": "working",
            "started_at": int((datetime.now(timezone.utc) - timedelta(hours=3)).timestamp() * 1000),
        }
        report = dispatcher.reconcile()
        self.assertEqual((report["abandoned"], report["done"]), (1, 0))
        self.assertEqual(bridge.cancelled, ["job01"])

    def test_a_question_the_runtime_asks_again_is_owed_one_more_job(self):
        """The attempt cap bounds a burst; it must not orphan a question still being asked.

        Measured on ``unknown__control__78694f1b`` (屏幕 ``UNKNOWN::对战``): both attempts were spent
        by ``2026-09-22T19:41`` and the runtime asked the same question again at ``2026-09-23T08:30``
        with no job possible, because ``ask`` refreshes the request file on every visit and the cap
        was being read as a lifetime limit.  That screen was stood on **20 times in 23 hours**, so
        the question was answerable -- the channel had just stopped asking it.
        """
        bridge = _StubBridge()
        now = datetime.now(timezone.utc)
        request_path = self.root / f"{self.request.request_id}.json"
        ledger = unknown_dispatch.UnknownDispatcher(
            root=self.root, bridge=bridge
        ).ledger_path
        ledger.parent.mkdir(parents=True, exist_ok=True)

        def spend_both_attempts(*, last_attempt_ago_hours: float) -> None:
            last = (now - timedelta(hours=last_attempt_ago_hours)).isoformat()
            ledger.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in (
                {"at": last, "event": "submitted", "request_id": self.request.request_id,
                 "job_id": "job01", "state": "working"},
                {"at": last, "event": "reconciled", "request_id": self.request.request_id,
                 "job_id": "job01", "state": "ABANDONED"},
                {"at": last, "event": "submitted", "request_id": self.request.request_id,
                 "job_id": "job02", "state": "working"},
                {"at": last, "event": "reconciled", "request_id": self.request.request_id,
                 "job_id": "job02", "state": "ABANDONED"},
            )) + "\n", encoding="utf-8")

        def the_request_was_asked(*, ago_hours: float) -> None:
            payload = json.loads(request_path.read_text(encoding="utf-8"))
            payload["created_at"] = (now - timedelta(hours=ago_hours)).isoformat()
            request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        # Two attempts spent 17 hours ago, and the question was last asked *before* them.
        spend_both_attempts(last_attempt_ago_hours=17)
        the_request_was_asked(ago_hours=30)
        capped = self._dispatcher(bridge, cooldown=0.0)
        self.assertNotIn(
            self.request.request_id, [row[0].request_id for row in capped.candidates()],
            "two spent attempts and no new ask is the cap, and it still holds",
        )
        self.assertEqual(
            [row[0].request_id for row in capped.orphans()], [self.request.request_id],
            "and the channel says out loud that this question is waiting for a person",
        )

        # The runtime stands on that screen again four hours ago: ``ask`` rewrites the file.
        the_request_was_asked(ago_hours=4)
        again = self._dispatcher(bridge, cooldown=0.0)
        self.assertIn(
            self.request.request_id, [row[0].request_id for row in again.candidates()],
            "a re-ask is the runtime saying the question is still open, so one more job is owed",
        )
        self.assertEqual(again.orphans(), [], "and it is not an orphan any more")

    def test_a_worker_that_never_started_is_not_charged_to_the_question(self):
        """Measured 2026-09-24: a job whose own process died before it read the screenshot.

        The gateway reaps a worker whose process is gone and says so in its own words --
        ``session ended — press enter to restart it``.  Nothing about the question can cause that
        and nothing about the question can fix it, so it must not spend the question's attempt
        budget; otherwise a single environment fault orphans every question in the channel, which
        is exactly what happened: seven questions pending, ``no job``, every one capped at two.
        """
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=1)
        bridge.statuses["job01"] = {
            "verdict": "FAILED", "terminal": True, "state": "failed",
            "detail": "session ended — press enter to restart it",
        }
        report = dispatcher.reconcile()
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report.get("failure_classes"), {unknown_dispatch.FAILURE_WORKER_DIED: 1})
        row = [r for r in dispatcher.rows() if r["event"] == "reconciled"][-1]
        self.assertEqual(row["failure_class"], unknown_dispatch.FAILURE_WORKER_DIED)

        record = dispatcher.records()[self.request.request_id]
        self.assertEqual((record.answer_failures, record.worker_deaths), (0, 1))

        # ...and the question is owed another job even though a *second* failure would have hit the
        # answer cap: the answer budget has not been touched at all.
        bridge.statuses["job01"] = {
            "verdict": "FAILED", "terminal": True, "state": "failed",
            "detail": "session ended — press enter to restart it",
        }
        owed = self._dispatcher(bridge, cooldown=0.0)
        self.assertIn(
            self.request.request_id, [row[0].request_id for row in owed.candidates()],
            "a dead worker does not close a question",
        )

    def test_the_worker_death_budget_is_bounded_too(self):
        """A channel that cannot start workers must not become a job generator."""
        bridge = _StubBridge()
        now = datetime.now(timezone.utc).isoformat()
        dispatcher = self._dispatcher(bridge)
        dispatcher.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for index in range(unknown_dispatch.MAX_WORKER_DEATH_ATTEMPTS):
            job = f"job{index:02d}"
            rows.append({"at": now, "event": "submitted", "request_id": self.request.request_id,
                         "job_id": job, "state": "working"})
            rows.append({"at": now, "event": "reconciled", "request_id": self.request.request_id,
                         "job_id": job, "state": "failed",
                         "failure_class": unknown_dispatch.FAILURE_WORKER_DIED})
        dispatcher.ledger_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )
        capped = self._dispatcher(bridge, cooldown=0.0)
        self.assertNotIn(
            self.request.request_id, [row[0].request_id for row in capped.candidates()],
            "the worker-death budget is finite",
        )
        reason = dict((r.request_id, why) for r, why in capped.orphans())[self.request.request_id]
        self.assertIn("worker deaths", reason)

    def test_the_channel_says_degraded_after_repeated_worker_deaths(self):
        """A condition an operator must be told, not left to infer from a shrinking list."""
        bridge = _StubBridge()
        now = datetime.now(timezone.utc).isoformat()
        dispatcher = self._dispatcher(bridge)
        dispatcher.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for index in range(unknown_dispatch.DEGRADED_AFTER_WORKER_DEATHS):
            job = f"job{index:02d}"
            rows.append({"at": now, "event": "submitted", "request_id": self.request.request_id,
                         "job_id": job, "state": "working"})
            rows.append({"at": now, "event": "reconciled", "request_id": self.request.request_id,
                         "job_id": job, "state": "failed",
                         "failure_class": unknown_dispatch.FAILURE_WORKER_DIED})
        dispatcher.ledger_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )
        health = dispatcher.health()
        self.assertEqual(health["state"], "DEGRADED")
        self.assertEqual(health["consecutive_worker_deaths"], unknown_dispatch.DEGRADED_AFTER_WORKER_DEATHS)
        self.assertIn("worker", health["detail"])
        self.assertEqual(dispatcher.state()["health"], "DEGRADED")

        # One answer-shaped failure behind it and the "in a row" clock resets: the channel is not
        # allowed to call itself degraded for ever because of one bad afternoon.
        with dispatcher.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": now, "event": "reconciled", "request_id": "other",
                "job_id": "job99", "state": "failed",
                "failure_class": unknown_dispatch.FAILURE_NO_ANSWER,
            }, ensure_ascii=False) + "\n")
        self.assertEqual(dispatcher.consecutive_worker_deaths(), 0)
        self.assertEqual(dispatcher.health()["state"], "OK")

    def test_an_attempt_that_produced_clears_the_degraded_state(self):
        """Otherwise the channel would call itself broken for ever after one bad afternoon.

        The health clock reads the same per-job fold the budgets do, so the one outcome that
        matters -- an attempt that produced an answer -- is also the one that clears it.
        """
        bridge = _StubBridge()
        now = datetime.now(timezone.utc).isoformat()
        dispatcher = self._dispatcher(bridge)
        dispatcher.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for index in range(unknown_dispatch.DEGRADED_AFTER_WORKER_DEATHS):
            job = f"job{index:02d}"
            rows.append({"at": now, "event": "submitted", "request_id": self.request.request_id,
                         "job_id": job, "state": "working"})
            rows.append({"at": now, "event": "reconciled", "request_id": self.request.request_id,
                         "job_id": job, "state": "failed",
                         "failure_class": unknown_dispatch.FAILURE_WORKER_DIED})
        rows.append({"at": now, "event": "submitted", "request_id": "other",
                     "job_id": "job99", "state": "working"})
        rows.append({"at": now, "event": "reconciled", "request_id": "other",
                     "job_id": "job99", "state": "done", "note": "answer written"})
        dispatcher.ledger_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )
        self.assertEqual(dispatcher.consecutive_worker_deaths(), 0)
        self.assertEqual(dispatcher.health()["state"], "OK")

    def test_a_reclassification_with_evidence_corrects_an_earlier_verdict(self):
        """The conservative default charges the question; evidence may move the charge off it.

        ``reconciled`` rows written before this vocabulary existed cannot tell "the agent could not
        answer" from "the worker never started", so they are charged to the question.  Where the
        proof is still on disk -- the job's own log -- a ``reclassified`` row carries it and the
        question is owed the attempt back.  Folded per job, so a correction replaces a verdict
        rather than adding to it.
        """
        bridge = _StubBridge()
        now = datetime.now(timezone.utc).isoformat()
        dispatcher = self._dispatcher(bridge)
        dispatcher.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"at": now, "event": "submitted", "request_id": self.request.request_id,
             "job_id": "job01", "state": "working"},
            {"at": now, "event": "reconciled", "request_id": self.request.request_id,
             "job_id": "job01", "state": "failed", "note": "no answer written"},
            {"at": now, "event": "submitted", "request_id": self.request.request_id,
             "job_id": "job02", "state": "working"},
            {"at": now, "event": "reconciled", "request_id": self.request.request_id,
             "job_id": "job02", "state": "failed", "note": "no answer written"},
        ]
        dispatcher.ledger_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )
        capped = self._dispatcher(bridge, cooldown=0.0)
        self.assertNotIn(
            self.request.request_id, [row[0].request_id for row in capped.candidates()],
            "with no class recorded the question is charged, which is the conservative default",
        )

        with dispatcher.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": now, "event": "reclassified", "request_id": self.request.request_id,
                "job_id": "job02", "failure_class": unknown_dispatch.FAILURE_WORKER_DIED,
                "evidence": "C:/Users/xhw/.codebuddy/logs/job-job02.log",
            }, ensure_ascii=False) + "\n")
        corrected = self._dispatcher(bridge, cooldown=0.0)
        record = corrected.records()[self.request.request_id]
        self.assertEqual((record.answer_failures, record.worker_deaths), (1, 1))
        self.assertIn(
            self.request.request_id, [row[0].request_id for row in corrected.candidates()],
            "the correction is what makes the retry earned rather than merely hoped for",
        )

    def test_a_question_whose_frame_is_gone_does_not_take_the_slot(self):
        """A question is answerable from its frame and nothing else.

        Measured 2026-09-24: ``unknown_i__control__b860b24a`` had been pending for two days with a
        screenshot that no longer exists.  No number of retries can answer it, so it must not spend
        the single in-flight slot -- but it is reported, not deleted.
        """
        ghost = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL,
            page_label="UNKNOWN",
            page_key="UNKNOWN::跳过I",
            frame_path=self.root / "no-such-frame.png",
            goal="MAIL",
        )
        unknown_advisor.UnknownAdvisor(root=self.root).ask(ghost, force=True)
        dispatcher = self._dispatcher(_StubBridge())
        self.assertTrue(dispatcher.frame_missing(ghost))
        self.assertNotIn(ghost.request_id, [row[0].request_id for row in dispatcher.candidates()])
        self.assertIn(
            ghost.request_id,
            dict((r.request_id, why) for r, why in dispatcher.orphans()),
            "and the channel says so out loud instead of quietly retrying it for ever",
        )

    def test_a_correction_does_not_buy_the_question_another_cooldown(self):
        """Measured on this module's own repair, 2026-09-24.

        Appending the ``reclassified`` row moved ``updated_at``, so the dispatch cooldown restarted
        from the correction -- and because the worker-death back-off multiplies it, a data fix about
        an old attempt silently bought the question another 45 minutes of silence.  Only an attempt
        may move that clock; bookkeeping must not delay the retry it exists to enable.
        """
        bridge = _StubBridge()
        attempt_at = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        dispatcher = self._dispatcher(bridge)
        dispatcher.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"at": attempt_at, "event": "submitted", "request_id": self.request.request_id,
             "job_id": "job01", "state": "working"},
            {"at": attempt_at, "event": "reconciled", "request_id": self.request.request_id,
             "job_id": "job01", "state": "failed", "note": "no answer written"},
            {"at": datetime.now(timezone.utc).isoformat(), "event": "reclassified",
             "request_id": self.request.request_id, "job_id": "job01",
             "failure_class": unknown_dispatch.FAILURE_WORKER_DIED, "evidence": "log"},
        ]
        dispatcher.ledger_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )
        record = dispatcher.records()[self.request.request_id]
        self.assertEqual(record.updated_at, attempt_at)
        self.assertEqual(record.worker_deaths, 1)
        self.assertIn(
            self.request.request_id, [row[0].request_id for row in dispatcher.candidates()],
            "the retry the correction earns must not be delayed by the correction itself",
        )

    def test_reconcile_records_what_became_of_each_job(self):
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=1)
        # "done" means the job finished **and** the answer is on disk: a job that stopped without
        # writing one is a failed attempt, and the two must not be conflated.
        answers = dispatcher.advisor.root / unknown_advisor.ANSWERS_DIR
        answers.mkdir(parents=True, exist_ok=True)
        (answers / f"{self.request.request_id}.json").write_text(
            json.dumps(_answer(self.request.request_id), ensure_ascii=False), encoding="utf-8"
        )
        bridge.statuses["job01"] = {"verdict": "DONE", "terminal": True, "state": "done"}
        report = dispatcher.reconcile()
        self.assertEqual((report["checked"], report["done"]), (1, 1))
        row = [r for r in dispatcher.rows() if r["event"] == "reconciled"][-1]
        # The ledger's ``state`` is the gateway's own word, so the two writers agree; the bridge's
        # verdict is kept beside it.
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["verdict"], "DONE")
        self.assertIn("answer written", row["note"])
        self.assertFalse(dispatcher.in_flight(), "a finished job holds no slot")

        # A job the gateway no longer knows frees its slot rather than blocking the channel.
        other = _StubBridge()
        dispatcher2 = self._dispatcher(other)
        other._next = 0
        dispatcher2._append({
            "event": "submitted", "request_id": self.request.request_id,
            "job_id": "vanished", "state": "working",
        })
        report2 = dispatcher2.reconcile()
        self.assertEqual(report2["lost"], 1)
        self.assertFalse(dispatcher2.in_flight())

    def test_a_running_job_keeps_holding_its_slot_after_a_reconcile(self):
        """The bound survived contact with the real gateway only after this was fixed.

        Measured on the channel's first live dispatch: ``dispatch`` recorded the state the submission
        reported (``working``) while ``reconcile`` recorded the bridge's verdict (``RUNNING``), so one
        reconcile pass made every running job look finished -- the in-flight limit read zero and a
        second job went out while the first was still working.  Both writers now speak the gateway's
        vocabulary, and this is the case that has to stay true.
        """
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge, max_in_flight=1)
        dispatcher.dispatch(limit=1)
        bridge.statuses["job01"] = {"verdict": "RUNNING", "terminal": False, "state": "working"}
        report = dispatcher.reconcile()
        self.assertEqual(report["checked"], 1)
        self.assertEqual(len(dispatcher.in_flight()), 1, "a running job still holds its slot")
        self.assertEqual(dispatcher.dispatch(limit=1)["submitted"], [], "so nothing else is sent")

    def test_a_row_written_with_the_bridge_verdict_still_reads_as_open(self):
        """The live ledger holds one of these: the real 13ffdac6 row says ``RUNNING``.

        Rows written before the vocabulary was unified are not rewritten -- an append-only ledger is
        the record of what happened -- so both spellings have to be understood or the in-flight bound
        silently frees itself again on the first real run after a restart.
        """
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher._append({
            "event": "reconciled",
            "request_id": self.request.request_id,
            "job_id": "legacy01",
            "state": "RUNNING",
        })
        records = dispatcher.records()
        self.assertTrue(records[self.request.request_id].open)
        self.assertEqual([record.job_id for record in dispatcher.open_jobs()], ["legacy01"])

    def test_a_second_consumer_cannot_run_a_pass_at_the_same_time(self):
        """There can legitimately be two consumers -- the panel's clock and the console tool while
        the panel runs an older build -- and two passes reading one ledger could both decide a
        question has no job and both submit one.  The lock is what makes that impossible; a refused
        pass reports it rather than pretending it did the work.
        """
        bridge = _StubBridge()
        first = self._dispatcher(bridge)
        second = self._dispatcher(bridge)
        with first._pass_lock() as held:
            self.assertTrue(held)
            self.assertIn("another consumer", second.worker()["lock"])
            self.assertEqual(bridge.submitted, [], "the refused pass submitted nothing")
        # ...and the lock is released however the pass ended, so the next one works.
        self.assertEqual(second.worker()["lock"], "")
        self.assertEqual(len(bridge.submitted), 1)

    def test_a_lock_left_by_a_dead_process_is_taken_over(self):
        """Measured during this round: a lock file outlived the process that wrote it, and every
        consumer that read it refused to work while printing "nothing to do".  A holder that is
        gone must not be able to stop the channel, and one that cannot be asked about falls back to
        the age.
        """
        import os as _os

        from winter_agent_v2.unknown_dispatch import _pid_alive

        self.assertIs(_pid_alive(_os.getpid()), True)
        self.assertIs(_pid_alive(999999), False)
        dispatcher = self._dispatcher(_StubBridge())
        lock = dispatcher.ledger_path.with_suffix(".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999 gone", encoding="utf-8")
        result = dispatcher.worker()
        self.assertEqual(result["lock"], "", "a dead holder is not a reason to refuse")
        self.assertIn("checked", result["reconcile"], "the pass actually ran")
        self.assertFalse(lock.exists(), "and it left nothing behind")

    def test_a_job_that_never_finishes_releases_its_slot(self):
        """Measured live: both dispatched jobs were still working at 49 and 43 minutes, so the
        gateway does not apply the escalation queue's 45-minute timebox -- a job dispatched from here
        has nobody's timebox but this module's.  Without abandoning it, the in-flight slot is held for
        ever and the question is never retried: the channel stops answering while looking busy.
        """
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=1)
        long_ago = int(datetime.now(timezone.utc).timestamp() * 1000) - (60 * 60 * 1000)
        bridge.statuses["job01"] = {
            "verdict": "RUNNING", "terminal": False, "state": "working",
            "started_at": long_ago, "progress_at": long_ago,
        }
        report = dispatcher.reconcile()
        self.assertEqual(report["abandoned"], 1)
        self.assertEqual(bridge.cancelled, ["job01"], "and it is asked to stop")
        self.assertFalse(dispatcher.in_flight(), "the slot is free again")
        row = [r for r in dispatcher.rows() if r["event"] == "reconciled"][-1]
        self.assertEqual(row["state"], "ABANDONED")

    def test_a_slow_job_that_is_still_working_keeps_its_slot(self):
        """The other side of it: a job that is thinking is not a job that is stuck.

        The frozen ``updatedAt`` is passed in on purpose.  It is what the second, rejected clock would
        have fired on -- every observed job freezes it about seven seconds in, healthy ones included
        -- so this case is what stops that rule being reintroduced by someone reading the gateway
        docs and believing the signal.
        """
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        dispatcher.dispatch(limit=1)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        bridge.statuses["job01"] = {
            "verdict": "RUNNING", "terminal": False, "state": "working",
            "started_at": now - (40 * 60 * 1000), "progress_at": now - (39 * 60 * 1000),
        }
        report = dispatcher.reconcile()
        self.assertEqual(report["abandoned"], 0, "40 minutes of honest work is not a slot to reclaim")
        self.assertEqual(len(dispatcher.in_flight()), 1)

    def test_a_gateway_that_is_gone_is_an_answer_not_a_crash(self):
        class _Broken(_StubBridge):
            def submit_prompt(self, *args, **kwargs):
                from winter_agent_v2.workbuddy_bridge import GatewayUnavailable

                raise GatewayUnavailable("port closed")

            def is_available(self):
                raise RuntimeError("probe blew up")

        dispatcher = self._dispatcher(_Broken())
        result = dispatcher.worker()
        self.assertEqual(result["dispatch"]["submitted"], [])
        self.assertTrue(result["dispatch"]["errors"], "the failure is reported, not swallowed")
        self.assertIs(dispatcher.state()["gateway"], False)

    def test_the_dry_run_shows_the_prompt_and_submits_nothing(self):
        bridge = _StubBridge()
        dispatcher = self._dispatcher(bridge)
        report = dispatcher.dispatch(limit=1, dry_run=True)
        self.assertEqual(bridge.submitted, [], "a dry run touches no gateway")
        self.assertEqual(dispatcher.rows(), [], "and writes no ledger row")
        prompt = report["submitted"][0]["prompt"]
        self.assertIn(self.request.request_id, prompt)
        self.assertIn(str(EVENT_FRAME), prompt)
        self.assertIn("ORDINARY_CONTROL[", prompt)
        self.assertIn("L1[", prompt)


class NeverWaitsTests(unittest.TestCase):
    """Item 一's other half: the AUTO must not be able to wait for a model."""

    def test_the_runtime_never_reaches_the_dispatcher(self):
        """The channel is driven by the panel's clock and by the tool -- never by a step."""
        runtime_source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
        brain_source = (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8")
        for name, source in (("runtime", runtime_source), ("brain", brain_source)):
            self.assertNotIn(
                "unknown_dispatch",
                source,
                f"{name} must not import the dispatcher: a step that could dispatch could wait",
            )

    def test_the_consumer_the_channel_has_is_the_panel_and_the_tool(self):
        panel = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
        worker = (ROOT / "tools/unknown_ai_worker.py").read_text(encoding="utf-8")
        self.assertIn("unknown_dispatch", panel, "the panel's clock owns the channel")
        self.assertIn("UnknownDispatcher", worker)


class PanelClockTests(unittest.TestCase):
    """The channel rides the panel's clock, and that wiring is the part production depends on.

    The panel is a long-lived process, so a new tick only exists after a restart -- which is exactly
    why the wiring has to be checked here rather than discovered in the window.  ``UnknownDispatcher``
    is patched to a stub: the point is that the heartbeat gets filled in and that a failure inside the
    pass is reported rather than raised, not that a real job is submitted.
    """

    def _pump(self):
        from tools import control_panel as panel

        # ``preload_every=0`` disables the other background pass this thread carries, so a failure
        # here is this test's failure and not the preloader's.
        return panel, panel.QueuePump(interval=0.01, preload_every=0, unknown_every=1)

    def test_the_tick_reports_what_the_channel_did(self):
        panel, pump = self._pump()
        seen: dict[str, object] = {}

        class _Stub:
            def __init__(self, root=None):
                seen["root"] = root

            def worker(self, *, submit: bool = True):
                # ``submit`` mirrors the real dispatcher's signature: the panel asks it to
                # reconcile without placing a job while the WorkBuddy channel is retired
                # (operator directive 2026-09-25).  A stub that omitted it would make this test
                # pass while the production call raised TypeError inside the panel's try/except --
                # i.e. a green test over a silently dead channel.
                seen["submit"] = submit
                return {"reconcile": {"checked": 1, "done": 1}, "dispatch": {"submitted": []}}

            def state(self):
                return {"gateway": True, "pending": 2, "answered": 1, "in_flight": ["job01"],
                        "attempts": {"q": 1}}

        # Patched where the tick imports it from: the import is lazy (inside the pass), which is
        # what keeps a heavy dependency off the panel's import path -- and what makes patching the
        # panel module itself do nothing at all.
        with mock.patch("winter_agent_v2.unknown_dispatch.UnknownDispatcher", _Stub):
            pump.tick()
        state = pump.state()
        self.assertEqual(state["unknown_gateway"], True)
        self.assertEqual(state["unknown_pending"], 2)
        self.assertEqual(state["unknown_answered"], 1)
        self.assertEqual(state["unknown_in_flight"], ["job01"])
        self.assertIn("reconciled", state["unknown_note"])
        self.assertTrue(state["unknown_last"], "the heartbeat carries a time")

    def test_a_broken_channel_is_a_state_not_a_dead_window(self):
        panel, pump = self._pump()

        class _Exploding:
            def __init__(self, root=None):
                pass

            def worker(self, *, submit: bool = True):
                raise RuntimeError("gateway went away")

            def state(self):
                raise RuntimeError("and so did the probe")

        with mock.patch("winter_agent_v2.unknown_dispatch.UnknownDispatcher", _Exploding):
            pump.tick()
        self.assertIn("unknown channel failed", pump.state()["unknown_note"])

    def test_the_renderer_shows_the_channel(self):
        """The heartbeat is written to disk for a reader outside the window; it has to be shown."""
        panel, _ = self._pump()
        source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
        for key in ("unknown_note", "unknown_pending", "unknown_in_flight"):
            self.assertIn(key, source)


class GroundingTests(unittest.TestCase):
    """Item 三: three bases, all measured on the current frame, and nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.ocr = _ocr()

    def test_a_region_anchored_to_real_text_resolves(self):
        regions = ui_collection.grounding_regions(EVENT_FRAME, self.ocr)
        texts = {region["text"] for region in regions}
        self.assertIn("说明", texts, "the frame really draws this label")
        anchored = ui_collection.anchored_region(ICON_ABOVE_EXPLAIN, regions)
        self.assertIsNotNone(anchored, "an icon above a real label is a grounded region")
        self.assertEqual(anchored["basis"], ui_collection.BASIS_ANCHOR)
        box = anchored["box_norm"]
        # The icon block sits above 说明 and is about 40 px tall: the derived region must be there
        # and not on the label itself, which is the whole point of the offset.
        self.assertLess(box["y_norm"] + box["h_norm"], EXPLAIN_BOX["y_norm"])
        self.assertAlmostEqual(box["w_norm"], 0.06, places=3)

    def test_an_anchor_on_text_the_frame_does_not_draw_is_refused(self):
        regions = ui_collection.grounding_regions(EVENT_FRAME, self.ocr)
        self.assertIsNone(
            ui_collection.anchored_region({"text": "这个字它没画", "dy_norm": -0.05}, regions)
        )

    def test_an_anchor_that_is_flung_across_the_screen_is_refused(self):
        """The offset is bounded: "next to" cannot mean the other side of the page."""
        regions = ui_collection.grounding_regions(EVENT_FRAME, self.ocr)
        self.assertIsNone(
            ui_collection.anchored_region(
                {"text": "说明", "dy_norm": -0.9, "w_norm": 0.05, "h_norm": 0.05}, regions
            )
        )
        self.assertIsNone(
            ui_collection.anchored_region({"text": "说明", "w_norm": 0.9, "h_norm": 0.9}, regions)
        )

    def test_a_template_this_project_collected_is_found_on_the_current_frame(self):
        """Item 三's third and fourth sources, through the project's own matcher."""
        import tempfile as _tempfile
        from PIL import Image

        with _tempfile.TemporaryDirectory() as tmp:
            crop = Path(tmp) / "icon.png"
            with Image.open(EVENT_FRAME) as image:
                width, height = image.size
                box = {
                    "x_norm": EXPLAIN_BOX["x_norm"],
                    "y_norm": EXPLAIN_BOX["y_norm"],
                    "w_norm": EXPLAIN_BOX["w_norm"],
                    "h_norm": EXPLAIN_BOX["h_norm"],
                }
                image.crop((
                    round(box["x_norm"] * width),
                    round(box["y_norm"] * height),
                    round((box["x_norm"] + box["w_norm"]) * width),
                    round((box["y_norm"] + box["h_norm"]) * height),
                )).save(crop)
            found = ui_collection.template_regions(
                EVENT_FRAME, [{"template_path": str(crop), "roi_norm": box, "semantic": "说明"}]
            )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["basis"], ui_collection.BASIS_TEMPLATE)
        self.assertGreaterEqual(found[0]["score"], 0.9)
        # And the region it reports is the one it *found*, not the one it was registered at.
        self.assertAlmostEqual(
            found[0]["box_norm"]["x_norm"], EXPLAIN_BOX["x_norm"], delta=0.02
        )

    def test_a_template_that_is_not_on_this_frame_is_not_a_region(self):
        entries = ui_collection.template_entries_from_candidates(
            ui_collection.UiCandidateStore().all(), page="DAILY"
        )
        if not entries:
            self.skipTest("no collected candidate crop to try")
        self.assertEqual(
            ui_collection.template_regions(EVENT_FRAME, entries, limit=4),
            [],
            "a template from another screen must not become evidence about this one",
        )

    def test_regions_alone_decide_what_may_be_tapped(self):
        regions = ui_collection.grounding_regions(EVENT_FRAME, self.ocr)
        artwork = (0.5, 0.42)   # the volcanic artwork: measured, this frame draws no text here
        self.assertFalse(
            [
                region for region in regions
                if region["box_norm"]["x_norm"] - 0.02 <= artwork[0]
                <= region["box_norm"]["x_norm"] + region["box_norm"]["w_norm"] + 0.02
                and region["box_norm"]["y_norm"] - 0.02 <= artwork[1]
                <= region["box_norm"]["y_norm"] + region["box_norm"]["h_norm"] + 0.02
            ],
            "the negative case has to be a point nothing measured",
        )
        advice = unknown_advisor.Advice(
            request_id="r",
            unknown_type="CONTROL",
            candidate_semantics=("x",),
            proposed_action="ORDINARY_CONTROL[关闭]",
            expected_result="",
            uncertainty="",
            target_point=artwork,
        )
        self.assertIsNone(
            unknown_advisor.grounded_region(advice, regions),
            "a point over nothing the frame measured is not a tap",
        )
        on_label = unknown_advisor.Advice(
            request_id="r",
            unknown_type="CONTROL",
            candidate_semantics=("x",),
            proposed_action="ORDINARY_CONTROL[已完成本期挑战]",
            expected_result="",
            uncertainty="",
            target_point=(
                DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2,
                DONE_BOX["y_norm"] + DONE_BOX["h_norm"] / 2,
            ),
        )
        region = unknown_advisor.grounded_region(on_label, regions)
        self.assertIsNotNone(region)
        self.assertEqual(region["basis"], ui_collection.BASIS_OCR_BOX)
        self.assertEqual(region["text"], "已完成本期挑战")


class AdvisedTapTests(unittest.TestCase):
    """Items 二/四/五 and the live wire, on the real frame the AUTO asked about."""

    @classmethod
    def setUpClass(cls):
        cls.ocr = _ocr()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = _runtime(self.root, ocr=self.ocr, goal="DAILY")

    def tearDown(self):
        self.tmp.cleanup()

    def _ask_and_answer(self, **overrides):
        world = WorldState(page=Page.UNKNOWN)
        self.assertIsNone(self.runtime._ordinary_control_candidate(world, EVENT_FRAME))
        pending = self.runtime._advisor.pending()
        self.assertEqual(len(pending), 1, "the frame files exactly one question")
        key = pending[0].request_id
        answers = self.runtime._advisor.root / unknown_advisor.ANSWERS_DIR
        answers.mkdir(parents=True, exist_ok=True)
        payload = _answer(key, **overrides)
        self.runtime._advisor.take  # (documented below: the answer is written as the reasoner would)
        (answers / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return key

    def test_an_unregistered_candidate_becomes_the_tap(self):
        """Item 二 C: no skill, no template, no prior verification -- and it still taps."""
        key = self._ask_and_answer(
            proposed_action="ORDINARY_CONTROL[已完成本期挑战]",
            target_semantics="已完成本期挑战",
            target_point=[
                DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2,
                DONE_BOX["y_norm"] + DONE_BOX["h_norm"] / 2,
            ],
        )
        point = self.runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), EVENT_FRAME)
        self.assertIsNotNone(point, "the answer has to become a tap")
        self.assertAlmostEqual(point[0], DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2, delta=0.01)
        last = self.runtime._ordinary_last
        # The key is the project's own vocabulary, which is what lets the next visit *reuse* the
        # step instead of asking again.
        self.assertEqual(last["semantic"], "ORDINARY_CONTROL[已完成本期挑战]")
        self.assertEqual(last["basis"], "AI_ADVICE/OCR_BOX")
        self.assertEqual(self.runtime._last_advice["request_id"], key)
        self.assertEqual(
            self.runtime._last_advice["action_kind"], unknown_advisor.ACTION_ORDINARY
        )

    def test_an_answer_that_is_only_a_wordless_element_is_grounded_by_its_anchor(self):
        """Item 三 in one case: the icon above 说明, which no template covers."""
        self._ask_and_answer(
            proposed_action="ORDINARY_CONTROL[说明旁的图标]",
            target_anchor=ICON_ABOVE_EXPLAIN,
        )
        point = self.runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), EVENT_FRAME)
        self.assertIsNotNone(point, "an anchored answer must become a tap")
        self.assertLess(point[1], EXPLAIN_BOX["y_norm"], "the icon, not the label under it")
        self.assertEqual(self.runtime._ordinary_last["basis"], "AI_ADVICE/ANCHORED_TO_TEXT")
        # A wordless element has no screen word to key a reuse on, so it keeps the advice's name.
        self.assertTrue(self.runtime._ordinary_last["semantic"].startswith("AI_ADVICE["))

    def test_an_answer_for_another_goal_is_refused_and_re_asked(self):
        """Item 四: the same screen under a different purpose is a different question."""
        key = self._ask_and_answer(
            target_point=[
                DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2,
                DONE_BOX["y_norm"] + DONE_BOX["h_norm"] / 2,
            ],
        )
        asker = _runtime(Path(self.tmp.name), ocr=self.ocr, goal="MAIL_ROUTINE")
        asker._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), EVENT_FRAME)
        self.assertIsNone(asker._ordinary_last, "nothing was tapped")
        self.assertIn("GOAL_CHANGED", str(asker._last_advice.get("filed_only")))
        self.assertTrue(
            (Path(self.root) / "requests" / f"{key}.json").exists(),
            "the stale answer stays on file as knowledge, and the question is still there",
        )

    def test_a_low_risk_candidate_is_allowed_on_a_page_that_offers_purchases(self):
        """Item 五: a page whose text mentions 钻石 and 加速 is analysable, and 关闭 on it works."""
        self._ask_and_answer(
            proposed_action="ORDINARY_CONTROL[关闭]",
            target_semantics="关闭",
            note="这个页面在卖钻石和加速礼包，我只点关闭",
            target_point=[
                DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2,
                DONE_BOX["y_norm"] + DONE_BOX["h_norm"] / 2,
            ],
        )
        allowed = self.runtime._ordinary_control_candidate(
            WorldState(page=Page.UNKNOWN), EVENT_FRAME
        )
        self.assertIsNotNone(allowed, "understanding such a page is allowed")
        # The key is the word the *screen* prints at the point that was grounded, not the reasoner's
        # label for it: reuse has to find the recorded wording on the next frame, so the screen's own
        # word is the only usable key.  What the reasoner called it is kept beside that.
        self.assertEqual(
            self.runtime._ordinary_last["semantic"], "ORDINARY_CONTROL[已完成本期挑战]"
        )
        self.assertEqual(self.runtime._last_advice["target_semantics"], "关闭")

    def test_a_candidate_that_is_the_purchase_itself_is_refused(self):
        """Item 五's other half: the fence is on the action, and it holds."""
        key = self._ask_and_answer(
            proposed_action="ORDINARY_CONTROL[立即购买]",
            target_semantics="立即购买",
            target_point=[
                DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2,
                DONE_BOX["y_norm"] + DONE_BOX["h_norm"] / 2,
            ],
        )
        self.runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), EVENT_FRAME)
        answers = Path(self.root) / "requests" / unknown_advisor.ANSWERS_DIR
        self.assertTrue(
            list(answers.glob("*.rejected.json")),
            "refused where every other answer is checked, and kept aside with its reason",
        )
        self.assertIsNone(self.runtime._ordinary_last, "and nothing was resolved into a tap")
        self.assertTrue(
            (Path(self.root) / "requests" / f"{key}.json").exists(),
            "the question stays on file rather than being silently consumed",
        )

    def test_a_proven_advised_step_is_learned_and_then_reused_without_a_reasoner(self):
        """The whole sentence: AI candidate -> tap -> verifier passes -> L1 -> reuse with no answer."""
        key = self._ask_and_answer(
            proposed_action="ORDINARY_CONTROL[已完成本期挑战]",
            target_semantics="已完成本期挑战",
            target_point=[
                DONE_BOX["x_norm"] + DONE_BOX["w_norm"] / 2,
                DONE_BOX["y_norm"] + DONE_BOX["h_norm"] / 2,
            ],
        )
        point = self.runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), EVENT_FRAME)
        self.assertIsNotNone(point)
        world = WorldState(page=Page.UNKNOWN)
        execution = ExecutionResult(
            executed=True,
            dry_run=False,
            action=Action(kind="TAP_SEMANTIC", target="ORDINARY_CONTROL"),
            error=None,
            backend="MAA",
            capture_backend="MAA",
            recognition_backend="MAA",
            latency_ms=120.0,
            tap_point=(round(point[0] * 720), round(point[1] * 1280)),
        )
        self.runtime._fold_control_experience(
            decision=Decision("TRY_ORDINARY_CONTROL", "advised", 0.0, "ordinary_control_observed"),
            before_state=world.to_dict(),
            after_state=world.to_dict(),
            execution=execution,
            observed_change="PAGE_CHANGED",
            goal_id="DAILY",
            frame=EVENT_FRAME,
            verification_ok=True,
        )
        entry = self.runtime._control_ledger.get(
            __import__("winter_agent_v2.control_experience", fromlist=["x"]).control_key(
                "UNKNOWN", "ORDINARY_CONTROL[已完成本期挑战]"
            )
        )
        self.assertIsNotNone(entry, "the advised step earned a ledger record")
        self.assertEqual(entry.level, "L1")
        self.assertEqual(entry.conditions.get("goal"), "DAILY")
        self.assertEqual(entry.visual_features["text"], "已完成本期挑战")

        # Now the same screen and goal again, with the answer deleted: the L1 action is reused.
        (Path(self.root) / "requests" / unknown_advisor.ANSWERS_DIR / f"{key}.json").unlink()
        reuse = self.runtime._l1_action_point(
            "UNKNOWN", "燃霜矿区", world, EVENT_FRAME, self.ocr,
            [region["text"] for region in ui_collection.grounding_regions(EVENT_FRAME, self.ocr)],
        )
        self.assertIsNotNone(reuse, "a proven step must be reusable with no reasoner in the loop")
        self.assertEqual(self.runtime._ordinary_last["source"], "L1_REUSE")
        self.assertEqual(self.runtime._ordinary_last["semantic"], "ORDINARY_CONTROL[已完成本期挑战]")


class RetiredChannelReportShapeTest(unittest.TestCase):
    """``submit=False`` must reconcile and keep the report's documented shape.

    Operator directive 2026-09-25 section 1 retires the automatic WorkBuddy call.  The panel and
    ``tools/unknown_ai_worker.py`` both read this report, so the retirement is expressed as an
    extra key rather than by changing what an existing key means.

    Written because the first version got exactly that wrong: it put the marker into
    ``dispatch["skipped"]``, which is a **list of per-request records**, and the console tool's own
    loop over it raised ``TypeError: string indices must be integers`` one line later.  The
    dispatcher's report looked right; only running the tool showed it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _dispatcher(self):
        return unknown_dispatch.UnknownDispatcher(
            root=self.root,
            advisor=unknown_advisor.UnknownAdvisor(root=self.root),
            bridge=_StubBridge(),
        )

    def test_submit_false_reports_a_list_where_a_list_is_documented(self):
        dispatcher = self._dispatcher()
        result = dispatcher.worker(submit=False)
        dispatch = result["dispatch"]
        self.assertIsInstance(dispatch["skipped"], list, "callers iterate this as records")
        self.assertEqual(dispatch["skipped"], [])
        self.assertEqual(dispatch["submitted"], [])
        self.assertEqual(dispatch["retired"], "WORKBUDDY_CHANNEL_RETIRED")

    def test_submit_false_places_no_job(self):
        bridge = _StubBridge()
        dispatcher = unknown_dispatch.UnknownDispatcher(
            root=self.root,
            advisor=unknown_advisor.UnknownAdvisor(root=self.root),
            bridge=bridge,
        )
        _seed_question(self.root, key="q", goal="DAILY", frame=EVENT_FRAME)
        dispatcher.worker(submit=False)
        self.assertEqual(bridge.submitted, [], "the retired channel must submit nothing")

    def test_submit_true_is_still_the_default(self):
        """A caller that knows nothing about the switch keeps the old behaviour."""
        import inspect

        signature = inspect.signature(unknown_dispatch.UnknownDispatcher.worker)
        self.assertIs(signature.parameters["submit"].default, True)


if __name__ == "__main__":
    unittest.main()
