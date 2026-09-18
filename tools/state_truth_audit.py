"""Truth Source Audit — is what we display what the client actually is?

Why this exists
---------------
The operator found a GUI cell reading ``current_role = xhw`` while the real client was a
different role.  The cause was a **string literal** in the panel, sitting next to another
literal that claimed the device was online unconditionally.  That is not a stale-cache
bug; it is a system property: any *displayed* state without a source can drift arbitrarily
far from the client and still look confident.

This command answers, for every key runtime state, the operator's five questions:

    value?  source?  confirmed when?  evidence?  which role/episode/version?  expired?

and exits non-zero if any state is being displayed from a literal or a default, because
that is the defect class this command exists for.

```
python tools/state_truth_audit.py              the whole table
python tools/state_truth_audit.py --stale      only what is not current
python tools/state_truth_audit.py --conflicts  only the disagreements, as STATE_CONFLICT
python tools/state_truth_audit.py --role       the role chain, which scopes everything
python tools/state_truth_audit.py --write      persist the report under learning/
python tools/state_truth_audit.py --json       machine-readable
```

Not to be confused with ``tools/truth_audit.py``, which recomputes project *statistics*
(episode success rates, failure rankings) into ``docs/CURRENT_TRUTH.md``.  That one asks
"how is the project doing"; this one asks "is this value currently true, and who says so".

Read-only: it writes nothing except with ``--write``, and it reads only artifacts other
parts of the system already maintain.  It owns no state, which is what makes it usable as
a cross-check rather than as another thing that can go stale.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import state_truth as audit  # noqa: E402
from winter_agent_v2.state_truth import STATUS_ZH, TruthAudit  # noqa: E402

REPORT_PATH = "learning/truth_source_audit/STATE_TRUTH.json"


def _status_cell(value: audit.TruthValue) -> str:
    mark = {"CONFLICT": "!", "STALE": "~", "UNKNOWN": "?", "ASSUMED": "X"}.get(value.status, " ")
    return f"{mark}{value.status:<15}"


def _table(values) -> list[str]:
    lines = [
        "TRUTH SOURCE AUDIT  (value? source? confirmed when? evidence? which role? expired?)",
        "  " + "-" * 118,
        f"  {'state':<20} {'status':<16} {'value':<30} {'source':<34} {'age':>8}",
        "  " + "-" * 118,
    ]
    for value in values:
        age = "-" if value.age_seconds is None else f"{value.age_seconds:.0f}s"
        lines.append(
            f"  {value.name:<20} {_status_cell(value)} {value.value[:30]:<30} "
            f"{value.source[:34]:<34} {age:>8}"
        )
        bits = []
        if value.role_id:
            bits.append(f"role={value.role_id}")
        if value.episode:
            bits.append(f"episode={value.episode}")
        if value.version:
            bits.append(f"version={value.version}")
        if value.verification:
            bits.append(f"verifier={value.verification}")
        if value.evidence:
            bits.append(f"evidence={value.evidence[0]}")
        if bits:
            lines.append(f"  {'':<20} {'':<16}  " + "  ".join(bits))
        if value.seen:
            lines.append(f"  {'':<20} {'':<16}  also seen: "
                         + ", ".join(f"{w}={v}" for w, v in value.seen))
        if value.note:
            lines.append(f"  {'':<20} {'':<16}  note: {value.note}")
    return lines


def _record_role(frame: str) -> int:
    """Read the role off a real frame and persist it -- the role chain's other half.

    Before this, the vision reader existed and was verified, and nothing wrote its answer
    anywhere, so the window had no choice but to print a literal.  The frame is required
    and is stored in the artifact: an identity with no frame behind it is exactly the
    defect that started this audit.

    The observation is dated by **the frame**, not by the moment of reading.  Stamping a
    two-day-old replay with ``now()`` would make an old observation look current, which is
    the same mistake in the opposite direction -- so a replay is labelled a replay and
    inherits the frame's own age.
    """
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.state_truth import ROLE_PROBE_DIR, record_role
    from winter_agent_v2.vision import SemanticWorldVision

    path = Path(frame)
    if not path.is_file():
        print(f"no such frame: {path}")
        return 1
    # Built exactly the way production builds it (same manifest, same OCR backend), so a
    # frame that reads correctly here reads correctly in the runtime.
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    vision = HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
        OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
    )
    identity = vision.read_role_identity(path)
    if identity is None:
        print("this frame is not the 领主档案 panel -- nothing was recorded")
        return 1

    import datetime as _dt

    captured = _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.timezone.utc)
    age = _dt.datetime.now(_dt.timezone.utc) - captured
    replay = age.total_seconds() > 600
    label = "REPLAY OF AN ARCHIVED FRAME" if replay else "LIVE READ"

    print(f"ROLE READ ({label})")
    print(f"  role_id     : {identity.role_id}")
    print(f"  role_name   : {identity.role_name}")
    print(f"  alliance_tag: {identity.alliance_tag}")
    print(f"  kingdom     : {identity.kingdom}")
    print(f"  power_text  : {identity.power_text}")
    print(f"  confidence  : {identity.confidence}")
    print(f"  frame       : {path.as_posix()}")
    print(f"  captured    : {captured.isoformat()}  ({age.total_seconds() / 3600:.1f}h ago)")
    if replay:
        print("  ⚠ this frame is not fresh: the identity is recorded with the frame's own")
        print("    age, so the audit will report PERSISTED/STALE rather than LIVE_OBSERVED.")
        print("    A fresh live read needs the avatar tap on the running device.")
    written = record_role(
        ROOT, identity, evidence=(path.as_posix(),), observed_at=captured,
        verification="VISION_READ_REPLAY" if replay else "VISION_READ",
    )
    print(f"  written     : {written}")
    print("\n  The window shows this with its date and status -- never as a bare name.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stale", action="store_true", help="only what is not current")
    parser.add_argument("--conflicts", action="store_true", help="only the disagreements")
    parser.add_argument("--role", action="store_true", help="the role chain only")
    parser.add_argument("--write", action="store_true", help="persist the report under learning/")
    parser.add_argument("--json", action="store_true", help="machine-readable on stdout")
    parser.add_argument("--record-role", metavar="FRAME_PNG", default="",
                        help="read the 领主档案 panel from a real frame and persist the identity")
    args = parser.parse_args()

    if args.record_role:
        return _record_role(args.record_role)

    report = TruthAudit(ROOT).report()

    if args.json:
        print(json.dumps(report.as_row(), ensure_ascii=False, indent=1))
    elif args.conflicts:
        print("STATE CONFLICTS (nobody may silently pick a winner)")
        if not report.conflicts:
            print("  none -- every source that answered, answered the same thing")
        for conflict in report.conflicts:
            print(f"  {conflict.describe()}")
    elif args.role:
        role = report.by_name("current_role")
        print("ROLE CHAIN (this scopes every other state)")
        if role is None:
            print("  (the audit returned no role row)")
        else:
            print(f"  value       : {role.value or audit.UNKNOWN}")
            print(f"  status      : {role.status}  ({STATUS_ZH.get(role.status, role.status)})")
            print(f"  source      : {role.source}")
            print(f"  observed_at : {role.observed_at or '-'}")
            print(f"  age         : "
                  f"{'-' if role.age_seconds is None else f'{role.age_seconds/3600:.1f}h'}")
            print(f"  role_id     : {role.role_id or '-'}")
            print(f"  verification: {role.verification or '-'}")
            for item in role.evidence:
                print(f"  evidence    : {item}")
            if role.note:
                print(f"  note        : {role.note}")
            unscoped = [v.name for v in report.values
                        if v.name != "current_role" and v.role_id != role.role_id]
            if unscoped:
                print(f"  not scoped to this role: {', '.join(unscoped)}")
    elif args.stale:
        print(report.line())
        for value in report.worst():
            print(f"  {value.name:<20} {value.status:<16} {value.display[:60]}")
            if value.note:
                print(f"  {'':<20} {value.note}")
    else:
        print(report.line())
        print()
        for line in _table(report.values):
            print(line)
        print()
        if report.conflicts:
            for conflict in report.conflicts:
                print(f"  {conflict.describe()}")
        else:
            print("  conflicts: none")

    if args.write:
        path = ROOT / REPORT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.as_row(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nwrote {path}")

    assumed = [v.name for v in report.values if v.status == audit.ASSUMED]
    if assumed:
        print(f"\nASSUMED states are a defect, not a state: {', '.join(assumed)}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
