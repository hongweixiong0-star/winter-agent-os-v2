"""What version of the code is this?  One canonical answer, computed before anything loads.

Two holes this closes, both named by the operator, both of which would have made every rung
above them compare nothing while looking like a pass.

**A. A count is not an identity, and a path is not content.**  The token used to be
``head[:12] + "+" + dirty_count``; then it became ``sha256(staged diff + unstaged diff +
untracked *manifest*)``.  The manifest listed untracked paths without their bytes, so editing
the contents of an untracked file produced the *same* version -- and an untracked file is
exactly how a development agent delivers a new template or knowledge file.  The fingerprint
now hashes the contents of the dirty paths that matter.

**B. The disk is not what is running.**  ``tools/run_live.py`` imports fifteen
``winter_agent_v2`` modules at module scope and only reads the revision inside ``main()``
(line 129), so its "revision" described the disk *after* the imports -- which is not the code
those imports loaded.  This module therefore offers a *frozen* process revision: capture it
first, then import the runtime.

Stdlib only, on purpose: :func:`freeze_process_revision` has to run before the runtime is
imported, so the thing that runs first must not drag the runtime in with it.
"""

from __future__ import annotations

import hashlib
import subprocess  # noqa: F401 - only for the TimeoutExpired type below
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import winproc

# --------------------------------------------------------------------- the path policy

#: Paths whose contents the runtime actually loads.  A version is the code and the rules the
#: *running* process consumes -- nothing else.
#:
#: The exclusion list is not tidiness.  Hashing the whole dirty tree would make the version
#: drift every time an episode was recorded, a screenshot was written or the control panel
#: logged a line -- so a version could never be observed twice, and "the same version ran"
#: would be unfalsifiable.  A version identity that changes when a log is appended is not an
#: identity.
VERSION_RELEVANT_PREFIXES: tuple[str, ...] = (
    "winter_agent_v2/",       # the runtime itself
    "config/",                # its configuration
    "knowledge/",             # the rules and mappings it reads
    "dataset/candidate/",     # templates and candidate assets it consumes
)

#: Runtime entry points and tools it drives.  Listed by name rather than by ``tools/`` as a
#: whole: the GUI is not part of what a live cycle loads, and including it would make every
#: window edit look like a new runtime version.
VERSION_RELEVANT_FILES: tuple[str, ...] = (
    "tools/run_live.py",
    "tools/preflight.py",
)

#: Pure run products.  Checked before the include lists, so a path can never be dragged in by
#: a prefix match it does not deserve.
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "learning/",              # episode stream, runtime snapshots, panel state and logs
    "evidence/",              # acceptance evidence
    "dataset/raw/",           # screenshots
    "dataset/truth_audit/",   # fixture frames
    "docs/",
    ".git/",
    ".workbuddy",
    "__pycache__/",
    "out_",
)

#: Files that live under an *included* prefix but are written by the running system rather
#: than by a developer.  Listed individually because their prefix cannot be excluded wholesale
#: -- ``config/`` holds real configuration alongside them.
#:
#: Measured 2026-09-18, and it cost a restart loop: the panel writes
#: ``config/control_panel_state.json`` on start-up to persist the operator's intent, so the
#: fingerprint changed the instant the window opened.  The window then compared its frozen
#: version with the disk, found them different, and concluded a control-plane file had changed
#: -- so it restarted itself, wrote the file again, and restarted again.  A file the system
#: writes about its own state is not a change to the system's code, and a version identity that
#: fires on it is a version identity that fires on nothing.
#:
#: Extended 2026-09-21 to the knowledge records the same loop writes, and the cost this time was
#: a whole capability, not a restart loop.
#:
#: ``capability_bootstrap`` is the *consumer* side of the escalation queue: whenever a research
#: job settles it folds the answer back into ``knowledge/preload/<CAPABILITY>.json`` and
#: regenerates ``knowledge/preload/INDEX.json`` (``KnowledgeStore.save`` / ``write_index``), and
#: the panel runs that pass on its own clock (``QueuePump.PRELOAD_EVERY = 20`` ticks).  Those
#: paths sit under ``knowledge/``, which the include list keeps because the runtime really does
#: load them -- so the panel's own bookkeeping made the tree dirty with a digest that changed
#: every time it ran, and ``repo_revision`` could never equal the ``after_version`` a job had
#: fingerprinted at the moment its development ended.
#:
#: The measured consequence: job 280d1659's validation cycle took the device lease, exited
#: ``EXIT_4`` in the version gate of ``run_live`` without touching the device, and released --
#: every 40 to 90 seconds for 6.5 hours, 54 attempts, one per AUTO cycle.  ``OPEN_TRAINING_PAGE``
#: could not be examined by any amount of real play, because the version it demanded was one the
#: running window itself kept invalidating.
#:
#: The distinction that decides membership here is the same one the ``config/`` entries rest on:
#: a knowledge record is a *product of the loop* (what we have learned so far, stamped with the
#: moment we learned it), while the hand-written rule files beside it (``knowledge/game/beasts``
#: and the rest of the tracked corpus) are *inputs a developer edits*.  Excluding the former does
#: not weaken the identity -- the code, the configuration and the rules are still fingerprinted
#: byte for byte, and ``test_version_fingerprint_content`` pins that a real content edit still
#: moves the token.
EXCLUDED_FILES: tuple[str, ...] = (
    "config/control_panel_state.json",
    "config/policy_state.json",
)

#: Directories under an *included* prefix that the running system populates itself.  The same
#: argument as :data:`EXCLUDED_FILES`, for a set of paths that grows at runtime and therefore
#: cannot be listed one by one.
#:
#: ``knowledge/preload/`` is the escalation queue's own durable memory: one record per capability,
#: created when a capability is first examined and rewritten every time an answer comes back.
#: A record that did not exist when the job started is not a change to the code under test.
#: Kept as a directory rather than a file list because the set of capabilities is 194 and open.
EXCLUDED_DIRECTORIES: tuple[str, ...] = (
    "knowledge/preload/",     # per-capability research records, written by capability_bootstrap
)


def is_version_relevant(relative: str) -> bool:
    """Would a change to this path change what the runtime loads?"""
    path = str(relative).replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    if not path:
        return False
    if any(part == "__pycache__" for part in path.split("/")):
        return False
    if path.endswith(".pyc"):
        return False
    if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if path in EXCLUDED_FILES:
        return False
    if any(path.startswith(prefix) for prefix in EXCLUDED_DIRECTORIES):
        return False
    if path in VERSION_RELEVANT_FILES:
        return True
    return any(path.startswith(prefix) for prefix in VERSION_RELEVANT_PREFIXES)


# --------------------------------------------------------------------- the revision


@dataclass(frozen=True)
class Revision:
    """One moment of the version-relevant tree."""

    head: str = ""
    dirty: int = 0
    digest: str = ""
    ok: bool = False
    #: The dirty paths the digest was computed over, sorted.  Kept for the same reason the
    #: launch plan keeps ``cli_source``: a fingerprint nobody can explain is a number.
    paths: tuple[str, ...] = ()

    @property
    def token(self) -> str:
        """The comparable form: a clean tree is its full commit; a dirty tree is commit + digest."""
        if not self.ok:
            return ""
        if not self.dirty:
            return self.head
        return f"{self.head}+{self.digest[:16]}"

    def as_episode_fields(self) -> dict[str, object]:
        """What an episode records, so a reader can reconstruct the comparison."""
        return {
            "repo_revision": self.token,
            "repo_head": self.head,
            "repo_dirty": self.dirty,
            "repo_digest": self.digest,
        }


def _run(argv: Sequence[str], cwd: Path, timeout: float) -> str:
    """One hidden git call, decoded as **UTF-8**.

    Not the OEM codepage ``winproc`` defaults to for console tools: git emits raw UTF-8 path
    bytes under ``-z``, and this tree has a directory whose name is Chinese.  Decoding those
    bytes as OEM would produce mojibake, the path would not resolve, and the file would be
    hashed as a deletion -- a wrong fingerprint that looks like a correct one.
    """
    try:
        result = winproc.run(["git", *argv], cwd=cwd, timeout=timeout, encoding="utf-8")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout or ""


def dirty_entries(root: Path, *, timeout: float = 30.0) -> list[tuple[str, str]]:
    """``(status, path)`` for every dirty entry git reports, NUL-separated so paths are safe.

    ``-z`` rather than line-splitting because this tree contains a directory with a space and
    a Chinese character in its name; a parser that splits on newlines would mangle it and
    silently drop the very paths the fingerprint is supposed to cover.
    """
    raw = _run(["status", "--porcelain", "-z"], root, timeout)
    if not raw:
        return []
    fields = raw.split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry or len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[:1] in ("R", "C") and index < len(fields):
            # A rename reports the new path in this field and the old one in the next.
            index += 1
        entries.append((status, path))
    return entries


def _hash_tree(root: Path, path: str) -> str:
    """A digest over a path's contents: a file's bytes, or every file under a directory."""
    target = root / path
    digest = hashlib.sha256()
    if not target.exists():
        # Deleted, or the odd git state where the entry outlives the file.  Recorded as a
        # marker rather than skipped: "this file was removed" is a change, and skipping it
        # would let a deletion join two different trees into one version.
        digest.update(b"DELETE")
        return digest.hexdigest()
    if target.is_file():
        digest.update(target.read_bytes())
        return digest.hexdigest()
    for child in sorted(target.rglob("*")):
        if not child.is_file() or "__pycache__" in child.parts:
            continue
        digest.update(child.relative_to(root).as_posix().encode("utf-8", "replace"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _could_be_relevant(relative: str) -> bool:
    """Is this path, or anything beneath it, version-relevant?

    Needed because git collapses an untracked *directory* into one entry: a fresh
    ``dataset/candidate/`` arrives as ``?? dataset/``, and asking :func:`is_version_relevant`
    about ``dataset/`` answers no -- so the relevant files inside it would never be looked at.
    This answers the question about the subtree instead, and lets the walk prune
    ``learning/``, ``evidence/`` and ``dataset/raw/`` without descending into them.
    """
    path = str(relative).replace("\\", "/").strip().rstrip("/")
    if not path:
        return True
    if is_version_relevant(path):
        return True
    prefix = path + "/"
    return any(known.startswith(prefix)
               for known in (*VERSION_RELEVANT_PREFIXES, *VERSION_RELEVANT_FILES))


def _expand(root: Path, path: str) -> list[str]:
    """The files an entry stands for: itself, or every file under it if it is a directory."""
    target = root / path
    if not target.is_dir():
        return [path]
    out: list[str] = []
    for child in sorted(target.rglob("*")):
        if not child.is_file() or "__pycache__" in child.parts:
            continue
        relative = child.relative_to(root).as_posix()
        if is_version_relevant(relative):
            out.append(relative)
    return out


def canonical_revision(root: Path | str, *, timeout: float = 30.0) -> Revision:
    """The version-relevant fingerprint of the working tree.

    Clean tree: the full commit sha -- a twelve-character prefix is a display convenience and
    not something to build an identity on.  Dirty tree: the commit plus a digest over the
    *contents* of every version-relevant dirty path, canonically sorted, including files that
    are untracked and files that were deleted.
    """
    base = Path(root)
    head = _run(["rev-parse", "HEAD"], base, timeout).strip()
    if not head:
        return Revision(ok=False)

    relevant: dict[str, str] = {}
    for status, path in dirty_entries(base, timeout=timeout):
        if not _could_be_relevant(path):
            continue
        for expanded in _expand(base, path):
            relevant[expanded] = status
    if not relevant:
        return Revision(head=head, dirty=0, ok=True)

    digest = hashlib.sha256()
    for path in sorted(relevant):
        digest.update(f"{relevant[path]} {path}".encode("utf-8", "replace"))
        digest.update(b"\0")
        digest.update(_hash_tree(base, path).encode())
        digest.update(b"\0")
    return Revision(head=head, dirty=len(relevant), digest=digest.hexdigest(), ok=True,
                    paths=tuple(sorted(relevant)))


# ----------------------------------------------------------- the frozen process revision

#: Captured once, before the runtime is imported, and never re-read.  ``None`` means this
#: process never froze one, which is a fact worth reporting rather than guessing around.
_FROZEN: Revision | None = None


def freeze_process_revision(root: Path | str, *, timeout: float = 30.0) -> Revision:
    """Capture the version this process is *about to load*, and freeze it.

    Called at the very top of a runtime entry point, before the ``winter_agent_v2`` imports.
    Everything downstream -- the episode, the activation comparison, the validation binding,
    the production-reuse check -- must compare *this*, because an episode written later that
    re-reads git only proves what is on the disk at that moment, not what this process loaded.

    Freezing is idempotent: a second call returns the first answer, so no later code path can
    quietly move the goalposts mid-process.
    """
    global _FROZEN
    if _FROZEN is None:
        _FROZEN = canonical_revision(root, timeout=timeout)
    return _FROZEN


def process_revision() -> Revision | None:
    """The revision this process froze, or ``None`` if it never did."""
    return _FROZEN


def process_revision_token() -> str:
    """The frozen token, or ``""`` -- never a fresh read of the disk."""
    return _FROZEN.token if _FROZEN is not None else ""


def reset_process_revision_for_tests() -> None:
    """Clear the freeze.  Named for tests so production code cannot call it by accident."""
    global _FROZEN
    _FROZEN = None


def startup_fence(root: Path | str, *, timeout: float = 30.0) -> tuple[bool, Revision, Revision]:
    """``(ok, frozen, current)`` -- has the tree moved since this process froze it?

    The freeze says which code the process *loaded*; this says the tree has not moved
    *since*.  Between the two lie the whole runtime import block and the verifier-mapping
    assertion, and during that window another agent's edit, a reload or a ``git checkout``
    would leave the process running a mixture -- whose episodes belong to no version at all.

    A failed fence is not an error to recover from mid-run: the honest answer is to produce
    nothing this cycle, because an episode written by a half-changed process would be evidence
    for whichever version a later reader assumed.  Keeping the comparison here rather than
    inline in the entry point means it can be exercised without running a live cycle.
    """
    frozen = process_revision() or freeze_process_revision(root, timeout=timeout)
    current = canonical_revision(root, timeout=timeout)
    return (bool(frozen.token) and frozen.token == current.token), frozen, current


__all__ = [
    "Revision", "VERSION_RELEVANT_PREFIXES", "VERSION_RELEVANT_FILES", "EXCLUDED_PREFIXES",
    "is_version_relevant", "dirty_entries", "canonical_revision",
    "freeze_process_revision", "process_revision", "process_revision_token",
    "reset_process_revision_for_tests", "startup_fence",
]
