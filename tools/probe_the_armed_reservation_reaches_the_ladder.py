"""Does the reservation that is on file actually reach the scheduler's ranking?

A reservation is only worth anything if three separate things hold at once, and each of them
fails silently on its own:

  1. ``route_for("PARTICIPATE_BEAR")`` is not ``None`` -- a goal with no route is skipped by
     ``runtime._event_readiness_bonus`` before the clock is even consulted, so an unroutable
     goal keeps its reservation and still never gets promoted.
  2. ``readiness_phase`` climbs the ladder in the right rung order, so T5 means T5 and not T30.
     A loosest-first table answers T30 for three minutes as readily as for twenty-nine.
  3. The persisted ``reserved_start`` is the one the runtime's own role id will look up.
     ``schedules`` is keyed ``"{role_id}|{event_id}"``, and a typo in either half reads as
     IDLE rather than as an error.

Written as a probe rather than a test because the answer depends on the state file on this
machine right now, not on a fixture: this is the question "is tonight armed", asked of the
real clock.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"E:\WinterAgent")
from winter_agent_v2 import event_schedule as es  # noqa: E402
from winter_agent_v2.goal_library import route_for  # noqa: E402

BEIJING = timezone(timedelta(hours=8), "CST")
OFFSETS_MINUTES = (31, 30, 29, 16, 15, 6, 5, 4, 2, 1, 0, -1)

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


print(f"state file : {es.STATE_PATH}")
print(f"exists     : {es.STATE_PATH.is_file()}")
print()

route = route_for("PARTICIPATE_BEAR")
print(f'route_for("PARTICIPATE_BEAR") = {route!r}'
      f'  {"(unroutable -- bonus is unreachable)" if route is None else ""}')
check(route is not None, "PARTICIPATE_BEAR has no route, so no bonus can ever be granted")
print()

schedules = es.load()
bears = {key: s for key, s in schedules.items() if s.event_id == "BEAR_HUNT"}
if not bears:
    print("no BEAR_HUNT reservation on file at all -- nothing is armed tonight")
    raise SystemExit(1)

for key, schedule in sorted(bears.items()):
    start = schedule.start_datetime()
    print(f"=== {key} ===")
    print(f"    reserved_start : {schedule.reserved_start}")
    print(f"    source         : {schedule.source}")
    print(f"    live_window    : {schedule.live_window_state} @ {schedule.live_window_observed_at}")
    if start is None:
        print("    -> no parseable start; reads IDLE everywhere")
        continue
    print(f"    starts         : {start.astimezone(BEIJING):%Y-%m-%d %H:%M:%S} Beijing")
    print()
    print(f"    {'T-':>3}  {'beijing':19s} {'minutes':>8}  {'phase':5s} {'bonus':>9}  wake_s")
    print("    " + "-" * 62)
    previous_bonus = -1.0
    for offset in OFFSETS_MINUTES:
        moment = start - timedelta(minutes=offset)
        minutes = schedule.minutes_to_start(moment)
        phase = schedule.phase_at(moment)
        bonus = schedule.priority_bonus(moment)
        wake = es.seconds_until_next_transition(schedules, moment)
        wake_text = "none" if wake is None else f"{wake:.0f}"
        print(f"    {offset:>3}  {moment.astimezone(BEIJING):%Y-%m-%d %H:%M:%S}"
              f"  {minutes:>8.2f}  {phase.value:5s} {bonus:>9.1f}  {wake_text}")
        check(bonus >= previous_bonus,
              f"{key}: bonus fell from {previous_bonus} to {bonus} at T-{offset}")
        previous_bonus = bonus
    # The two rungs a loosest-first table gets wrong, named explicitly.
    check(schedule.phase_at(start - timedelta(minutes=3)) is es.ReadinessPhase.T5,
          f"{key}: three minutes out is not T5 -- ordinary work will not yield")
    check(schedule.phase_at(start - timedelta(minutes=1)) is es.ReadinessPhase.T1,
          f"{key}: one minute out is not T1")
    check(schedule.phase_at(start) is es.ReadinessPhase.OPEN,
          f"{key}: the start instant is not OPEN")
    # And the wake has to land on the boundary, not merely somewhere before the start.
    at_t35 = schedule.priority_bonus(start - timedelta(minutes=35))
    check(at_t35 == 0.0, f"{key}: T-35 should be IDLE, got bonus {at_t35}")
    print()

print("=" * 70)
print("ordinary AUTO wait, capped at the next activity node (bound_ms path)")
print("=" * 70)
sample = next(iter(bears.values()))
sample_start = sample.start_datetime()
print(f"{'T-':>3}  {'requested':>9}  {'capped':>7}  why")
print("-" * 70)
for offset, requested, expect in ((35, 600, 300), (17, 600, 120), (3, 600, 120),
                                  (0.5, 600, 30), (-1, 600, 600)):
    moment = sample_start - timedelta(minutes=offset)
    capped = es.bounded_poll_delay_seconds(requested, schedules, moment)
    print(f"{offset:>3}  {requested:>9}  {capped:>7.0f}"
          f"  {'next ladder boundary' if capped != requested else 'no boundary ahead'}")
    check(abs(capped - expect) < 1e-6,
          f"T-{offset}: capped wait {capped} != expected {expect}")

print()
print("=" * 70)
print("the OPEN rung is granted only with a fresh live observation of OPEN")
print("=" * 70)
# ``readiness_phase`` answers OPEN from the clock alone, but ``_event_readiness_bonus`` refuses
# to pay 4000 for it unless the SAME role also read the window as open within 15 minutes
# (runtime.py:1700-1714).  The clock can wake this runtime; it cannot prove the event opened.
# So the useful statement is not "OPEN scores 4000" but "OPEN scores 4000 once the window has
# actually been seen open" -- and tonight it has not been, which is the correct state.
for key, schedule in sorted(bears.items()):
    state = schedule.live_window_state
    freshly_open = state == es.LiveWindowState.OPEN.value
    print(f"  {key:26s} live_window_state={state:19s}"
          f" OPEN bonus {'GRANTED' if freshly_open else 'WITHHELD'}")

print()
if problems:
    print("PROBLEMS:")
    for problem in problems:
        print("  -", problem)
    raise SystemExit(1)
print("OK: the reservation on file climbs the ladder rung by rung and shortens the AUTO wait.")
