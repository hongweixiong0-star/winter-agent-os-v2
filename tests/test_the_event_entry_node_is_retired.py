"""Retire the REGULAR_EVENT_ENTRY node, the way OPEN_BUILDING_UPGRADE was retired.

Measured 2026-10-03 over every ``REGULAR_EVENT_ENTRY`` episode the ledger holds: **638 steps,
all of them on the MAA backend, ADB never called once.**  612 succeeded, 26 failed, and the 26
carry ``MAA_TEMPLATE:NO_MATCH`` with scores spread across 0.4175..0.6909 against a 0.7 gate --
not one attempt ever crossed it.

That makes this the second instance of a shape ``test_unvalidated_node_keeps_adb`` was written
for: a node that is green in the routing file and dead on the client, while the resolver that
*does* read the frame never gets consulted because ``preferred: MAA`` means the router asks the
node first and ``maa_resolver`` answers a miss with ``None`` without falling through -- which is
deliberate, because a position-blind legacy resolver must not become a blind tap.

The resolver half is already in place and verified on the exact frame that stopped production:
``_resolve_semantic_target`` now consumes ``events.calendar_entry.tap_norm`` on HOME/MAP, and
re-measured that frame with the project's own OCR at ``[0.925, 0.14883]`` while the node's roi
``[632, 101, 67, 84]`` does not contain the point (the label sits at py 191, the roi ends at 185).

So the retirement is the missing half: empty ``recognition``, ``preferred: ADB``,
``recognition_backend: LEGACY``, and the measurement recorded where a reader looks.  The
template image is kept so a re-measurement starts from the picture, per the file's own precedent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROUTING = ROOT / "knowledge" / "execution" / "backend_routing.json"
TEMPLATE = "dataset/candidate/autogen/regular_event_entry__autogen_5d2c9a0f.png"

#: Both skills declare this semantic, and both carry the same node from the same harvest.
SKILLS = ("OPEN_EVENT_CALENDAR_FROM_HOME", "OPEN_EVENT_CALENDAR_FROM_MAP")
SEMANTIC = "REGULAR_EVENT_ENTRY"
LEGACY_KEY = f"{SKILLS[0]}_RECOGNITION"


def _payload() -> dict:
    return json.loads(ROUTING.read_text(encoding="utf-8"))


class TheNodeIsRetiredTests:
    def __init__(self):
        self.payload = _payload()
        self.entry = self.payload["skills"][SKILLS[0]]
        self.record = (self.payload.get("not_migrated") or {}).get(LEGACY_KEY) or {}

    def __call__(self):
        failures = []
        for name, check in (
            ("node_retired", self.node_retired),
            ("route_prefers_adb", self.route_prefers_adb),
            ("recognition_backend_legacy", self.recognition_backend_legacy),
            ("both_declaring_skills_retired", self.both_declaring_skills_retired),
            ("measurement_is_recorded", self.measurement_is_recorded),
            ("template_kept", self.template_kept),
            ("the_resolver_answers_on_both_pages", self.the_resolver_answers_on_both_pages),
            ("the_node_would_have_missed_that_point", self.the_node_would_have_missed_that_point),
            ("no_route_claims_unreachable_recognition", self.no_route_claims_unreachable_recognition),
        ):
            try:
                check()
                print("  [OK  ] %s" % name)
            except AssertionError as exc:
                failures.append((name, str(exc)))
                print("  [FAIL] %s: %s" % (name, exc))
        return failures

    def node_retired(self):
        assert self.entry.get("recognition") == {} or not self.entry.get("recognition"), (
            "a retired node must not stay wired: it would silently override the declaration "
            "and the router would keep asking it first")
        assert not (self.entry.get("recognition") or {}).get(SEMANTIC), SEMANTIC

    def route_prefers_adb(self):
        assert self.entry["preferred"] == "ADB", self.entry["preferred"]
        assert self.entry["fallback"] == "MAA", (
            "ADB cannot capture, so the device fallback stays MAA")

    def recognition_backend_legacy(self):
        assert self.entry["recognition_backend"] == "LEGACY", self.entry["recognition_backend"]

    def both_declaring_skills_retired(self):
        """``OPEN_EVENT_CALENDAR_FROM_MAP`` declares the same semantic; retiring one half would
        leave the other asking a node that is known not to answer."""
        for skill_id in SKILLS[1:]:
            entry = self.payload["skills"][skill_id]
            assert not (entry.get("recognition") or {}), (
                "%s still carries the retired node" % skill_id)
            assert entry["preferred"] == "ADB", (skill_id, entry.get("preferred"))

    def measurement_is_recorded(self):
        assert self.record.get("semantic") == SEMANTIC, "the key names the skill, the record the semantic"
        assert self.record.get("measured_at"), "a demotion with no date is not evidence"
        reason = self.record.get("reason") or ""
        # The numbers are what make this checkable later: 638/0 says the node was never even
        # reached by ADB, and the score ceiling says the failure is the node, not the gate.
        for needle in ("638", "0.4175", "0.6909", "0.925"):
            assert needle in reason, "reason is missing %r" % needle
        assert (self.entry.get("evidence") or {}).get("demotion_reason"), (
            "the entry itself must carry demotion_reason so the table-wide check can see it")

    def template_kept(self):
        assert (ROOT / TEMPLATE).is_file(), (
            "the picture is kept for a re-measurement: %s" % TEMPLATE)

    def the_resolver_answers_on_both_pages(self):
        """The reason the retirement is safe: the frame-reading resolver is reachable now."""
        from winter_agent_v2.models import Page, WorldState
        from winter_agent_v2.runtime import LiveRuntime

        reading = {"visible": True, "tap_norm": [0.925, 0.14883],
                   "source": "CURRENT_FRAME_OCR", "confidence": 0.9983089715242386}
        runtime = LiveRuntime.__new__(LiveRuntime)
        for page in (Page.HOME, Page.MAP):
            world = WorldState(page=page, confidence=0.99, events={"calendar_entry": reading})
            point = runtime._resolve_semantic_target(SEMANTIC, world)
            assert point == (0.925, 0.14883), (page, point)

    def the_node_would_have_missed_that_point(self):
        """The geometric claim, recomputed rather than quoted: the reading is py 191 on a
        720x1280 frame and the node's roi covered y 101..185, so the node was looking above it."""
        width, height = 720, 1280
        x_norm, y_norm = 0.925, 0.14883
        px, py = x_norm * width, y_norm * height
        x0, y0, w, h = 632, 101, 67, 84
        inside = (x0 <= px <= x0 + w) and (y0 <= py <= y0 + h)
        assert not inside, (
            "if the roi now contains the measured point, this retirement is not the fix and "
            "the node's problem is something else: px=%d py=%d" % (px, py))

    def no_route_claims_unreachable_recognition(self):
        """The table-wide invariant: MAA is only reachable when MAA is preferred."""
        unreachable = {sid for sid, e in self.payload["skills"].items()
                       if str(e.get("recognition_backend")) == "MAA" and e.get("preferred") != "MAA"}
        assert unreachable == set(), sorted(unreachable)


if __name__ == "__main__":
    print("REGULAR_EVENT_ENTRY node retirement:")
    fails = TheNodeIsRetiredTests()()
    print("VERDICT:", "PASS" if not fails else "FAIL %d" % len(fails))
    raise SystemExit(1 if fails else 0)
