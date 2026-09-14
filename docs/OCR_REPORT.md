# OCR Report

V2 now has an independent `OCRService`, optional `RapidOCRBackend`, normalized ROI cropping, screenshot-hash cache, a conservative page classifier, and Template-first `HybridVision`.

The third-party RapidOCR runtime/models are loaded from the old environment only as a dependency. No legacy Vision, Brain, Scheduler, or Agent code is imported.

Targeted current-client evaluation:

- Page classification: 6/6 across Research, two Training states, Intel, Daily, and Alliance.
- Expected-keyword probe: 10/10.
- Alliance `您的捐献：49.680` was normalized and structured as `49680`.
- Training OCR structures `INFANTRY`, batch `806`, timer `10:03:12`, and `IN_PROGRESS`.
- Exact page-title matching prevents Daily task text containing “情报” from being misclassified as the Intel page.

This is a targeted baseline, not a general OCR accuracy claim. Evidence is in `evidence/ocr_live_eval.json`.
