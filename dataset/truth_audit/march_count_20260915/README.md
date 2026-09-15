# March counter: drawn vs not drawn (2026-09-15)

Two real live-client frames, **both classified MAP at confidence 0.99**, differing in
exactly one respect: whether the march counter is drawn at all.

- `idle_state_maa_20260915T124440.png` — the counter ROI (`MARCH_COUNT_ROI`,
  x 0.24 / y 0.172 / w 0.14 / h 0.036) returns **no OCR tokens**, and no march
  states are present. The client draws no counter because nothing is marching.
  This is the frame that used to be read as "unreadable", which stopped every
  gather run at its first step.
- `busy_live_page_20260915_133152.png` — the same ROI OCRs as **6/6**, and a
  MARCHING state is present.

They are the two poles of the rule added to `winter_agent_v2/ocr.py`: a counter
that is not drawn means idle — but **only** when no march state is present either.

That conjunction is what the corpus forced. Across every recorded MAP
observation:

| observation | count |
|---|---:|
| `march_used is None` and no march states | 98 |
| `march_used is None` and march states present | 35 |

Only the first may be read as idle. The second is a count we genuinely cannot
read, and inventing a zero there would be inventing a queue length.

## Why copies live here

`tests/` may not reference frames under `dataset/raw` or `dataset/evidence`:
those directories are prunable, and `tests/test_evidence_integrity.py` fails the
suite if any test hard-codes a path inside them. So the two frames are archived
here and the test points at these copies.

## Provenance

| file | original |
|---|---|
| `idle_state_maa_20260915T124440.png` | `dataset/evidence/maa_live/state_maa_20260915T124440.png` |
| `busy_live_page_20260915_133152.png` | `dataset/raw/control_panel/probe/live_page_20260915_133152.png` |
