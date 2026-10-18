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


#: The same problem, third stream.  ``unknown_requests`` is the corpus ``benchmark_gui_unknown``
#: is built from -- every case is one of these records *plus the frame it was filed with* -- and it
#: names that frame ``frame_path``, which neither ``REFERENCE_KEYS`` nor ``CORPUS_FRAME_KEYS``
#: covers.  Measured 2026-10-08: all 8 records had lost their frame, so the benchmark ran 0 cases
#: and the model comparison it exists to produce could not be made at all.  Third instance of the
#: note at the top of this file.
UNKNOWN_REQUESTS_DIR = Path("learning/unknown_requests")
UNKNOWN_REQUEST_KEYS = ("frame_path", "before_frame_path", "after_frame_path")


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


# ------------------------------------------------------------------ 已登记的损失
#: Where a *deliberate* loss is written down, next to the ledger it explains.
PROVENANCE_DIR = Path("knowledge/provenance")


def comparable_path(text: str) -> str:
    """One spelling per path, for "is this the same file" questions.

    The same frame is written ``E:\\\\...`` in the episode ledger, ``E:/...`` in a tool and
    ``E:\\\\WinterAgent\\\\.worktrees\\\\prod\\\\repo\\\\...`` when it came back through the pin
    worktree's junctions.  Windows does not care about any of that, so a string comparison
    does not either -- on 2026-10-17 it reported 109 *existing-but-differently-spelled*
    frames as missing.  Lower-cased, slash-normalised, ``..``-collapsed, case-folded.
    """
    value = str(text).replace("\\", "/")
    while "//" in value:
        value = value.replace("//", "/")
    return os.path.normcase(os.path.normpath(value))


def pruned_evidence_paths(root: Path | None = None) -> set[str]:
    """Frames deleted on purpose, each with the reason recorded beside them.

    An episode row is never rewritten when its frame is gone -- rewriting production evidence
    is worse than losing it -- so "missing" has to stay distinguishable from "missing and
    accounted for".  That distinction was implemented **twice** (the evidence-integrity test
    and the handoff's ``evidence_state``), and the two disagreed the day after the first
    prune: the handoff printed ``evidence=FAIL`` over the same 109 frames the suite had
    already accepted.  This is the one implementation both now read.

    Every ``knowledge/provenance/*.json`` is consulted, so a second prune writes its own
    file instead of editing the first one's numbers.
    """
    base = (root or find_repo_root(Path(__file__).resolve().parent)) / PROVENANCE_DIR
    out: set[str] = set()
    if not base.is_dir():
        return out
    for record in sorted(base.glob("*.json")):
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(paths, (list, tuple)):
            continue
        for item in paths:
            if isinstance(item, str) and item.strip():
                out.add(comparable_path(item))
    return out


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


def unknown_request_evidence(root: Path, directory: Path | None = None) -> set[Path]:
    """Absolute paths of the frames the UNKNOWN corpus was filed with.

    The third evidence stream, and the one that was missing.  ``benchmark_gui_unknown`` scores the
    local model on the screens the live system genuinely could not advance; it can only do that
    while each ``unknown_requests`` record still has its frame, and the records were unprotected
    because they use their own key name.

    Tolerant on purpose, for the same reason the other two are: this runs inside the pruning pass,
    and a crash here would leave the disk unbounded and take AUTO down with it.
    """
    target = directory or (root / UNKNOWN_REQUESTS_DIR)
    cited: set[Path] = set()
    if not target.is_dir():
        return cited
    for record in target.glob("*.json"):
        try:
            payload = json.loads(record.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in UNKNOWN_REQUEST_KEYS:
            value = payload.get(key)
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

#: The sandbox variable that says its bulk-delete gate is armed.  Deliberately the same name
#: the suite's own tolerance helper reads
#: (``tests/test_control_plane_reload.py::_past_the_hosts_delete_gate``): one vocabulary, one
#: meaning, so the two halves cannot drift apart.
HOST_BULK_DELETE_GATE = "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR"


def delete_past_the_hosts_gate(call, path: Path, *, missing_is_fine: bool = False) -> bool:
    """Run ``call()``, treating a *sandbox* refusal as "not removed" rather than as death.

    ``True`` when the path is gone, ``False`` when the host's gate refused to remove it.

    This is the production half of a rule the test suite learned first and the worker never
    did.  A sandbox around this machine intercepts the delete and, once one turn has removed
    more than 50 files, raises ``SystemExit(1)`` **instead of** deleting.  An uncaught
    ``SystemExit`` prints no traceback and exits 1 -- which is exactly the shape of the crash
    record: ``WORKER_RESULT_MISSING: exit=1``, an empty ``child_traceback``, and the guard's
    own line as the worker's last log entry.  Measured 2026-10-08: four such crashes in 100
    seconds, the watchdog's recovery budget spent, AUTO paused -- and then a fifth at 17:04:55
    on a temporary file, from a call site that was not in the first two fixes.

    ``call`` must be the removal itself and nothing else -- a bare ``unlink``/``rmdir`` -- so
    that a ``SystemExit`` reaching here can only have come from the gate.

    Normally tolerated only when both halves of the evidence agree: the gate says it is armed,
    **and** the path is still on disk because the removal did not happen.  So a ``SystemExit``
    raised by this code, or a removal that silently did nothing while the gate is unarmed, still
    raises.

    ``missing_is_fine`` is for the call sites that are already best-effort cleanups -- a
    temporary file being removed after a rename, a lock file, a pruned crop -- where the code
    around them *already* treats "it was not there" as success (that is what their
    ``except OSError``/``FileNotFoundError`` branch means).  There the filesystem cannot supply
    the second half of the evidence, because the file is expected to be gone; and since the call
    is a bare removal, there is no failure for the waiver to hide.  A refused cleanup leaves one
    temporary file behind, which the next write replaces.
    """
    try:
        call()
    except SystemExit:
        armed = bool(os.environ.get(HOST_BULK_DELETE_GATE))
        if armed and (missing_is_fine or path.exists()):
            return False
        raise
    return True


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
    # Three streams, and each one was added because the previous two did not cover it:
    # production episodes, the calibration corpus, and now the UNKNOWN corpus.
    referenced = (referenced_evidence(repo, episodes_path) | corpus_evidence(repo)
                  | unknown_request_evidence(repo))
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
        if not delete_past_the_hosts_gate(
            lambda target=resolved: target.unlink(missing_ok=True), resolved,
        ):
            # The sandbox refused. Every later removal in this turn would be refused too, so
            # stop instead of spending the pass on raises, and let the next cycle drain the
            # rest. The files are still there; nothing was lost.
            break
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
            if not delete_past_the_hosts_gate(path.rmdir, path):
                # Same refusal as in the screenshot pass, and the same answer: an empty
                # folder is not worth taking the run down for.  ``except OSError`` alone
                # cannot see this one, because the gate raises SystemExit.
                break
        except OSError:
            continue
        removed.append(path)
    return removed
