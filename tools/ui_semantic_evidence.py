"""Read-only: which generic UI strings does the CURRENT client actually show?

The user's ask is to stop treating a candidate list as fact.  This tool turns
`knowledge/ui/semantic_dictionary.json` (gate CANDIDATE) into evidence: it OCRs the
page-labelled real-client corpus and reports, per candidate, the pages and frames where
its strings were actually read -- and, in the other direction, the strings the client
shows that no candidate names at all (the dictionary's blind spots, which is where
去重/退出/继续 这类通用提示 live).

Corpus: dataset/truth_audit/ui_semantics_corpus -- frames whose page production itself
labelled (learning/episodes.jsonl).

Usage:
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/ui_semantic_evidence.py [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import OCRService, RapidOCRBackend  # noqa: E402

CORPUS = ROOT / "dataset" / "truth_audit" / "ui_semantics_corpus"
DICTIONARY = ROOT / "knowledge" / "ui" / "semantic_dictionary.json"
OUT = ROOT / "knowledge" / "ui" / "semantic_evidence.json"

# Strings that are UI chrome on every frame and carry no semantic by themselves; kept out
# of the "discovered" list so it reports things that could become semantics.
NOISE = {"", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "/", "%", ":", "-", "+", "x",
         "X", "OK", "VIP", "cm", "m"}


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-pages", type=int, default=2,
                        help="how many distinct pages a string must appear on to count as generic")
    args = parser.parse_args()

    dictionary = json.loads(DICTIONARY.read_text(encoding="utf-8"))
    frames = sorted(CORPUS.glob("*.png"))
    if args.limit:
        frames = frames[: args.limit]
    print(f"{len(frames)} labelled frames, {len(dictionary['records'])} candidates", flush=True)

    service = OCRService(RapidOCRBackend())

    # string -> {page: frames}, and the raw token text seen
    seen: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.defaultdict(int))
    for i, frame in enumerate(frames, 1):
        page = frame.name.split("__")[0]
        try:
            result = service.recognize(frame)
        except Exception as exc:  # noqa: BLE001
            print(f"  OCR failed on {frame.name}: {exc}", flush=True)
            continue
        for token in result.tokens:
            text = (token.text or "").strip()
            if not text or text in NOISE or len(text) < 2:
                continue
            seen[text][page] += 1
        if i % 20 == 0:
            print(f"  ... {i}/{len(frames)}", flush=True)

    # (a) candidate side: which candidates have real-client evidence
    confirmed, unconfirmed = [], []
    for record in dictionary["records"]:
        wanted = [s for s in (as_list(record.get("ocr")) + as_list(record.get("cn_aliases")))
                  if s and s.strip()]
        wanted = [w for w in wanted if w != "*"]
        hits = {w: dict(seen[w]) for w in wanted if w in seen}
        pages = sorted({p for h in hits.values() for p in h})
        row = {"id": record["id"], "cn": record.get("cn"), "wanted": wanted,
               "pages_seen": pages, "strings_seen": hits, "dictionary_pages": record.get("pages")}
        (confirmed if hits else unconfirmed).append(row)

    # (b) client side: strings the client shows repeatedly that no candidate names
    named = {s for record in dictionary["records"]
             for s in as_list(record.get("ocr")) + as_list(record.get("cn_aliases"))}
    discovered = []
    for text, pages in seen.items():
        if text in named:
            continue
        if len(pages) >= args.min_pages and sum(pages.values()) >= 2:
            discovered.append({"text": text, "pages": sorted(pages), "frames": sum(pages.values())})
    discovered.sort(key=lambda r: (-len(r["pages"]), -r["frames"], r["text"]))

    print(f"\n=== candidates with real-client evidence: {len(confirmed)} / {len(dictionary['records'])} ===")
    for row in confirmed:
        print(f"  {row['id']:34s} seen on {','.join(row['pages_seen']):24s} "
              f"strings={list(row['strings_seen'])}")
    print(f"\n=== candidates with NO evidence on these frames: {len(unconfirmed)} ===")
    for row in unconfirmed:
        print(f"  {row['id']:34s} wanted={row['wanted']}  dict_pages={row['dictionary_pages']}")

    print(f"\n=== strings the client shows on >= {args.min_pages} pages that NO candidate names: "
          f"{len(discovered)} ===")
    for row in discovered[:60]:
        print(f"  {row['text'][:28]:30s} pages={len(row['pages']):>2d} frames={row['frames']:>3d}  {','.join(row['pages'])}")

    OUT.write_text(json.dumps({
        "schema_version": "1.0",
        "purpose": "从真机帧 OCR 出的通用 UI 文字证据；词典候选的校准结果与客户端的盲区",
        "corpus": str(CORPUS.relative_to(ROOT)),
        "frames_scanned": len(frames),
        "method": "tools/ui_semantic_evidence.py（整帧 OCR，页面标签来自 learning/episodes.jsonl 的 state.page）",
        "confirmed": confirmed,
        "unconfirmed": unconfirmed,
        "strings_unnamed_by_the_dictionary": discovered,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
