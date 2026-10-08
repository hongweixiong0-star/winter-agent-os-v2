"""Which reply constraint was in force has to be on the record, because it can degrade silently.

``ui_planner`` caps ``reason`` at ``maxLength: 120`` in the grammar, and the contract then *refuses*
an over-long reason rather than truncating it, on the stated grounds that the tokens were already
spent at generation.  That argument holds only while the grammar is actually constraining the decode.

And ``ask_json`` can lose the grammar without saying so: when the server rejects an optional key,
``_post`` raises ``_RejectedKey`` and the recovery swaps ``json_schema`` for plain ``json_object``,
then drops ``response_format`` altogether.

Measured 2026-10-08T13:51:35Z, which is why this field exists: a reply whose reason is three
sentences and past 120 characters reached the validator and was refused with ``PLAN_REASON_TOO_LONG``.
llama.cpp's own grammar conversion does enforce ``maxLength`` -- its README's worked example turns
``maxLength: 100`` into ``char{1,100}`` -- so on that call the exact schema was **not** in force, and
nothing in the ledger said which constraint the call had actually used.

These tests pin the three states to the recorded value, including the two that only exist because of
the downgrade.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import local_gui_model  # noqa: E402
from winter_agent_v2.local_gui_model import LocalGUIModel, _RejectedKey  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string", "maxLength": 120}},
    "required": ["reason"],
    "additionalProperties": False,
}


def _body(text: str = '{"reason": "ok"}') -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 14},
    }


class TheReplyConstraintIsRecordedTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "calls.jsonl"
        self.client = LocalGUIModel(multimodal=False, ledger_path=self.ledger)
        # No probe of a server that is not there, and no dependence on one being there.
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(LocalGUIModel, "available",
                          lambda self, force=False: (True, "")).start()

    def _ask(self, post):
        with mock.patch.object(LocalGUIModel, "_post", post):
            return self.client.ask_json(system="s", user="u", response_schema=SCHEMA)

    def test_a_schema_that_holds_is_recorded_as_schema(self):
        self._ask(lambda self, payload, timeout_s=None: _body())
        row = json.loads(self.ledger.read_text(encoding="utf-8").strip())
        self.assertEqual(row["reply_constraint"], "schema")

    def test_a_rejected_schema_is_recorded_as_the_json_object_it_fell_back_to(self):
        """The downgrade this field exists for: it must not be reported as ``schema``."""
        seen: list[dict] = []

        def post(self, payload, timeout_s=None):
            seen.append(dict(payload.get("response_format") or {}))
            if len(seen) == 1:
                raise _RejectedKey("response_format")
            return _body()

        self._ask(post)
        row = json.loads(self.ledger.read_text(encoding="utf-8").strip())
        self.assertEqual([r.get("type") for r in seen], ["json_schema", "json_object"])
        self.assertEqual(row["reply_constraint"], "json_object",
                         "the record must name the constraint that was really used")

    def test_losing_it_entirely_is_recorded_as_none(self):
        """The third state, and the one a two-state field would have hidden.

        The downgrade is one step per attempt: a *schema* refused becomes a loose object, and it is
        a *loose object* refused that leaves the request with no constraint at all.  So this case
        starts from a call that asked for no schema, which is how the online path reaches it.
        """

        def post(self, payload, timeout_s=None):
            if "response_format" in payload:
                raise _RejectedKey("response_format")
            return _body()

        with mock.patch.object(LocalGUIModel, "_post", post):
            self.client.ask_json(system="s", user="u")
        row = json.loads(self.ledger.read_text(encoding="utf-8").strip())
        self.assertEqual(row["reply_constraint"], "none",
                         "an unconstrained request is a different fact from a loose one")

    def test_a_call_with_no_schema_asked_for_is_recorded_as_json_object(self):
        with mock.patch.object(LocalGUIModel, "_post",
                               lambda self, payload, timeout_s=None: _body()):
            self.client.ask_json(system="s", user="u")
        row = json.loads(self.ledger.read_text(encoding="utf-8").strip())
        self.assertEqual(row["reply_constraint"], "json_object")

    def test_a_failed_call_still_says_what_it_was_asking_for(self):
        """A transport failure is not a reason to forget which constraint was attempted."""
        with mock.patch.object(LocalGUIModel, "_post",
                               lambda self, payload, timeout_s=None: (
                                   _ for _ in ()).throw(TimeoutError("no answer"))):
            self.client.ask_json(system="s", user="u", response_schema=SCHEMA)
        row = json.loads(self.ledger.read_text(encoding="utf-8").strip())
        self.assertFalse(row["ok"])
        self.assertEqual(row["reply_constraint"], "schema")

    def test_the_field_is_on_every_row_not_only_the_new_ones(self):
        self.assertTrue(hasattr(local_gui_model.GUIModelCall(True), "reply_constraint"))
        self.assertIn("reply_constraint", local_gui_model.GUIModelCall(True).to_row())


if __name__ == "__main__":
    unittest.main()
