# -*- coding: utf-8 -*-
"""CLI: read EVERYTHING on one screenshot (or every PNG in a folder).

Standing operator rule 2026-09-28: "以后任意截图你都要能读出来，不要漏掉按钮信息".
Uses winter_agent_v2.ocr_full.read_all (whole frame + 3x5 tiles + 7 UI bands).

usage:
  python tools/ocr_readall.py <image.png> [--json]
  python tools/ocr_readall.py <dir> [--limit 20]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image  # noqa: E402
from winter_agent_v2.ocr_full import read_all  # noqa: E402


def one(p: Path, as_json: bool) -> None:
    im = Image.open(p)
    toks = read_all(im)
    if as_json:
        print(json.dumps({"file": str(p), "tokens": toks}, ensure_ascii=False, indent=1))
        return
    print(f"== {p.name}  ({len(toks)} tokens)")
    for t in toks:
        print(f"  {t['centre'][0]:>4},{t['centre'][1]:>4} [{t['source']:>14}] {t['text']}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print(__doc__); return 2
    target = Path(sys.argv[1])
    as_json = "--json" in sys.argv
    if target.is_dir():
        limit = 20
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        files = sorted(target.rglob("*.png"))[:limit]
        for f in files:
            one(f, as_json)
        return 0
    one(target, as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
