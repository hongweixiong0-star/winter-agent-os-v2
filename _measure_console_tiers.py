"""Measure what the information tiers actually do to the 总览 page.

A throwaway measurement, not a test: the guard tests pin the *rules*, this prints the numbers so
the claim "the page asks for less of the screen" is a reading rather than a hope.

Run:  .venv/Scripts/python.exe _measure_console_tiers.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402


def load_panel():
    spec = importlib.util.spec_from_file_location("cp_measure", ROOT / "tools" / "control_panel.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def harness(panel, tk_root, tmp: Path):
    class _Harness:
        def __init__(self):
            self.root = tk_root
            self.tabs = ttk.Notebook(tk_root)
            self._tab_names = []
            self._tab_refreshers = {}
            self.values = {key: tk.StringVar(value=value)
                           for key, value in panel.status_defaults().items()}
            self.kpi = {}
            self.config = {"device": {"adb_path": "adb", "serial": "unused"}, "auto_execution": False}
            self.policy_enabled = {name: tk.BooleanVar(value=True)
                                   for name in panel.POLICY_CATEGORIES}
            self.task_enabled = {}
            self.preview_mode = tk.StringVar(value="原始画面")
            self.continuous = tk.BooleanVar(value=True)
            self.vision_debug = tk.BooleanVar(value=False)
            self.event_text = tk.StringVar(value="")
            self.policy_buttons = {}
            self.session = {}
            self.event_lines = []
            self.registry = panel.v2_registry()
            self.operator_intent = "RUNNING"
            self.startup_preflight = None
            self._other_instance = 0
            self.process = None
            self.runtime_store = panel.RuntimeSnapshotStore(tmp / "learning/runtime_snapshot.json")

        def _save_panel_state(self, *a, **k):
            raise AssertionError("measuring must not persist anything")

        def _save_policy_state(self, *a, **k):
            raise AssertionError("measuring must not persist anything")

        def _render_preview(self, *a, **k):
            pass

        def _schedule_preview_render(self, *a, **k):
            pass

        def _append(self, *a, **k):
            pass

        def __getattr__(self, name):
            import inspect
            raw = inspect.getattr_static(panel.ControlPanel, name)
            if isinstance(raw, (staticmethod, classmethod)):
                return getattr(panel.ControlPanel, name)
            attr = getattr(panel.ControlPanel, name)
            return types.MethodType(attr, self) if callable(attr) else attr

    return _Harness()


def main() -> int:
    panel = load_panel()
    tk_root = tk.Tk()
    tk_root.withdraw()
    # Outside the repository: the dev repo *is* the data root here, and a measurement that leaves
    # directories inside ``learning/`` pollutes every later repo-wide scan.
    tmp = Path(tempfile.mkdtemp(prefix="measure_tiers_"))

    h = harness(panel, tk_root, tmp)
    h._overview()
    tk_root.update_idletasks()

    # ``_tab(..., scroll=True)`` returns the *scroll area's inner frame*, which is a child of the
    # canvas rather than of the notebook tab -- so measuring the tab frame measures an empty
    # frame and returns the same number whatever the folds do.  Reach through the canvas.
    tab_frame = h.tabs.winfo_children()[0]
    canvas = next(child for child in tab_frame.winfo_children()
                  if child.winfo_class() == "Canvas")
    page = canvas.winfo_children()[0]

    def page_height() -> int:
        tk_root.update_idletasks()
        return int(page.winfo_reqheight())

    print("=" * 78)
    print("总览 · measured on a real Tk root, this window's own builders")
    print("=" * 78)

    print(f"\n[1] blocks declared, and whether they open themselves")
    for key, fold in h._folds.items():
        rule = "has a rule" if fold.escalate is not None else "INERT (declared, see the reason)"
        print(f"    {fold.level}  {key:<10} {fold.title:<18} "
              f"open={str(fold.expanded):<5} {rule}")
    print(f"    --   {'(no fold)':<10} 需不需要干预 / 需要关注 / 进度行 / 控制按钮"
          f"        <- permanent L1, cannot be folded")

    as_declared = page_height()

    print(f"\n[2] page height, as the operator receives it")
    print(f"    folds as declared            : {as_declared:>5} px")
    declared_state = {key: fold.expanded for key, fold in h._folds.items()}
    for fold in h._folds.values():
        fold.expanded = True
        fold.paint()
    all_open = page_height()
    print(f"    every fold forced open       : {all_open:>5} px")
    print(f"    the tiers hide               : {all_open - as_declared:>5} px"
          f"  ({100 * (all_open - as_declared) / max(all_open, 1):.0f}% of the all-open page)")
    # Put it back, or the readings below are taken on top of "everything open" and every number
    # after this point is wrong in the flattering direction.
    for key, fold in h._folds.items():
        fold.expanded = declared_state[key]
        fold.paint()
    assert page_height() == as_declared, "state was not restored before the next measurement"

    # The claim that matters: an abnormal block surfaces with no click.
    print(f"\n[3] an abnormal block opens itself (no click, no restart)")
    h._attention_kinds = {"WORKBUDDY_QUEUE_STUCK"}
    h._gateway_value = None
    h._sync_folds()
    tk_root.update_idletasks()
    wb = h._folds["workbuddy"]
    print(f"    WORKBUDDY_QUEUE_STUCK -> workbuddy expanded={wb.expanded}"
          f"  badge={wb.badge.get()!r}")
    after_alarm = page_height()
    print(f"    page height with the alarm showing: {after_alarm:>5} px")

    # ...and that closing it by hand does not hide the statement.
    h._toggle_fold("workbuddy")
    h._sync_folds()
    print(f"\n[4] operator shuts it by hand")
    print(f"    expanded={wb.expanded}   badge still reads {wb.badge.get()!r}")
    print(f"    -> folded is allowed; silent is not")

    # ...and that a rule which cannot run is not an all-clear.
    print(f"\n[5] a rule that cannot run is not an all-clear")
    h._folds["kpi"].escalate = lambda: (_ for _ in ()).throw(RuntimeError("predicate broke"))
    h._sync_folds()
    print(f"    kpi expanded={h._folds['kpi'].expanded}  badge={h._folds['kpi'].badge.get()!r}")

    # The one that matters, and the one v1 of this change got wrong: against the REAL data root,
    # with the real freshness table and the real truth audit, which blocks does the operator find
    # open before touching anything?
    print(f"\n[6] against the REAL data root, with AUTO assumed running")
    real = harness(panel, tk_root, ROOT)
    real.process = type("P", (), {"poll": lambda self: None})()
    real._overview()
    tk_root.update_idletasks()
    try:
        from winter_agent_v2.state_truth import TruthAudit

        report = TruthAudit(ROOT).report()
        real._attention_kinds = {str(a.get("kind") or "") for a in report.needs_attention()}
        real._gateway_value = report.by_name("gateway_health")
        real._watchdog_value = report.by_name("watchdog")
    except Exception as exc:  # noqa: BLE001 - a measurement must still print
        print(f"    (truth audit unavailable here: {type(exc).__name__}; "
              f"the source rules are still evaluated)")
        real._attention_kinds, real._gateway_value, real._watchdog_value = set(), None, None
    real._sync_folds()
    opened = 0
    for key, fold in real._folds.items():
        opened += 1 if fold.expanded else 0
        print(f"    {fold.level}  {key:<10} open={str(fold.expanded):<5} {fold.badge.get()}")
    print(f"    -> {opened} of {len(real._folds)} blocks open unasked; "
          f"{len(real._folds) - opened} folded")

    tk_root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
