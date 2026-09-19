"""Goal discovery coverage: defined ≠ discoverable, and the gap must not be silent.

The operator's P0-B.  ``goal_capability_map.json`` defines goals; ``GoalLibrary.discover()``
produces goals; nothing compared the two sets, so a goal could be defined, documented, have its
capability chain mapped -- and never exist at runtime.  The panel then shows it as 未读取 forever
and no one can tell "nothing to do" from "never looked".

The audit measures the discoverable set by **probing the engine**, not by reading it: each probe
carries the observation a branch tests for, so a goal that comes out is genuinely reachable.  A
branch can sit in the source and still be unreachable because nothing ever populates its field --
``CLEAR_INTEL`` is exactly that, and reading the code would have called it covered.

What these tests defend
-----------------------
* The two buckets are exhaustive and derived, not hand-counted.
* The missing set is **declared**, so a newly-defined goal with no discovery entry fails here
  instead of quietly becoming another 未读取 row.  Declaring it is the operator's
  ``GOAL_DISCOVERY_MISSING``; the alternative -- an unasserted list that drifts -- is how the
  project got seven of them.
* The audit is read-only: it must not write the state it measures.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tools"))

import goal_discovery_audit as audit  # noqa: E402

#: Goals that are defined in the capability map and that the engine has **no branch** for.
#: Every one of these needs a discovery entry of its own kind -- a WorldState discover rule, a
#: periodic observation producer, or an event/deadline producer (operator §7).  Listed one at a
#: time on purpose: when this list changes, someone decided it should, and the reason belongs
#: next to the name.
KNOWN_MISSING = {
    # A periodic panel routine: the page is cheap to open and its state is claimable-or-not.
    "MAIL_ROUTINE": "no rule reads world.mail",
    "DAILY_ACTIVITY_TARGET": "no rule reads world.daily",
    "ALLIANCE_ROUTINE": "no rule reads world.alliance",
    "CLAIM_EXPLORATION_IDLE": "no rule reads world.exploration",
    # Attempt-limited activities: the state that matters is a counter, not a queue.
    "USE_FREE_ARENA_ATTEMPTS": "no rule reads world.attempts",
    "LABYRINTH_DAILY": "no rule reads world.attempts",
    # Event-gated, so the entry is a producer rather than a reading.
    "ALLIANCE_TIMED_EVENTS": "event/deadline producer missing (only the stamina goal's bear "
                             "window is read today)",
}


def test_the_two_buckets_are_derived_and_exhaustive():
    """Every defined goal is either discoverable or missing -- nothing falls between."""
    defined = audit.defined_goals()
    discoverable = audit.discoverable_goals()
    covered = set(discoverable)
    if any(g.startswith("CLAIM_FREE_") for g in discoverable):
        covered.add("CLAIM_FREE_REWARDS")
    missing = set(defined) - covered

    self_partition = sorted(missing & covered)
    assert self_partition == [], f"a goal cannot be both: {self_partition}"
    assert missing | (set(defined) & covered) == set(defined), "the partition must cover DEFINED"
    assert len(defined) > 0, "an empty map would make this test vacuous"


def test_the_missing_set_is_the_declared_one():
    """A new defined goal with no discovery entry fails here rather than becoming 未读取.

    This is the whole point of declaring the list: the failure mode being fixed is a gap that
    nobody notices, and only an explicit expectation can notice it.
    """
    defined = audit.defined_goals()
    discoverable = audit.discoverable_goals()
    covered = set(discoverable)
    if any(g.startswith("CLAIM_FREE_") for g in discoverable):
        covered.add("CLAIM_FREE_REWARDS")
    missing = set(defined) - covered
    assert missing == set(KNOWN_MISSING), (
        f"the discovery gap changed: new={sorted(missing - set(KNOWN_MISSING))} "
        f"fixed={sorted(set(KNOWN_MISSING) - missing)}.  "
        f"Give the new goal a discovery entry, or declare it here with its reason."
    )


def test_the_discoverable_set_proves_itself_with_a_probe():
    """A goal counts as discoverable only because a probe produced it."""
    discoverable = audit.discoverable_goals()
    assert "CLEAR_INTEL" in discoverable, "the intel branch exists and its probe must find it"
    assert discoverable["CLEAR_INTEL"] == ["intel.status"]
    for goal_id, probes in discoverable.items():
        assert probes, f"{goal_id} is claimed discoverable with no probe behind it"


def test_a_domain_the_engine_cannot_read_is_reported_not_guessed():
    """The probes for unread domains must run and produce nothing -- that is the evidence.

    ``world.mail`` / ``world.daily`` / ``world.alliance`` / ``world.exploration`` /
    ``world.attempts`` / ``world.rally`` / ``world.queues`` all exist as fields.  The claim
    "there is no branch for these" is only worth anything if something looked.
    """
    probed = {label for label, _ in audit.PROBES}
    for domain in ("mail", "daily", "alliance", "exploration", "attempts", "rally", "queues"):
        assert domain in probed, f"{domain} was never probed, so its gap is unmeasured"


def test_the_audit_writes_nothing():
    """A coverage report that mutates what it measures cannot be run against production.

    Matched against the file-writing APIs rather than a bare word: ``append`` is how a list is
    built in memory, and banning the word would have failed this test on correct code.
    """
    source = (ROOT / "tools/goal_discovery_audit.py").read_text(encoding="utf-8")
    writing = re.search(
        r"\.write_text\(|\.write_bytes\(|\.write\(|\.mkdir\(|\.unlink\(|\.touch\(|shutil\.|"
        r"open\([^)]*[\"'](?:w|a|w\+|a\+|wb|ab)",
        source,
    )
    assert writing is None, f"the audit must stay read-only, found {writing.group(0)!r}"
