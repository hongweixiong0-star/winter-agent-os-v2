"""The call the contract refuses on needs a number the ledger did not keep.

Measured 2026-10-06 against ``learning/ui_venus_online.jsonl``: of 105 model replies, **58 named a
target and every single one named a printed label**, refused by ``parse_plan`` as
``PLAN_TARGET_IS_NOT_A_CONTROL`` -- 50 of them ``E16 is TEXT_LABEL`` on one screen
(``unknown__control__57d12023``) -- and the other 47 named nothing at all
(REPLAN 91 / DEFER 12 / OBSERVE 2).  ``EXECUTE`` has never once been reached, which is why
``_contract_gate`` (only reached *after* an EXECUTE) has never written a row, and why the
funnel's ``CONTRACT_ONLINE_*`` triple reads 0 / 723 forever.

None of that says **why** the model named a label, and the two readings need opposite fixes:

    the frame offered nothing tappable  -> the call should not have been spent at all
    it offered controls and the model
      still named a printed label       -> a prompt / salience problem

``element_count`` cannot separate them, because it counts printed labels and measured controls
together.  These tests pin the instrument that can, and reproduce the production refusal through
it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from winter_agent_v2 import ui_planner, ui_venus_online, unknown_advisor


class _Client:
    """A model that answers with one plan; the text is the test's to choose."""

    def __init__(self, *, reply: str = "") -> None:
        self.calls = 0
        self._reply = reply or json.dumps({
            "goal": "KEEP_BUILDING_PRODUCTIVE", "decision": "EXECUTE",
            "action": {"type": "OPEN_PAGE", "target_element_id": "E1"},
            "expected": {"page": "HOME", "result": "opened"},
            "reason": "tap the control",
        })

    def ask_json(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(ok=True, error="", latency_ms=12.0, prompt_tokens=100,
                               text=self._reply)


def _advise(tmp_path, boxes, texts, *, reply=""):
    frame = tmp_path / "current.png"
    frame.write_bytes(b"fresh captured frame")
    request = unknown_advisor.build_request(
        unknown_type=unknown_advisor.UNKNOWN_CONTROL,
        page_label="UNKNOWN::城墙", page_key="UNKNOWN::城墙", frame_path=frame,
        goal="KEEP_BUILDING_PRODUCTIVE", character="ROLE_A",
        ocr_texts=tuple(texts), ocr_boxes=tuple(boxes),
    )
    advisor = ui_planner.ManagedAdvisor(
        client=_Client(reply=reply), ledger=ui_planner.PlannerLedger(tmp_path / "plans.jsonl"),
        root=tmp_path, max_steps_per_screen=2)
    advisor.take_request(request)
    lines = (tmp_path / ui_venus_online.ONLINE_LEDGER_PATH).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _stage(rows, stage):
    found = [row for row in rows if row.get("stage") == stage]
    assert found, f"no {stage} row; stages were {[r.get('stage') for r in rows]}"
    return found[-1]


# -- the pure classification -------------------------------------------------------------

def test_the_three_counts_partition_the_table():
    elements = [
        {"id": "E1", "executable": True},
        {"id": "E2", "executable": False},
        {"id": "E3", "executable": False},
        {"id": "E4"},                      # no verdict from this frame at all
        {"id": "E5", "executable": None},  # explicitly unmeasured
    ]
    mix = ui_planner._element_mix(elements)
    assert mix == {"element_count": 5, "executable_count": 1,
                   "text_label_count": 2, "unjudged_count": 2}


def test_an_unjudged_element_is_not_counted_as_either_verdict():
    """``parse_plan`` only refuses an *explicit* ``executable is False``.

    So an element this frame never judged is not a label and not a control, and folding it into
    either column would make the number answer a question it did not measure -- the whole failure
    this file exists to stop repeating.
    """
    mix = ui_planner._element_mix([{"id": "E1"}, {"id": "E2", "executable": None}])
    assert mix["executable_count"] == 0 and mix["text_label_count"] == 0
    assert mix["unjudged_count"] == 2


def test_an_empty_table_is_all_zeroes():
    assert ui_planner._element_mix([]) == {
        "element_count": 0, "executable_count": 0, "text_label_count": 0, "unjudged_count": 0}


# -- the production refusal, reproduced through the instrument ----------------------------

def test_a_frame_with_nothing_tappable_is_visible_as_zero_executable(tmp_path):
    """The ``UNKNOWN::城墙`` shape: printed words, no measured control anywhere.

    This is the reading that would say "the call should not have been spent", and until this
    instrument existed it was indistinguishable from the reading below.
    """
    rows = _advise(
        tmp_path,
        boxes=[{"text": "城墙", "element_kind": "TEXT_LABEL", "element_executable": False},
               {"text": "耐久", "element_kind": "TEXT_LABEL", "element_executable": False}],
        texts=["城墙", "耐久"],
        # ``CLICK_ELEMENT`` is the offered action a tap uses; the action set is validated *before*
        # the target, so a made-up type would be refused for the wrong reason and this test would
        # pass while measuring nothing.
        reply=json.dumps({
            "goal": "KEEP_BUILDING_PRODUCTIVE", "decision": "EXECUTE",
            "action": {"type": "CLICK_ELEMENT", "target_element_id": "E1"},
            "reason": "tap the control",
        }),
    )
    rejected = _stage(rows, "VENUS_PROPOSAL_REJECTED")
    assert rejected["error"].startswith("PLAN_TARGET_IS_NOT_A_CONTROL")
    # The instrument says why, on the row that refused it.
    assert rejected["element_count"] == 2
    assert rejected["executable_count"] == 0
    assert rejected["text_label_count"] == 2


def test_a_frame_that_offered_a_control_says_so(tmp_path):
    """The other reading, on the same instrument: one measured control among the labels."""
    rows = _advise(
        tmp_path,
        boxes=[{"text": "城墙", "element_kind": "TEXT_LABEL", "element_executable": False},
               {"text": "升级", "element_kind": "COMPOSITE_CONTROL", "element_executable": True}],
        texts=["城墙", "升级"],
    )
    called = _stage(rows, "VENUS_CALLED")
    assert called["element_count"] == 2
    assert called["executable_count"] == 1
    assert called["text_label_count"] == 1


def test_the_called_row_keeps_the_field_it_always_had(tmp_path):
    """``element_count`` is what every existing reader joins on -- it must survive the change."""
    rows = _advise(tmp_path, boxes=[{"text": "城墙"}], texts=["城墙"])
    called = _stage(rows, "VENUS_CALLED")
    assert called["element_count"] == 1
    assert called["element_count"] == (called["executable_count"] + called["text_label_count"]
                                       + called["unjudged_count"])


def test_a_proposal_row_carries_the_counts_too(tmp_path):
    """``VENUS_PROPOSED`` is where REPLAN/DEFER were joined by target, so it needs them as well."""
    rows = _advise(
        tmp_path,
        boxes=[{"text": "升级", "element_kind": "COMPOSITE_CONTROL", "element_executable": True}],
        texts=["升级"],
    )
    proposed = _stage(rows, "VENUS_PROPOSED")
    assert proposed["decision"] == "EXECUTE"
    assert proposed["executable_count"] == 1
    assert proposed["element_count"] == 1
