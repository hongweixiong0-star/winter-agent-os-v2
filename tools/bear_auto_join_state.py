"""BEAR_AUTO_JOIN_STATE CLI — thin wrapper over winter_agent_v2.bear_state.

Usage:
  .venv/Scripts/python.exe tools/bear_auto_join_state.py FRAME.png [FRAME2.png ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from winter_agent_v2.bear_state import read_state  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = [read_state(p) for p in argv[1:]]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
