# P0 GATHER_RESOURCE Evidence

Status: **VERIFIED**  
Promotion: `GATHER_RESOURCE → VERIFIED`; not `STABLE` until long-duration runs pass.

## Confirmed

- Independent V2 ADB connection: PASS
- Current game foreground package: PASS (`com.gof.china`)
- Current screenshot capture: PASS (720×1280 PNG)
- Targeted live popup recognition probe: PASS (1/1, 0.99; not a general accuracy claim)
- Production semantic Executor: PASS
- Paid/purchase action blocking: PASS
- Semantic ROI verification: PASS on the current client
- WorldState recognition: search, resource detail, march, MARCHING, RETURNING, IDLE — PASS
- Brain → single Scheduler → Skill → Executor: PASS live in attempt 8
- Dispatch Verifier: PASS (`1/6 → 2/6`, WOOD target, MARCHING)
- Return Verifier: PASS (`RETURNING → 1/6 IDLE`)
- Replay dataset: 110 labeled samples (`SIMULATION`); full dataset has 267 normalized ROI candidates
- Consecutive natural live cycles: PASS (attempts 6–8)
- Bounded unattended dispatch: four verifier-clean starts; the latest filled the march queue to 6/6
- Full-queue guard: PASS; `SAFE_STOP/no_idle_march`, zero click

## Remaining before Stable

- 30-minute, 1-hour, 3-hour and 6-hour endurance stages
- Broader OCR outside the calibrated march HUD; current P0 now parses dynamic 3/6, 4/6 and 5/6 counts plus MARCHING/GATHERING/RETURNING text or short timers
- Resource rotation and occupied-node recovery under the autonomous loop

## Production attempts

| Attempt | Result | Evidence |
|---:|---|---|
| 1 | ACCELERATED_VALIDATION | MARCHING → GATHERING → recalled RETURNING → IDLE; not counted as natural success |
| 2 | SUCCESS | Full level-8 gather completed naturally overnight |
| 3 | BLOCKED | Levels 1–3 unavailable; bounded retry stopped with `RESOURCE_NOT_FOUND` |
| 4 | BLOCKED | Level 4 unavailable |
| 5 | SUCCESS | One-troop natural cycle; MARCHING → IDLE |
| 6 | SUCCESS | One-troop natural cycle; MARCHING → RETURNING → IDLE |
| 7 | SUCCESS | One-troop natural cycle; MARCHING → RETURNING → IDLE |
| 8 | SUCCESS | Full V2 execution chain and code Verifier PASS |
| 9 | START_VERIFIED | Bounded runtime dispatched Wood gathering, march count 3/6→4/6, then observed GATHERING and safely returned HOME |
| 10 | START_VERIFIED | Second consecutive bounded runtime dispatch, march count 4/6→5/6; all five step Verifiers and OPEN_HOME passed |
| 11 | START_VERIFIED | An earlier march returned before execution; runtime correctly observed 4/6 and dispatched to 5/6 |
| 12 | BLOCKED_NO_ACTION | Search semantic pHash variance at 5/6; executor refused the click, evidence entered Replay, narrow tolerance added |
| 13 | START_VERIFIED | Replay-backed retry passed and dispatched 5/6→6/6 |
| 14 | BLOCKED_EXPECTED | Full queue 6/6 caused `SAFE_STOP/no_idle_march`; zero click |

The acceptance sequence is attempts 6, 7 and 8: `3/3 SUCCESS`. Attempts 9–10 prove repeatable unattended dispatch starts, but remain distinct from a completed natural return cycle. Replay, unit tests, dry runs and legacy evidence are not counted as live successes.
