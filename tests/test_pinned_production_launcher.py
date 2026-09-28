"""The pinned GUI exports its shared data root to runtime evidence writers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import launch_pinned_production as launcher  # noqa: E402


def test_launcher_sets_shared_data_root_before_loading_control_panel(tmp_path, monkeypatch):
    data_root = tmp_path / "shared-data"
    data_root.mkdir()
    observed = {}
    monkeypatch.delenv("WINTER_AGENT_DATA_ROOT", raising=False)

    monkeypatch.setattr(launcher, "verify_pin", lambda _path: ("a" * 40, data_root))
    monkeypatch.setattr(launcher, "_startup_log", lambda _root: tmp_path / "startup.log")
    monkeypatch.setattr(launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(
        launcher.runpy,
        "run_path",
        lambda path, run_name: observed.update(
            data_root=launcher.os.environ.get("WINTER_AGENT_DATA_ROOT"),
            path=str(path),
            run_name=run_name,
        ),
    )

    assert launcher.main(["--manifest", str(tmp_path / "pin.json")]) == 0

    assert observed == {
        "data_root": str(data_root),
        "path": str(launcher.CODE_ROOT / "tools" / "control_panel.py"),
        "run_name": "__main__",
    }
