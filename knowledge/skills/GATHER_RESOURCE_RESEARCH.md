# GATHER_RESOURCE Research

Status: `VERIFIED / LIVE_CLIENT`  
Retrieved: 2026-09-02; live-verified 2026-09-03  
Mode: Just-in-time research for the active P0 skill.

## Evidence-fused flow

1. From HOME, open the world map.
2. Read march queue usage; queue capacity and troop deployment capacity are different concepts.
3. Open resource search.
4. Select one of Meat, Wood, Coal or Iron and a target level.
5. Submit search and verify an available node rather than trusting the camera move alone.
6. Tap Gather and verify the deployment page.
7. Confirm troop load is appropriate; the client may preselect gathering heroes/troops.
8. Tap the current-client deployment control.
9. Verify march usage increased, target identity/coordinate is consistent, and state is MARCHING or GATHERING.
10. Verify GATHERING, then RETURNING/IDLE before considering a full loop complete.

## Current CN client facts

- HOME → MAP navigation is verified live.
- Search panel contains beast/giant-beast and four base resource categories.
- WOOD level 8 search is verified live.
- A level-8 abandoned lumber mill visibly reports capacity 14,000,000.
- Resource nodes can become occupied between discovery and Gather. Recovery is re-search, not repeated clicking on the stale node.
- Deployment page title is `木材` and its final button is `出征`; the earlier `派遣` text is retained only as an alias/prior.
- Current troop load 14,000,085 is sufficient for a 14,000,000 node.
- Current-client deployment action text is `出征`; `派遣` remains an alias only.
- Resource nodes can disappear or become occupied between discovery and selection; bounded recovery re-searches and never clicks a stale target indefinitely.
- One-troop capacity is 188 on the verified role. This was used only to shorten natural P0 validation, not as a production gathering strategy.
- Attempts 6–8 completed consecutive natural `MARCHING → RETURNING → IDLE` cycles. Attempt 8 ran through the V2 Vision → WorldState → Brain → single Scheduler → Skill → Executor → Verifier chain.
- Four later bounded Production runs completed verifier-backed Wood level-8 dispatches without intervention. Dynamic march usage was re-read rather than assumed, including an earlier march returning between runs; the latest dispatch reached 6/6.
- A fresh 6/6 observation produced `SAFE_STOP/no_idle_march` and zero clicks, proving the runtime does not over-dispatch when all queues are occupied.
- One 5/6 world-map frame missed the search icon because of perceptual variance. The Executor refused the click, the screenshot entered Replay/Candidate, and a semantic-specific tolerance plus live retry resolved it without weakening global matching.
- Android BACK on MAP opens the game's exit-confirmation popup in the current client. Vision recognizes this popup, `CLOSE_POPUP` safely dismisses it, and normal MAP → HOME navigation uses `OPEN_HOME`.

## External implementation ideas retained

- Use OCR for march `used/max`, timers and button text.
- Use templates for stable icons such as world search and recall.
- Keep percentage/normalized ROIs and map to pixels only at the device edge.
- Rotate resource types when a node is unavailable.
- Re-read march usage after dispatch instead of decrementing an internal counter optimistically.
- Defer until real return timing instead of blind retry loops.

## Rejected external behavior

- Never fall back to an invented march capacity when OCR fails.
- Never treat a tap return value as gathering success.
- Do not import fixed 1080×2460 coordinates.
- Do not import account files, credentials or unknown-license images into Production.
- Do not copy an external scheduler or overall architecture.

## Strategy candidates

- High-level resource tiles and keeping otherwise idle marches gathering are common recommendations, but remain `STRATEGY_CANDIDATE`.
- Reserving one march for alliance auto-join is player-goal dependent and must not be a universal rule.
