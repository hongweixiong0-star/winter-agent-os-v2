"""Merge reviewed template manifests without duplicate evidence records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.target.read_text(encoding="utf-8"))
    records = list(payload.get("records", []))
    keys = {(row.get("semantic"), row.get("parent_sha256"), json.dumps(row.get("roi_norm", {}), sort_keys=True)) for row in records}
    added = 0
    for source in args.sources:
        incoming = json.loads(source.read_text(encoding="utf-8"))
        for row in incoming.get("records", []):
            key = (row.get("semantic"), row.get("parent_sha256"), json.dumps(row.get("roi_norm", {}), sort_keys=True))
            if key in keys:
                continue
            row["source"] = "LIVE_CLIENT_REPLAY_REVIEWED"
            records.append(row)
            keys.add(key)
            added += 1
    payload["records"] = records
    payload["count"] = len(records)
    args.target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"added": added, "count": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
