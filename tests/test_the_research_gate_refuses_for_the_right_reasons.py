"""The research gate has to say no for the right reasons, not just say no.

Winter Agent OS V2 already stores what the charter asks about -- provenance, conflicts,
priority, parity, event state -- so the gate's whole job is to read those assets and report
truthfully.  A gate that reports everything as READY is decoration; one that reports
everything as NEEDS_RESEARCH is a wall.  Both failure modes are pinned here.

The fixtures are the project's own entities rather than invented ones, because the claims being
checked are claims about this tree: CLEAR_INTEL is fully sourced (``intel_research_sources.json``
existed all along, filed under ``intel`` rather than under the goal id), and BEAR_HUNT is
registered at ``REVIEWED`` while the registry's own policy requires ``VERIFIED``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.research_gate import (  # noqa: E402
    _goal_needles,
    _mentions,
    build_report,
)


def _check(report, check_id: str):
    for c in report.checks:
        if c["check"] == check_id:
            return c
    return None


class TheGateFindsWhatIsActuallyThereTests:
    def test_a_fully_sourced_goal_is_ready(self):
        """CLEAR_INTEL: sources + mechanism + parity + risks all present.

        The first version of the gate called this NEEDS_RESEARCH because it matched only the
        literal goal id and the provenance file is named ``intel_research_sources.json``.  A
        verified-against-a-real-tree expectation, not a fixture invented to match the code.
        """
        report = build_report("goal", "CLEAR_INTEL")
        assert _check(report, "SOURCE_RECORDED")["ok"] is True, _check(report, "SOURCE_RECORDED")
        assert report.verdict == "READY", report.as_dict()

    def test_the_source_check_accepts_a_domain_named_after_the_domain(self):
        """The tree files domain sources under the domain, not under the goal id."""
        assert _mentions({"f": "intel_research_sources"}, "intel")
        report = build_report("goal", "KEEP_TRAINING_PRODUCTIVE")
        assert _check(report, "SOURCE_RECORDED")["ok"] is True

    def test_a_goal_id_loses_its_verb_before_lookup(self):
        """CLEAR_INTEL -> intel, KEEP_TRAINING_PRODUCTIVE -> train/training."""
        assert "intel" in _goal_needles("CLEAR_INTEL")
        assert "training" in _goal_needles("KEEP_TRAINING_PRODUCTIVE")
        assert "train" in _goal_needles("KEEP_TRAINING_PRODUCTIVE")
        # A name with no known verb is passed through rather than mangled.
        assert "SOMETHING_ELSE" in _goal_needles("SOMETHING_ELSE")


class TheGateRefusesForTheRightReasonsTests:
    def test_an_event_below_its_registry_gate_is_not_ready(self):
        """BEAR_HUNT is registered at REVIEWED; the registry policy requires VERIFIED.

        Asserted against the two values rather than against a hardcoded verdict string, so
        this keeps meaning something if the registry is legitimately promoted later.
        """
        report = build_report("event", "BEAR_HUNT")
        state = _check(report, "EVENT_REGISTRY_STATE")
        assert state is not None
        # Either the tree still says REVIEWED (gap) or somebody promoted it (ready) -- what
        # must never happen is the check reading no state at all and calling that a pass.
        assert "REVIEWED" in state["detail"] or state["ok"], state["detail"]
        if not state["ok"]:
            assert report.verdict == "NEEDS_RESEARCH", report.as_dict()

    def test_an_unknown_entity_is_not_silently_ready(self):
        """Nothing in the tree names this; every evidence check must be a gap."""
        report = build_report("goal", "NO_SUCH_GOAL_XYZ")
        assert report.verdict != "READY", (
            "an entity no knowledge file mentions cannot satisfy the charter"
        )
        assert _check(report, "SOURCE_RECORDED")["ok"] is False
        assert _check(report, "MECHANISM_KNOWLEDGE")["ok"] is False

    def test_unhandled_blocking_risk_outranks_every_other_gap(self):
        """BLOCKED_UNSAFE is a refusal, not a to-do list.

        A risk class with no statement on the record must block even when nothing else is
        wrong, because silence about spend or identity is exactly the state that let a
        misidentified target become a real march.
        """
        report = build_report("goal", "NO_SUCH_GOAL_XYZ")
        blocking = [c for c in report.checks if c["blocking"]]
        assert blocking, "an unsourced entity with no risk statement must block"
        assert report.verdict == "BLOCKED_UNSAFE", report.as_dict()
        assert any(c["check"].startswith("RISK_") for c in blocking)

    def test_a_blocked_verdict_names_the_risk_class(self):
        report = build_report("goal", "NO_SUCH_GOAL_XYZ")
        names = {c["check"] for c in report.blocking_failures}
        assert names, report.as_dict()
        assert all(n.startswith("RISK_") for n in names), names


class TheGateReadsTheFieldTheRegistryActuallyUsesTests:
    def test_registry_state_comes_from_gate_not_lifecycle(self):
        """The registry's field is ``gate``; an earlier version read lifecycle/status and
        reported an empty state for every event, which reads as a gap for everything."""
        report = build_report("event", "BEAR_HUNT")
        state = _check(report, "EVENT_REGISTRY_STATE")
        assert state["detail"], state
        assert "states=[]" not in state["detail"], (
            "reading no state means reading the wrong field, not that the registry is empty: "
            + state["detail"]
        )

    def test_an_event_absent_from_the_registry_is_a_gap_not_a_crash(self):
        report = build_report("event", "NO_SUCH_EVENT_XYZ")
        state = _check(report, "EVENT_REGISTRY_STATE")
        assert state is not None and state["ok"] is False


class TheRuleLandsWithoutASecondSystemTests:
    """Every clause of the supplied rule must resolve to something already in the tree.

    The rule names concepts the project had never used -- IRREVERSIBLE_ACTIONS,
    EXTERNAL_FAST_TRACK_STEP, PERMANENTLY_BLOCKED, a three-step slowdown ladder.  Recording
    them as prose would be a second source of truth for facts the tree already owns, so each
    one is either pointed at its existing home or written down as genuinely new.
    """

    def _charter(self):
        import json

        return json.loads(
            (Path(__file__).resolve().parents[1] / "knowledge/research/RESEARCH_CHARTER.json")
            .read_text(encoding="utf-8"))

    def test_the_two_reusable_fallbacks_point_at_existing_mechanisms(self):
        """Money and slowdown already exist; the charter must say so rather than restate."""
        fb = self._charter()["three_fallbacks"]
        assert "ALREADY EXISTS" in fb["fallback_2_real_money"]["project_landing"]
        assert "ALREADY EXISTS" in fb["fallback_3_failure_slowdown"]["project_landing"]
        assert "repeat_failure_penalty" in fb["fallback_3_failure_slowdown"]["project_landing"]

    def test_the_one_genuinely_new_fallback_is_marked_new(self):
        """Reversibility had no home; saying so is what stops it being quietly assumed."""
        fb = self._charter()["three_fallbacks"]
        assert "NEW" in fb["fallback_1_reversibility"]["project_landing"]

    def test_the_instruction_was_reviewed_before_being_adopted(self):
        """§三·八 applies to operator directives too, and the review must be inspectable."""
        review = self._charter()["instruction_review"]
        assert review["verdict"].startswith("ACCEPTED")
        assert len(review["alignments"]) == 3
        # The failure-distrust clause is the one that needed narrowing; its alignment must
        # state the narrowing rather than silently drop the clause.
        points = " ".join(a["point"] for a in review["alignments"])
        assert "资料不可信" in points

    def test_the_two_ladders_are_declared_equivalent_not_competing(self):
        """EXTERNAL_HYPOTHESIS/OBSERVED/CONFIRMED vs DISCOVERED/REVIEWED/VERIFIED."""
        kp = self._charter()["knowledge_promotion"]
        mapping = kp["knowledge_gate_mapping"]
        assert mapping["EXTERNAL_HYPOTHESIS"] == "DISCOVERED"
        assert mapping["OBSERVED"] == "REVIEWED"
        assert mapping["CONFIRMED"] == "VERIFIED"


class TheRuntimeStaysOfflineTests:
    """The no-network rule is scanned, and a local model over loopback is not a violation."""

    def test_a_loopback_endpoint_is_not_treated_as_reaching_outside(self):
        from tools.research_gate import _endpoints_in, _LOOPBACK_MARKERS

        eps = _endpoints_in('DEFAULT_ENDPOINT = "http://127.0.0.1:18080"')
        assert eps == ["http://127.0.0.1:18080"]
        assert all(any(m in ep for m in _LOOPBACK_MARKERS) for ep in eps), (
            "the local UI-Venus service is what the rule requires for an unknown frame; "
            "calling it a violation would make the gate a wall"
        )

    def test_the_real_runtime_is_reported_as_loopback_only(self):
        """Live check, not a fixture: this is the state of winter_agent_v2/ right now."""
        report = build_report("goal", "CLEAR_INTEL")
        check = _check(report, "RUNTIME_HAS_NO_NETWORK")
        assert check["ok"] is True, check["detail"]
        assert "loopback only" in check["detail"], check["detail"]

    def test_an_external_endpoint_would_be_reported(self):
        """The permissive direction is the dangerous one here, so it is pinned."""
        from tools.research_gate import _endpoints_in, _LOOPBACK_MARKERS

        eps = _endpoints_in('ENDPOINT = "https://api.example.com/v1"')
        external = [ep for ep in eps
                    if not any(m in ep for m in _LOOPBACK_MARKERS)]
        assert external == ["https://api.example.com/v1"], (
            "a non-loopback address must not be absorbed by the loopback exemption"
        )


class TheSearchMustProduceSomethingTests:
    def test_an_entity_with_no_output_anywhere_is_not_allowed_to_start(self):
        report = build_report("goal", "NO_SUCH_GOAL_XYZ")
        check = _check(report, "SEARCH_OUTPUTS_RECORDED")
        assert check is not None and check["ok"] is False, check

    def test_a_researched_entity_shows_which_outputs_it_produced(self):
        report = build_report("goal", "CLEAR_INTEL")
        check = _check(report, "SEARCH_OUTPUTS_RECORDED")
        assert check["ok"] is True
        assert "知识摘要" in check["detail"], check["detail"]

    def test_an_unhandled_risk_does_not_count_as_an_output(self):
        """Otherwise a round could pass by saying nothing about risk anywhere."""
        report = build_report("goal", "NO_SUCH_GOAL_XYZ")
        assert _check(report, "SEARCH_OUTPUTS_RECORDED")["ok"] is False
        assert report.verdict == "BLOCKED_UNSAFE"


class TheCharterIsMachineReadableTests:
    def test_the_charter_parses_and_declares_its_sections(self):
        import json

        charter = json.loads(
            (Path(__file__).resolve().parents[1] / "knowledge/research/RESEARCH_CHARTER.json")
            .read_text(encoding="utf-8"))
        for key in ("coverage_a_information_scope", "b_filtering_and_priority",
                    "c_translation_to_decisions", "d_judgement_dimensions",
                    "risks_section", "execution_hook"):
            assert key in charter, key
        # The gate advertises itself in the charter; a rename on either side is a silent break.
        assert charter["execution_hook"]["gate"] == "tools/research_gate.py"
        assert charter["execution_hook"]["gate_verdicts"] == [
            "READY", "NEEDS_RESEARCH", "BLOCKED_UNSAFE"]

    def test_the_charter_does_not_redeclare_the_authority_order(self):
        """It must defer to provenance, not restate a competing ladder.

        Two ladders would be two sources of truth for the same fact -- the charter's own
        single_source_of_truth_rule forbids it.
        """
        import json

        charter = json.loads(
            (Path(__file__).resolve().parents[1] / "knowledge/research/RESEARCH_CHARTER.json")
            .read_text(encoding="utf-8"))
        assert "single_source_of_truth_rule" in charter
        order = charter["b_filtering_and_priority"]["authority_tiers"]["order"]
        assert order[0].startswith("LIVE_CLIENT"), (
            "the highest tier must be the live client, matching the project's fact priority"
        )
