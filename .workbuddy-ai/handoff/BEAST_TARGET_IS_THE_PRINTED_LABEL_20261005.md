# The beast target is the label the frame printed, not a sprite

**Date:** 2026-10-05
**Change:** `winter_agent_v2/runtime.py` (`BEAST_LABEL_TARGET_SPECIES`, one resolver branch),
`tests/test_the_beast_target_is_the_label_the_frame_printed.py`
**Family:** `AVOID_STAMINA_WASTE / SELECT_BEAST_TARGET_MAMMOTH / SEMANTIC_TARGET_NOT_VERIFIED`
**Ledger size at measurement:** 35 rows — **0 successes**

---

## 1. What was wrong

`SELECT_BEAST_TARGET_MAMMOTH` taps the mammoth the client's map label named, so the route can
dispatch a march at it. Every one of its 35 recorded rows says the same thing:

```
result             FAILURE
failure_type       SEMANTIC_TARGET_NOT_VERIFIED
recognition_error  UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION
observed_change    UNKNOWN
duration           0.062 - 0.11 s
after_screenshot   ""            <- no after-frame, because no tap was sent
state_after        {}
```

0 successes in 35 attempts, and **not one tap ever reached the device**.

## 2. Why

The skill declares `Action("TAP_SEMANTIC", "TARGET_BEAST_MAMMOTH_5")` (`skills.py:851`) — a
**sprite template**. Measured over the same 35 frames, in `_semantic.find(frame, "TARGET_BEAST_MAMMOTH_5")`:

> **the sprite matched none of them.**

The resolver therefore fell through to its navigation advisor, whose own gate is
`skill_id.startswith("OPEN_") or skill_id.startswith("TAP_FOCUSED_TRAINING_CAMP_")`
(`runtime.py:6601`). `SELECT_BEAST_TARGET_MAMMOTH` starts with neither, so the advisor answered
`UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION` and the step ended without acting. That refusal string is
the one the ledger carries.

## 3. The frame was carrying the answer the whole time

`state_before.beast` on those rows:

```json
{"visible_target": "MAMMOTH", "level": 5, "available": true,
 "source": "BEAST_LABEL", "label_text": "猛犸象", "label_confidence": 0.9868,
 "table_level": 5, "level_matches_table": true, "tap_norm": [0.516, 0.586]}
```

The client printed the animal's own name at 0.9868, and the box of that name carries a
current-frame tap point. The sibling skill already works this way: `SELECT_BEAST_TARGET_LABELLED`
declares `BEAST_ON_MAP`, whose branch (`runtime.py:5626`) consumes exactly `frame.beast["tap_norm"]`
— 58 rows, 20 successes, and **all 38 of its failures have an after-frame**, i.e. that route does
tap. The species-specific skills were written against one sprite per animal and never got the same
treatment.

## 4. The change

Two pieces, both additive.

`runtime.py`, module scope, beside the other target tables:

```python
BEAST_LABEL_TARGET_SPECIES: dict[str, str] = {
    "TARGET_BEAST_MAMMOTH_5": "MAMMOTH",
    "TARGET_BEAST_MUSK_OX_9": "MUSK_OX",
}
```

and one branch in `_resolve_semantic_target`, placed **immediately before the sprite fallback**:

```python
_beast_species = BEAST_LABEL_TARGET_SPECIES.get(semantic)
if _beast_species is not None:
    beast = frame.beast if isinstance(frame.beast, Mapping) else {}
    if (frame.page is Page.MAP
            and beast.get("source") == "BEAST_LABEL"
            and beast.get("visible_target") == _beast_species):
        point = beast.get("tap_norm")
        ... return (x_norm, y_norm)
```

Three properties are deliberate:

* **Non-pre-empting.** `visible_target` is filled from the sprite template *as well as* from the
  label (`vision.py:2552` reads both spans for the same field), so a frame the sprite does match
  must still reach the fallback below. This is therefore the only branch in this resolver with no
  `return None` in it: it answers when the label answers, and otherwise falls through untouched.
* **Species-guarded.** The brain picks a species-specific skill from the observation it read,
  while the resolver is handed the *dispatch-time* frame. A label naming a different animal there
  must not be tapped by the skill that names this one.
* **Frame-derived.** The point is the box of a word this frame printed — which is the "detector"
  the constitutional amendment allows (`runtime.py:5994`: *模板、印字、或探测器*). No remembered
  coordinate, no config constant, no historical screenshot.

## 5. Evidence

**35/35, on the recorded production frames** (`_verify_beast_label_target.py`), each frame read
three ways:

| reading | result |
|---|---|
| `find(frame, "TARGET_BEAST_MAMMOTH_5")` (sprite) | **None on all 35** |
| the production resolver, as deployed | a point on all 35, and the set of distinct points matches the recorded `tap_norm` values exactly |
| the ledger's own `after_screenshot == ""` | True on all 35 |

`verdict tally: {'PASS': 35}`, with `TEMPLATE_ANSWERS 0`, `NO_POINT 0`, `TAP_WAS_SENT 0` — so the
sprite was never the answer on these frames, which is what makes this fix the one that matters
here rather than a second guess at the same clause.

The pre-fix side is the **ledger itself**, not an emulation: 35 rows that recorded no tap and the
advisor's refusal. Emulating half of a long resolver chain in-process would be weaker evidence
than the production record of the whole of it.

**Mutation, on a copy of the tree** (so the mutated file is never the live one): neutering the
branch fails exactly the two tests that require the label to answer, while the seven that assert
refusal and fall-through stay green; removing the species guard fails exactly
`test_a_label_naming_another_animal_does_not_answer_the_mammoth_target`.

## 6. What this does NOT cover

`SELECT_BEAST_TARGET_LABELLED` — the sibling that *does* tap — fails 38 of 58 with
`BEAST_TARGET_SELECTION_NOT_PROVEN`, and all 38 have an after-frame (durations 9.8–24.4 s). So
the tap lands and the card does not open. That is a different defect and needs its own
measurement: is the label's box off the animal's sprite, or did the map move between the
observation and the tap? It is not addressed here.

Also unmeasured: `SELECT_BEAST_TARGET` (the musk-ox skill) has **0 rows in the ledger** — it has
never been selected. It is named in the table for symmetry with the vision layer's two species
templates, and so that the day the brain picks it, it resolves the same way.

## 7. Acceptance criteria for a later reader

* On a frame whose `beast.source == "BEAST_LABEL"` and `visible_target == "MAMMOTH"`,
  `SELECT_BEAST_TARGET_MAMMOTH` must record a **non-empty `after_screenshot`** and a duration in
  seconds, not milliseconds. A step that still records its old 0.06 s and an empty after-frame has
  not been fixed.
* `SEMANTIC_TARGET_NOT_VERIFIED` with `recognition_error = UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION`
  on these revs **shall not** recur for this skill.
* A label naming a species other than the semantic's must still not be tapped by it.
