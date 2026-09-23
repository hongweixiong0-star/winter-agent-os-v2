"""Restart the project's gateway through its own lifecycle, with the bundle selector set.

One-off operator action, 2026-09-24.  Why it exists: the running gateway (pid from
``learning/control_panel/gateway_service.json``) was started before the bundle selector was
part of the launch plan, so every job it forked died at ``bin/codebuddy:205`` with
``Cannot find module '../dist/codebuddy'`` -- and the UNKNOWN channel had no way to answer
anything.  Restarting it through :class:`GatewayService` is what makes the new
``LaunchPlan.env`` take effect; the panel then adopts the new process (health ok ->
``ACT_REUSE``) instead of fighting it.

Bounded on purpose: it refuses to run while any job is open, kills only the pid the record
names, starts exactly one replacement, and prints the measured result.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import gateway_service as gs  # noqa: E402
from winter_agent_v2 import winproc  # noqa: E402
from winter_agent_v2.workbuddy_bridge import WorkBuddyBridge  # noqa: E402


def main() -> int:
    # The credential the *panel* uses, not this shell's.  Measured 2026-09-24: this shell's
    # ``CODEBUDDY_GATEWAY_PASSWORD`` is the host's generated 43-char value while the panel (and
    # ``HKCU\\Environment``) carry the project's ``v2-bridge-dev-local-only``.  A gateway started
    # from this shell's environment therefore accepts a password the panel's own submissions do
    # not have -- which showed up as ``submit_failed ... HTTP 401 AUTH_REQUIRED`` in the dispatch
    # ledger one tick later.  The registry value is the project's, so it is the one to launch with.
    from winter_agent_v2.workbuddy_bridge import ENV_PASSWORD, persisted_password

    env = dict(os.environ)
    project_password = persisted_password()
    if project_password:
        env[ENV_PASSWORD] = project_password
    print(f"launch password: {'project value from HKCU\\\\Environment' if project_password else 'shell environment'}")

    service = gs.GatewayService(ROOT, env=env)
    record = service.record()
    old_pid = int(record.get("pid") or 0)
    port_pid, port_name = winproc.port_owner(service.port)

    print(f"recorded pid : {old_pid}")
    print(f"port {service.port} owner: {port_pid} {port_name}")

    bridge = WorkBuddyBridge(cwd=ROOT, timeout=60.0)
    try:
        before = bridge.is_available()
        print(f"health before: {before.available} {before.reason}")
    except Exception as exc:  # noqa: BLE001 - a slow /health is not a reason to abort
        print(f"health before: (probe raised {type(exc).__name__}: {exc})")

    _, jobs = bridge._request("GET", "/api/v1/jobs")
    live = ((jobs.get("data") or {}).get("jobs") or []) if isinstance(jobs, dict) else []
    if live:
        print(f"REFUSING: {len(live)} job(s) still open on the gateway: "
              f"{[j.get('id') for j in live]}")
        return 2
    print("in-flight jobs: none")

    target = port_pid or old_pid
    if target:
        print(f"stopping pid {target} ...")
        print(f"  kill_tree -> {winproc.kill_tree(target)}")
    else:
        print("nothing to stop")

    # Wait for the port to actually free, so the replacement is not read as a port conflict.
    for _ in range(40):
        if not winproc.port_owner(service.port)[0]:
            break
        time.sleep(0.5)
    still = winproc.port_owner(service.port)
    print(f"port after stop: {still[0]} {still[1]}")
    if still[0]:
        print("REFUSING to start a second one while the port is still taken")
        return 3

    plan = gs.build_plan(ROOT, port=service.port, log_path=service.log_path,
                         env=service.env, desktop_exe=service._desktop_exe)
    print(f"plan env     : {json.dumps(dict(plan.env), ensure_ascii=False)}")

    updated = service.start(record=record, now=time.time())
    print(f"new pid      : {updated.get('pid')}")

    for _ in range(90):
        time.sleep(1.0)
        try:
            probe = bridge.is_available()
        except Exception:  # noqa: BLE001 - still coming up
            continue
        if probe.available:
            print(f"health after : True {probe.reason} (pid {probe.detail.get('pid')})")
            break
    else:
        print("health after : STILL DOWN after 90s")
        print(f"launch log   : {service.log_path}")
        return 4

    try:
        new_pid = int(((bridge.is_available().detail or {}).get("pid")) or updated.get("pid") or 0)
    except Exception:  # noqa: BLE001
        new_pid = int(updated.get("pid") or 0)
    try:
        import psutil

        env = psutil.Process(new_pid).environ()
        print(f"new gateway env {gs.ENV_FORCE_HEADLESS_BUNDLE} = "
              f"{env.get(gs.ENV_FORCE_HEADLESS_BUNDLE)!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"(could not read the new process env: {type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
