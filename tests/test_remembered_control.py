"""Experience has to be evidence before it can steer anything.

Two faults, measured on the live files on 2026-09-22, and the second cannot be fixed
without the first.

**1. The ledger was writable by anything.**  ``STATE_PATH`` is a module constant, so a test
or a throwaway probe that did not redirect it wrote the real store.  Eleven of thirty-five
records had a ``read_from_frame`` under the system temp directory, and their positions gave
them away: ``HOME|PAGE_MAP``, ``MAP|BTN_OPEN_HOME``, ``EXPLORATION|BTN_HERO_CAMP_FIGHT``,
``POPUP|BTN_CLAIM_FREE_STAMINA``, ``ALLIANCE|BTN_CLOSE`` and ``ALLIANCE|BTN_ALLY_GIFT_CLAIM``
were all filed at exactly ``(0.8403, 0.50)`` -- six controls at one point, which no client
draws.  A test harness stubs ``target_resolver`` with a constant; nothing objected.

**2. Nobody read the ledger.**  ``load`` / ``classify_change`` / ``save`` were the only call
sites in the runtime.  ``known_result``, ``resolved``, ``sterile`` and the two helpers
written for exactly this purpose (``candidates``, ``known_outcomes``) had no production
caller, so a control this device had tapped thirty-five times successfully became unusable
the moment its template stopped matching.

So the read is only allowed to exist behind the provenance rule.  These tests pin both, and
the last one pins the wiring itself -- a reuse branch nothing calls is the same bug as no
reuse branch.
"""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402

PROJECT_FRAME = str(ROOT / "dataset/raw/control_panel/runtime_auto/run/step_001_before.png")
SCRATCH_FRAME = str(Path(tempfile.gettempdir()) / "tmpscratch" / "captures" / "step_001.png")


def _entry(**over) -> control_experience.ControlExperience:
    body = {
        "page": "HOME",
        "control": "PAGE_MAP",
        "position_norm": (0.9236, 0.9539),
        "read_from_frame": PROJECT_FRAME,
        "known_result": "PAGE_MAP",
        "known_change": "PAGE_CHANGED",
        "attempts": 5,
        "last_result": "PAGE_CHANGED",
        "last_at": "2026-09-22T00:00:00+00:00",
    }
    body.update(over)
    return control_experience.ControlExperience(**body)


# ----------------------------------------------------------------- provenance


def test_a_project_frame_is_evidence_and_a_scratch_frame_is_not():
    assert control_experience.measured_on_a_real_frame(_entry()) is True
    assert control_experience.measured_on_a_real_frame(
        _entry(read_from_frame=SCRATCH_FRAME)) is False


def test_a_record_with_no_frame_at_all_is_not_evidence():
    """No frame means nothing was measured, so there is nothing to reuse."""
    assert control_experience.measured_on_a_real_frame(_entry(read_from_frame="")) is False


def test_load_drops_scratch_records_so_a_polluted_file_cleans_itself(tmp_path):
    """The read-side half: an already-polluted store must not keep handing the bad rows back."""
    store = tmp_path / "control_experience.json"
    store.write_text(json.dumps({
        "schema_version": "1.0",
        "controls": {
            "HOME|PAGE_MAP": _entry().as_json(),
            "EXPLORATION|BTN_HERO_CAMP_FIGHT": _entry(
                page="EXPLORATION", control="BTN_HERO_CAMP_FIGHT",
                position_norm=(0.8403, 0.5), read_from_frame=SCRATCH_FRAME).as_json(),
        },
    }), encoding="utf-8")

    loaded = control_experience.load(store)
    assert set(loaded) == {"HOME|PAGE_MAP"}, (
        "a scratch measurement must not survive being read back"
    )


def test_save_refuses_to_write_scratch_records(tmp_path):
    """The write-side half: this is what makes the pollution impossible, not merely corrected."""
    store = tmp_path / "control_experience.json"
    control_experience.save({
        "HOME|PAGE_MAP": _entry(),
        "EXPLORATION|BTN_HERO_CAMP_FIGHT": _entry(
            control="BTN_HERO_CAMP_FIGHT", read_from_frame=SCRATCH_FRAME),
    }, store)

    written = json.loads(store.read_text(encoding="utf-8"))["controls"]
    assert "HOME|PAGE_MAP" in written
    assert "EXPLORATION|BTN_HERO_CAMP_FIGHT" not in written


# ----------------------------------------------------------------- the read


def _runtime_with(entries: dict) -> object:
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime._control_ledger = entries
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    return runtime


def test_a_measured_control_is_reused_where_its_template_no_longer_matches():
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry()})
    point = runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME))
    assert point == (0.9236, 0.9539)
    assert runtime._remembered_reuse, "the reuse must be visible, not silent"


def test_a_control_measured_on_a_different_page_is_not_reused():
    """The key is (page, semantic); a point is only valid on the page it was read from."""
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry()})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.INTEL)) is None


def test_an_unknown_outcome_is_not_reused():
    """§四.7: UNKNOWN means unconfirmed, and unconfirmed must not be tapped as if known."""
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(last_result="UNKNOWN")})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None


def test_a_control_with_no_known_result_is_not_reused():
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(known_result="", known_change="")})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None


def test_a_sterile_control_is_not_reused():
    """Three taps with nothing moving retires it from automatic repetition (§八)."""
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(
        attempts=4, last_result="NO_OP", known_result="", known_change="")})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None


def test_a_control_a_live_cooldown_is_not_reused_early():
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(
        cooldown_seconds=3600, last_at="2026-09-22T00:00:00+00:00")})
    # last_at is in the past relative to now only if the clock has moved; assert on the
    # guard rather than on the wall clock by asking a control whose cooldown is tiny.
    runtime._control_ledger = {"HOME|PAGE_MAP": _entry(
        cooldown_seconds=86400, last_at=control_experience.datetime.now(
            control_experience.timezone.utc).isoformat())}
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None


def test_a_control_with_no_located_position_is_not_reused():
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(position_norm=None)})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None


def test_an_out_of_bounds_position_is_refused():
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(position_norm=(1.4, 0.5))})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None


def test_a_control_labelled_with_a_forbidden_risk_is_not_reused():
    """The permanent block survives the shortcut.

    Nothing writes a risk label yet, so this branch costs nothing today -- but the field
    is in the ledger schema and round-trips, and operator §二 states the boundary as
    something established *before* submitting an operation: real money, account safety
    and the irreversible class.  A remembered position is a weaker basis than a live
    template match, so it is the last place that should be allowed to skip that check.
    """
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(risk="REAL_MONEY")})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) is None
    assert runtime._remembered_reuse == [], "and it must not be reported as a reuse either"


def test_an_explorable_risk_label_does_not_block_reuse():
    """The check is on the label, not on labelling: a low-risk control still reuses."""
    runtime = _runtime_with({"HOME|PAGE_MAP": _entry(risk="LOW")})
    assert runtime._remembered_control_center("PAGE_MAP", WorldState(page=Page.HOME)) == (
        0.9236, 0.9539)


# ----------------------------------------------------------------- the wiring


def test_the_resolver_actually_asks_the_ledger_before_giving_up():
    """A reuse branch nothing calls is the same bug as no reuse branch.

    Source-level on purpose: reaching this line for real needs a frame with no template
    match, which is the live condition, and the run-time path is covered by the tests above.
    """
    from winter_agent_v2.runtime import LiveRuntime

    body = inspect.getsource(LiveRuntime._resolve_semantic_target)
    assert "_remembered_control_center" in body, (
        "the resolver must consult the ledger before answering None"
    )
    # ...and the call must come before the final refusal, not after it.
    assert body.index("_remembered_control_center") < body.rindex("return None")
