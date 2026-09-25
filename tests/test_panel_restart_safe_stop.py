from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import panel_restart  # noqa: E402


def test_panel_safe_stop_ignores_workers_owned_by_other_processes(monkeypatch):
    calls: list[int | None] = []

    def workers(pid=None):
        calls.append(pid)
        if pid is None:
            return ["unrelated process mentioning run_live.py"]
        return []

    monkeypatch.setattr(panel_restart, "current_worker", workers)

    assert panel_restart.panel_workers([16588]) == []
    assert calls == [16588]


def test_panel_safe_stop_still_sees_its_own_worker(monkeypatch):
    monkeypatch.setattr(
        panel_restart, "current_worker",
        lambda pid=None: [f"{pid + 1}|{pid}|run_live.py"] if pid is not None else [],
    )

    assert panel_restart.panel_workers([16588]) == ["16589|16588|run_live.py"]
