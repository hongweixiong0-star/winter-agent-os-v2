"""WB-0BB: is the whole stamina route already closed in ONE run, with a real
stamina increase and zero paid taps?  Plus the current supply-clock state."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]

    print("=== the 20:30Z window (episodes 12:26 - 12:33) ===")
    win = [r for r in rows if "2026-09-15T12:2" <= (r.get("recorded_at") or "") <= "2026-09-15T12:33"]
    prev_stamina = None
    for r in win:
        b = r.get("state_before") or {}
        a = r.get("state_after") or {}
        sb = (b.get("stamina") or {}).get("current")
        sa = (a.get("stamina") or {}).get("current")
        print(
            "  %s | %-22s | %-8s | page %-16s -> %-16s | stamina %s -> %s | cb=%s ab=%s eb=%s | ep=%s"
            % (
                (r.get("recorded_at") or "")[:19],
                r.get("skill"),
                str(r.get("result")).upper(),
                b.get("page"),
                a.get("page"),
                sb,
                sa,
                r.get("capture_backend") or "-",
                r.get("action_backend") or "-",
                r.get("executor_backend") or "-",
                r.get("episode_id"),
            )
        )

    print()
    print("=== the same window grouped by run (episode_id) ===")
    from collections import OrderedDict

    runs: dict[str, list[dict]] = OrderedDict()
    for r in win:
        runs.setdefault(str(r.get("episode_id")), []).append(r)
    for eid, items in runs.items():
        skills = [i.get("skill") for i in items]
        print("  %s  (%d steps)" % (eid, len(items)))
        print("      %s" % " -> ".join(str(s) for s in skills))

    print()
    print("=== every CLAIM_FREE_STAMINA ever recorded ===")
    for r in rows:
        if r.get("skill") == "CLAIM_FREE_STAMINA":
            b = r.get("state_before") or {}
            a = r.get("state_after") or {}
            print(
                "  %s | %-8s | stamina %s -> %s | page %s -> %s | verifier=%s"
                % (
                    (r.get("recorded_at") or "")[:19],
                    str(r.get("result")).upper(),
                    (b.get("stamina") or {}).get("current"),
                    (a.get("stamina") or {}).get("current"),
                    b.get("page"),
                    a.get("page"),
                    r.get("verifier_ok"),
                )
            )

    print()
    print("=== supply clock state ===")
    sp = ROOT / "learning/stamina_supply.json"
    if sp.exists():
        raw = sp.read_text(encoding="utf-8")
        print("  file:", raw.strip()[:300])
        try:
            d = json.loads(raw)
            ns = d.get("next_supply_at")
            if ns:
                t = datetime.fromisoformat(ns)
                now = datetime.now(timezone.utc)
                print("  next_supply_at :", t.isoformat())
                print("  now            :", now.isoformat(timespec="seconds"))
                print("  DUE            :", now >= t, "| seconds remaining:", int((t - now).total_seconds()))
        except Exception as exc:  # noqa: BLE001
            print("  parse failed:", exc)
    else:
        print("  MISSING")

    print()
    print("=== paid-control safety: any episode touching a diamond/paid semantic? ===")
    paid = [
        r
        for r in rows
        if any(
            k in json.dumps(r.get("action") or {}, ensure_ascii=False)
            for k in ("DIAMOND", "BUY", "PURCHASE", "PAY", "STORE", "SHOP", "PAID")
        )
    ]
    print("  episodes with a paid-looking action target:", len(paid))
    for r in paid[-10:]:
        print("   ", (r.get("recorded_at") or "")[:19], r.get("skill"), (r.get("action") or {}).get("target"))


if __name__ == "__main__":
    main()
