"""§14.5: the console must say who owns the machine, and let the operator change it.

Why this file exists, stated as the measurement that produced it (2026-10-06): the operator
asked 「manual模式，控制台怎么没看见显示和切换按钮」 and the answer was not "the button is
hidden" but **"there is no consumer"** -- ``winter_agent_v2.mode_state`` shipped with
``console_fields()`` and a complete CLI, and not one module under ``tools/`` imported it.
A data source without a reader is the same shape as a rule that exists only in a prompt:
correct, and inert.

So these tests are written against the two halves that failed separately:

* the **painting** half -- the row prints what the one source says, including the §9
  disagreement line, and an unreadable record prints 未读取 instead of raising;
* the **wiring** half -- the widgets are really built, and ``mode_state`` is really imported,
  so "the source exists" cannot be mistaken again for "the console shows it".

The painting tests use a stub rather than a full window because the row is a pure function of
one dict; the build test uses real Tk, because the failure being guarded against was a
*widget that was never constructed*, which no stub can detect.
"""

from __future__ import annotations

import unittest
import unittest.mock

from tools import control_panel as module
from winter_agent_v2 import mode_state


class _Var:
    """The one ``StringVar`` behaviour these methods use: remember what was set."""

    def __init__(self, value: str = "") -> None:
        self.value = str(value)

    def set(self, value: object) -> None:
        self.value = str(value)

    def get(self) -> str:
        return self.value


class _StubPanel:
    """Enough of ``ControlPanel`` to exercise the ownership row -- no window, no threads."""

    def __init__(self) -> None:
        # Derived from the panel's own table, so this stub cannot keep working after a key
        # is added there and silently stop matching the real window.
        self.values = {key: _Var(value) for key, value in module.status_defaults().items()}
        self.appended: list[str] = []
        self.root = None

    # Bound to the real methods in each test, so what runs is the shipped code rather than
    # a copy of it that could drift.
    def _refresh_mode_bar(self) -> None:
        module.ControlPanel._refresh_mode_bar(self)

    def _switch_to_manual(self) -> None:
        module.ControlPanel._switch_to_manual(self)

    def _switch_to_auto(self) -> None:
        module.ControlPanel._switch_to_auto(self)

    def _append(self, message: str) -> None:
        self.appended.append(message)


def _fields(**overrides: str) -> dict[str, str]:
    base = {
        "当前模式": mode_state.MODE_AUTO,
        "机器状态": "系统运行中",
        "切换发起方": "WORKBUDDY",
        "切换理由": "（未登记）",
        "已持续": "1 小时",
        "预计剩余": "（未登记预计时长）",
        "回切条件": "无需回切：当前已是 Auto",
        "循环存活": "RUNNING（面板进程 1 存活）",
    }
    base.update(overrides)
    return base


class OwnershipRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = _StubPanel()
        self._patch = unittest.mock.patch.object(
            mode_state, "console_fields", return_value=_fields())
        self._patch.start()
        self.addCleanup(self._patch.stop)

    # -- the failure that made this row necessary -----------------------------------------

    def test_the_panel_actually_imports_the_mode_source(self) -> None:
        """The regression itself: a source with no consumer.  Guarded at the import."""
        self.assertIs(module.mode_state, mode_state)
        for name in ("_build_mode_bar", "_refresh_mode_bar",
                     "_switch_to_manual", "_switch_to_auto"):
            self.assertTrue(hasattr(module.ControlPanel, name), name)

    def test_the_status_table_carries_the_ownership_keys(self) -> None:
        """Handler tests build stubs from this table; a missing key desyncs them silently."""
        defaults = module.status_defaults()
        self.assertIn("mode_owner", defaults)
        self.assertIn("mode_owner_detail", defaults)

    # -- painting -------------------------------------------------------------------------

    def test_manual_names_workbuddy_and_the_return_criteria(self) -> None:
        mode_state.console_fields.return_value = _fields(
            当前模式=mode_state.MODE_MANUAL,
            机器状态="WorkBuddy 开发中",
            切换理由="补 §14.5 控制台接线",
            回切条件="面板顶部有模式格+切换按钮",
        )
        self.panel._refresh_mode_bar()

        self.assertIn(mode_state.MODE_MANUAL, self.panel.values["mode_owner"].get())
        self.assertIn("WorkBuddy 开发中", self.panel.values["mode_owner"].get())
        self.assertIn("回切条件：面板顶部有模式格+切换按钮",
                      self.panel.values["mode_owner_detail"].get())

    def test_auto_with_the_loop_down_names_the_disagreement(self) -> None:
        """§9: 'mode is Auto' and 'Auto is running' are two facts; the row must say both."""
        mode_state.console_fields.return_value = _fields(
            机器状态="系统未运行（AUTO 已停）",
            循环存活="STOPPED（面板 pid 文件不存在）",
            不一致="模式是 Auto 但 AUTO 并未运行。",
        )
        self.panel._refresh_mode_bar()

        headline = self.panel.values["mode_owner"].get()
        self.assertIn(mode_state.MODE_AUTO, headline)
        # The old lie was printing 系统运行中 whenever the mode was AUTO.  The headline
        # carries the mode and the elapsed time; the liveness lives in the detail line,
        # where it can disagree out loud.
        self.assertNotIn("系统运行中", headline)
        detail = self.panel.values["mode_owner_detail"].get()
        self.assertIn("机器状态：系统未运行（AUTO 已停）", detail)
        self.assertIn("不一致", detail)

    def test_auto_with_the_loop_up_reports_running_and_no_disagreement(self) -> None:
        self.panel._refresh_mode_bar()

        detail = self.panel.values["mode_owner_detail"].get()
        self.assertIn("机器状态：系统运行中", detail)
        self.assertNotIn("不一致", detail)

    def test_an_unreadable_record_shows_unread_instead_of_raising(self) -> None:
        """A display must never take the page down -- and must never look like a healthy AUTO."""
        mode_state.console_fields.side_effect = ValueError("bad json")
        self.panel._refresh_mode_bar()

        self.assertEqual(module.PENDING, self.panel.values["mode_owner"].get())
        self.assertNotIn(mode_state.MODE_AUTO, self.panel.values["mode_owner_detail"].get())

    # -- switching ------------------------------------------------------------------------

    def _patch_dialogs(self, *, reason="接线", minutes=30.0, criteria="面板能切换"):
        # Answered in the order the row asks: 理由 → 预计分钟 → 完成判据.  An ordered queue
        # rather than a prompt-to-answer map, because the second askstring is only
        # distinguishable by position.
        asked: list[str] = []
        strings = iter([reason, criteria])
        floats = iter([minutes])

        def askstring(title, prompt, **_kwargs):
            asked.append(prompt)
            return next(strings)

        def askfloat(title, prompt, **_kwargs):
            asked.append(prompt)
            return next(floats)

        self._dialogs = unittest.mock.patch.object(module, "simpledialog")
        stub = self._dialogs.start()
        self.addCleanup(self._dialogs.stop)
        stub.askstring.side_effect = askstring
        stub.askfloat.side_effect = askfloat
        return asked  # a list, so the caller can count what was asked

    def test_switching_to_manual_records_the_users_reason_and_minutes(self) -> None:
        asked = self._patch_dialogs()
        calls = []

        def fake_switch(to, **kwargs):
            calls.append((to, kwargs))
            return None

        with unittest.mock.patch.object(mode_state, "switch", side_effect=fake_switch):
            self.panel._switch_to_manual()

        self.assertEqual(1, len(calls))
        to, kwargs = calls[0]
        self.assertEqual(mode_state.MODE_MANUAL, to)
        self.assertEqual(mode_state.BY_USER, kwargs["initiator"])
        self.assertEqual("接线", kwargs["reason"])
        self.assertEqual(30.0 * 60.0, kwargs["expected_seconds"])
        self.assertEqual("面板能切换", kwargs["completion_criteria"])
        # The three §5 prompts are asked, not assumed -- an unregistered reason produces a
        # decision point later that nobody can argue with.
        self.assertEqual(3, len(asked))

    def test_cancelling_the_prompt_switches_nothing(self) -> None:
        self._patch_dialogs(reason=None)
        with unittest.mock.patch.object(mode_state, "switch") as switch:
            self.panel._switch_to_manual()
        switch.assert_not_called()
        self.assertEqual([], self.panel.appended)

    def test_a_refusal_is_shown_and_never_claimed_as_switched(self) -> None:
        """§7's wrap-up gate belongs to ``mode_state``; this button must only report it."""
        self._patch_dialogs(reason=None)  # unused: Auto needs no prompts
        errors = []
        with unittest.mock.patch.object(
            mode_state, "switch",
            side_effect=mode_state.ModeRefused("收尾未完成：committed, repinned"),
        ):
            with unittest.mock.patch.object(module, "messagebox") as box:
                box.showerror.side_effect = lambda title, message, **_k: errors.append(
                    (title, message))
                self.panel._switch_to_auto()

        self.assertEqual(1, len(errors))
        self.assertIn("收尾未完成", errors[0][1])
        # The window must not narrate a handover that did not happen.
        self.assertEqual([], self.panel.appended)

    def test_handing_back_says_the_loop_is_not_started_by_it(self) -> None:
        with unittest.mock.patch.object(mode_state, "switch", return_value=None):
            self.panel._switch_to_auto()

        joined = " ".join(self.panel.appended)
        self.assertIn("已交还 Auto", joined)
        # §7 owns the mode, not the process: 「交还了」 reading as 「在跑了」 is the §9 lie again.
        self.assertIn("不拉起循环", joined)


class ModeBarBuildTests(unittest.TestCase):
    """The half a stub cannot catch: the widgets really exist on the real window."""

    def setUp(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tkinter unavailable: {exc}")
        self.root = None
        try:
            self.root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - no display
            raise unittest.SkipTest(f"no display: {exc}")
        self.addCleanup(self.root.destroy)

    def test_the_bar_builds_the_two_switch_buttons(self) -> None:
        from tkinter import ttk

        panel = _StubPanel()
        shell = ttk.Frame(self.root)
        panel.root = self.root

        with unittest.mock.patch.object(mode_state, "console_fields",
                                        return_value=_fields()):
            module.ControlPanel._build_mode_bar(panel, shell)

        # The row is drawn, and it is not blank before the first refresh: it is painted from
        # the real source at build time rather than waiting for a tick that may never come.
        self.assertIn(mode_state.MODE_AUTO, panel.values["mode_owner"].get())

        buttons = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    buttons.append(str(child.cget("text")))
                walk(child)

        walk(shell)
        self.assertIn("我要用机器（切 Manual）", buttons)
        self.assertIn("交还机器（切 Auto）", buttons)


if __name__ == "__main__":
    unittest.main()
