"""Measure what the information tiers actually do to the pages that have them.

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


class _IdlePump:
    """A pump stand-in that cannot consume anything -- the point of the class is a *non*-action.

    ``_narrate_pump`` asks the pump two questions: what it has consumed (``state``) and whether its
    clock is alive (``alive``).  A real ``QueuePump()`` answers the first correctly and the second
    with ``False``, and the narration's very next move on a dead clock is ``self.pump.revive()`` --
    which calls ``start()`` and spawns a daemon thread that would consume the **real** production
    queue and write ``pump.json``, from inside a measurement.  So the harness may not use a real pump
    here, however convenient: measuring the fold rules must not become a second consumer.

    ``alive()`` therefore reports ``True``.  That is an assumption this harness makes and states,
    not a reading -- and it is the assumption under which the narration does nothing but read.
    """

    def state(self) -> dict:
        return {}

    def alive(self) -> bool:
        return True

    def revive(self) -> bool:  # pragma: no cover - unreachable while ``alive`` is True
        raise AssertionError("measuring must never revive a real pump")


class _HeaderStrip:
    """A stub panel that owns a **real** nine-cell strip, so the width is Tk's own measurement.

    The stub exists because ``_set_health`` / ``_show_header_cell`` reach for ``self.values``,
    ``self.indicators`` and ``self._indicator_cells``; everything else they touch is the real
    methods, bound here rather than re-implemented, because a re-implementation would measure this
    script instead of the window.
    """

    def __init__(self, panel, tk_root, strip) -> None:
        self.values = {key: tk.StringVar(value=value)
                       for key, value in panel.status_defaults().items()}
        self.indicators: dict = {}
        self._indicator_cells: dict = {}
        for i, (label, key) in enumerate(panel.SYSTEM_INDICATORS):
            cell = ttk.Frame(strip, style="Card.TFrame")
            cell.grid(row=0, column=i, padx=6, sticky="w")
            ttk.Label(cell, text=label, style="Muted.TLabel",
                      background=panel.PANEL).pack(anchor="w")
            mark = tk.Label(cell, textvariable=self.values[key], background=panel.PANEL,
                            fg=panel.MUTED)
            mark.pack(anchor="w")
            self.indicators[key] = mark
            self._indicator_cells[key] = cell
            if key in panel.HEADER_FOLD_TO_L1:
                cell.grid_remove()
        for name in ("_set_health", "_show_header_cell"):
            setattr(self, name, types.MethodType(getattr(panel.ControlPanel, name), self))


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
            # Both are *instance* attributes: ``__getattr__`` below rebuilds missing names from the
            # class, and neither ``pump`` nor ``_pump_prev`` exists on ``ControlPanel``, so the
            # narration died on ``AttributeError: pump`` and took the whole measurement with it.
            # ``_IdlePump`` rather than the real ``QueuePump`` -- see its docstring; a real one would
            # have been revived into consuming the production queue.
            self.pump = _IdlePump()
            self._pump_prev: dict = {}
            # Read-only soak artifacts, built the way the real panel builds them.  No device: the
            # harness owns no ADB connection, and ``PanelProbes`` starts no thread until ``start()``
            # is called, so this reads and nothing else.
            self.probes = panel.PanelProbes(ROOT, device=None)

        def _save_panel_state(self, *a, **k):
            raise AssertionError("measuring must not persist anything")

        def _save_policy_state(self, *a, **k):
            raise AssertionError("measuring must not persist anything")

        def _render_preview(self, *a, **k):
            pass

        def _check_control_plane_reload(self, *a, **k):
            # A no-op, and this is the sharpest of the three suppressions here, because the real
            # method does not merely read -- it *writes shared, cross-process state*.  On a clean
            # tree it clears the live reload marker; on a dirty tree it writes one asking the
            # running window to restart itself, then may call ``_start_control_plane_reload``.
            # This measurement runs on a dirty tree *by definition* -- it is measuring edits that
            # are not committed yet -- so building a real ``control_plane_probe`` here would have
            # had a measuring script ask the production panel to restart.  Nothing about measuring
            # a fold rule needs that marker touched, so the harness answers "nothing to say" and
            # leaves the cell as declared.
            return

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

    # 总览 is a multi-column grid, so the page is as tall as its tallest column -- and a fold that
    # shortens one column need not shorten the page.  Measured on the fold's *own container* and on
    # its *immediate parent*, because "the page height did not move" on its own leaves the claim
    # untestable: the honest sentence has to name which frame got shorter.
    print(f"\n[2b] 实时画面 folds away whose height")
    pv = h._folds["preview"]
    owner = pv.outer.master
    cell = pv.outer.grid_info() or pv.outer.pack_info()
    where = (f"grid row={cell.get('row')} column={cell.get('column')}"
             if pv.outer.winfo_manager() == "grid" else f"pack {cell.get('side')}")
    readings = {}
    for state in (True, False):
        pv.expanded = state
        pv.paint()
        tk_root.update_idletasks()
        readings[state] = (int(pv.outer.winfo_reqheight()), int(owner.winfo_reqheight()),
                           page_height())
    pv.expanded = declared_state["preview"]
    pv.paint()
    tk_root.update_idletasks()
    assert page_height() == as_declared, "state was not restored before the next measurement"
    open_self, open_owner, open_page = readings[True]
    shut_self, shut_owner, shut_page = readings[False]
    print(f"    the block sits at            : {where}")
    print(f"    the block itself             : {open_self:>5} px open -> {shut_self:>5} px folded"
          f"  ({shut_self - open_self:+d})")
    print(f"    its parent (one column)      : {open_owner:>5} px open -> {shut_owner:>5} px folded"
          f"  ({shut_owner - open_owner:+d})")
    print(f"    the whole page               : {open_page:>5} px open -> {shut_page:>5} px folded"
          f"  ({shut_page - open_page:+d})")
    # Why the page loses 15 px and not 368: a grid row is as tall as its tallest cell, so shortening
    # the centre column only pays back whatever the centre used to exceed its neighbours by.  Printed
    # with its numbers so the sentence in the report is arithmetic the reader can redo, not a story.
    if owner.winfo_manager() == "grid":
        seat = owner.grid_info()
        others = "  ".join(
            f"col{child.grid_info().get('column')}={int(child.winfo_reqheight())}px"
            for child in page.winfo_children()
            if child.winfo_manager() == "grid" and child is not owner
            and child.grid_info().get("row") == seat.get("row"))
        print(f"    the column sits at           : grid row={seat.get('row')}"
              f" column={seat.get('column')}")
        print(f"    the other cells in that row  : {others or '(none)'}"
              f"   <- the row is their max, so the tallest cell binds")

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

    # The same question for the three rules added with the 能力 / 自动开发 pages, because a rule that
    # fires on steady-state data is the wolf-cry this whole mechanism exists to avoid.  The pages are
    # built and ``_narrate_pump`` is run, so ``_closure_card`` is the real one the window would have
    # -- a reading taken with an empty card would prove nothing about the breakpoint rule.
    real._capabilities()
    real._auto_development()
    real._narrate_pump()
    real._sync_folds()
    print(f"    -- and the three new opening rules, on real data --")
    for key in ("cap_runtime", "dev_loop", "dev_wb", "dev_failures"):
        fold = real._folds[key]
        print(f"    {fold.level}  {key:<14} open={str(fold.expanded):<5} {fold.badge.get()}")

    # The 系统 page, measured the same way.  It is the page §六 leaves with a single L1 *row* and
    # no L1 fold at all, which is the shape most likely to open as a column of shut bars -- so the
    # number that matters here is how much of the page is still readable before any click.
    print(f"\n[7] 系统 page, folded with the same primitive")
    h._system()
    tk_root.update_idletasks()
    sys_tab = h.tabs.winfo_children()[-1]
    sys_keys = ("sys_decision", "runtime_watchdog", "arbitration", "header_evidence", "sys_logs")

    def sys_height() -> int:
        tk_root.update_idletasks()
        return int(sys_tab.winfo_reqheight())

    for key in sys_keys:
        fold = h._folds[key]
        rule = "has a rule" if fold.escalate is not None else "INERT (declared, see the reason)"
        print(f"    {fold.level}  {key:<18} {fold.title:<26} open={str(fold.expanded):<5} {rule}")
    print(f"    --   (no fold)           当前角色 / 角色Session                "
          f"<- permanent L1, the page's scope")
    sys_declared = sys_height()
    sys_state = {key: h._folds[key].expanded for key in sys_keys}
    for key in sys_keys:
        h._folds[key].expanded = True
        h._folds[key].paint()
    sys_open = sys_height()
    for key in sys_keys:
        h._folds[key].expanded = sys_state[key]
        h._folds[key].paint()
    assert sys_height() == sys_declared, "state was not restored"
    print(f"    folds as declared : {sys_declared:>5} px")
    print(f"    every fold open   : {sys_open:>5} px")
    print(f"    the tiers hide    : {sys_open - sys_declared:>5} px"
          f"  ({100 * (sys_open - sys_declared) / max(sys_open, 1):.0f}% of the all-open page)")

    print(f"\n[8] §六's counter threshold really opens the watchdog block")
    # The live values on this machine are ``unexpected_worker_exits = 22`` and
    # ``watchdog_restart_count = 28``, both cumulative.  The first case below is the one that
    # matters: a big historical count with no growth must NOT hold the block open, or the
    # threshold would be measuring the machine's history rather than the present.
    h._watchdog_value = None
    h._exits_baseline, h._unexpected_exits = 22, 22
    h._restart_baseline, h._restart_count = 28, 28
    h._sync_folds()
    steady = (h._folds["runtime_watchdog"].expanded, h._folds["runtime_watchdog"].badge.get())
    print(f"    the real cumulative values, no growth -> expanded={steady[0]}  badge={steady[1]!r}")
    h._unexpected_exits = 23
    h._sync_folds()
    exit_case = (h._folds["runtime_watchdog"].expanded, h._folds["runtime_watchdog"].badge.get())
    print(f"    one more unexpected exit (22 -> 23)  -> expanded={exit_case[0]}  badge={exit_case[1]!r}")
    h._unexpected_exits = 22
    h._restart_count = 30
    h._sync_folds()
    grew = (h._folds["runtime_watchdog"].expanded, h._folds["runtime_watchdog"].badge.get())
    print(f"    restarts grew 28 -> 30               -> expanded={grew[0]}  badge={grew[1]!r}")
    h._restart_count = 28
    h._sync_folds()
    healed = (h._folds["runtime_watchdog"].expanded, h._folds["runtime_watchdog"].badge.get())
    print(f"    back to 22 exits / 28 restarts       -> expanded={healed[0]}  badge={healed[1]!r}"
          f"   (the alarm closed itself)")

    # The two remaining block-structured pages, measured the same way and with the same caveat as
    # 总览: ``_tab(..., scroll=True)`` hands back the scroll area's inner frame, so the page height
    # has to be read off the canvas's child rather than off the notebook tab.
    print(f"\n[9] 能力 / 自动开发, folded with the same primitive")
    for page_name, builder, keys in (
        ("能力", "_capabilities", ("cap_catalog", "cap_registry", "cap_runtime")),
        ("自动开发", "_auto_development",
         ("dev_loop", "dev_wb", "dev_pump", "dev_queue", "dev_failures", "dev_jobs")),
    ):
        getattr(h, builder)()
        tk_root.update_idletasks()
        tab_frame = h.tabs.winfo_children()[-1]
        canvas = next(child for child in tab_frame.winfo_children()
                      if child.winfo_class() == "Canvas")
        body = canvas.winfo_children()[0]

        def height() -> int:
            tk_root.update_idletasks()
            return int(body.winfo_reqheight())

        print(f"    -- {page_name} --")
        for key in keys:
            fold = h._folds[key]
            rule = "has a rule" if fold.escalate is not None else "INERT (declared, see the reason)"
            print(f"       {fold.level}  {key:<14} {fold.title:<28} open={str(fold.expanded):<5} {rule}")
        as_declared = height()
        state = {key: h._folds[key].expanded for key in keys}
        for key in keys:
            h._folds[key].expanded = True
            h._folds[key].paint()
        all_open = height()
        for key in keys:
            h._folds[key].expanded = state[key]
            h._folds[key].paint()
        assert height() == as_declared, f"{page_name}: state was not restored"
        print(f"       folds as declared : {as_declared:>5} px")
        print(f"       every fold open   : {all_open:>5} px")
        print(f"       the tiers hide    : {all_open - as_declared:>5} px"
              f"  ({100 * (all_open - as_declared) / max(all_open, 1):.0f}% of the all-open page)")

    print(f"\n[10] the two new opening rules, on their own exclusions")
    h._closure_card = None
    h._sync_folds()
    print(f"    no closure card at all            -> dev_loop open={h._folds['dev_loop'].expanded}"
          f"  badge={h._folds['dev_loop'].badge.get()!r}")
    h._closure_card = {"ok": False, "reason": "台账里还没有一轮"}
    h._sync_folds()
    print(f"    a loop that never ran             -> dev_loop open={h._folds['dev_loop'].expanded}"
          f"  badge={h._folds['dev_loop'].badge.get()!r}")
    h._closure_card = {"ok": True, "breakpoint": ""}
    h._sync_folds()
    print(f"    a clean PASS                      -> dev_loop open={h._folds['dev_loop'].expanded}"
          f"  badge={h._folds['dev_loop'].badge.get()!r}")
    h._closure_card = {"ok": True, "breakpoint": "VERSION_ACTIVE：等待真机校准"}
    h._sync_folds()
    print(f"    a real breakpoint                 -> dev_loop open={h._folds['dev_loop'].expanded}"
          f"  badge={h._folds['dev_loop'].badge.get()!r}")

    # The three pages the rollout had not reached when this script was first written.  Measured as an
    # A/B **inside one run** rather than against a "before" remembered from the previous run: a stale
    # baseline is an instrument that lies in the flattering direction, which is exactly §59.  "Every
    # fold on this page forced open" *is* the before-picture -- the page as it would be drawn if §六
    # had never been applied -- and it is obtained from the same widgets, in the same process.
    #
    # Built on ``h`` rather than ``real``: the data files these three read are resolved through the
    # module-level ROOT whatever harness is used, so the *content* is identical either way, while
    # ``h``'s ``_save_panel_state`` raises -- which makes it a tripwire if any path on the way
    # turns out to write.  That is the check §58 says to make rather than assume.
    print(f"\n[11] 策略 / 目标 / 活动：同一运行内的 A/B（全开 = 没做过分层的那个页面）")

    def body_of(tab_frame):
        """The frame whose height is the page: a scroll tab's canvas child, else the tab itself."""
        canvas = next((child for child in tab_frame.winfo_children()
                       if child.winfo_class() == "Canvas"), None)
        return canvas.winfo_children()[0] if canvas is not None else tab_frame

    for name, builder in (("策略", "_strategy"), ("目标", "_goals"), ("活动", "_event_goal")):
        known = set(h._folds)
        getattr(h, builder)()
        tk_root.update_idletasks()
        tab_frame = h.tabs.winfo_children()[-1]
        body = body_of(tab_frame)
        # Which folds belong to this page, attributed by construction order rather than typed out:
        # a hard-coded list would keep measuring the page it was written for.
        own = sorted(set(h._folds) - known)
        declared = {key: h._folds[key].expanded for key in own}
        for key in own:
            h._folds[key].expanded = True
            h._folds[key].paint()
        tk_root.update_idletasks()
        opened = int(body.winfo_reqheight())
        for key, state in declared.items():
            h._folds[key].expanded = state
            h._folds[key].paint()
        tk_root.update_idletasks()
        shut = int(body.winfo_reqheight())
        if own:
            note = (f"省 {opened - shut:>4} px（{100 * (opened - shut) / max(opened, 1):.0f}%）"
                    f"  {len(own)} 个折叠 {own}")
        else:
            note = "没有折叠（§六: 靠列序，不靠折叠）"
        print(f"    {name:<4} body {opened:>5} px 全开 -> {shut:>5} px 按声明   {note}")
        # Where the height actually is, in the state the operator receives.  Only the tall pages get
        # a breakdown: on 目标 the number is already small enough to act on, and the point there is
        # that its height is not the problem.
        if shut > 500:
            for index, child in enumerate(body.winfo_children()):
                height = child.winfo_reqheight()
                label = ""
                if child.winfo_class() == "TFrame":
                    labels = [grand.cget("text") for grand in child.winfo_children()
                              if grand.winfo_class() == "TLabel" and grand.cget("text")]
                    label = (labels[0] if labels else "")[:26]
                print(f"         [{index}] {child.winfo_class():<9} {height:>5} px  {label}")

    # The 目标 table is the one page whose tiers are honoured by **column order** rather than by
    # folds, and an order is exactly the kind of change that goes wrong silently: ``values=(...)``
    # is matched to ``columns=(...)`` by index, so a column moved in one place and not the other
    # relabels every cell while still looking like a working table.  Print a real row against its
    # own headings, in order -- the pairing is the assertion.
    print(f"\n[12] 目标: the headings and a real row, in the same order")
    h._goals()
    tk_root.update_idletasks()
    board = h.goal_board
    columns = list(board.cget("columns"))
    headings = [board.heading(key)["text"] for key in columns]
    tiers = [tier for key, _t, _w, tier in panel.GOAL_COLUMNS]
    print(f"    widths  : {[board.column(key)['width'] for key in columns]}")
    print(f"    tiers   : {tiers}")
    print(f"    headings: {headings}")
    rows = board.get_children()
    if rows:
        print(f"    row[0]  : {list(board.item(rows[0], 'values'))}")
    else:
        print(f"    row[0]  : (the board is empty on this data root)")
    seen: list[str] = []
    for tier in tiers:
        if not seen or seen[-1] != tier:
            seen.append(tier)
    print(f"    -> L1 columns come first, tiers read {seen}, "
          f"and no tier is split by a later one: {len(seen) == len(set(seen))}")

    # §六's 「游戏实时画面 L2 → 卡住时 L1」.  The interesting state is the one that stays shut: a
    # window that has not read the episode stream yet must not open a 300 px screenshot on the
    # strength of not knowing anything.
    print(f"\n[13] 实时画面的开启判据，四种输入")
    for label, rows in (
        ("no reading yet（没跑过 _progress_line）", None),
        ("no rows at all（episode 里没有行）", []),
        ("actions failing（verifier 未通过）", [{"verifier_ok": False, "goal_progress": False}]),
        ("a clean pass（动作成功且目标前进）", [{"verifier_ok": True, "goal_progress": True}]),
        ("actions ok, goal flat（§六 的「卡住」）", [{"verifier_ok": True, "goal_progress": False}]),
    ):
        if rows is None:
            h.__dict__.pop("_progress_stalled", None)
        else:
            h._progress_stalled = panel.progress_is_stalled(rows)
        h._sync_folds()
        fold = h._folds["preview"]
        print(f"    {label:<34} -> open={str(fold.expanded):<5} {panel.progress_is_stalled(rows) if rows is not None else 'no reading'}"
              f"  badge={fold.badge.get()!r}")

    # 顶栏: nine cells, three of them L3 by §六.  Measured on a *real* strip made of the panel's own
    # SYSTEM_INDICATORS, so the width is Tk's own answer and not a sum of font estimates.  The real
    # readings that decide which state is "today" come from _probe_header_cells.py (measured
    # 2026-10-04: WorkBuddy 正常 / 预载 等待 / 本地模型 正常 -- all three healthy, so today is the
    # 6-cell strip).
    print(f"\n[14] 顶栏 9 格：§六 收起三格之后，条子有多宽")
    from winter_agent_v2.state_truth import CONFLICT, LIVE_OBSERVED, TruthValue

    strip = ttk.Frame(tk_root)
    strip.pack(anchor="w")
    stub = _HeaderStrip(panel, tk_root, strip)
    healthy = TruthValue(name="gateway_health", value="正常", status=LIVE_OBSERVED)
    sick = TruthValue(name="gateway_health", value="不可达", status=CONFLICT)

    def strip_width() -> int:
        tk_root.update_idletasks()
        return int(strip.winfo_reqwidth())

    for key in [k for _, k in panel.SYSTEM_INDICATORS]:
        stub._set_health(key, healthy)
    six = strip_width()
    still_seated = [k for k in panel.HEADER_FOLD_TO_L1 if stub._indicator_cells[k].grid_info()]
    for key in panel.HEADER_FOLD_TO_L1:
        stub._set_health(key, sick)
    nine = strip_width()
    print(f"    all nine healthy（今天真实取数）      : {six:>5} px"
          f"   L3 三格里还在条上的：{still_seated}（空 = 三格都收起了）")
    print(f"    the three not healthy              : {nine:>5} px"
          f"   多占 {nine - six} px（{100 * (nine - six) / max(nine, 1):.0f}%）")
    back = {k: stub._indicator_cells[k].grid_info().get("column")
            for k in panel.HEADER_FOLD_TO_L1}
    print(f"    收起后各自的列号（重排会骗人）        : {back}")
    print(f"    L1 六格任何读数下都在                : "
          f"{[k for k in panel.HEADER_ALWAYS if stub._indicator_cells[k].grid_info()] == list(panel.HEADER_ALWAYS)}")

    tk_root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
