# Legacy Winter Agent OS Audit

Audit date: 2026-09-02  
Legacy root: `E:\dongri-mumu-bot`  
Mode: read-only; no legacy files changed or deleted.

## Executive conclusion

The legacy repository is a confirmed failed product. Its architecture and modules are not the V2 baseline and receive no reuse preference. It has accumulated parallel schedulers, registries, learning systems, agent modes, gates, role orchestration, model-promotion layers, and generated artifacts. V2 may extract evidence, data, verified flows, and independently testable tool ideas only; implementation is rewritten against V2 contracts.

The strongest legacy truth about the P0 goal is negative but useful: its own capability audit reports `GATHER_V1.stable=false`, `live_successes=2`, operational `CONDITIONALLY_STABLE`, and governance label `FALSE_STABLE`. This does **not** satisfy V2's requirement for three consecutive, fully evidenced real-game loops.

## Repository evidence

| Area | Files | Approx. bytes | Audit implication |
|---|---:|---:|---|
| core | 226 | 1,928,308 | Many infrastructure and orchestration layers |
| agent | 962 | 6,418,119 | Multiple generations/modes and overlapping concerns |
| vision | 49 | 381,910 | Small enough for targeted review |
| learning | 7,055 | 1,695,613,354 | Excessive generated state/model artifacts |
| knowledge | 141 | 7,653,857 | Useful reference, not canonical V2 truth |
| templates | 9,431 | 3,667,744,982 | Large candidate pool requiring dedup/provenance/license gates |
| screenshots | 10 | 1,312,565 | High-value current-client evidence candidates |
| logs | 3 | 1,395,664 | Useful runtime evidence; not success by itself |
| tests | 830 | 10,817,838 | Mine contracts and failure cases, do not clone suite |
| whiteout_bot | 210 | 39,501,713 | Separate/older implementation family; reference only |

The repository instruction points to `PROJECT_HANDOVER.md`, but that file is absent at the repository root. The available `docs/agent/ARCHITECTURE.md` and `docs/agent/SKILL_FACTORY.md` were read instead. Several temporary directories under `tmp` denied access; they were not bypassed and are not needed for the core audit.

Git status could not be read because the sandbox identity is not trusted by Git for this differently owned repository. No global safe-directory setting was changed.

## Classification

### KEEP

Keep means preserve evidence/data only. It does not mean copy a module.

| Legacy asset | Why it is valuable | V2 handling |
|---|---|---|
| `screenshots/` | Real-client visual evidence candidates | Inventory, hash, deduplicate, label, then copy only selected evidence into `dataset/raw` with provenance |
| Gather diagnostics and production failure JSON/JSONL | Real failure modes and state transitions | Normalize into replay episodes; never reinterpret `WAITING/PARTIAL` as success |
| `agent/verifier/world_change.py` and `agent/verifier/capability.py` concepts | Explicitly enforce “click OK != task success” | Reimplement a small Verifier contract around before/after WorldState |
| MuMu/ADB discovery behavior | Detects instance state, ADB status, serial and resolution | Reimplement one independent Device adapter after verifying current paths/package names |
| `core/diagnostics_retention.py` and `core/jsonl_rotation.py` concepts | Directly address disk growth | Reimplement bounded TTL/count/size policies from day one |
| OCR region preprocessing in `modules/gather_executor.py` | Real march HUD problem and practical crop/CLAHE approach | Extract as a candidate Vision fixture; eliminate stale-cache fallback as truth |
| Normalized/semantic ROI concepts | Avoid sole dependence on fixed pixels | Rebuild in V2 schema and validate across actual resolutions |

### ADAPT (ideas/data only; no legacy module import)

| Legacy asset | Adaptation rule |
|---|---|
| Template/OCR/detector observations | Reimplement one four-layer Vision service: template, OCR, detector, Qwen fallback. No legacy runtime imports and no hidden clicking. |
| Historical WorldState fields | Select only evidenced fields and express them in one new immutable WorldState schema. |
| Historical gathering flow/failures | Use only as evidence. Rewrite GATHER_RESOURCE as independent small skills with explicit preconditions and verifiers. |
| Recovery failure patterns | Implement the approved V2 recovery enum and retry limit `<=2` from scratch. |
| `vision/semantic_ui.py` plus `knowledge/ui_semantics/` | Reconcile names into the new V1 semantic dictionary; current-client screenshot wins. |
| Existing tests for UNKNOWN, march changes, popup recovery and resolution | Port behaviors as new contract tests, not imports tied to old packages. |
| Existing template images | Treat as external/legacy candidates. Require SHA-256/pHash/dHash, source path, client/version inference, and visual verification before promotion. |

Every candidate crossing from legacy into V2 must satisfy independence, simplicity, unit tests, Replay tests, and compatibility with the single V2 loop. Failure of any gate makes it `REFERENCE_ONLY` or `DISCARD`.

### REWRITE

| Area | Reason |
|---|---|
| Scheduler | V2 permits one Scheduler. Legacy contains central, cross-role, event, background-learning and phased scheduling families. |
| Skill registry | V2 needs one registry and five lifecycle states; legacy has several registry/evolution/factory generations. |
| Learning | V2 starts with append-only Episodes and proposals, not neural retraining or automatic production patching. |
| Brain | Replace overlapping goal/priority/constraint/value planners with one strict-JSON skill selector. |
| Executor | Provide one Maa/ADB boundary with safety policy and normalized targets. |
| Configuration | Create a small V2 config with `PRODUCTION=false`, `DRY_RUN=true`, retention limits and risk policy. Do not inherit account files. |
| GUI | Rebuild only Status, Page, Current Skill, Confidence, Last Action, Result, Start and Stop. |

### DELETE_FROM_V2

This means “do not include in V2”; it does **not** authorize deletion from the legacy repository.

- Multiple scheduler implementations and scheduler bridges.
- Multiple registry generations and factory/daily/evolution registries.
- `agent_mode`, complex decision gates, cross-role scheduler, role rotation and bear multi-role orchestration during P0–P2.
- Neural Vision V3A–V3H training/report proliferation for the first V2 release.
- Automatic code patching or direct Production promotion.
- Qwen-driven pixel or coordinate actions.
- Any behavior that retries a blocked task beyond the V2 retry budget; legacy evidence includes blocked gather retries reaching 13.
- Fixed schedule assumptions such as stamina hours `12` and `19` as production truth.
- Duplicate `whiteout_bot`, root scripts, older recipes, backups and alternate runtime families from the V2 dependency graph.

### REFERENCE_ONLY

- `learning/skill_factory/`, `learning/skill_evolution/`, `core/skill_discovery/` and model-promotion pipelines: useful histories of governance attempts, too complex for V2 bootstrap.
- `knowledge/` and `knowledge_sources/`: candidates for reconciliation against the new provenance-led KB, never authoritative wholesale.
- `templates/` bulk corpus: no direct Production import because source/license/version/duplication status varies.
- Historical final/acceptance reports: claims must be checked against raw episode, screenshot and verifier evidence.
- Multi-account and multi-role code: explicitly deferred until P0–P2 stability.

## GATHER_RESOURCE reality audit

Evidence found:

- `docs/capability/CAPABILITY_MATRIX.md`: `live_successes=2`, historical approximately 72%, pipeline not Stable.
- `docs/capability/CAPABILITY_AUDIT_SUMMARY.md`: `GATHER_V1.stable=false`, `FALSE_STABLE`.
- `docs/capability/GATHER_REALITY_AUDIT.md`: recent window has 4 success-like and 5 fail-like episodes.
- Runtime validation records show repeated `WAITING / NO_IDLE_NO_PREEMPT` and recovery counters beyond the intended V2 limit.
- Template growth records explicitly keep gather templates `EVIDENCE_ONLY/CANDIDATE` and state `ONE_SUCCESS_NOT_ENOUGH`.

Conclusion: legacy gathering supplies useful screenshots, ROI/OCR lessons, failure taxonomy, and verifier ideas, but **zero successes are inherited into V2 acceptance**. V2 starts at `CANDIDATE` and must produce its own 3/3 consecutive evidence bundle.

## Specific engineering findings

1. `modules/gather_executor.py` correctly prefers cropped and enlarged march-HUD OCR, but later falls back to cached march values. V2 may cache by screenshot hash, but must not use stale march state to authorize a click.
2. `modules/gathering_manager.py` has a risky inconsistency: when march parsing is unknown, `idle_slots()` can return at least one trial slot. That conflicts with `UNKNOWN → no guess/no click` and must not be retained.
3. The gather verifier uses march-count change and gathering/marching text, which is the right direction. V2 must additionally bind resource target identity and verify the full gathering/return loop.
4. Some coordinates are normalized or dimension-derived, but hardcoded pixel observations and source-resolution constants still exist. They may serve as annotations only.
5. Retention utilities exist, yet the 3.67 GB template tree shows that policy enforcement and lifecycle storage were not sufficiently bounded.

## Import safety plan

No legacy asset was copied during this audit. A later import step must generate a manifest before copying:

```text
legacy_path, sha256, phash, dhash, width, height, format,
source=LEGACY_PROJECT, observed_client/version, semantic,
license/provenance, status=CANDIDATE
```

Only current-client-correlated assets may reach `verified`; historical labels cannot directly produce `production` status.

## V2 decisions resulting from the audit

- Build V2 independently under `winter_agent_v2/`.
- Preserve one Scheduler, one SkillRegistry, one Learning episode store, one WorldState model and one Executor boundary.
- First use selected legacy screenshots to create replay fixtures and validate page/march/resource semantics.
- Implement disk limits before any screenshot capture loop.
- Treat all legacy skills as `DISCOVERED` or `CANDIDATE`; none is `STABLE` by inheritance.
- Do not begin multi-role work before P0–P2 stability.

## Classification summary

| Class | Counted groups |
|---|---:|
| KEEP | 7 |
| ADAPT | 7 |
| REWRITE | 7 |
| DELETE_FROM_V2 | 9 |
| REFERENCE_ONLY | 5 |

This audit completes legacy discovery/classification. It does not modify or certify the old system.
