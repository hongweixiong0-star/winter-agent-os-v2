"""WB-0BB honesty check: was the 12:30Z route triggered by the clock or forced?

Dumps the full decision records for the key steps of run
`codex_0ba_0bb_live_20260915`, and every recorded decision reason that mentions
the stamina gift, so the trigger can be established from evidence rather than
assumed.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]

    print("=== full records, run codex_0ba_0bb_live_20260915 ===")
    for r in rows:
        if r.get("episode_id") != "codex_0ba_0bb_live_20260915":
            continue
        keep = {k: v for k, v in r.items() if k not in ("state_before", "state_after")}
        print(json.dumps(keep, ensure_ascii=False)[:900])
        b = r.get("state_before") or {}
        a = r.get("state_after") or {}
        print("    before.stamina =", json.dumps(b.get("stamina") or {}, ensure_ascii=False)[:280])
        print("    after.stamina  =", json.dumps(a.get("stamina") or {}, ensure_ascii=False)[:280])
        print()

    print("=== every episode whose reason mentions the stamina gift / supply ===")
    for r in rows:
        blob = json.dumps(
            {k: r.get(k) for k in ("reason", "skill", "decision", "note")}, ensure_ascii=False
        )
        if "stamina" in blob.lower() and ("free" in blob.lower() or "supply" in blob.lower()):
            print(
                "  %s | %-22s | reason=%s"
                % ((r.get("recorded_at") or "")[:19], r.get("skill"), r.get("reason"))
            )

    print()
    print("=== keys available on an episode (so nothing is silently missing) ===")
    if rows:
        print("  ", sorted(rows[-1].keys()))


if __name__ == "__main__":
    main()
