"""The unattended-development closure ladder, derived from the real artifacts.

Operator directive 2026-09-18: the next real capability gap must prove the whole
unattended loop end to end, and only when the *real* chain succeeded may anything
print "无人值守闭环: PASS 13/13".  Nothing here may be hand-created -- no job
submitted by hand, no escalation triggered by hand, no reload by hand, no AUTO
started by a click.  So this tool asserts nothing: it reads the evidence the
running system already wrote and joins it by ``trace_id``.

The chain it looks for, in order (13 steps):

    gap_detected -> escalation_created -> queue_deduped -> job_submitted ->
    job_working -> code_changed -> tests_passed -> live_verify_episode ->
    outcome_live_verified -> reload_requested -> reload_settled -> auto_resumed ->
    post_resume_verified

``trace_id`` is the escalation key (``CAPABILITY|FAILURE_TYPE|SKILL``) -- the one
identifier the queue, the job and the verification all already carry -- plus the
job id once it exists, so a reader can follow episode -> escalation -> job ->
commit -> live_verify_episode -> reload -> resumed session in one line.

    python tools/unattended_closure.py                  # the newest chain
    python tools/unattended_closure.py --all            # every chain on record
    python tools/unattended_closure.py --json <path>

A chain with no verdict yet is reported as INCOMPLETE with its ``failure_step``;
that is the honest answer and the tool never rounds it up.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import winproc  # noqa: E402

LEDGER = ROOT / "learning/workbuddy_escalations.jsonl"
EPISODES = ROOT / "learning/episodes.jsonl"
RELOAD_MARKER = ROOT / "learning/RUNTIME_RELOAD_REQUIRED.json"

STEPS: tuple[str, ...] = (
    "gap_detected", "escalation_created", "queue_deduped", "job_submitted",
    "job_working", "code_changed", "tests_passed", "live_verify_episode",
    "outcome_live_verified", "reload_requested", "reload_settled", "auto_resumed",
    "post_resume_verified",
)

# Steps whose condition may simply never arise, and which must therefore be
# reported as "not applicable" rather than as a hole.  Marking them applicable
# unconditionally would make the verdict depend on luck; hiding them would be
# worse, so they are always printed, with their applicability stated.
CONDITIONAL: frozenset[str] = frozenset({"queue_deduped", "reload_requested", "reload_settled"})


def moment(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").strip().splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


@dataclass
class Step:
    name: str
    done: bool = False
    evidence: list[str] = field(default_factory=list)
    note: str = ""
    applicable: bool = True

    @property
    def conditional(self) -> bool:
        return self.name in CONDITIONAL


@dataclass
class Chain:
    trace_id: str
    job_id: str = ""
    capability: str = ""
    skill: str = ""
    failure_type: str = ""
    commit: str = ""
    commit_note: str = ""
    submitted_at: datetime | None = None
    reload_id: str = ""
    steps: list[Step] = field(default_factory=list)

    @property
    def applicable(self) -> list[Step]:
        return [step for step in self.steps if step.applicable]

    @property
    def completed(self) -> int:
        return sum(1 for step in self.steps if step.done)

    @property
    def failure_step(self) -> str:
        for step in self.steps:
            if step.applicable and not step.done:
                return step.name
        return ""

    @property
    def verdict(self) -> str:
        return "PASS" if not self.failure_step else "INCOMPLETE"


def heads() -> list[str]:
    """The last 40 commits as ``"<sha> <cI>"`` lines, or ``()`` when git cannot run.

    Through the one runner rather than a bare ``subprocess.run``.  This module is not only
    an operator's terminal tool: ``control_panel`` imports it and calls this on the refresh
    path that draws the closure card, and the panel runs under a console-less ``pythonw``.
    A console tool spawned from there without the hidden-window flags makes Windows attach
    a console to the Git-for-Windows shim, and that launch fails outright -- measured
    2026-09-19, the operator saw a modal ``[出现错误 2147942632 (0x800700e8)
    (启动"git log "--format=%h %cI" -40"时)]``, and 0x800700E8 is Win32 error 232
    ``ERROR_NO_DATA``, "the pipe is being closed".

    The ``OSError`` is absorbed rather than raised -- a guard that crashes cannot be
    trusted, and a card that raises takes the whole refresh with it -- so the flags are the
    only thing standing between a failure and silence: without them ``heads()`` returns
    ``()``, and ``build`` then reports "no commit landed after the submission" over a
    submission the operator did in fact commit.  ``winproc.run`` is what every other call
    site in the panel's reach already uses; there is no second runner.
    """
    try:
        done = winproc.run(["git", "log", "--format=%h %cI", "-40"], cwd=ROOT, timeout=20)
    except OSError:
        return []
    return [line for line in (done.stdout or "").splitlines() if line.strip()]


def build(trace_id: str, ledger: list[dict[str, Any]], episodes: list[dict[str, Any]],
          commits: list[tuple[str, datetime]]) -> Chain:
    chain = Chain(trace_id=trace_id)
    capability, failure_type, skill = (trace_id.split("|") + ["", "", ""])[:3]
    chain.capability, chain.failure_type, chain.skill = capability, failure_type, skill

    mine = [row for row in ledger if str(row.get("key") or "") == trace_id]
    if not mine:  # a bridge-only submission carries no key
        mine = [row for row in ledger if str(row.get("capability") or "") == capability]
    submitted = next((row for row in mine if row.get("event") == "submitted"), None)
    job_id = str((submitted or {}).get("job_id") or "")
    chain.job_id = job_id
    at = moment((submitted or {}).get("recorded_at"))
    chain.submitted_at = at
    repo_head = str((submitted or {}).get("repo_head") or "")

    steps: dict[str, Step] = {name: Step(name) for name in STEPS}

    # 1. gap_detected -- the production episode that failed this way, before the job.
    for episode in episodes:
        when = moment(episode.get("recorded_at"))
        if when is None or at is None or when > at:
            continue
        if str(episode.get("skill") or "") != skill:
            continue
        if failure_type and str(episode.get("failure_type") or "") != failure_type:
            continue
        if str(episode.get("result") or "").upper() != "FAILURE":
            continue
        steps["gap_detected"].done = True
        steps["gap_detected"].evidence.append(
            f"episode {episode.get('episode_id')} {episode.get('failure_type')} at {episode.get('recorded_at')}")
    if not steps["gap_detected"].done:
        steps["gap_detected"].note = "no failing episode of this shape before the escalation"

    # 1b. ...or the gap is a deferral.  A goal the scheduler refused to re-enter
    # produced no failing step at all -- that is the whole point of refusing it -- so
    # there is no FAILURE episode to find, and the chain would look like it began from
    # nothing.  The queue was handed the scheduler's own deferral, and the run's
    # episodes carry the measurement behind it: episodes of that goal that passed their
    # verifier and moved nothing.  2026-09-18 is the first chain of this shape
    # (SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST).
    creation = next((row for row in mine if row.get("event") == "escalation_created"), None)
    if creation is not None and str(creation.get("failure_type") or "") == "NO_GOAL_PROGRESS":
        goal_id = str(creation.get("goal") or "")
        stalled = [
            episode for episode in episodes
            if str(episode.get("goal_id") or "") == goal_id
            and episode.get("goal_progress") is False
            and (when := moment(episode.get("recorded_at"))) is not None
            and at is not None and when <= at
        ]
        if stalled:
            steps["gap_detected"].done = True
            steps["gap_detected"].evidence.append(
                f"{len(stalled)} measured episode(s) of {goal_id} whose verifier passed "
                f"while the goal did not move, before {at.isoformat()}")
        handed = [str(item) for item in (creation.get("evidence") or [])]
        if handed:
            steps["gap_detected"].evidence.append(
                "the queue was handed the scheduler's own deferral: " + ", ".join(handed))

    # 2. escalation_created
    created = [row for row in mine if row.get("event") in {"submitted", "candidate", "dispatch"}]
    if created and job_id:
        steps["escalation_created"].done = True
        steps["escalation_created"].evidence.append(
            f"ledger {created[0].get('event')} {trace_id} job={job_id}")
        # Who triggered it?  The ledger records the transport's own source field, and
        # 2026-09-18 showed both a queue-mediated and an operator-submitted escalation
        # carrying the same two-row shape (source=bridge + source=queue), so the field
        # alone does not attribute the trigger.  It is printed verbatim instead of
        # being read as proof of "V2 triggered this by itself".
        sources = [str(row.get("source") or "?") for row in mine if row.get("event") == "submitted"]
        steps["escalation_created"].evidence.append(
            f"submission sources recorded: {', '.join(sources) or '?'}"
            " (the ledger does not by itself prove whether V2 or the operator triggered it)")

    # 3. queue_deduped -- a skip/correction shows the queue decided about a duplicate
    skips = [row for row in ledger if row.get("event") in {"skipped", "corrected", "correction"}
             and (str(row.get("key") or "") == trace_id or capability in json.dumps(row))]
    if skips:
        steps["queue_deduped"].done = True
        steps["queue_deduped"].evidence.append(f"queue event {skips[-1].get('event')}")
    else:
        # No duplicate arose for this chain, so there was nothing for the queue to
        # refuse.  That is not a hole in the chain, and it is printed either way.
        steps["queue_deduped"].applicable = False
        steps["queue_deduped"].note = "no duplicate arose; the queue's dedupe had nothing to refuse"

    # 4/5. job_submitted + job_working
    if job_id:
        steps["job_submitted"].done = True
        steps["job_submitted"].evidence.append(f"job {job_id} submitted at {at.isoformat() if at else '?'}")
        states = [row for row in mine if row.get("event") == "job_state" and row.get("job_id") == job_id]
        if states or any(row.get("event") == "reconciled" for row in mine):
            steps["job_working"].done = True
            steps["job_working"].evidence.append(
                f"gateway state {states[-1].get('state') if states else 'WORKING/inferred from reconcile'}")

    # 6/7. code_changed + tests_passed -- the reconciled row carries both
    reconciled = next((row for row in mine if row.get("event") == "reconciled"
                       and not row.get("correction")), None)
    if reconciled:
        if reconciled.get("code_changed"):
            steps["code_changed"].done = True
            steps["code_changed"].evidence.append(
                f"engine reports code_changed; repo_head at submit {repo_head[:12]}")
            # Whose commit?  Not simply the next one on main -- measured 2026-09-18:
            # that returned the harness's own commit, because the operator and the
            # job share one branch.  The job's own report is the only attribution
            # available, so a hash it names is used and anything else is labelled
            # as unattributed rather than guessed.
            report = json.dumps({k: reconciled.get(k) for k in ("job_detail", "explanation")},
                                ensure_ascii=False)
            named = re.findall(r"\b[0-9a-f]{7,40}\b", report)
            head_tokens = {repo_head[:length] for length in range(7, min(len(repo_head), 40) + 1)}
            named = [sha for sha in named if sha not in head_tokens and sha != "problems"]
            if named:
                chain.commit = named[0]
                steps["code_changed"].evidence.append(f"commit {chain.commit} named by the job's own report")
            else:
                window = [f"{sha} at {when.isoformat()}" for sha, when in commits if at and when >= at]
                chain.commit_note = ("the job's report names no commit; commits landing after "
                                     "the submission are listed as candidates, not attributed")
                steps["code_changed"].evidence.extend(window[:4] or ["no commit landed after the submission"])
        if reconciled.get("wiring_problems") == 0:
            steps["tests_passed"].done = True
            steps["tests_passed"].evidence.append("check_wiring reports problems: 0")
        if reconciled.get("verified_episodes"):
            steps["live_verify_episode"].done = True
            steps["live_verify_episode"].evidence.append(
                f"verifier-passing episodes at reconcile: {reconciled.get('verified_episodes')}")
        outcome = str(reconciled.get("outcome") or "")
        steps["outcome_live_verified"].done = outcome == "LIVE_VERIFIED"
        steps["outcome_live_verified"].evidence.append(f"outcome {outcome or '?'}")
        if outcome != "LIVE_VERIFIED":
            steps["outcome_live_verified"].note = f"engine reported {outcome}"

    # 8. live_verify_episode, from the episode stream itself (stronger than the count)
    if not steps["live_verify_episode"].done and at is not None:
        for episode in episodes:
            when = moment(episode.get("recorded_at"))
            if when and when > at and str(episode.get("skill") or "") == skill \
                    and episode.get("verifier_ok") is True:
                steps["live_verify_episode"].done = True
                steps["live_verify_episode"].evidence.append(
                    f"episode {episode.get('episode_id')} verifier_ok at {episode.get('recorded_at')}")
                break

    # 9. the outcome row is the engine's own verdict; the episodes above are the grounds
    if steps["live_verify_episode"].done and mine:
        pass  # already set from the reconcile row when present

    # 10/11. reload_requested + reload_settled
    reloads = [row for row in ledger if row.get("event") == "reload_required"
               and (not job_id or str(row.get("job_id") or "") == job_id or str(row.get("key") or "") == trace_id)]
    requested = moment((reloads[-1] or {}).get("requested_at")) if reloads else None
    if reloads:
        steps["reload_requested"].done = True
        chain.reload_id = f"reload:{job_id}:{reloads[-1].get('requested_at')}"
        steps["reload_requested"].evidence.append(
            f"reload_id {chain.reload_id}"
            + ("" if RELOAD_MARKER.exists() else "; marker since cleared"))
    if requested is not None and not RELOAD_MARKER.exists():
        after = [e for e in episodes if (moment(e.get("recorded_at")) or requested) > requested]
        if after:
            steps["reload_settled"].done = True
            steps["reload_settled"].evidence.append(
                f"marker cleared and {len(after)} episodes recorded after the request")
    if not reloads:
        # "如需则安全Reload": a reload is needed exactly when code changed, so with
        # no code change these two steps have no condition to satisfy -- but if code
        # did change and no reload was requested, that *is* the failure step.
        needs_reload = steps["code_changed"].done
        for name in ("reload_requested", "reload_settled"):
            steps[name].applicable = needs_reload
            if not needs_reload:
                steps[name].note = "no code change, so no reload was needed"
            else:
                steps[name].note = "code changed but no reload was requested"

    # 12/13. auto_resumed + post_resume_verified -- the run that came back must verify
    if requested is not None:
        resumed = [e for e in episodes if (moment(e.get("recorded_at")) or requested) > requested]
        verified = [e for e in resumed if e.get("verifier_ok") is True]
        if resumed:
            steps["auto_resumed"].done = True
            steps["auto_resumed"].evidence.append(
                f"{len(resumed)} episodes after the reload; newest {resumed[-1].get('recorded_at')}")
        if verified:
            steps["post_resume_verified"].done = True
            steps["post_resume_verified"].evidence.append(
                f"episode {verified[-1].get('episode_id')} {verified[-1].get('skill')} "
                f"verifier_ok at {verified[-1].get('recorded_at')}")
        elif resumed:
            steps["post_resume_verified"].note = "resumed but nothing verified after the reload"

    chain.steps = [steps[name] for name in STEPS]
    return chain


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="unattended closure ladder")
    parser.add_argument("--all", action="store_true", help="every chain, not only the newest")
    parser.add_argument("--json", help="write the derived chains here")
    args = parser.parse_args(argv)

    ledger, episodes = rows(LEDGER), rows(EPISODES)
    commits = [(line.split(" ", 1)[0], moment(line.split(" ", 1)[1])) for line in heads()]
    commits = [(sha, when) for sha, when in commits if when is not None]

    keys: list[str] = []
    for row in ledger:
        key = str(row.get("key") or "")
        if key and key not in keys:
            keys.append(key)
    chains = [build(key, ledger, episodes, commits) for key in keys]
    chains = [chain for chain in chains if chain.job_id]
    # By submission time, not by job id.  Job ids are opaque hex, and sorting them
    # string-wise put an older chain after a newer one -- so the default view reported
    # the wrong chain as the newest (measured 2026-09-18: 2934e9cd sorted before
    # a7ce58f0, and a7ce58f0 is three hours older).
    chains.sort(key=lambda chain: (chain.submitted_at is None, chain.submitted_at))
    if not args.all:
        chains = chains[-1:]

    for chain in chains:
        print("=" * 78)
        print(f"trace_id : {chain.trace_id}")
        print(f"job      : {chain.job_id}   capability: {chain.capability}   skill: {chain.skill}")
        print(f"commit   : {chain.commit or '(unattributed)'}"
              + (f"   -- {chain.commit_note}" if chain.commit_note else ""))
        print(f"reload   : {chain.reload_id or '(none)'}")
        print("-" * 78)
        for index, step in enumerate(chain.steps, 1):
            mark = "OK  " if step.done else ("n/a " if not step.applicable else "....")
            print(f"  {index:>2}. {mark} {step.name}")
            for item in step.evidence:
                print(f"          - {item}")
            if step.note and not step.done:
                print(f"          {'~' if not step.applicable else '!'} {step.note}")
        print("-" * 78)
        applicable = chain.applicable
        not_applicable = [step.name for step in chain.steps if not step.applicable]
        if chain.failure_step:
            print(f"无人值守闭环: INCOMPLETE {chain.completed}/{len(applicable)} 适用步骤"
                  f"   failure_step={chain.failure_step}")
        else:
            print(f"无人值守闭环: PASS {chain.completed}/{len(applicable)} 适用步骤"
                  f"（{len(STEPS)} 步中 {len(not_applicable)} 步不适用）")
        if not_applicable:
            print(f"           不适用：{', '.join(not_applicable)}")

    if args.json:
        Path(args.json).write_text(json.dumps([{
            "trace_id": chain.trace_id, "job_id": chain.job_id,
            "capability": chain.capability, "skill": chain.skill, "commit": chain.commit,
            "commit_note": chain.commit_note,
            "verdict": chain.verdict, "completed": chain.completed,
            "applicable": len(chain.applicable), "total": len(STEPS),
            "failure_step": chain.failure_step,
            "steps": [vars(step) for step in chain.steps],
        } for chain in chains], ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
