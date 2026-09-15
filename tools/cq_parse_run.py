"""Parse a run_live.py stdout dump into a compact per-step table."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(path: pathlib.Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    i = raw.find('{"steps"')
    j = raw.rfind("}")
    return json.loads(raw[i : j + 1])


def main() -> None:
    for name in sys.argv[1:]:
        p = ROOT / name
        print("=" * 78)
        print(name)
        try:
            d = load(p)
        except Exception as exc:  # noqa: BLE001
            print("  UNPARSEABLE:", exc)
            continue
        print("  stop_reason:", d.get("stop_reason"))
        for s in d.get("steps") or []:
            dec = s.get("decision") or {}
            ex = s.get("execution") or {}
            ver = s.get("verification") or {}
            b = s.get("before") or {}
            a = s.get("after") or {}
            intel_after = (a.get("intel") or {})
            print(
                "  %-3s %-22s reason=%-38s exec=%-5s %s->%s ver=%-5s/%s"
                % (
                    s.get("index"),
                    dec.get("skill"),
                    str(dec.get("reason"))[:38],
                    bool(ex.get("executed")),
                    b.get("page"),
                    a.get("page"),
                    ver.get("ok"),
                    ver.get("reason"),
                )
            )
            if ex:
                print(
                    "        action=%-14s target=%-28s backend=%-6s cap=%-16s recog=%-4s lat=%sms"
                    % (
                        (ex.get("action") or {}).get("kind"),
                        (ex.get("action") or {}).get("target"),
                        ex.get("backend"),
                        ex.get("capture_backend"),
                        ex.get("recognition_backend"),
                        ex.get("latency_ms"),
                    )
                )
            if intel_after:
                print("        intel_after=%s" % json.dumps(intel_after, ensure_ascii=False)[:220])


if __name__ == "__main__":
    main()
