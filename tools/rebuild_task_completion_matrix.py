from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from winter_agent_v2.task_completion import TaskCompletionStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the role-scoped task completion matrix from Goal and production Episode evidence."
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1],
        help="V2 data root (defaults to the repository containing this tool).",
    )
    args = parser.parse_args()
    result = TaskCompletionStore.rebuild_from_root(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
