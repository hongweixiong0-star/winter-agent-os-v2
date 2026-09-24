"""The readiness ladder, checked rung by rung.

Written as a probe rather than a test because it found the loosest-first ordering bug on its
first run, and a table is the clearest way to keep that from coming back.
"""
import sys
sys.path.insert(0, r"E:\无尽冬日智能体")
from winter_agent_v2 import event_schedule as es

EXPECTED = [
    (None, "IDLE"), (120, "IDLE"), (45, "IDLE"), (30, "T30"), (29, "T30"),
    (15, "T15"), (12, "T15"), (6, "T15"), (5, "T5"), (3, "T5"),
    (1, "T1"), (0.5, "T1"), (0, "OPEN"), (-1, "OPEN"),
]
bad = 0
print(f"{'minutes':>8}  {'got':5s} {'want':5s}  bonus    instruction")
print("-" * 78)
for minutes, want in EXPECTED:
    got = es.readiness_phase(minutes)
    ok = got.value == want
    bad += 0 if ok else 1
    print(f"{str(minutes):>8}  {got.value:5s} {want:5s}  {es.PHASE_PRIORITY[got]:>8.1f}"
          f"  {es.phase_instruction(got) if ok else '<<< MISMATCH'}")
print("-" * 78)
print(f"mismatches: {bad}")
raise SystemExit(1 if bad else 0)
