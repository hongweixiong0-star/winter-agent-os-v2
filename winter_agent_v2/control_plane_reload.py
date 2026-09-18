"""The *control plane* has its own reload, and it is not the worker's.

Measured 2026-09-18: the repository was updated, the gateway fix was committed, and the running
window went on showing "WorkBuddy 异常" at the top.  Nothing was wrong with the fix -- the GUI
process had imported the old `gateway_service`/`workbuddy_bridge`/`control_panel` at start-up
and no code path ever told it that the files under it had changed.  A worker reload would not
have helped either: the stale code was in the *window*, not in a live cycle.

So the marker is different from the worker's on purpose:

    worker        RUNTIME_RELOAD_REQUIRED          the next run_live must import the new tree
    control plane CONTROL_PLANE_RELOAD_REQUIRED    this process must be replaced

They share ``ReloadSignal`` -- the same class, the same file format, the same pending/clear
semantics -- because a second reload *system* is exactly what the operator forbade.  What
differs is the subject and therefore the path it is written to, so the two can be pending
independently without either consuming the other's request.

What this module deliberately does not do: restart anything.  A process cannot replace itself
through its own imports, and the decision to restart needs gates this module has no business
knowing (a safe point, the device lease, the operator's intent).  It answers one question --
"is this process running code that is no longer on disk, in a file it actually imports?" -- and
the window acts on the answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .runtime_reload import ReloadSignal, ReloadRequest
from . import winproc

#: The marker kind.  Distinct from ``RUNTIME_RELOAD_REQUIRED`` so a reader can tell "the next
#: cycle will pick this up" from "somebody has to restart this window".
CONTROL_PLANE_KIND = "CONTROL_PLANE_RELOAD_REQUIRED"

#: Where the marker lives, beside the worker's own signal.
MARKER_NAME = "CONTROL_PLANE_RELOAD_REQUIRED.json"

#: The files whose staleness invalidates the *running window*, as opposed to the next cycle.
#:
#: Named explicitly rather than derived by walking imports: the point is to be inspectable.  A
#: reader asking "why is this window telling me to reload" should be able to read the list and
#: agree, and a list computed at runtime from a module graph would be correct and unarguable
#: with.  ``escalation_queue`` and ``device_lease`` are here because the window folds the ledger
#: and reads the lease in its own process; ``gateway_service`` and ``workbuddy_bridge`` because
#: they are what the top bar's gateway cell is computed from -- the measured symptom.
CONTROL_PLANE_PATHS: tuple[str, ...] = (
    "tools/control_panel.py",
    "winter_agent_v2/workbuddy_bridge.py",
    "winter_agent_v2/gateway_service.py",
    "winter_agent_v2/escalation_queue.py",
    "winter_agent_v2/device_lease.py",
    "winter_agent_v2/version_identity.py",
    "winter_agent_v2/state_truth.py",
)


def control_plane_path(root: Path | str) -> Path:
    """Where this window's reload marker lives."""
    return Path(root) / "learning" / MARKER_NAME


def control_plane_signal(root: Path | str) -> ReloadSignal:
    """The control plane's own signal -- same machinery, its own file."""
    return ReloadSignal(control_plane_path(root))


def touched_control_plane(changed: Iterable[str]) -> tuple[str, ...]:
    """Which of the changed paths require replacing the window rather than the next cycle."""
    wanted = {path.replace("\\", "/") for path in CONTROL_PLANE_PATHS}
    hits: list[str] = []
    for path in changed:
        normalised = str(path).replace("\\", "/").lstrip("./")
        if normalised in wanted:
            hits.append(normalised)
    return tuple(sorted(set(hits)))


def changed_paths_since(root: Path | str, loaded_head: str) -> tuple[str, ...]:
    """Paths that differ between the commit this process loaded and the working tree now.

    ``git diff --name-only <head>`` answers both halves at once: files committed *after* that
    commit, and files edited but not committed.  The measured symptom was the first case -- the
    gateway fix was committed and the window never noticed -- so a comparison of heads alone
    would have missed the dirty case and a dirty-path listing alone would have missed the
    commit.
    """
    if not loaded_head:
        return ()
    result = winproc.run(["git", "diff", "--name-only", loaded_head],
                         cwd=Path(root), timeout=30.0, encoding="utf-8")
    return tuple(line.strip() for line in (result.stdout or "").splitlines() if line.strip())


def needs_reload(loaded_version: str, on_disk_version: str, changed: Iterable[str]) -> bool:
    """Must this process be replaced?

    Three conditions, and all three matter:

    * the version must have moved -- equal versions mean nothing changed, whatever the caller
      thinks it saw;
    * a *control-plane* file must be among the changes -- a new knowledge file or a template
      changes the next cycle, not this window, and telling the operator to restart for one
      would train them to ignore the notice;
    * an empty ``loaded_version`` cannot be compared, so it answers no.  A window that never
      captured its own version cannot honestly claim to be stale -- it should say it does not
      know, which is what ``None`` is for in :func:`reload_reason`.
    """
    if not loaded_version or not on_disk_version:
        return False
    if loaded_version == on_disk_version:
        return False
    return bool(touched_control_plane(changed))


def reload_reason(loaded_version: str, on_disk_version: str,
                  changed: Iterable[str]) -> str:
    """A one-line answer for the window to print, or ``""`` when nothing is owed."""
    changed = tuple(changed)
    if not loaded_version:
        return "本进程未记录自身版本，无法判断是否需要重载"
    if not on_disk_version:
        return "读不到磁盘版本，无法判断是否需要重载"
    if loaded_version == on_disk_version:
        return ""
    hits = touched_control_plane(changed)
    if not hits:
        return ""
    return (f"{CONTROL_PLANE_KIND}：本进程加载的 {loaded_version[:12]} 已被 "
            f"{on_disk_version[:12]} 取代，涉及控制面 " + "、".join(hits))


def safe_to_reload(*, atomic_step_running: bool, lease_holder: str,
                   operator_intent: str, panel_owned: bool = True) -> tuple[bool, str]:
    """May the window be replaced *now*?

    Every one of these is a way an automatic restart could do damage, and each is a refusal
    rather than a warning:

    * an atomic gameplay step in flight -- restarting would cut a transaction in half, which is
      the same rule the device lease already enforces at a safe boundary;
    * a development-validation lease held -- the device belongs to an examination, and the
      window that would restart is the one holding it;
    * the operator said STOP or PAUSE -- their instruction outranks a reload, and a watchdog
      that overrides it is the failure mode the operator named explicitly;
    * a window that is not the owner -- a read-only second window must not restart the real one.

    Returns ``(ok, why)`` with the reason always populated, so the window can say what it is
    waiting for instead of silently doing nothing.
    """
    if operator_intent.upper() != "RUNNING":
        return False, f"操作员当前为 {operator_intent}，用户 STOP/PAUSE 优先于自动重载"
    if atomic_step_running:
        return False, "当前 atomic gameplay 尚未到安全边界，等这一步结束"
    if str(lease_holder or "").strip():
        return False, f"设备租约由 {lease_holder} 持有，等它归还后再重载"
    if not panel_owned:
        return False, "本窗口不是队列时钟的唯一持有者，不由它重启"
    return True, "已到安全点：无 atomic 步骤、无租约、操作员 RUNNING"


__all__ = [
    "CONTROL_PLANE_KIND", "CONTROL_PLANE_PATHS", "MARKER_NAME",
    "control_plane_path", "control_plane_signal", "touched_control_plane",
    "needs_reload", "reload_reason", "safe_to_reload", "ReloadSignal", "ReloadRequest",
]
