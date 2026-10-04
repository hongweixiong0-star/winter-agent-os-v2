"""The single source of truth for where Winter Agent OS V2 keeps its data.

Why this module exists
----------------------
The same three facts used to be re-typed by hand in dozens of files:

* which checkout is the *canonical* one (the main repository, not a worktree),
* where that checkout's mutable data lives (``dataset/``, ``learning/``, ...),
* which interpreter runs it (``.venv``).

By 2026-10-04 that had produced 81 literal ``E:\\无尽冬日智能体`` strings across 67
files -- 2 of them in production code, 79 in ``tools/`` scripts.  A path spelled out
80 times is 80 places to forget during a migration, so the literal now appears exactly
once, here, and everything else derives from this module.

The one subtlety that makes this work
-------------------------------------
``config/`` is a directory **junction** into the main repository for the pinned
production worktree (``...\\winter-prod-pinned\\无尽冬日智能体\\config`` ->
``E:\\无尽冬日智能体\\config``).  :func:`Path.resolve` follows that junction, so
``__file__`` here reports the *main repository* when production imports this module,
and the calling worktree when a plain branch imports it.  That is why
:data:`MAIN_REPO` needs no hardcoded answer for the production case, and why
:data:`DATA_ROOT` still points at the shared 27 GB corpus from inside a worktree.

``MAIN_REPO`` versus ``WINTER_AGENT_DATA_ROOT`` -- do not confuse them
---------------------------------------------------------------------
``tools/launch_pinned_production.py`` exports ``WINTER_AGENT_DATA_ROOT`` and sets it to
the *repository* that owns the data directories.  This module's :data:`DATA_ROOT` is
that repository's ``dataset/`` directory, as the migration plan defines it.  So
:data:`DATA_HOME` is the counterpart of ``WINTER_AGENT_DATA_ROOT``, and :data:`DATA_ROOT`
is one level below it.  Both spellings are supported below so an operator can relocate
the corpus without editing code.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "ENV_MAIN_REPO",
    "ENV_DATA_HOME",
    "MAIN_REPO",
    "DATA_HOME",
    "DATA_ROOT",
    "LOG_ROOT",
    "OUT_ROOT",
    "KNOWLEDGE_ROOT",
    "CONFIG_ROOT",
    "VENV",
    "VENV_PYTHON",
    "VENV_PYTHONW",
    "describe",
    "as_dict",
]

#: Point at a different clone of the project (env override for :data:`MAIN_REPO`).
ENV_MAIN_REPO = "WINTER_MAIN_REPO"

#: The name the production launcher already uses for "the repository that owns the
#: data directories".  Honoured so the launcher's ``os.environ`` export is authoritative.
ENV_DATA_HOME = "WINTER_AGENT_DATA_ROOT"

#: The canonical checkout.  Spelled once, on purpose -- see the module docstring.
#: Overridable via :data:`ENV_MAIN_REPO` so no future migration has to edit code again.
_DEFAULT_MAIN_REPO = Path("E:/无尽冬日智能体")


def _looks_like_checkout(candidate: Path) -> bool:
    """True when *candidate* is the root of this project rather than any directory."""
    return (candidate / "winter_agent_v2").is_dir() and (candidate / "tools").is_dir()


def _is_main_checkout(candidate: Path) -> bool:
    """A main checkout keeps ``.git`` as a directory; a linked worktree keeps it as a file.

    This is the discriminator that separates "the canonical repository" from "one of the
    seven worktrees", and it needs no path comparison to work.
    """
    return (candidate / ".git").is_dir()


def _self_repo() -> Path:
    """The checkout this file resolves into, following the ``config/`` junction."""
    return Path(__file__).resolve().parent.parent


def _pick_main_repo() -> Path:
    override = os.environ.get(ENV_MAIN_REPO, "").strip()
    if override:
        return Path(override).expanduser().resolve()

    here = _self_repo()
    if _is_main_checkout(here):
        # Running from the main checkout itself, or from the pinned production worktree
        # whose ``config/`` junction lands here.
        return here

    # A plain branch worktree: its ``config/`` is a real copy, so ``_self_repo()`` is the
    # worktree.  Data still belongs to the canonical checkout.
    if _looks_like_checkout(_DEFAULT_MAIN_REPO):
        return _DEFAULT_MAIN_REPO.resolve()
    return here


MAIN_REPO: Path = _pick_main_repo()


def _pick_data_home() -> Path:
    override = os.environ.get(ENV_DATA_HOME, "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    return MAIN_REPO


#: The repository that owns ``dataset/``, ``learning/``, ``knowledge/`` and ``config/``.
DATA_HOME: Path = _pick_data_home()

#: The screenshot / template corpus.  Defined by the migration plan as
#: ``<main repo>/dataset``.
DATA_ROOT: Path = DATA_HOME / "dataset"

#: Production logs and episodes live under ``learning/``.
LOG_ROOT: Path = DATA_HOME / "learning"

#: Scratch output that is not part of the corpus.
OUT_ROOT: Path = DATA_HOME / "out"

#: Durable game/capability knowledge.
KNOWLEDGE_ROOT: Path = DATA_HOME / "knowledge"

#: Machine-readable configuration, including this package.
CONFIG_ROOT: Path = DATA_HOME / "config"

#: The interpreter every project script is documented to run in.  Always taken from the
#: canonical checkout: worktrees never carry their own ``.venv``.
VENV: Path = MAIN_REPO / ".venv"
VENV_PYTHON: Path = VENV / "Scripts" / "python.exe"
VENV_PYTHONW: Path = VENV / "Scripts" / "pythonw.exe"


def as_dict() -> dict[str, str]:
    """Every resolved root, for logging and for the migration's own verification."""
    return {
        "MAIN_REPO": str(MAIN_REPO),
        "DATA_HOME": str(DATA_HOME),
        "DATA_ROOT": str(DATA_ROOT),
        "LOG_ROOT": str(LOG_ROOT),
        "OUT_ROOT": str(OUT_ROOT),
        "KNOWLEDGE_ROOT": str(KNOWLEDGE_ROOT),
        "CONFIG_ROOT": str(CONFIG_ROOT),
        "VENV": str(VENV),
    }


def describe() -> str:
    """One line per root, with an existence mark -- reads like an acceptance record."""
    lines = []
    for name, value in as_dict().items():
        mark = "ok " if Path(value).exists() else "MISSING"
        lines.append(f"{mark} {name:<14} {value}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - operator convenience
    print(describe())
