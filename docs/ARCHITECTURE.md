# Winter Agent OS V2 Architecture

V2 is independent. It imports no legacy Agent, Brain, Scheduler, Vision gateway, or task architecture.

```text
Screenshot → Template Vision → OCR fallback/enrichment → WorldState
    → Brain → single Scheduler → Skill → Executor
    → Verifier → Learning → next WorldState
```

There is one Scheduler, one SkillRegistry, one WorldState model, one Executor boundary, and one Episode stream. `RuleBrain` decides WHAT; Skills define HOW; Vision and Qwen never click.

Vision is Template-first. `HybridVision` invokes OCR only for UNKNOWN or explicitly missing structured fields. The independent RapidOCR adapter may load the already-installed third-party runtime/models from the legacy environment, but never imports legacy project code. Screenshot hash + ROI form the OCR cache key. Exact, high-confidence page semantics are required; ambiguous text remains UNKNOWN.

The Scheduler can examine an ordered set of observed task states, record every skipped reason, and select the first actionable Skill. It does not perform Vision. `RuleBrain` accepts an explicit `CurrentGoal`, so `HOME` and `GATHER_RESOURCE` produce bounded, goal-directed choices instead of a free-running action sequence. Known pages with unknown DAILY/ALLIANCE state now `SAFE_STOP` instead of falling through to an arbitrary registered action.

Runtime policy is `AUTO_EXECUTION=true`, `PRODUCTION=true`, `DRY_RUN=false`. Normal game actions are allowed and scarce-resource spends are logged. Real-money/payment, account/role deletion, account-security changes, and system-dangerous operations remain blocked.

`LiveRuntime` is the bounded production entry point. It does not add another Scheduler: every action still passes through the single `Scheduler`, semantic `Executor`, and a skill-specific Verifier. Only explicitly allowlisted, verifier-backed atomic skills execute. A transient `UNKNOWN` observation may refresh the screenshot and Vision result at most twice, without repeating the preceding action; persistent `UNKNOWN`, unsupported skills, uncertain execution, or failed verification cause `SAFE_STOP`. `max_actions` and optional `stop_after` prevent an endless loop or an unintended second dispatch.

Map-to-city navigation uses the verified in-game `OPEN_HOME` action. Android BACK on MAP is not treated as navigation because the current client opens an exit-confirmation popup; that popup is now a recognized, safely dismissible state.

Semantic matching keeps strict global pHash thresholds. The moving MAP background produced one verified variance case for the fixed-position resource-search control, so only that semantic has a narrowly larger threshold and still requires its normal post-action page verifier. At 6/6 marches, Brain returns `SAFE_STOP/no_idle_march` before the Executor, producing zero clicks.

Replay is always `SIMULATION`. Production success requires live state change plus Vision and Verifier evidence. No current Skill is labelled `STABLE` without endurance/variance evidence.
