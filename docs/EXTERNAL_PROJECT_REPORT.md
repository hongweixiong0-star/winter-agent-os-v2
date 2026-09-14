# External Project Report — V1

## AminulIslamSifat/wos

This is a device-facing Whiteout Survival automation project. Its public README describes OpenCV template matching, PaddleOCR, fuzzy OCR matching, ADB actions, JSON ROI definitions, task modules, gathering, alliance tasks, Intel, troop training, scheduling, and account rotation. Those ideas validate a hybrid deterministic vision stack and small use-case modules.

The same README explicitly warns that the implementation is hardcoded to 1080×2460 and may misclick at other resolutions. V2 must not inherit that constraint. Account files, coordinates, templates, purchase behavior, and the whole architecture are excluded. The README claims MIT licensing, but the actual LICENSE must be inspected before any code reuse.

## whiteout-project/bot

This repository is a Discord/alliance-management bot for reminders, gift codes, and alliance operations. It is not evidence for screenshot-driven gameplay automation. It may later inform the event registry, but its license and code paths require deeper inspection first.

## Shederator/wosbot

The project is useful as an AGPL-3.0 capability reference for task boundaries, queue handling and recovery patterns. V2 does not copy its code, architecture or media; the license makes direct incorporation inappropriate for this clean V2 core without a deliberate compliance decision.

## batazor/whiteout-survival-autopilot

The public project supplied reference-only OCR and dataset workflow ideas. Its license remains unknown, so no code or media is eligible for V2 Production.

## Current impact on GATHER_RESOURCE

External projects supplied priors for search navigation, march-count re-reading, OCR regions and bounded retry. Current CN-client evidence overrode text and coordinates: the final deployment action is `出征`, targets are normalized, and success requires the live queue/state Verifier.

Concrete V2 adaptations now shipped:

- `ResilientOCRBackend`: two bounded retries with short exponential backoff around the existing OCR backend; no second OCR manager or service.
- Global march capacity is re-read on both MAP and RESOURCE_DETAIL before a gather action. Full queues and the configured stamina-reserve slot block the action before formation opens.
- Battle-result blockers preempt the underlying page, following the external startup/blocker recovery pattern. Recovery is a semantic popup transition, not a blind coordinate retry.
- Reviewed template extraction now includes the parent screenshot hash in filenames, preventing common `step_001_before.png` names from overwriting evidence from another episode.

Actual inspected paths and decisions are preserved in:

- `knowledge/external/capabilities/gather_best_of_breed.json`
- `knowledge/external/capabilities/ocr_recovery_adapter.json`
- `knowledge/external/capabilities/mail_claim_best_of_breed.json`

Frostguard/wosbot remains AGPL-3.0 `REFERENCE_ONLY`. AminulIslamSifat/whiteout-survival-bot has no verified license file at the inspected commit, so it also remains pattern-only. No external source or image was copied into Production.

## Provenance rule

External artifacts may only move through `external → raw → normalized → candidate → verified → production`. V2 imported no external code, coordinates, screenshots, icons, tokens, cookies, or account data.
