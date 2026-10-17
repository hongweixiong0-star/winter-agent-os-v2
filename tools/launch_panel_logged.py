"""Desktop control panel entry that records otherwise invisible pythonw failures."""

from __future__ import annotations

import os
import runpy
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "learning/control_panel/desktop_startup.log"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8", buffering=1) as stream:
        stream.write(f"\n[{datetime.now().isoformat()}] launch pid={os.getpid()} interpreter={sys.executable}\n")
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = stream
        try:
            os.chdir(ROOT)
            runpy.run_path(str(ROOT / "tools/control_panel.py"), run_name="__main__")
            return 0
        except SystemExit as exc:
            stream.write(f"exit={exc.code!r}\n")
            return exc.code if isinstance(exc.code, int) else 1
        except BaseException:
            traceback.print_exc(file=stream)
            return 1
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


if __name__ == "__main__":
    raise SystemExit(main())
