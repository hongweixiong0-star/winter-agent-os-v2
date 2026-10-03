"""Gate: may this entity be implemented yet?

Winter Agent OS V2 keeps asking "why did we build this before knowing what it was".  The
knowledge to answer that is already in the tree -- ``provenance/`` records where each domain's
facts came from, ``conflicts.json`` records where sources disagree, ``strategy/`` records what
is worth doing, ``events/`` records what each activity is.  What was missing is the step that
reads them *before* code is written and says no.

This tool is that step.  It does not add a second knowledge store and it does not re-derive
any fact: it reads the existing assets and reports which of the charter's requirements the
entity already satisfies and which it does not.

    python tools/research_gate.py --event BEAR_HUNT
    python tools/research_gate.py --goal  CLEAR_INTEL --json

Verdicts, from ``knowledge/research/RESEARCH_CHARTER.json``:

    READY            every check has evidence; implementation may start
    NEEDS_RESEARCH   specific gaps; the report names each one
    BLOCKED_UNSAFE   a risk class is unhandled; implementation is refused

Read-only.  It never writes knowledge and never touches the device.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"

#: Risk classes the charter treats as blocking.  ``UNKNOWN_MECHANISM`` is deliberately absent:
#: it allows observation, only spending is blocked, so it is a note rather than a refusal.
BLOCKING_RISK_CLASSES = ("IRREVERSIBLE_SPEND", "ACCOUNT_SAFETY", "MISIDENTIFICATION")

#: Words that mark a knowledge file as still unresolved.  A file may legitimately contain these
#: about *other* things, so they are only reported when they land on the entity's own record.
UNRESOLVED = ("UNKNOWN", "PENDING", "TODO", "TBD")


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_json(directory: Path):
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        doc = _load(path)
        if doc is not None:
            yield path, doc


def _mentions(doc, *needles: str) -> bool:
    """Does this document name any of these, at any depth?

    Substring rather than exact key match: the tree names the same thing as ``BEAR_HUNT``,
    ``bear_hunt``, ``PARTICIPATE_BEAR`` and ``狩猎陷阱``, and a gate that only understood one
    spelling would report a fully documented entity as undocumented.
    """
    blob = json.dumps(doc, ensure_ascii=False).lower()
    return any(n.lower() in blob for n in needles if n)


class Report:
    def __init__(self, kind: str, name: str) -> None:
        self.kind = kind
        self.name = name
        self.checks: list[dict] = []

    def add(self, check_id: str, ok: bool, detail: str, *, blocking: bool = False) -> None:
        self.checks.append({"check": check_id, "ok": bool(ok), "detail": detail,
                            "blocking": bool(blocking) and not ok})

    @property
    def blocking_failures(self):
        return [c for c in self.checks if c["blocking"]]

    @property
    def gaps(self):
        return [c for c in self.checks if not c["ok"] and not c["blocking"]]

    @property
    def verdict(self) -> str:
        if self.blocking_failures:
            return "BLOCKED_UNSAFE"
        if self.gaps:
            return "NEEDS_RESEARCH"
        return "READY"

    def as_dict(self) -> dict:
        return {"entity": {"kind": self.kind, "name": self.name}, "verdict": self.verdict,
                "checks": self.checks,
                "blocking": [c["check"] for c in self.blocking_failures],
                "gaps": [c["check"] for c in self.gaps]}


# --------------------------------------------------------------------------- checks

def check_sources(report: Report, *needles: str) -> None:
    """Is there a recorded source for this domain at all?

    The file *name* counts as a match as well as its contents.  The tree names domain files
    after the domain -- ``intel_research_sources.json``, ``train_research_sources.json`` --
    while the goal ids carry a verb (``CLEAR_INTEL``, ``KEEP_TRAINING_PRODUCTIVE``).  Matching
    contents alone reported a fully sourced domain as unsourced.
    """
    hits = []
    for path, doc in _iter_json(KNOWLEDGE / "provenance"):
        if _mentions(doc, *needles) or _mentions({"f": path.stem}, *needles):
            hits.append(path.name)
    report.add(
        "SOURCE_RECORDED", bool(hits),
        "provenance: " + ", ".join(hits[:4]) if hits else
        "no provenance file names this entity; nothing records where its facts came from",
    )


def check_conflicts(report: Report, *needles: str) -> None:
    """Are disagreements recorded rather than privately resolved?"""
    doc = _load(KNOWLEDGE / "provenance" / "conflicts.json") or {}
    items = doc.get("conflicts") or []
    related = [c for c in items if _mentions(c, *needles)]
    unresolved = [c for c in related if not c.get("verification_required")]
    if not related:
        report.add("CONFLICTS_TRIAGED", True,
                   "no recorded conflict names this entity (nothing known to disagree)")
        return
    ok = not unresolved
    report.add("CONFLICTS_TRIAGED", ok,
               ("%d related conflict(s), all carry verification_required" % len(related)) if ok
               else "%d related conflict(s) with no verification_required: %s"
                    % (len(unresolved), ", ".join(str(c.get("id")) for c in unresolved[:3])))


def check_mechanism(report: Report, *needles: str) -> None:
    """WHETHER / WHEN / HOW FAR -- is there a knowledge record that is not still a placeholder?"""
    candidates = []
    for directory in ("events", "game", "strategy"):
        for path, doc in _iter_json(KNOWLEDGE / directory):
            if _mentions(doc, *needles):
                candidates.append((path, doc))
    if not candidates:
        report.add("MECHANISM_KNOWLEDGE", False,
                   "no knowledge file in events/ game/ strategy/ names this entity")
        return
    # A file that exists but is all placeholders is not knowledge.
    resolved = [p for p, d in candidates
                if not any(t in json.dumps(d, ensure_ascii=False) for t in UNRESOLVED)]
    if resolved:
        report.add("MECHANISM_KNOWLEDGE", True,
                   "resolved record(s): " + ", ".join(p.name for p in resolved[:3]))
    else:
        report.add("MECHANISM_KNOWLEDGE", False,
                   "record exists but still carries placeholders (%s): %s"
                   % ("/".join(UNRESOLVED), ", ".join(p.name for p in candidates[:3])))


def check_event_registry(report: Report, name: str) -> None:
    """For activities: does the registry carry this occurrence's state?

    ``event_registry.json`` states its own policy -- new or changed events enter at
    ``DISCOVERED`` and production requires ``VERIFIED``.  The gate reads that policy rather
    than restating it, so the two cannot drift.
    """
    doc = _load(KNOWLEDGE / "events" / "event_registry.json") or {}
    events = doc.get("events") or []
    entries = [e for e in events if _mentions(e, name)] if events else []
    policy = doc.get("policy") or {}
    required = str(policy.get("production_requires") or "VERIFIED")
    if not entries:
        report.add("EVENT_REGISTRY_STATE", False,
                   "event_registry.json has no entry for %s (policy requires %s before production)"
                   % (name, required))
        return
    # The registry's own field is ``gate``; ``lifecycle``/``status`` are accepted too so a
    # future rename does not silently turn this check into a permanent gap.  Read all three
    # rather than the first one that exists -- an entry carrying both should not hide the
    # stricter of the two.
    states = set()
    for entry in entries:
        for key in ("gate", "lifecycle", "status"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                states.add(value.strip())
    if not states:
        report.add("EVENT_REGISTRY_STATE", False,
                   "entry exists for %s but carries no gate/lifecycle/status, so its readiness "
                   "cannot be read (policy requires %s)" % (name, required))
        return
    ok = required.upper() in {s.upper() for s in states}
    report.add("EVENT_REGISTRY_STATE", ok,
               "states=%s, registry policy requires %s" % (sorted(states), required))


def check_parity(report: Report, *needles: str) -> None:
    """Competitor practice: is this feature tracked, and what does its record say?"""
    doc = _load(KNOWLEDGE / "coverage" / "commercial_bot_parity.json") or {}
    features = doc.get("features") or []
    hits = [f for f in features if _mentions(f, *needles)]
    if not hits:
        report.add("PARITY_RECORDED", False,
                   "commercial_bot_parity.json does not track this feature; whether a mature "
                   "implementation exists -- and whether it is cheaper -- is unrecorded")
        return
    f = hits[0]
    report.add("PARITY_RECORDED", True,
               "feature=%s lifecycle=%s attempts=%s success=%s"
               % (f.get("feature"), f.get("lifecycle"), f.get("attempts"), f.get("success")))


def check_risk(report: Report, *needles: str) -> None:
    """Are the blocking risk classes addressed anywhere on this entity's record?

    The charter blocks three classes outright.  A record that never mentions spend,
    identity or account safety is treated as *unhandled*, not as *safe* -- silence is
    exactly the state that let a misidentification become a real march.
    """
    blob = []
    for directory in ("events", "game", "strategy", "failure_patterns"):
        for path, doc in _iter_json(KNOWLEDGE / directory):
            if _mentions(doc, *needles):
                blob.append(json.dumps(doc, ensure_ascii=False).lower())
    text = " ".join(blob)
    declared = {
        "IRREVERSIBLE_SPEND": any(w in text for w in ("irreversible", "spend", "cost", "火晶", "加速", "白名单", "whitelist")),
        "MISIDENTIFICATION": any(w in text for w in ("misidentif", "不得过滤", "区分", "distinguish", "identity")),
        "ACCOUNT_SAFETY": any(w in text for w in ("account", "账号", "封", "ban", "rate limit", "节流")),
    }
    for cls in BLOCKING_RISK_CLASSES:
        handled = declared.get(cls, False)
        report.add("RISK_" + cls, handled,
                   ("declared on this entity's record" if handled else
                    "no statement found; the charter treats silence as unhandled for %s" % cls),
                   blocking=not handled)


def check_no_cross_version_coordinates(report: Report, *needles: str) -> None:
    """A stored absolute point is not a plan; the charter forbids it as an implementation basis."""
    suspicious = []
    for directory in ("events", "game", "strategy"):
        for path, doc in _iter_json(KNOWLEDGE / directory):
            if not _mentions(doc, *needles):
                continue
            text = json.dumps(doc, ensure_ascii=False).lower()
            if "tap_norm" in text or "click_norm" in text or "fixed coordinate" in text:
                suspicious.append(path.name)
    report.add("NO_STORED_CLICK_COORDINATE", not suspicious,
               "clean" if not suspicious else
               "these records carry stored click points: %s -- coordinates must come from the "
               "current frame" % ", ".join(suspicious[:3]))


#: Goal ids carry a verb the knowledge tree does not: ``CLEAR_INTEL`` is filed under ``intel``,
#: ``KEEP_TRAINING_PRODUCTIVE`` under ``train``, ``DISCOVER_EVENT_CALENDAR`` under
#: ``calendar``.  Stripping the prefix is what lets the gate find a domain that *is*
#: documented instead of reporting the tree as empty.
GOAL_VERB_PREFIXES = ("CLEAR_", "KEEP_", "CLAIM_", "USE_", "DISCOVER_", "AVOID_",
                      "PARTICIPATE_", "CHECK_", "OPEN_", "JOIN_", "START_", "READ_",
                      "SPEND_", "DO_")


#: Words too generic to identify anything.  ``NO_SUCH_GOAL_XYZ`` splits into
#: ``such``/``goal``/``xyz``, and ``goal`` appears in ``goal_library_v1.json``,
#: ``goal_capability_map.json`` and every strategy file -- so an unknown entity matched the
#: whole tree and the gate called it READY.  A needle has to be able to *fail* to be a check.
GENERIC_WORDS = frozenset({
    "goal", "goals", "event", "events", "task", "tasks", "data", "state", "states",
    "check", "checking", "list", "lists", "live", "info", "information", "current",
    "target", "targets", "action", "actions", "main", "general", "basic", "common",
})


def _goal_needles(name: str) -> tuple[str, ...]:
    upper = name.strip().upper()
    bare = upper
    for prefix in GOAL_VERB_PREFIXES:
        if upper.startswith(prefix):
            bare = upper[len(prefix):]
            break
    words = [w for w in bare.split("_") if len(w) >= 4 and w.lower() not in GENERIC_WORDS]
    extra = [bare.lower()] if bare.lower() not in GENERIC_WORDS else []
    extra.extend(w.lower() for w in words)
    # The tree files some domains under a shorter name than the goal uses
    # (``KEEP_TRAINING_PRODUCTIVE`` -> ``train_research_sources.json``).
    if "TRAINING" in upper:
        extra.append("train")
    if "CALENDAR" in upper:
        extra.append("calendar")
    return tuple(dict.fromkeys([name, name.lower(), *extra]))


def build_report(kind: str, name: str) -> Report:
    report = Report(kind, name)
    # The entity's own name plus the goal ids the project uses for the same thing.
    needles = (name,)
    if kind == "event" and name.upper() == "BEAR_HUNT":
        needles = needles + ("PARTICIPATE_BEAR", "bear", "巨熊")
    if kind == "goal":
        needles = needles + _goal_needles(name)
    needles = tuple(dict.fromkeys(needles))
    check_sources(report, *needles)
    check_conflicts(report, *needles)
    check_mechanism(report, *needles)
    check_parity(report, *needles)
    check_no_cross_version_coordinates(report, *needles)
    check_risk(report, *needles)
    if kind == "event":
        check_event_registry(report, name)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Research gate for Winter Agent OS V2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event")
    group.add_argument("--goal")
    group.add_argument("--skill")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    kind = "event" if args.event else "goal" if args.goal else "skill"
    name = args.event or args.goal or args.skill
    report = build_report(kind, name)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0 if report.verdict == "READY" else 1

    print("research gate: %s %s" % (kind.upper(), name))
    print("charter: knowledge/research/RESEARCH_CHARTER.json")
    print()
    for c in report.checks:
        print("  [%s] %-28s %s" % ("OK  " if c["ok"] else "GAP ", c["check"], c["detail"]))
    print()
    print("VERDICT: %s" % report.verdict)
    if report.verdict == "BLOCKED_UNSAFE":
        print("  unhandled blocking risk: %s" % ", ".join(c["check"] for c in report.blocking_failures))
    elif report.verdict == "NEEDS_RESEARCH":
        print("  missing: %s" % ", ".join(c["check"] for c in report.gaps))
    return 0 if report.verdict == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
