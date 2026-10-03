from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Evidence that tests, reviewed manifests, the verifier calibration set, or a
# production episode point at must survive retention.  Deleting it made the suite
# non-deterministic (a test would pass until the panel pruned the screenshot it
# references) and, worse, destroyed the only frames that could prove a live run
# ever happened.
#
# The data lifecycle this encodes:
#
#   RAW        -> prunable, rotating runtime captures
#   AUTO_LABEL -> prunable
#   CANDIDATE  -> protected
#   VERIFIED   -> protected, long-term
#   HARD       -> protected forever (hard-block evidence)
#   REJECTED   -> prunable
#
# ``dataset/verified`` and ``dataset/production`` are the long-term areas and
# were previously missing from the protection list, so they could be pruned.
PROTECTED_DIRECTORY_NAMES = frozenset({
    "candidate",     # AUTO_LABEL / reviewed templates
    "verified",      # VERIFIED: long-term retention area
    "production",    # PRODUCTION evidence referenced by episodes
    "normalized",
    "truth_audit",   # audit frames, regression fixtures
    "seed",
    "evidence",      # hard-block evidence and failure reproductions
    "external",      # external reference material with provenance
    "panel_redesign",
    "resource_tabs",
})
PROTECTED_SUFFIXES = {".json", ".jsonl", ".md", ".py"}

# Files that are referenced by the production episode stream are protected even
# when they live inside an otherwise rotating capture directory.
EPISODE_STREAM = "learning/episodes.jsonl"
REFERENCE_KEYS = ("before_screenshot", "after_screenshot", "screenshot")

#: The same problem, second stream.  ``truth_audit`` protects the calibration corpus *file*, but
#: every ``frame`` its rows name lives under the prunable runtime capture tree, so a row survived
#: only while some episode happened to cite the same file.  Measured 2026-10-02: 80 of the 136
#: positive frames were already gone, and the sweep had taken the source frame of 10 of the 31
#: auto-collected templates.  A calibration set that shrinks every cycle cannot calibrate.
CORPUS_REL = Path("dataset/truth_audit/icon_label_controls/samples.json")
CORPUS_FRAME_KEYS = ("frame",)


def _normalized(parts: tuple[str, ...]) -> set[str]:
    return {part.lower() for part in parts}


def _is_protected(path: Path) -> bool:
    return bool(_normalized(path.parts) & PROTECTED_DIRECTORY_NAMES)


def referenced_evidence(root: Path, stream: Path | None = None) -> set[Path]:
    """Absolute paths of every screenshot referenced by the episode stream.

    Section 13 of the takeover brief requires evidence to be unique and
    traceable, which is only meaningful if the referenced frames also survive
    retention.  Unknown keys and malformed lines are skipped: this function must
    never raise while pruning, because a crash here would leave the disk
    unbounded.
    """
    target = stream or (root / EPISODE_STREAM)
    referenced: set[Path] = set()
    if not target.is_file():
        return referenced
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return referenced
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        for key in REFERENCE_KEYS:
            value = row.get(key)
            if isinstance(value, str) and value:
                referenced.add(Path(value))
    return referenced


def corpus_evidence(root: Path, corpus: Path | None = None) -> set[Path]:
    """Absolute paths of every screenshot the calibration corpus cites.

    The second of the two evidence streams.  ``referenced_evidence`` covers frames a production
    episode points at; this covers frames a calibration row points at, and they are different sets
    -- measured 2026-10-02, 80 of the corpus's 136 positive frames had been pruned while nothing
    in the episode stream referred to them.

    Tolerant on purpose, for the same reason ``referenced_evidence`` is: this runs inside the
    pruning pass, and a crash here would leave the disk unbounded and take AUTO down with it.
    """
    target = corpus or (root / CORPUS_REL)
    cited: set[Path] = set()
    if not target.is_file():
        return cited
    try:
        payload = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return cited
    rows = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return cited
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in CORPUS_FRAME_KEYS:
            value = row.get(key)
            if isinstance(value, str) and value:
                cited.add(Path(value))
    return cited


def select_prunable_screenshots(
    paths: list[Path],
    *,
    max_count: int,
    ttl_days: int,
    now: datetime | None = None,
    referenced: set[Path] | None = None,
    referenced_ttl_days: int | None = None,
) -> list[Path]:
    """Return prune candidates without deleting them.

    Two retention tiers, because a frame an episode cites and a frame that was only
    glanced at are not the same object:

    * an unreferenced capture is a working frame -- it was read once and its content is already
      in the episode -- so it lives ``ttl_days``;
    * a referenced frame is evidence for a finished step, so it lives ``referenced_ttl_days``.

    ``referenced_ttl_days=None`` keeps the older behaviour of excluding cited frames from
    pruning entirely.  That reading is wrong in the long run and was the second half of why the
    trees reached 33 GB: "cited" is a growing set, so a rule that never prunes it accumulates
    for ever, however good the rate.  Evidence needs a lifetime, not an exemption.

    Only files that are neither location-protected nor (still) inside their reference window
    participate in either the TTL or the count budget, so the ``max_count`` ceiling applies to
    the rotating runtime captures rather than to reviewed templates or live proofs.
    """
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=ttl_days)
    ref_cutoff = (current - timedelta(days=referenced_ttl_days)
                  if referenced_ttl_days is not None else None)
    protected_refs = {path.resolve() for path in (referenced or set())}
    existing = []
    for path in paths:
        if not path.is_file() or _is_protected(path):
            continue
        try:
            resolved = path.resolve()
            if resolved in protected_refs:
                if ref_cutoff is None:
                    continue
                # Referenced, but past its own reference window: eligible like any other
                # capture, on the same TTL/count budget below.
                if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= ref_cutoff:
                    continue
        except OSError:
            continue
        existing.append(path)
    old = {
        path
        for path in existing
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff
    }
    newest_first = sorted(existing, key=lambda path: path.stat().st_mtime, reverse=True)
    overflow = set(newest_first[max_count:]) if max_count >= 0 else set()
    return sorted(old | overflow, key=lambda path: path.stat().st_mtime)


# One prune pass deletes at most this many files.  Measured 2026-09-18: the host
# kills a process whose single delete call carries 50 items, and the panel -- which
# had been running unattended for 6h45m -- died exactly there and took AUTO with it.
# Ten is also the project's own batch size for deletions, because bulk deletion is
# how evidence was lost before.
#: One prune pass deletes at most this many files.
#:
#: Two measured numbers set this, and the old value (10) lost to the first of them:
#:
#: * a round *produces* about 28 frames (median 23, mean 28, max 86 across 1647 recorded
#:   episodes).  A pass of 10 therefore left +18 frames per round, every round, and the trees
#:   reached 50,051 files / 33 GB by 2026-10-03.  A drain below the production rate is not a
#:   retention policy, it is a slower leak;
#: * the host aborts a process that deletes 50 files inside one turn
#:   (``CODEBUDDY_SAFE_DELETE_BULK_GUARD``), and 2026-09-18 that abort killed the panel with
#:   AUTO attached -- see the note on the caller.
#:
#: 30 sits above the production rate and 40% under the guard.  The caller runs once per round,
#: so the backlog now shrinks by roughly 2 frames per round and keeps shrinking; the pass size
#: bounds one burst rather than the whole sweep.
MAX_DELETIONS_PER_PASS = 30


def find_repo_root(start: Path) -> Path:
    """Walk up from a capture root until the repository root is found.

    The episode stream lives at ``<repo>/learning/episodes.jsonl``, so that file
    is the anchor.  A depth count was wrong before (it resolved to ``dataset``).
    """
    for candidate in (start, *start.parents):
        if (candidate / EPISODE_STREAM).is_file():
            return candidate
    return start


def prune_runtime_screenshots(
    root: Path,
    *,
    max_count: int,
    ttl_days: int,
    now: datetime | None = None,
    episodes_path: Path | None = None,
    limit: int = MAX_DELETIONS_PER_PASS,
    referenced_ttl_days: int | None = None,
) -> list[Path]:
    """Delete only image files inside one explicitly scoped runtime root.

    Referenced production frames inside that root are excluded while they are inside their
    reference window (``referenced_ttl_days``), so pruning cannot destroy the evidence an
    episode still relies on -- and cannot keep it for ever either, which is what "excluded
    outright" did.

    ``limit`` bounds one pass.  It is not a nicety: measured 2026-09-18, the panel
    ran unattended for 6h45m and then died because a single prune deleted 50 files
    at once, which is the host's bulk-delete threshold -- the guard intercepted the
    call and killed the process, taking AUTO with it.  The panel prunes once per
    cycle, so a bounded pass drains any backlog within a few minutes and never in a
    burst.  The project's own rule is that bulk deletion is how evidence was lost
    before; a cap here makes that structural instead of remembered.
    """
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        return []
    repo = find_repo_root(resolved_root)
    # Both evidence streams, not just the episode one: a frame the calibration corpus cites is as
    # load-bearing as a frame an episode cites, and it lives in the same prunable tree.
    referenced = referenced_evidence(repo, episodes_path) | corpus_evidence(repo)
    images = [
        path
        for path in resolved_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    candidates = select_prunable_screenshots(
        images, max_count=max_count, ttl_days=ttl_days, now=now, referenced=referenced,
        referenced_ttl_days=referenced_ttl_days,
    )
    removed: list[Path] = []
    for path in candidates:
        if len(removed) >= max(0, int(limit)):
            break
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_root):
            continue
        resolved.unlink(missing_ok=True)
        removed.append(resolved)
    return removed


def remove_empty_run_dirs(root: Path) -> list[Path]:
    """Delete directories left behind after their screenshots were pruned.

    Retention removed the images but not the per-run folders, leaving 436
    empty directories inside the runtime capture root.  Only directories are
    removed, only when they contain nothing at all, and never the root itself.

    ``os.walk`` with ``topdown=False`` is used on purpose: constructing a full
    ``rglob`` list over the capture root was slow enough that the pruning pass
    was killed by the shell timeout before it could report anything.  Walking
    bottom-up also means a parent that only held now-empty children is removed
    in the same pass.
    """
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        return []
    removed: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(resolved_root, topdown=False):
        path = Path(dirpath)
        if path == resolved_root:
            continue
        if dirnames or filenames:
            continue
        try:
            path.rmdir()
        except OSError:
            continue
        removed.append(path)
    return removed
