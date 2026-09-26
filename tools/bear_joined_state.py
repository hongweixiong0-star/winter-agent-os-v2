"""BEAR_JOINED_STATE — define and read "already joined the bear rally".

Real-game state definition (operator directive section 7): the character has
successfully joined the ice-giant rally when the rally/march state shows our
own participation.  Observable client evidence, in order of reliability:

  1. The alliance war page rally rows show a joined march of ours (the row
     carries our role name / 「已加入」/「集结中」 member marker).
  2. The march queue HUD shows an active march whose target is the bear.
  3. The rally detail popup lists our role among the members.

Until a real bear-war frame exists (no war during 2026-09-26 sessions), the
reader implements rule (1): OCR the alliance-war rally tab body and look for
our stored role name or the 「已加入」 marker, page-scoped to the rally list
region.  With no war the page prints 「当前暂无战事」 → NOT_JOINED.

Returns JOINED / NOT_JOINED / UNKNOWN.  UNKNOWN never feeds a verifier PASS.

The role name comes from learning/bear_role.json (written once per character
by the ROLE_CONFIRMED reader); without it the reader is name-blind and can
only trust explicit markers.

Usage:
  .venv/Scripts/python.exe tools/bear_joined_state.py FRAME.png [--role NAME]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402

# Rally tab body (below the 集结/单人/活动 tabs, above the auto-join bar).
BODY_BOX = (0, 140, 720, 1130)
JOINED_MARKERS = ("已加入", "集结中")
NO_WAR_MARKERS = ("当前暂无战事",)
ROLE_STORE = PROJECT_ROOT / "learning" / "bear_role.json"


def _stored_role() -> str:
    try:
        return str(json.loads(ROLE_STORE.read_text(encoding="utf-8")).get("role_name", ""))
    except Exception:  # noqa: BLE001
        return ""


def read_joined_state(frame_path: str | Path, role_name: str = "") -> dict:
    """Read whether this character has joined the current bear rally."""
    frame = Image.open(frame_path).convert("RGB")
    try:
        from winter_agent_v2.ocr import RapidOCRBackend
        tokens = RapidOCRBackend().recognize(frame.crop(BODY_BOX))
    except Exception as exc:  # noqa: BLE001
        return {"frame": str(frame_path), "state": "UNKNOWN",
                "reason": f"OCR_UNAVAILABLE:{type(exc).__name__}"}
    text = "".join(t.text for t in tokens)

    if any(m in text for m in NO_WAR_MARKERS):
        return {"frame": str(frame_path), "state": "NOT_JOINED",
                "reason": "no war on the rally tab (当前暂无战事)"}

    role = role_name or _stored_role()
    markers = list(JOINED_MARKERS)
    if role:
        markers.append(role)
    for marker in markers:
        if marker in text:
            return {"frame": str(frame_path), "state": "JOINED",
                    "reason": f"marker {marker!r} present in rally body"}
    return {"frame": str(frame_path), "state": "UNKNOWN",
            "reason": "war present but no joined marker/role name found; needs rally detail read"}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    role = ""
    if "--role" in argv:
        role = argv[argv.index("--role") + 1]
    if not args:
        print(__doc__)
        return 2
    out = [read_joined_state(p, role) for p in args]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
