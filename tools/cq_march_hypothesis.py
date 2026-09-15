"""Is `march_used is None` "unreadable", or does it mean "nothing is marching"?

On two live MAP frames the counter ROI OCR'd as `6/6` on one and as *nothing* on
the other; the second frame also had `marches == []`.  So the counter may simply
not be drawn when no march is out -- in which case None means idle, and treating
it as unreadable is what blocks the whole gather workflow (CHECK_MARCH /
MARCH_COUNT_NOT_READ at step 1, live 2026-09-15T12:59:36Z).

Test: across every recorded MAP observation, is `march_used is None` ever paired
with a non-empty marches list?  If it never is, the "idle" reading is supported.

Read-only.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]

    combos = Counter()
    examples: dict[tuple, dict] = {}
    for r in rows:
        for side in ("state_before", "state_after"):
            st = r.get(side) or {}
            if st.get("page") != "MAP":
                continue
            used = st.get("march_used")
            marches = tuple(str(m) for m in (st.get("marches") or []))
            key = (used is None, bool(marches), used)
            combos[key] += 1
            examples.setdefault(key, r)

    print("=== MAP observations: (used is None, has marches, used) -> count ===")
    for key, n in combos.most_common():
        print("   used_is_none=%-6s has_marches=%-6s used=%-6s  x%d" % (key[0], key[1], key[2], n))

    print()
    print("=== the decisive case: None used BUT marches present ===")
    found = [k for k in combos if k[0] and k[1]]
    print("   present:", len(found))
    if found:
        for k in found[:5]:
            r = examples[k]
            print("   e.g. %s %s" % ((r.get("recorded_at") or "")[:19], r.get("episode_id")))

    print()
    print("=== and the inverse: used a number BUT no marches ===")
    found = [k for k in combos if not k[0] and not k[1]]
    print("   present:", len(found), "counts:", [combos[k] for k in found])

    print()
    print("=== every CHECK_MARCH episode ===")
    for r in rows:
        if r.get("skill") == "CHECK_MARCH":
            b = r.get("state_before") or {}
            print(
                "   %s | %-8s | page=%s used=%s max=%s marches=%s"
                % (
                    (r.get("recorded_at") or "")[:19],
                    str(r.get("result")).upper(),
                    b.get("page"),
                    b.get("march_used"),
                    b.get("march_max"),
                    [str(m) for m in (b.get("marches") or [])],
                )
            )


if __name__ == "__main__":
    main()
