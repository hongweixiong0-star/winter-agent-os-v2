"""Where existence and executability are conflated, measured with the real GoalLibrary.

Not a test -- an instrument.  Every number the round's report quotes comes from here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.goal_library import GoalLibrary, GoalStatus, deadline_pressure  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.rally import bear_phase  # noqa: E402


def board(world: WorldState, only: tuple[str, ...] = ()) -> None:
    library = GoalLibrary()
    rows = [g for g in library.discover(world, observations={})
            if not only or any(key in g.goal_id for key in only)]
    if not rows:
        print("     (no such goal on the board)")
    for goal in rows:
        priority = "None" if goal.priority == float("-inf") else f"{goal.priority:.0f}"
        print("     {:<28} {:<11} priority={:<8} skills={} remaining={}".format(
            goal.goal_id, goal.status.value, priority,
            ",".join(goal.available_skills) or "-", goal.remaining_seconds))


print("=== what bear_phase already answers (the project owns SCHEDULED) ===")
for seconds in (None, 7200, 500, 60, 0):
    print("   seconds_to_start={:<7} -> {}".format(str(seconds), bear_phase(None, seconds, None).value))

print()
print("=== A. the window is ignored: bear opens in two hours ===")
board(WorldState(page=Page.EVENT, confidence=0.99,
                 events={"bear": {"status": None, "seconds_to_start": 7200}}), ("BEAR",))

print()
print("=== B. bear is running ===")
board(WorldState(page=Page.EVENT, confidence=0.99,
                 events={"bear": {"status": "ACTIVE", "remaining_seconds": 900}}), ("BEAR",))

print()
print("=== C. bear already ended ===")
board(WorldState(page=Page.EVENT, confidence=0.99,
                 events={"bear": {"status": "FINISHED"}}), ("BEAR",))

print()
print("=== D. existence needs a frame: same world, events not read this frame ===")
board(WorldState(page=Page.EVENT, confidence=0.99, events={}), ("BEAR", "EVENT", "MINIMUM"))

print()
print("=== E. a busy queue is a game condition, not a finished task ===")
board(WorldState(page=Page.TRAINING, confidence=0.99,
                 training={"status": "IN_PROGRESS", "queue_available": False, "timer": "01:00:00"}),
      ("TRAINING",))
print("   and an idle one, for contrast:")
board(WorldState(page=Page.TRAINING, confidence=0.99,
                 training={"status": "IDLE", "queue_available": True}), ("TRAINING",))

print()
print("=== F. no idle march slot is also a condition, not a finished task ===")
board(WorldState(page=Page.MAP, confidence=0.99, march_used=3, march_max=3, normal_march_slots=3),
      ("MARCHES",))

print()
print("=== G. deadline_pressure, the only term that knows about time ===")
print("   ", {str(s): deadline_pressure(s) for s in (None, 0, 60, 3600, 86400)})

print()
print("=== H. the two statuses the directive names that GoalStatus does not have ===")
print("   GoalStatus members:", [s.value for s in GoalStatus])
print("   SCHEDULED_NOT_OPEN:", "SCHEDULED_NOT_OPEN" in {s.value for s in GoalStatus})
print("   EXPIRED          :", "EXPIRED" in {s.value for s in GoalStatus})
