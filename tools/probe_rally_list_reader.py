"""Run the new rally-list reader over the four archived frames and print what it read."""
import sys
from pathlib import Path
sys.path.insert(0, r"E:\无尽冬日智能体")

import json
from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2 import rally

ROOT = Path(r"E:\无尽冬日智能体")
RAW = ROOT / "dataset/raw/bear_live_20260909"
cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
svc = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))

for name in ["join_list_now.png", "join_list_after_detail.png", "bear_rally_panel.png",
             "joined_with_jesse.png", "special_buildings.png"]:
    p = RAW / name
    if not p.is_file():
        print(f"--- {name}: MISSING"); continue
    r = rally.read_rally_list(p, svc)
    print(f"=== {name} ===  rows={len(r.rows)}  container={r.container_norm}")
    print(f"    evidence={dict(r.evidence)}")
    for row in r.rows:
        print(f"    row{row.row_index} y={row.header_y_norm} band={row.band_norm} "
              f"{row.target_type.value}/{row.state.value} cap={row.capacity_used}/{row.capacity_max} "
              f"t={row.remaining_seconds}s leader={row.leader!r} join={row.join_norm}")
    best = r.best_joinable()
    print(f"    BEST_JOINABLE: {None if best is None else (best.row_index, best.remaining_seconds, best.join_norm)}")
    print()
