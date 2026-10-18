"""The handoff and the suite must classify a lost frame the same way.

Measured 2026-10-18, one morning after the first prune: the evidence-integrity test accepted
all 109 missing frames because they were written down in
``knowledge/provenance/pruned_evidence_20261017.json``, while ``08_LIVE_METRICS.json`` printed
``"status": "FAIL"`` for the same 109 -- a second implementation of "is this loss documented"
that did not know the ledger existed.

Two answers to one question is the failure mode this repo keeps paying for (the same shape as
``config/paths.py`` owning the only root literal).  The fix was to make
``retention.pruned_evidence_paths`` the only reader, but a shared function is only shared while
somebody checks: this test recomputes the classification from the raw facts and asserts the
handoff agrees with it, in both directions -- no documented loss may read as FAIL, and no
undocumented one may read as PASS.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from update_workbuddy_handoff import evidence_state  # noqa: E402
from winter_agent_v2.retention import (  # noqa: E402
    comparable_path,
    pruned_evidence_paths,
    referenced_evidence,
)


def test_a_documented_loss_is_not_reported_as_a_failure() -> None:
    referenced = referenced_evidence(ROOT)
    pruned = pruned_evidence_paths(ROOT)
    absent = [path for path in referenced if not path.is_file()]
    documented = [path for path in absent if comparable_path(str(path)) in pruned]
    undocumented = [path for path in absent if comparable_path(str(path)) not in pruned]

    state = evidence_state({"total": 0})

    assert state.get("documented_pruned") == len(documented), (
        "the handoff counted a different number of documented losses than the ledger holds: "
        f"{state.get('documented_pruned')} vs {len(documented)}"
    )
    if undocumented:
        assert state["status"] == "FAIL", (
            "an undocumented missing frame must still fail: "
            + ", ".join(str(p) for p in undocumented[:5])
        )
    else:
        assert state["status"] == "PASS", (
            "every missing frame is written down in knowledge/provenance, so the handoff must "
            f"not call it a failure (status={state['status']})"
        )
