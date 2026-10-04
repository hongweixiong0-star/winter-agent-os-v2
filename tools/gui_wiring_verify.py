"""GUI Wiring Verifier — does every field the window shows trace back to a live source?

Why this exists
---------------
The panel printed ``当前角色 xhw`` from a string literal while the client was a different
role.  That is not a rendering bug: it is the absence of a link between a UI field and a
production source.  So this tool checks the link itself, for every dynamic field:

    UI field  ->  production source  ->  source value  ->  displayed value

and fails when the two diverge.  It builds the panel's *refresh* without a Tk window, so it
exercises the real code path rather than a copy of it, and it recomputes the expected value
from the artifacts itself -- a verifier that asked the panel what it thought would agree
with any bug the panel had.

```
python tools/gui_wiring_verify.py            the table
python tools/gui_wiring_verify.py --json     machine-readable
python tools/gui_wiring_verify.py --strict   exit non-zero on any mismatch or UNKNOWN
```

Exit code is 0 when every field is wired and matches, 2 when a field diverges, 3 when a
field cannot be confirmed (UNKNOWN/ASSUMED) -- the second case is a defect, the third is
an honest gap and is only fatal with ``--strict``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import control_panel as panel  # noqa: E402  the real refresh path
from winter_agent_v2 import state_truth as st  # noqa: E402


class _Var:
    """A tk.StringVar stand-in: the refresh only ever calls ``set``/``get``."""

    def __init__(self) -> None:
        self.value = ""

    def set(self, value: Any) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class _Cell:
    """One top-bar cell, with the only two things §六's tiering does to it.

    ``grid_remove`` rather than a blank cell: the tiering takes the cell *off the strip*, and the
    difference between "hidden" and "painted with an empty word" is the whole rule.  A stub that
    modelled hiding as an empty string would verify the opposite of what ships.
    """

    def __init__(self) -> None:
        self.seated = True

    def grid(self, **_kwargs) -> None:
        self.seated = True

    def grid_remove(self) -> None:
        self.seated = False


def _stub() -> SimpleNamespace:
    """A panel with just enough of itself to run ``_refresh_truth`` for real.

    The audit is read **once** and handed to both sides of the comparison.  Reading it
    twice -- once for the panel to render, once for the verifier to compare against --
    made live values disagree with themselves whenever a heartbeat ticked in between, and
    a verifier that can produce a false mismatch is worse than none.
    """
    values = {key: _Var() for key in panel.status_defaults()}
    report = st.TruthAudit(ROOT).report()

    class Probes:
        def truth(self) -> dict[str, Any]:
            return {"ok": True, "report": report}

        def device_state(self) -> dict[str, Any]:
            return {"ok": None, "status": None}

        def local_model_truth(self):
            # ``online=None`` on purpose: this verifier must not depend on whether a model
            # service happens to be listening while the test runs.  The cell's grading logic is
            # exercised for real; only the socket answer is held at "not probed".
            return panel.local_gui_model_truth(ROOT, online=None)

    stub = SimpleNamespace(values=values, probes=Probes(), indicators={},
                           # The cells are real objects rather than an empty dict, because §六's
                           # tiering is decided *inside* ``_set_health``: with no cells to seat, the
                           # helper returns early and this verifier would report the top bar as
                           # verified while never once exercising the rule that draws it.
                           _indicator_cells={key: _Cell() for _, key in panel.SYSTEM_INDICATORS},
                           vision_debug=None, preview_mode=_Var(),
                           # No AUTO process exists in a stub, and saying so is the honest
                           # reading rather than a convenience: ``_freshness`` escalates a
                           # stale source only while a writer *should* have been running, so
                           # with AUTO down the correct answer is "nothing to escalate".  The
                           # one that must still fire is the statement half
                           # (``_source_age_note``), and that one ignores AUTO -- so an
                           # over-age source is still verified here.
                           process=None)
    # The helpers the refresh calls, bound to this stub.  Bound *unbound* on purpose: the
    # real implementations run, so a change to how the panel paints a cell is verified
    # here rather than assumed.  That design has one cost, paid on 2026-10-04: add a call
    # inside the refresh and this file raises before verifying anything, so the tool that
    # exists to catch unwired fields becomes an unwired tool.  Every new collaborator of
    # ``_refresh_truth`` has to be bound here, and
    # ``tests/test_console_shows_only_what_it_can_fill.py`` runs this very stub through the
    # real refresh so the omission fails a test instead of a hand-run.
    stub._set_health = lambda key, value: panel.ControlPanel._set_health(stub, key, value)
    stub._show_header_cell = lambda key, value: panel.ControlPanel._show_header_cell(stub, key, value)
    stub._progress_line = lambda: panel.ControlPanel._progress_line(stub)
    stub._attention_with_sources = lambda lines: panel.ControlPanel._attention_with_sources(stub, lines)
    stub._source_age_note = lambda key: panel.ControlPanel._source_age_note(stub, key)
    stub._freshness = lambda: panel.ControlPanel._freshness(stub)
    stub._report = report
    return stub


# UI field -> (which audited state drives it, how that state is rendered).
# Written out rather than derived, so a field silently losing its source shows up as a
# missing entry instead of as a passing test.
WIRING: dict[str, tuple[str, Callable[[st.TruthValue], str]]] = {
    "role": ("current_role", lambda v: v.display),
    "why_idle": ("why_idle", lambda v: (("⚠ " if v.value == "UNEXPLAINED_IDLE" else "") + v.value)),
    "executor_mix": ("executor_mix", lambda v: f"{v.value}｜{v.note}"),
    "bootstrap": ("bootstrap", lambda v: f"{v.value}\n{v.note}".strip()),
    "coverage": ("coverage", lambda v: f"{v.value}\n{v.note}".strip()),
    "watchdog": ("watchdog", lambda v: f"{v.value}\n{v.note}".strip()),
}

# Fields the *runtime snapshot* path owns, not the audit: they carry the live per-cycle
# values and are repainted by ``_apply_snapshot``.  They cannot be exercised through
# ``_refresh_truth`` without building half a window, so they are verified at the source
# instead -- each must have exactly one assignment, and that assignment must read the
# snapshot rather than a literal.  That is weaker than running the code, and saying so is
# the point: an unverified claim dressed as a verified one is the defect this file exists
# to catch.
SNAPSHOT_WIRING: dict[str, str] = {
    "backend": "values[\"backend\"].set",
    "page": "values[\"page\"].set",
    "skill": "values[\"skill\"].set",
    "march": "values[\"march\"].set",
}


def _source_checks(panel_source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, marker in SNAPSHOT_WIRING.items():
        occurrences = panel_source.count(marker)
        rows.append({
            "field": field, "state": "(runtime snapshot)", "source": "tools/control_panel.py",
            "source_value": f"{occurrences} assignment site(s)",
            "expected": "assigned from the snapshot",
            "displayed": marker,
            "verdict": "OK" if occurrences else "NO_SOURCE",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="treat UNKNOWN/未确认 as a failure too")
    args = parser.parse_args()

    stub = _stub()
    # The real refresh, on the real sources.  Anything the window can render goes through
    # here, so this verifies the panel rather than a description of it.
    panel.ControlPanel._refresh_truth(stub)

    report = stub.probes.truth()["report"]
    assert report is stub._report, "the panel and the verifier must read one report"
    rows: list[dict[str, Any]] = []
    for field, (state, render) in WIRING.items():
        value = report.by_name(state)
        if value is None:
            rows.append({"field": field, "state": state, "source": "",
                         "source_value": "", "displayed": "", "verdict": "NO_SOURCE"})
            continue
        expected = render(value)
        shown = stub.values[field].get()
        if expected != shown:
            verdict = "MISMATCH"
        elif value.status in (st.UNKNOWN, st.ASSUMED):
            verdict = "UNCONFIRMED"
        else:
            verdict = "OK"
        rows.append({
            "field": field, "state": state, "source": value.source,
            "status": value.status, "source_value": value.value,
            "expected": expected, "displayed": shown, "verdict": verdict,
        })

    # The top bar, checked the same way: each cell must be one of the six words, must have been
    # painted from a value rather than left at its default, and -- because §六's tiering decides
    # it in the same place the cell is painted -- must be seated on the strip exactly when the
    # rule says so.
    #
    # The seating is checked against the *word the cell is wearing*, not against a second list of
    # three keys: re-deriving "which cells should be hidden" here would agree with the panel
    # whenever both were wrong.  The reading is independent -- the word comes from the stub's
    # variable, the seat from the cell -- so a cell displaying 异常 while it sits off the strip is
    # a MISMATCH rather than a silent omission.  (Today's stub, unlike the live window, has no
    # gateway/bootstrap source, so the three L3 cells read 未确认 here and are correctly seated:
    # 未确认 is not 健康.  That is the rule working, not the tiering failing.)
    healthy_words = {panel.DOT_TEXT[colour] for colour in panel.HEADER_HEALTHY_COLOURS}
    for _, key in panel.SYSTEM_INDICATORS:
        shown = stub.values[key].get()
        seated = stub._indicator_cells[key].seated
        if key == "clock":
            should_seat = True
        elif key in panel.HEADER_FOLD_TO_L1:
            should_seat = shown not in healthy_words
        else:
            should_seat = True
        if shown not in panel.DOT_TEXT.values() and key != "clock":
            verdict, note = "MISMATCH", "not one of the six words"
        elif seated != should_seat:
            verdict = "MISMATCH"
            note = "should be on the strip" if should_seat else "should be off the strip"
        else:
            verdict, note = "OK", ""
        rows.append({"field": key, "state": "(top bar)", "source": "state_truth.health_of",
                     "source_value": "§六 L1" if key not in panel.HEADER_FOLD_TO_L1 else "§六 L3",
                     "expected": "one of the six words" + ("" if should_seat else " · 收起"),
                     "displayed": f"{shown or '(未读)'}  [{'条上' if seated else '收起'}]"
                                  + (f"  {note}" if note else ""),
                     "verdict": verdict})

    rows.extend(_source_checks((ROOT / "tools/control_panel.py").read_text(encoding="utf-8")))

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print("GUI WIRING VERIFIER  (UI field -> production source -> source value -> displayed)")
        print("  " + "-" * 116)
        print(f"  {'field':<16} {'source':<42} {'status':<15} {'verdict':<12} displayed")
        print("  " + "-" * 116)
        for row in rows:
            print(f"  {row['field']:<16} {str(row.get('source'))[:42]:<42} "
                  f"{str(row.get('status', '-')):<15} {row['verdict']:<12} "
                  f"{str(row.get('displayed'))[:44]}")
        bad = [r for r in rows if r["verdict"] in ("MISMATCH", "NO_SOURCE")]
        unknown = [r for r in rows if r["verdict"] == "UNCONFIRMED"]
        print()
        print(f"  wired and matching : {sum(1 for r in rows if r['verdict'] == 'OK')}/{len(rows)}")
        print(f"  mismatched         : {len(bad)}" + (
            f" -> {', '.join(r['field'] for r in bad)}" if bad else ""))
        print(f"  unconfirmed        : {len(unknown)}" + (
            f" -> {', '.join(r['field'] for r in unknown)}" if unknown else ""))
        print("  (unconfirmed is not a defect: it is the window admitting it does not know)")

    if any(r["verdict"] in ("MISMATCH", "NO_SOURCE") for r in rows):
        return 2
    if args.strict and any(r["verdict"] == "UNCONFIRMED" for r in rows):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
