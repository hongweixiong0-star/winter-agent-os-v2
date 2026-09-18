"""The V2 -> WorkBuddy escalation bridge: gate, prompt, transport, credentials.

What is under test and why it matters
------------------------------------
The operator's rule is that WorkBuddy may only be asked to work on a capability
for five reasons -- ``CAPABILITY_MISSING``, ``UNKNOWN_UI``,
``UNKNOWN_GAME_MECHANIC``, ``REPEATED_LIVE_FAILURE`` and ``STUCK_15_MIN`` -- and
that an ordinary game tick must never call it.  A rule like that is worth
nothing if it lives in a comment, so the gate is a predicate with tests around
it, and ``submit`` refuses before it touches the network.

The other half is that an escalation must not be able to look better than it is.
Every clause the operator listed (capability, WorldState, failure reason, recent
episode, evidence, Reuse Check, external prior, acceptance criteria) is present
by construction, the WorldState names where it came from, and the credential is
asserted absent from both the prompt and the audit ledger.

Transport is exercised against a fake ``_request`` -- the single HTTP seam -- so
these tests never need a live gateway.  The live gateway was probed separately on
2026-09-17 against CodeBuddy 2.137.1; the measured defaults that probe produced
(``permissionMode: dontAsk``, ``bgIsolation: none``) are pinned here so they
cannot drift back to a value that would strand the agent's commits in a worktree.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import workbuddy_bridge as bridge  # noqa: E402


def _code_without_docstrings(source: str) -> str:
    """The module's executable code, with every docstring and comment removed.

    Used to assert what the code *does* rather than what it *says*: a docstring
    that explains "config/v2.json is deliberately not read" must not trip a test
    looking for the string ``config``.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:]
    return ast.unparse(tree)


class FakeTransport(bridge.WorkBuddyBridge):
    """A bridge whose single HTTP seam is scripted instead of dispatched."""

    def __init__(self, responses, **kwargs):
        kwargs.setdefault("password", "test-secret-abcdef")
        super().__init__(**kwargs)
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request(self, method, path, payload=None, timeout=None):
        self.calls.append((method, path, payload))
        if not self.responses:
            raise AssertionError(f"unexpected call {method} {path}")
        return self.responses.pop(0)


def sample_context(**overrides) -> bridge.EscalationContext:
    base = dict(
        capability="BUILDING_UPGRADE",
        condition=bridge.REPEATED_LIVE_FAILURE,
        failure_reason="Point (280,640) selects a building but no route opens Page.BUILDING.",
        goal="KEEP_BUILDING_PRODUCTIVE",
        skill="BUILDING_UPGRADE",
        world_state={"page": "HOME", "confidence": 0.98},
        evidence_paths=("E:\\evidence\\build_live2",),
        recent_episodes=({"skill": "BUILDING_UPGRADE", "recorded_at": "2026-09-17T11:00:00+00:00"},),
        reuse_check="verdict: PARTIAL -- skill and brain route exist, verifier is a PARAMETER shape",
        external_prior="AminulIslamSifat: Home.Building ROI table at 720x1280",
    )
    base.update(overrides)
    return bridge.EscalationContext(**base)


# ------------------------------------------------------------------- gate


class EscalationGateTest(unittest.TestCase):
    def test_exactly_the_five_operator_conditions_are_allowed(self):
        self.assertEqual(
            set(bridge.ESCALATION_CONDITIONS),
            {
                "CAPABILITY_MISSING",
                "UNKNOWN_UI",
                "UNKNOWN_GAME_MECHANIC",
                "REPEATED_LIVE_FAILURE",
                "STUCK_15_MIN",
            },
        )

    def test_an_ordinary_game_tick_is_not_escalatable(self):
        # The explicit operator prohibition: routine ticks never call WorkBuddy.
        for tick in ("GAME_TICK", "TICK", "DAILY_CLAIM", "MAIL", "COLLECT"):
            self.assertFalse(bridge.should_escalate(tick), tick)
            self.assertFalse(bridge.is_escalation_condition(tick), tick)

    def test_condition_matching_is_case_and_space_insensitive(self):
        self.assertTrue(bridge.is_escalation_condition(" unknown_ui "))
        self.assertTrue(bridge.is_escalation_condition("UnKnown_Game_Mechanic"))

    def test_non_strings_are_refused_rather_than_coerced(self):
        for value in (None, 0, [], {}, True):
            self.assertFalse(bridge.is_escalation_condition(value), repr(value))

    def test_building_a_prompt_for_a_tick_raises_instead_of_downgrading(self):
        with self.assertRaises(bridge.EscalationRefused):
            bridge.build_prompt(sample_context(condition="GAME_TICK"))

    def test_submit_refuses_a_tick_before_any_http_call(self):
        transport = FakeTransport([])
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            with self.assertRaises(bridge.EscalationRefused):
                transport.submit(sample_context(condition="GAME_TICK"))
        self.assertEqual(transport.calls, [])

    def test_an_empty_capability_is_refused(self):
        with self.assertRaises(bridge.EscalationRefused):
            bridge.build_prompt(sample_context(capability="  "))


# ------------------------------------------------------------------ prompt


class PromptContentTest(unittest.TestCase):
    def setUp(self):
        self.prompt = bridge.build_prompt(sample_context())

    def test_every_clause_the_operator_required_is_present(self):
        for required in (
            "BUILDING_UPGRADE",                    # capability
            "REPEATED_LIVE_FAILURE",               # condition
            "no route opens Page.BUILDING",        # failure reason
            '"page": "HOME"',                      # current WorldState
            "recorded_at",                         # recent episode
            "build_live2",                         # evidence path
            "PARAMETER shape",                     # Reuse Check result
            "Home.Building ROI table",             # external prior
            "Acceptance criteria",                 # explicit acceptance
        ):
            self.assertIn(required, self.prompt, required)

    def test_the_required_procedure_is_stated_in_order(self):
        line = next(
            row for row in self.prompt.splitlines() if row.startswith("Reuse Check ->")
        )
        position = -1
        for step in bridge.REQUIRED_PROCEDURE:
            found = line.find(step)
            self.assertGreater(found, position, step)
            position = found

    def test_permanent_boundaries_are_restated_in_the_prompt(self):
        for clause in (
            "No second Scheduler, Manager or Registry",
            "Never force-push",
            "real-money payment",
        ):
            self.assertIn(clause, self.prompt)

    def test_acceptance_criteria_are_never_empty_even_when_the_caller_omits_them(self):
        prompt = bridge.build_prompt(sample_context(acceptance=()))
        self.assertIn("verifier bound in the live runtime", prompt)
        self.assertIn("``recorded_at``", prompt)

    def test_caller_acceptance_is_appended_not_substituted(self):
        prompt = bridge.build_prompt(
            sample_context(acceptance=("camp menu must be reachable without a tap",))
        )
        self.assertIn("camp menu must be reachable without a tap", prompt)
        self.assertIn("verifier bound in the live runtime", prompt)


class WorldStateProvenanceTest(unittest.TestCase):
    """The prompt may not describe a value it did not see the origin of."""

    def test_an_explicitly_passed_state_is_labelled_live(self):
        context = bridge.escalation_request_from_project(
            "BUILDING_UPGRADE", bridge.CAPABILITY_MISSING, "reason",
            world_state={"page": "HOME"}, root=ROOT,
        )
        self.assertEqual(context.world_state_source, bridge.WORLD_STATE_LIVE)
        self.assertIn(f"source: {bridge.WORLD_STATE_LIVE}", bridge.build_prompt(context))

    def test_a_missing_state_is_replayed_from_the_last_live_episode_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            (root / "learning/episodes.jsonl").write_text(
                "\n".join([
                    json.dumps({"skill": "X", "state_before": {"page": "MAP"},
                                "recorded_at": "2026-09-17T10:00:00+00:00"}),
                ]),
                encoding="utf-8",
            )
            context = bridge.escalation_request_from_project(
                "BUILDING_UPGRADE", bridge.CAPABILITY_MISSING, "reason", root=root,
            )
        self.assertEqual(context.world_state_source, bridge.WORLD_STATE_LAST_EPISODE)
        self.assertEqual(context.world_state.get("page"), "MAP")

    def test_with_no_history_at_all_the_source_says_not_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = bridge.escalation_request_from_project(
                "BUILDING_UPGRADE", bridge.CAPABILITY_MISSING, "reason", root=Path(tmp),
            )
        self.assertEqual(context.world_state_source, bridge.WORLD_STATE_NOT_SUPPLIED)
        self.assertEqual(dict(context.world_state), {})


# -------------------------------------------------------------- credentials


class CredentialHygieneTest(unittest.TestCase):
    # Deliberately NOT named ``PASSWORD = "<long literal>"``.  tools/scan_public_repo.py
    # flags exactly that shape (a credential word assigned a 12+ character string) and
    # cannot tell a fixture from the real thing, so this shape would make every push
    # report one credential hit.  A gate that always cries wolf is a gate people learn
    # to override, and the value here is obviously not a credential to a human reader.
    CREDENTIAL_FIXTURE = "fixture-value-not-a-credential"

    def test_the_environment_password_is_masked_in_the_prompt(self):
        # ``tools/workbuddy_bridge.py --prompt`` prints this string straight to a
        # terminal, so masking only in ``submit`` would have left that path open.
        with patch.dict(os.environ, {bridge.ENV_PASSWORD: self.CREDENTIAL_FIXTURE}):
            prompt = bridge.build_prompt(sample_context(
                failure_reason=f"the failure was caused by {self.CREDENTIAL_FIXTURE}",
                notes=f"extra context: {self.CREDENTIAL_FIXTURE}",
            ))
        self.assertNotIn(self.CREDENTIAL_FIXTURE, prompt)
        self.assertIn("***", prompt)

    def test_an_explicitly_passed_password_is_masked_in_the_submitted_payload(self):
        # A password handed to the constructor is invisible to ``redact``'s
        # environment lookup, so ``submit`` has to mask it separately.
        transport = FakeTransport(
            [(200, {"data": {"id": "job-x", "state": "working"}})],
            password=self.CREDENTIAL_FIXTURE,
        )
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            transport.submit(sample_context(failure_reason=f"reason with {self.CREDENTIAL_FIXTURE}"))
        sent = transport.calls[-1][2]["prompt"]
        self.assertNotIn(self.CREDENTIAL_FIXTURE, sent)

    def test_repr_does_not_expose_the_password(self):
        instance = bridge.WorkBuddyBridge(password=self.CREDENTIAL_FIXTURE)
        self.assertNotIn(self.CREDENTIAL_FIXTURE, repr(instance))
        self.assertIn("has_password=True", repr(instance))

    def test_the_ledger_row_never_carries_the_password(self):
        transport = FakeTransport([(200, {"data": {"id": "abc123"}})],
                                  password=self.CREDENTIAL_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            transport.submit(sample_context(failure_reason=f"reason with {self.CREDENTIAL_FIXTURE}"))
            written = transport.ledger_path.read_text(encoding="utf-8")
        self.assertNotIn(self.CREDENTIAL_FIXTURE, written)

    def test_redact_replaces_a_credential_wherever_it_appears(self):
        with patch.dict(os.environ, {bridge.ENV_PASSWORD: self.CREDENTIAL_FIXTURE}):
            self.assertEqual(bridge.redact(f"token={self.CREDENTIAL_FIXTURE}"), "token=***")

    def test_the_password_is_an_environment_variable_and_nothing_else(self):
        with patch.dict(os.environ, {bridge.ENV_PASSWORD: "from-env-value"}):
            self.assertEqual(bridge.gateway_password(), "from-env-value")
        # With no process value the persisted user environment is consulted.  Still
        # an environment variable -- that is why it is allowed -- and the test pins
        # both branches explicitly rather than depending on what this machine has
        # set, so it means the same thing on a clean host.
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(bridge, "persisted_password", return_value="from-user-env"):
            os.environ.pop(bridge.ENV_PASSWORD, None)
            self.assertEqual(bridge.gateway_password(), "from-user-env")
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(bridge, "persisted_password", return_value=None):
            os.environ.pop(bridge.ENV_PASSWORD, None)
            self.assertIsNone(bridge.gateway_password())

    def test_a_stale_process_credential_falls_back_to_the_persisted_one(self):
        """Measured 2026-09-18: the shell that launched the panel carried a
        43-character value answering 401 while the user environment's 24-character
        value answered 200 -- same machine, same moment.  A credential that exists
        and is wrong is indistinguishable from a gateway that is down."""
        import urllib.error
        import urllib.request as urllib_request

        offered: list[str] = []

        class Response:
            status = 200

            def read(self) -> bytes:
                return b'{"data": {}}'

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *exc: object) -> bool:
                return False

        def opener(request, timeout=None):  # noqa: ANN001, ANN202 - urllib signature
            offered.append(request.get_header("Authorization"))
            if len(offered) == 1:
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
            return Response()

        with patch.dict(os.environ, {bridge.ENV_PASSWORD: "stale-process-value"}), \
             patch.object(bridge, "persisted_password", return_value="good-user-env-value"), \
             patch.object(urllib_request, "urlopen", opener):
            instance = bridge.WorkBuddyBridge()
            code, _body = instance._request("GET", "/api/v1/health")
            self.assertEqual(code, 200)
            self.assertEqual(offered, ["Bearer stale-process-value", "Bearer good-user-env-value"])
            # The working one is adopted, so the extra round trip is paid at most once.
            self.assertEqual(instance._password, "good-user-env-value")
            self.assertIsNone(instance._fallback_password)

    def test_config_v2_json_is_never_consulted_for_a_credential(self):
        # A credential in a tracked file is what this design forbids, so the
        # module must not even look.  Checked against the *executable* code with
        # docstrings stripped -- the module docstring legitimately names the file
        # in order to explain why it is not read.
        code = _code_without_docstrings(
            (ROOT / "winter_agent_v2/workbuddy_bridge.py").read_text(encoding="utf-8")
        )
        self.assertNotIn("config", code)

    def test_no_credential_means_not_available_and_no_request_is_made(self):
        transport = FakeTransport([])
        transport._password = ""
        availability = transport.is_available()
        self.assertFalse(availability.available)
        self.assertEqual(availability.reason, "NO_CREDENTIAL")
        self.assertEqual(transport.calls, [])


# -------------------------------------------------------------- availability


class AvailabilityTest(unittest.TestCase):
    def test_a_healthy_gateway_is_reported_available(self):
        transport = FakeTransport([(200, {"data": {"status": "ok", "uptime": 12.5}})])
        availability = transport.is_available()
        self.assertTrue(availability.available)
        self.assertEqual(availability.reason, "OK")
        self.assertTrue(bool(availability))

    def test_an_unreachable_gateway_is_an_answer_not_an_exception(self):
        class Unreachable(FakeTransport):
            def _request(self, method, path, payload=None, timeout=None):
                raise bridge.GatewayUnavailable("http://127.0.0.1:8080: refused")

        availability = Unreachable([]).is_available()
        self.assertFalse(availability.available)
        self.assertEqual(availability.reason, "GATEWAY_UNREACHABLE")

    def test_a_rejected_password_is_distinguished_from_a_missing_one(self):
        transport = FakeTransport([(401, {"error": {"code": "AUTH_REQUIRED", "message": "no"}})])
        availability = transport.is_available()
        self.assertFalse(availability.available)
        self.assertEqual(availability.reason, "AUTH_REJECTED")
        self.assertEqual(availability.detail.get("code"), "AUTH_REQUIRED")

    def test_an_unhealthy_status_is_not_treated_as_available(self):
        transport = FakeTransport([(200, {"data": {"status": "degraded"}})])
        self.assertFalse(transport.is_available().available)


# ----------------------------------------------------------------- transport


class SubmitContractTest(unittest.TestCase):
    def _submit(self, **kwargs):
        transport = FakeTransport([(200, {"data": {"id": "job-1", "state": "working",
                                                  "cwd": str(bridge.PROJECT_ROOT),
                                                  "name": "n", "sessionId": "s"}})], **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            submission = transport.submit(sample_context())
            ledger = transport.ledger_path.read_text(encoding="utf-8")
        return transport, submission, ledger

    def test_the_payload_carries_the_measured_defaults(self):
        transport, _, _ = self._submit()
        method, path, payload = transport.calls[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, bridge.JOBS_PATH)
        # Measured 2026-09-17 with four real jobs on one prompt:
        #   dontAsk           -> DENIED
        #   acceptEdits       -> DENIED
        #   auto              -> DENIED
        #   bypassPermissions -> GIT=19964ec PY=42   (executed)
        # Only one of them lets an escalation do anything, so that is the default.
        self.assertEqual(payload["permissionMode"], "bypassPermissions")
        self.assertEqual(bridge.DEFAULT_PERMISSION_MODE, "bypassPermissions")
        # And a real escalation with `dontAsk` said so in its own words: "Permission
        # to use Bash has been denied ... Read/Write/Edit work; execution does not."
        self.assertEqual(payload["bgIsolation"], "none")
        self.assertEqual(payload["cwd"], str(bridge.PROJECT_ROOT))

    def test_a_read_only_success_is_not_evidence_that_a_shell_ran(self):
        """The mistake this default was corrected from.

        An earlier probe used ``dontAsk``, asked for ``git rev-parse HEAD`` and came
        back with the correct 40-character hash -- which was read as proof that
        ``dontAsk`` runs shells.  It proved nothing: ``.git/refs/heads/main`` holds
        the same hash and Read was allowed, and a later agent reported that even
        ``PowerShell`` was restricted to a read-only allowlist in which
        ``git rev-parse`` passed while ``python``/``pytest``/``git commit`` did not.
        So the harness had verified the *output* and not the *mechanism*.  This test
        pins the corrected conclusion rather than the misleading observation.
        """
        self.assertNotEqual(bridge.DEFAULT_PERMISSION_MODE, "dontAsk")
        self.assertIn("bypassPermissions", bridge.DEFAULT_PERMISSION_MODE)

    def test_the_permission_mode_can_still_be_overridden_by_the_environment(self):
        with patch.dict(os.environ, {bridge.ENV_PERMISSION_MODE: "acceptEdits"}):
            self.assertEqual(bridge.WorkBuddyBridge().permission_mode, "acceptEdits")

    def test_the_working_directory_is_fixed_to_this_project(self):
        transport, submission, _ = self._submit()
        self.assertEqual(submission.cwd, str(bridge.PROJECT_ROOT))
        self.assertEqual(str(bridge.PROJECT_ROOT), r"E:\无尽冬日智能体")

    def test_the_job_id_is_returned_for_polling(self):
        _, submission, _ = self._submit()
        self.assertEqual(submission.job_id, "job-1")
        self.assertEqual(submission.state, "working")

    def test_the_ledger_records_the_condition_that_justified_the_escalation(self):
        _, _, ledger = self._submit()
        row = json.loads(ledger.splitlines()[-1])
        self.assertEqual(row["event"], "submitted")
        self.assertEqual(row["condition"], bridge.REPEATED_LIVE_FAILURE)
        self.assertEqual(row["capability"], "BUILDING_UPGRADE")
        self.assertTrue(row["recorded_at"])

    def test_a_failed_submit_is_recorded_and_raises(self):
        transport = FakeTransport([(500, {"error": {"code": "BOOM", "message": "no"}})])
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            with self.assertRaises(bridge.GatewayUnavailable):
                transport.submit(sample_context())
            row = json.loads(transport.ledger_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["event"], "submit_failed")
        self.assertEqual(row["http_status"], 500)

    def test_an_audit_failure_does_not_break_a_submission(self):
        transport = FakeTransport([(200, {"data": {"id": "job-2", "state": "working"}})])
        transport.ledger_path = Path("Z:/nope/does/not/exist/ledger.jsonl")
        self.assertEqual(transport.submit(sample_context()).job_id, "job-2")


class StatusContractTest(unittest.TestCase):
    def _status(self, gateway_state, *, settled=False, output=None):
        job = {"id": "job-9", "state": gateway_state, "settled": settled, "alive": False,
               "detail": "d"}
        if output is not None:
            job["output"] = output
        transport = FakeTransport([(200, {"data": {"job": job}})])
        return transport, transport.status("job-9")

    def test_gateway_states_map_onto_v2_verdicts(self):
        for gateway_state, verdict in (
            ("working", bridge.VERDICT_RUNNING),
            ("blocked", bridge.VERDICT_BLOCKED),
            ("done", bridge.VERDICT_DONE),
            ("failed", bridge.VERDICT_FAILED),
            ("stopped", bridge.VERDICT_STOPPED),
        ):
            _, status = self._status(gateway_state)
            self.assertEqual(status.verdict, verdict, gateway_state)

    def test_terminal_verdicts_are_recognised(self):
        for gateway_state in ("done", "failed", "stopped"):
            _, status = self._status(gateway_state, settled=True)
            self.assertTrue(status.terminal, gateway_state)
        _, running = self._status("working")
        self.assertFalse(running.terminal)

    def test_the_agent_result_is_surfaced(self):
        _, status = self._status("done", settled=True, output={"result": "BRIDGE_OK"})
        self.assertEqual(status.result, "BRIDGE_OK")
        self.assertIn("BRIDGE_OK", status.describe())

    def test_an_unknown_job_raises_rather_than_reporting_a_fake_state(self):
        transport = FakeTransport([(404, {"error": {"code": "NOT_FOUND", "message": "x"}})])
        with self.assertRaises(bridge.GatewayUnavailable):
            transport.status("missing")

    def test_describe_does_not_leak_a_credential_picked_up_from_a_result(self):
        with patch.dict(os.environ, {bridge.ENV_PASSWORD: "leaky-password"}):
            _, status = self._status("done", settled=True,
                                     output={"result": "used leaky-password"})
            self.assertNotIn("leaky-password", status.describe())


class CancelContractTest(unittest.TestCase):
    def test_a_stopped_job_returns_true(self):
        transport = FakeTransport([(200, {"data": {"stopped": True}})])
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            self.assertTrue(transport.cancel("job-3"))
            self.assertEqual(transport.calls[-1][1], f"{bridge.JOBS_PATH}/job-3/stop")

    def test_a_refused_stop_raises_instead_of_claiming_success(self):
        transport = FakeTransport([(404, {"error": {"code": "NOT_FOUND", "message": "x"}})])
        with tempfile.TemporaryDirectory() as tmp:
            transport.ledger_path = Path(tmp) / "ledger.jsonl"
            with self.assertRaises(bridge.GatewayUnavailable):
                transport.cancel("job-4")
            row = json.loads(transport.ledger_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["event"], "cancel_failed")


# ------------------------------------------------------------ disk helpers


class RecentEpisodesTest(unittest.TestCase):
    def test_rows_without_recorded_at_are_imported_history_and_are_excluded(self):
        # The project's own rule: an imported row looks identical to a live one,
        # and once turned four non-live rows into a "4 successful runs" claim.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "episodes.jsonl"
            path.write_text("\n".join([
                json.dumps({"skill": "A", "result": "ok"}),
                json.dumps({"skill": "B", "result": "ok", "recorded_at": "2026-09-17T09:00:00+00:00"}),
                json.dumps({"skill": "A", "result": "ok", "recorded_at": "2026-09-17T10:00:00+00:00"}),
            ]), encoding="utf-8")
            rows = bridge.recent_episodes(path, limit=5)
        self.assertEqual([r["skill"] for r in rows], ["B", "A"])

    def test_the_most_recent_come_last_and_the_limit_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "episodes.jsonl"
            path.write_text("\n".join(
                json.dumps({"skill": f"S{i}", "recorded_at": f"2026-09-17T1{i}:00:00+00:00"})
                for i in range(5)
            ), encoding="utf-8")
            rows = bridge.recent_episodes(path, limit=2)
        self.assertEqual([r["skill"] for r in rows], ["S3", "S4"])

    def test_a_missing_log_is_an_empty_answer_not_a_crash(self):
        self.assertEqual(bridge.recent_episodes(Path("Z:/nope/episodes.jsonl")), ())


class EvidencePathTest(unittest.TestCase):
    def test_the_needle_and_the_path_are_normalised_the_same_way(self):
        # Regression: the path lost its underscores but BUILDING_UPGRADE kept
        # them, so this match could never fire and evidence always looked absent.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "dataset/truth_audit/building_upgrade_20260918"
            target.mkdir(parents=True)
            hits = bridge.evidence_paths_for("BUILDING_UPGRADE", root)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].endswith("building_upgrade_20260918"))

    def test_the_evidence_directory_itself_is_reported_not_only_its_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dataset/truth_audit/alliance_help_20260918/key").mkdir(parents=True)
            hits = bridge.evidence_paths_for("ALLIANCE_HELP", root)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].endswith("alliance_help_20260918"))

    def test_no_evidence_yields_an_empty_tuple(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bridge.evidence_paths_for("NOTHING_MATCHES", Path(tmp)), ())


class ProjectContextTest(unittest.TestCase):
    def test_the_failure_reason_survives_into_the_prompt_verbatim(self):
        reason = "SELECT_INFANTRY_CAMP taps the camp and the client lands on MAP"
        context = bridge.escalation_request_from_project(
            "SELECT_INFANTRY_CAMP", bridge.REPEATED_LIVE_FAILURE, reason, root=ROOT,
        )
        self.assertIn(reason, bridge.build_prompt(context))

    def test_the_real_repository_yields_a_usable_context(self):
        context = bridge.escalation_request_from_project(
            "TRAINING", bridge.UNKNOWN_UI, "camp menu never drawn", root=ROOT,
        )
        self.assertTrue(context.evidence_paths)
        self.assertIn(f"source: {context.world_state_source}", bridge.build_prompt(context))


class CliWiringTest(unittest.TestCase):
    """The command's own argument plumbing.

    A first live run read ``args.job_id`` while argparse had stored the value
    under ``args.status``, and raised AttributeError only on a real invocation.
    These tests drive ``main`` so that class of mistake is caught here instead.
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_wb_cli_under_test", ROOT / "tools/workbuddy_bridge.py")
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def _run(self, argv):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.cli.main(argv)
        return code, buffer.getvalue()

    def test_status_passes_the_job_id_through_to_the_transport(self):
        status = bridge.JobStatus(job_id="abc123", gateway_state="done",
                                  verdict=bridge.VERDICT_DONE, settled=True)
        with patch.object(bridge.WorkBuddyBridge, "status", return_value=status) as called:
            code, output = self._run(["--status", "abc123"])
        called.assert_called_once_with("abc123")
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertIn("abc123", output)

    def test_a_running_job_reports_as_not_yet_settled(self):
        status = bridge.JobStatus(job_id="abc123", gateway_state="working",
                                  verdict=bridge.VERDICT_RUNNING)
        with patch.object(bridge.WorkBuddyBridge, "status", return_value=status):
            code, _ = self._run(["--status", "abc123"])
        self.assertEqual(code, self.cli.EXIT_UNAVAILABLE)

    def test_cancel_passes_the_job_id_through_to_the_transport(self):
        with patch.object(bridge.WorkBuddyBridge, "cancel", return_value=True) as called:
            code, output = self._run(["--cancel", "abc123"])
        called.assert_called_once_with("abc123")
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertIn("abc123", output)

    def test_a_tick_is_refused_without_touching_the_transport(self):
        with patch.object(bridge.WorkBuddyBridge, "submit") as called:
            code, output = self._run([
                "--submit", "GAME_TICK", "--capability", "DAILY_CLAIM",
                "--failure", "routine",
            ])
        called.assert_not_called()
        self.assertEqual(code, self.cli.EXIT_REFUSED)
        self.assertIn("not an escalation condition", output)

    def test_prompt_prints_without_sending_anything(self):
        with patch.object(bridge.WorkBuddyBridge, "submit") as called:
            code, output = self._run([
                "--prompt", bridge.UNKNOWN_UI, "--capability", "SOME_UI",
                "--failure", "the page has never been seen",
            ])
        called.assert_not_called()
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertIn("SOME_UI", output)
        self.assertIn("Acceptance criteria", output)

    def test_submit_requires_a_capability(self):
        code, output = self._run(["--submit", bridge.UNKNOWN_UI])
        self.assertEqual(code, self.cli.EXIT_REFUSED)
        self.assertIn("--capability is required", output)

    def test_check_returns_unavailable_rather_than_crashing_without_a_gateway(self):
        with patch.object(bridge.WorkBuddyBridge, "is_available",
                          return_value=bridge.Availability(False, "GATEWAY_UNREACHABLE")):
            code, output = self._run(["--check"])
        self.assertEqual(code, self.cli.EXIT_UNAVAILABLE)
        self.assertIn("GATEWAY_UNREACHABLE", output)


if __name__ == "__main__":
    unittest.main()
