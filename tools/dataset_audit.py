"""Audit legacy/current screenshots before dataset promotion.

This tool never promotes an asset. It validates format/dimensions, computes
SHA-256, perceptual hash and difference hash, and marks exact/perceptual
duplicates for human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, UnidentifiedImageError

from winter_agent_v2.image_hash import dhash, hamming, phash


SUPPORTED = {"PNG", "JPEG", "WEBP"}


@dataclass
class AssetRecord:
    asset_id: str
    path: str
    source_path: str
    source: str
    retrieved_at: str
    width: int | None
    height: int | None
    format: str | None
    sha256: str | None
    phash: str | None
    dhash: str | None
    status: str
    duplicate_of: str | None
    semantic: str
    page: str
    confidence: float
    notes: str


def audit_file(path: Path, source_root: Path, metadata: dict[str, dict]) -> AssetRecord:
    relative = path.relative_to(source_root).as_posix()
    meta = metadata.get(relative, {})
    live_capture = relative.startswith("live_")
    base = dict(
        asset_id=hashlib.sha1(relative.encode("utf-8")).hexdigest()[:12],
        path=relative,
        source_path=str(meta.get("source_path", "ADB:emulator-5554/com.gof.china" if live_capture else "")),
        source=str(meta.get("source", "LIVE_CLIENT" if live_capture else "LEGACY_PROJECT")),
        retrieved_at=str(meta.get("retrieved_at", datetime.now(timezone.utc).isoformat())),
        semantic=str(meta.get("semantic", "UNKNOWN")),
        page=str(meta.get("page", "UNKNOWN")),
        confidence=float(meta.get("confidence", 0.0)),
        notes=str(meta.get("notes", "")),
    )
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            fmt = image.format
            width, height = image.size
            if fmt not in SUPPORTED or width < 16 or height < 16:
                status = "DAMAGED"
            else:
                status = "CANDIDATE"
            return AssetRecord(
                **base,
                width=width,
                height=height,
                format=fmt,
                sha256=sha,
                phash=phash(image),
                dhash=dhash(image),
                status=status,
                duplicate_of=None,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        base["notes"] = f"{base['notes']} decode_error={type(exc).__name__}".strip()
        return AssetRecord(
            **base,
            width=None,
            height=None,
            format=None,
            sha256=sha,
            phash=None,
            dhash=None,
            status="DAMAGED",
            duplicate_of=None,
        )


def build_manifest(source_root: Path, metadata_path: Path) -> dict:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")).get("assets", {})
    paths = sorted(p for p in source_root.rglob("*") if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    records = [audit_file(path, source_root, metadata) for path in paths]
    exact: dict[str, str] = {}
    perceptual: list[AssetRecord] = []
    for record in records:
        if record.status == "DAMAGED" or not record.sha256:
            continue
        if record.sha256 in exact:
            record.status = "DUPLICATE"
            record.duplicate_of = exact[record.sha256]
            continue
        exact[record.sha256] = record.asset_id
        near = next((prior for prior in perceptual if prior.phash and record.phash and hamming(prior.phash, record.phash) <= 2), None)
        if near:
            record.status = "DUPLICATE"
            record.duplicate_of = near.asset_id
        else:
            perceptual.append(record)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return {"schema_version":"1.0","generated_at":datetime.now(timezone.utc).isoformat(),"counts":counts,"records":[asdict(record) for record in records]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.source_root.resolve(), args.metadata.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
