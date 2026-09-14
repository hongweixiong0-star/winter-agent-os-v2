# Vision dataset

Lifecycle: `raw → normalized → candidate → verified → production`.

External material must remain under `external` until its source, project path, license, retrieval time and provenance are recorded. Production promotion requires current-client validation. Duplicate states are `DUPLICATE`, `DAMAGED`, and `UNKNOWN`; SHA-256, pHash, dHash, dimensions and format are mandatory metadata. Coordinates are normalized (`x_norm`, `y_norm`, `w_norm`, `h_norm`) and mapped to the runtime screen.

Current counts (2026-09-05 audit): 306 raw screenshots (214 candidates, 92 duplicates, 0 damaged), 255 normalized ROI template candidates, 26 verified current-client icon/semantic records, and 0 Production templates. Replay has 104 labeled samples and remains `SIMULATION`; live evidence is recorded under `learning/`, `evidence/`, and the per-skill reports.
