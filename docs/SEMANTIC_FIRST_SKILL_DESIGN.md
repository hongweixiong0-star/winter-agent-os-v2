# V2 Universal Skill Design Rule Semantic First

## Mandatory principle

Universal Skills recognize game semantics, not one remembered image. A Skill is defined by state, action, relationship, and verified before and after change. Templates, icons, OCR text, ROI, coordinates, numbers, reward contents, skins, and list positions are supporting evidence only.

## Detection order

1. Page and state context
2. Semantic anchor
3. Relative layout
4. Button state
5. OCR keyword or number
6. Template or icon
7. Historical normalized ROI
8. Absolute coordinate as the final bounded fallback

No Universal Skill may use a fixed coordinate, number, reward, event name, list index, full text string, or single template as its only execution or success condition.

## Mandatory Skill contract

Every new Skill and Candidate must define `skill_id`, `semantic_goal`, `parameters`, `context`, `preconditions`, `semantic_requirements`, `vision_evidence`, `execute`, `verifier`, `recovery`, `resource_cost`, `risk`, `latency_class`, `unknown_policy`, `ui_change_tolerance`, and `lifecycle`.

A Candidate missing its semantic contract cannot enter the real attempt pool. A Skill cannot become Stable unless `SEMANTIC_ROBUSTNESS_GATE` confirms that it is not bound to a coordinate, number, reward payload, activity name, or single template; its verifier must prove a real state transition.

## Generic reward claim

`CLAIM_REWARD(source, context)` ignores reward identity, icon, amount, rarity, count, and ordering when all of the following are semantically confirmed: claimable, free, no choice, no real-money cost, no game-resource cost, and no item consumption.

`UNKNOWN_REWARD` is allowed after free-claim semantics are confirmed. `UNKNOWN_ACTION` or `UNKNOWN_COST` blocks the click. Choice boxes and selectable rewards route to `SELECT_REWARD_OPTION(options, strategy)`.

`CLAIM_ALL` is preferred only when the same free, no-choice, no-cost conditions are confirmed. Success requires claimable state to clear, a counter or inventory state to change, or another attributable reward-state transition. A click return value or template disappearance alone is insufficient.

## Vision assets

The dependency direction is `Skill -> Semantic Requirement -> Vision Resolver -> Candidate Evidence`. Templates do not define Skills. Every Vision Asset must carry a semantic identifier, normalized ROI, provenance, lifecycle, and context. When artwork changes but meaning remains, update the Vision Asset rather than the Skill.

## UI change survival

Stable promotion must demonstrate tolerance to changed icons, numbers, reward payloads, list order, slight movement, resolution, and activity skin. If unchanged game semantics still require rewriting the Skill, the Skill remains Candidate or Verified.

## Hard rules

1. Recognize semantics, not dead images.
2. Recognize state, not fixed numbers.
3. Recognize relationships, not fixed coordinates.
4. Verify result changes, not successful clicks.
5. Unknown content is not an unknown action.
6. Free no-choice rewards do not require reward-content recognition.
7. Choices and costs route through Strategy.
8. Templates belong to Vision, never Skill logic.
9. UI reskins should not rewrite Universal Skills.
10. Target, icon, number, and reward changes are parameters or Vision adaptations, not new Skills.
