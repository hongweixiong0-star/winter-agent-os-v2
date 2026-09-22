"""Give the UNKNOWN question channel a consumer, so answering it is not an operator's job.

What was measured before this module existed (2026-09-22, this machine):

* the official CodeBuddy gateway is **up** -- ``GET /api/v1/health`` answers ``{"status":"ok"}`` --
  and ``POST /api/v1/jobs`` really dispatches a background agent: **99 jobs** are recorded in
  ``learning/workbuddy_escalations.jsonl``, every one of them submitted and every one of them
  reaching ``working``;
* the UNKNOWN channel itself had no consumer at all.  ``unknown_advisor`` writes a question to
  ``learning/unknown_requests/`` and reads an answer if one is there, and nothing in the project
  ever put one there.  The only way an answer appeared was a person running
  ``tools/unknown_advisor.py --list / --show / --answer``.

So the honest description of the old state is: the runtime half was automatic, the answering half
was manual, and calling that "自动 AI 推理" would have been false.  This module is the missing
consumer, and it is deliberately a *file-driven* one, exactly like the other state directories:

    a request with no answer  ->  one job is submitted for it (bounded, deduplicated, audited)
    the job reads the frame   ->  it writes ``answers/<id>.json`` through the project's own tool
    the runtime               ->  picks the answer up on a later step, through the chain it has

Three properties, and each is a rule rather than a preference:

* **the AUTO never waits.**  Nothing here is imported or called by a runtime step; it runs on the
  panel's existing clock (``tools/control_panel.py``, the same thread that pumps the escalation
  queue) and on demand from ``tools/unknown_ai_worker.py``.  A cycle that has no answer keeps
  playing with the chain that already works -- which is the directive's own sentence.
* **it is bounded.**  At most ``MAX_IN_FLIGHT`` jobs at once, one job per request, at most
  ``MAX_ATTEMPTS_PER_REQUEST`` attempts per question, and a cooldown between attempts.  A stuck
  screen cannot turn into a job generator, and a question that has been answered is never asked
  again.
* **it is auditable.**  Every submission and every reconciliation is one line in
  ``learning/unknown_dispatch.jsonl``: which request, which job, which model, which frame.  The
  claim "the channel is automatic" is therefore checkable rather than asserted.

What it deliberately does not do: it does not answer anything itself.  There is no model client
here, no prompt parsing, no fallback heuristic.  The reasoning is the job's, the answer is written
through ``tools/unknown_advisor.py`` so it is validated by the same ``parse_advice`` the runtime
uses, and a job that produces nothing leaves the request pending -- reported as such.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import unknown_advisor
from .workbuddy_bridge import (
    GatewayUnavailable,
    JobLost,
    PROJECT_ROOT,
    WorkBuddyBridge,
)

#: The dispatch ledger.  Append-only, one line per event, under ``learning/`` beside the requests
#: it is about and the escalation ledger it shares a shape with.
DISPATCH_LEDGER = Path("learning/unknown_dispatch.jsonl")

#: How many answering jobs may be in flight at once.  **One**, as a policy rather than as a
#: transport limit, and the distinction was measured rather than assumed: the escalation ledger
#: showed exactly one job in ``working`` at any moment all day, which looked like a serial gateway,
#: but submitting a second job while the first was still running showed both ``working`` / ``alive``
#: at the same moment -- so the gateway does run them concurrently and the single job in the ledger
#: was the queue's policy.  One question at a time is the right policy here too: each answer is
#: consumed by the next matching step, and a burst of answers for screens that have already moved on
#: is work nobody asked for.
MAX_IN_FLIGHT = 1

#: How many jobs one question may have.  Two, because the failure this guards against is a job that
#: is *stopped* rather than answered (measured once: a job that never wrote anything and was
#: reclaimed at the timebox) -- retrying that once is reasonable, retrying it forever is not.
MAX_ATTEMPTS_PER_REQUEST = 2

#: How long to wait before re-asking the same question after a job that produced nothing.  The
#: question itself is already rate-limited by ``unknown_advisor.REQUEST_COOLDOWN_SECONDS``; this is
#: the shorter "did the attempt visibly fail" clock.
DISPATCH_COOLDOWN_SECONDS = 900

#: The model-router task bucket this work belongs to.  ``UNKNOWN_UI`` maps to ``TASK_UI_RECOGNITION``
#: and, with ``needs="vision"``, the router's cold start picks the vision rung -- a text-only model
#: cannot read the screenshot the question is about.
TASK_CONDITION = "UNKNOWN_UI"
NEEDS = "vision"
CHANNEL = "UNKNOWN_REQUEST"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seconds_since(stamp: str) -> float:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


#: The vocabulary the ledger's ``state`` field is read in: **both** spellings, lower-cased.
#:
#: Measured on the channel's first live dispatch, and it cost a bound: ``dispatch`` writes the state
#: it got from the submission (``working``) while the first version of ``reconcile`` wrote the
#: bridge's *verdict* (``RUNNING``).  ``Dispatch.open`` then recognised only the first spelling, so
#: one reconcile pass made every running job look finished -- the in-flight limit read zero and a
#: second job was submitted while the first was still working.  New rows all carry the gateway's own
#: word, and both are accepted so a row written before that change still reads correctly.
OPEN_STATES = frozenset({"submitted", "working", "queued", "running"})


def _pid_alive(pid: int) -> bool | None:
    """Whether a process id is alive, or ``None`` when that cannot be established here.

    ``os.kill(pid, 0)`` is **not** usable for this on Windows: that platform supports only
    CTRL_C_EVENT / CTRL_BREAK_EVENT, and any other signal -- 0 included -- calls TerminateProcess, so
    the check would kill the very process it is asking about.  ``OpenProcess`` is the read-only way,
    and ``None`` means "no opinion", which the caller falls back to an age for.

    This exists because a lock file was left behind during this round's own first working session
    and silently blocked the next pass: the holding process was gone but the file was not, so every
    consumer that read it refused to work.  A leaked lock is survivable; a *silent* one is not.
    """
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:  # noqa: BLE001 - not Windows, no ctypes, no permission: no opinion
        return None


@dataclass(frozen=True)
class Dispatch:
    """One request's dispatch state, folded from the ledger."""

    request_id: str
    attempts: int = 0
    job_id: str = ""
    model: str = ""
    task_type: str = ""
    state: str = ""
    submitted_at: str = ""
    updated_at: str = ""
    note: str = ""

    @property
    def open(self) -> bool:
        """True while this request's current job may still produce an answer."""
        return bool(self.job_id) and str(self.state or "").strip().lower() in OPEN_STATES


class UnknownDispatcher:
    """The channel's consumer: submit one job per pending question, then reconcile.

    Held by the panel's clock, so its whole surface is written to be safe to call repeatedly: every
    method swallows transport failures into the state it returns, and nothing raises.
    """

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        advisor: unknown_advisor.UnknownAdvisor | None = None,
        bridge: Any | None = None,
        ledger_path: Path | str | None = None,
        router: Any | None = None,
        max_in_flight: int = MAX_IN_FLIGHT,
        max_attempts: int = MAX_ATTEMPTS_PER_REQUEST,
        cooldown: float = DISPATCH_COOLDOWN_SECONDS,
    ) -> None:
        self.root = Path(root) if root else PROJECT_ROOT
        self.advisor = advisor or unknown_advisor.UnknownAdvisor()
        self.bridge = bridge if bridge is not None else WorkBuddyBridge(cwd=self.root)
        self.ledger_path = Path(ledger_path) if ledger_path else self.root / DISPATCH_LEDGER
        self.max_in_flight = int(max_in_flight)
        self.max_attempts = int(max_attempts)
        self.cooldown = float(cooldown)
        # The task bucket is named once, before the router, so the two can never disagree about
        # what this work is (a screenshot question: ``TASK_UI_RECOGNITION``, vision-shaped).
        from .workbuddy_model_router import ModelRouter, default_stats_path, task_type_for

        self._task_type = task_type_for(TASK_CONDITION, needs=NEEDS)
        self.router = (
            router if router is not None else ModelRouter(default_stats_path(self.root))
        )

    # ------------------------------------------------------------------ reads

    def rows(self) -> list[dict[str, Any]]:
        try:
            lines = self.ledger_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("request_id"):
                out.append(row)
        return out

    def records(self) -> dict[str, Dispatch]:
        """Every request the ledger mentions, folded to its latest state."""
        folded: dict[str, Dispatch] = {}
        for row in self.rows():
            key = str(row.get("request_id"))
            previous = folded.get(key)
            attempts = (previous.attempts if previous else 0) + (
                1 if row.get("event") == "submitted" else 0
            )
            state = str(row.get("state") or (previous.state if previous else ""))
            folded[key] = Dispatch(
                request_id=key,
                attempts=attempts,
                job_id=str(row.get("job_id") or (previous.job_id if previous else "")),
                model=str(row.get("model") or (previous.model if previous else "")),
                task_type=str(row.get("task_type") or (previous.task_type if previous else "")),
                state=state,
                submitted_at=str(
                    row.get("at") if row.get("event") == "submitted"
                    else (previous.submitted_at if previous else "")
                ),
                updated_at=str(row.get("at") or ""),
                note=str(row.get("note") or (previous.note if previous else "")),
            )
        return folded

    def answered_ids(self) -> set[str]:
        """Requests whose answer file is already on disk."""
        answers = self.advisor.root / unknown_advisor.ANSWERS_DIR
        if not answers.exists():
            return set()
        return {path.stem for path in answers.glob("*.json") if path.is_file()}

    def open_jobs(self, records: Mapping[str, Dispatch] | None = None) -> list[Dispatch]:
        """Every job the ledger still shows as running, **whether or not an answer arrived**.

        This is what :meth:`reconcile` walks, and the distinction from :meth:`in_flight` is not
        cosmetic: an answer usually lands while the job that wrote it is still ``working``, so a
        reconcile that skipped answered requests would leave those jobs open in the ledger for ever
        -- and would never record the one outcome the model router most needs, the successful one.
        Measured on the first live dispatch: the answer file appeared, ``in_flight`` went empty, and
        the job stayed ``working`` with nobody left to read it back.
        """
        folded = records if records is not None else self.records()
        return [record for record in folded.values() if record.open]

    def in_flight(self, records: Mapping[str, Dispatch] | None = None) -> list[Dispatch]:
        """Open jobs whose answer has not arrived -- i.e. the ones holding a submission slot."""
        answered = self.answered_ids()
        return [
            record for record in self.open_jobs(records)
            if record.request_id not in answered
        ]

    def pending(self) -> list[unknown_advisor.UnknownRequest]:
        """Questions with no answer yet -- newest first, as the advisor defines them."""
        return self.advisor.pending()

    def candidates(self) -> list[tuple[unknown_advisor.UnknownRequest, str]]:
        """Questions this dispatcher may submit now, each with why it qualifies.

        A refusal is returned with its reason rather than silently dropped: "the channel is
        automatic" is only true if the reason a question was *not* submitted is visible.
        """
        folded = self.records()
        answered = self.answered_ids()
        out: list[tuple[unknown_advisor.UnknownRequest, str]] = []
        for request in self.pending():
            if request.request_id in answered:
                continue
            record = folded.get(request.request_id)
            if record is not None:
                if record.open:
                    continue
                if record.attempts >= self.max_attempts:
                    continue
                if _seconds_since(record.updated_at) < self.cooldown:
                    continue
            out.append((request, "pending" if record is None else f"retry {record.attempts + 1}"))
        return out

    # ------------------------------------------------------------------ acts

    def reconcile(self) -> dict[str, Any]:
        """Read every open job back and record what became of it.

        A job that is ``done`` with an answer on disk is a success; one that is terminal without an
        answer is a failed attempt that may be retried once; a job the gateway no longer knows is
        recorded as ``JOB_LOST`` and frees its slot, which is the distinction ``JobLost`` exists for.
        """
        folded = self.records()
        answered = self.answered_ids()
        report: dict[str, Any] = {"checked": 0, "done": 0, "failed": 0, "lost": 0, "errors": []}
        for record in self.open_jobs(folded):
            report["checked"] += 1
            try:
                status = self.bridge.status(record.job_id)
            except JobLost as exc:
                report["lost"] += 1
                self._append({
                    "event": "reconciled",
                    "request_id": record.request_id,
                    "job_id": record.job_id,
                    "state": "JOB_LOST",
                    "note": str(exc)[:300],
                })
                continue
            except GatewayUnavailable as exc:
                report["errors"].append(f"{record.job_id}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - a poll must never raise into the panel
                report["errors"].append(f"{record.job_id}: {type(exc).__name__}: {exc}")
                continue
            state = str(status.gateway_state or "").strip().lower() or "unknown"
            verdict = str(status.verdict or "UNKNOWN")
            if not status.terminal:
                if state != record.state:
                    self._append({
                        "event": "reconciled",
                        "request_id": record.request_id,
                        "job_id": record.job_id,
                        "state": state,
                        "verdict": verdict,
                    })
                continue
            produced = record.request_id in answered
            if produced:
                report["done"] += 1
            else:
                report["failed"] += 1
            self._append({
                "event": "reconciled",
                "request_id": record.request_id,
                "job_id": record.job_id,
                "state": state,
                "verdict": verdict,
                "note": "answer written" if produced else "no answer written",
            })
            self._record_model_outcome(record, success=produced, state=verdict)
        return report

    def dispatch(self, *, limit: int = 1, dry_run: bool = False) -> dict[str, Any]:
        """Submit jobs for pending questions, within every bound.

        ``dry_run`` reports exactly what would be submitted -- prompt included -- and touches
        nothing, which is how the prompt itself gets reviewed before a job is ever created.
        """
        report: dict[str, Any] = {
            "submitted": [], "skipped": [], "dry_run": bool(dry_run),
            "in_flight": len(self.in_flight()), "errors": [],
        }
        if dry_run:
            for request, reason in self.candidates()[: max(0, int(limit))]:
                report["submitted"].append({
                    "request_id": request.request_id,
                    "reason": reason,
                    "model": self._choose_model(),
                    "prompt": self.prompt_for(request),
                })
            return report

        available = max(0, self.max_in_flight - len(self.in_flight()))
        for request, reason in self.candidates():
            if len(report["submitted"]) >= max(0, int(limit)):
                break
            if available <= 0:
                report["skipped"].append(
                    {"request_id": request.request_id, "reason": "in-flight limit reached"}
                )
                continue
            model = self._choose_model()
            try:
                submission = self.bridge.submit_prompt(
                    self.prompt_for(request),
                    name=f"V2 unknown question: {request.request_id}",
                    model=model,
                    channel=CHANNEL,
                    extra={
                        "request_id": request.request_id,
                        "frame_digest": request.frame_digest,
                        "goal": request.goal,
                        "screen": request.page_key,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - the AUTO must not fail because asking did
                self._append({
                    "event": "submit_failed",
                    "request_id": request.request_id,
                    "state": "SUBMIT_FAILED",
                    "model": model,
                    "note": f"{type(exc).__name__}: {exc}"[:300],
                })
                report["errors"].append(f"{request.request_id}: {type(exc).__name__}: {exc}")
                continue
            available -= 1
            self._append({
                "event": "submitted",
                "request_id": request.request_id,
                "job_id": submission.job_id,
                "model": model,
                "task_type": self._task_type,
                "state": str(submission.state or "submitted").lower(),
                "frame_digest": request.frame_digest,
                "goal": request.goal,
                "screen": request.page_key,
                "reason": reason,
            })
            report["submitted"].append({
                "request_id": request.request_id,
                "job_id": submission.job_id,
                "model": model,
                "state": str(submission.state or ""),
                "reason": reason,
            })
        return report

    def worker(self) -> dict[str, Any]:
        """One full pass: reconcile what is open, then submit what is pending.  Never raises.

        Guards against a second consumer with a lock file, because there can legitimately be two: the
        panel's clock inside the long-lived process, and ``tools/unknown_ai_worker.py`` on a console
        while the panel is running an older build.  Two processes reading the same ledger could both
        decide a question has no job and both submit one -- and that costs a real job each time.  A
        pass that cannot take the lock simply reports so and returns; the other consumer is already
        doing this work.
        """
        out: dict[str, Any] = {"reconcile": {}, "dispatch": {}, "lock": ""}
        with self._pass_lock() as held:
            if not held:
                out["lock"] = "another consumer is running a pass"
                return out
            try:
                out["reconcile"] = self.reconcile()
            except Exception as exc:  # noqa: BLE001
                out["reconcile"] = {"errors": [f"{type(exc).__name__}: {exc}"]}
            try:
                out["dispatch"] = self.dispatch(limit=max(1, self.max_in_flight))
            except Exception as exc:  # noqa: BLE001
                out["dispatch"] = {"errors": [f"{type(exc).__name__}: {exc}"]}
        return out

    @contextmanager
    def _pass_lock(self, stale_after: float = 300.0):
        """A best-effort exclusive pass lock, released however the pass ends.

        ``O_CREAT|O_EXCL`` is the atomic step, so two processes cannot both win it.  A lock left
        behind by a process that is **gone** is taken over immediately -- measured during this
        round's first working session, where exactly that happened and the next consumer refused to
        work for no visible reason -- and one whose holder cannot be asked about is taken over once it
        is older than ``stale_after``.  Either way the alternative would be a channel that stops
        because something died while holding a file.
        """
        path = self.ledger_path.with_suffix(".lock")
        acquired = False
        handle = None

        def _take() -> bool:
            nonlocal handle
            try:
                handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(handle, f"{os.getpid()} {_now()}".encode("utf-8"))
                return True
            except OSError:
                return False

        def _holder_is_gone() -> bool:
            try:
                pid_text = path.read_text(encoding="utf-8").split(" ", 1)[0].strip()
                alive = _pid_alive(int(pid_text))
            except (OSError, ValueError):
                return True
            if alive is True:
                return False
            if alive is False:
                return True
            try:
                return datetime.now(timezone.utc).timestamp() - path.stat().st_mtime > stale_after
            except OSError:
                return True

        try:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                acquired = _take()
            except OSError:
                # A lock that cannot be created at all (a read-only tree) must not stop the channel:
                # the bound it protects is a nicety, and refusing to work would be the worse bug.
                acquired = True
            if not acquired and _holder_is_gone():
                try:
                    path.unlink()
                except OSError:
                    pass
                acquired = _take()
            yield acquired
        finally:
            if handle is not None:
                try:
                    os.close(handle)
                except OSError:
                    pass
            if acquired:
                try:
                    path.unlink()
                except OSError:
                    pass

    def state(self) -> dict[str, Any]:
        """A small, JSON-safe summary for the panel's heartbeat and for a person asking."""
        try:
            available = bool(self.bridge.is_available())
        except Exception:  # noqa: BLE001
            available = False
        folded = self.records()
        answered = self.answered_ids()
        return {
            "gateway": available,
            "pending": len(self.pending()),
            "answered": len(answered),
            "in_flight": [record.job_id for record in self.in_flight(folded)],
            "attempts": {key: record.attempts for key, record in folded.items()},
            "last": max((row.get("at") or "" for row in self.rows()), default=""),
        }

    # ------------------------------------------------------------------ the task text

    def _choose_model(self) -> str:
        try:
            choice = self.router.choose(self._task_type, needs=NEEDS)
            return str(getattr(choice, "model", "") or "")
        except Exception:  # noqa: BLE001
            return ""

    def prompt_for(self, request: unknown_advisor.UnknownRequest) -> str:
        """The whole task, composed for one question.

        Written to be answerable by an agent that has never seen this project: the request file, the
        screenshot, how to look at the picture closely, the three shapes an action may take, the
        boundary, the exact schema, and the one command that may write the answer.  It asks for
        nothing else -- no code change, no device use, no AUTO run -- because a question about one
        screenshot is a question about one screenshot.
        """
        answers = f"{self.advisor.root.as_posix()}/{unknown_advisor.ANSWERS_DIR}"
        request_file = str(self.advisor.root / f"{request.request_id}.json")
        root = str(self.root)
        frame = str(request.frame_path or "")
        py = r".\.venv\Scripts\python.exe"
        return f"""# Winter Agent OS V2 — answer one UNKNOWN question (this and nothing else)

The runtime (the agent that plays the game on the device) met a screen it could not work out, wrote
the question to disk, and moved on. Your whole task is to answer that one question and write the
answer down. Do not change project code, do not touch the device, do not run the AUTO.

## The question
Read this file first -- it is everything the runtime knows:
    {request_file}

It carries: the screen label the page model produced, the goal being pursued, this screenshot's
path, the text this frame's OCR read together with its boxes (normalised: `x_norm`/`y_norm`/
`w_norm`/`h_norm` relative to the whole frame), where the run came from, the state the screen was
read in, and what the last attempt expected against what actually happened.

## The picture
{frame}

Look at it with the Read tool (it is a 720x1280 PNG). To judge a small or wordless element, crop and
enlarge it with the project's own interpreter and look at the crop:
    {py} -c "from PIL import Image; im=Image.open(r'{frame}'); im.crop((L,T,R,B)).resize(((R-L)*3,(B-T)*3)).save(r'{root}\\learning\\_look.png')"
Then Read `{root}\\learning\\_look.png`. Convert whatever you see back into normalised coordinates by
dividing by 720 (x) and 1280 (y).

## What an action may be (directive §二 -- all three are allowed)
A. a registered skill id, e.g. `TRY_ORDINARY_CONTROL` or `BACK`;
B. an already-learned single-step action, written `L1[<control>]`, e.g. `L1[ORDINARY_CONTROL[退出]]`;
C. **a temporary ordinary-action candidate that is locatable on this very screenshot**, written
   `ORDINARY_CONTROL[<the element's own wording, or the name you give it>]`. Nothing needs to be
   registered, no template and no prior verification is required. This is the normal answer here.

## Where a point may be (directive §三 -- one of these, and only these)
* the centre of a text box this frame's OCR read (use a `text` and `box` from the request file);
* a region an existing template or an existing control-experience record matches on this frame --
  say so in `grounding_basis` and name it in `grounding_ref`;
* a wordless element next to text the frame really drew: give `target_anchor` as
  `{{"text": "<the text it sits by>", "dx_norm": <centre offset x>, "dy_norm": <centre offset y>,
  "w_norm": <width>, "h_norm": <height>}}` -- e.g. the icon directly above the label `说明`.
**Never invent a coordinate.** If you cannot ground a point, answer with no `target_point` and say
in `uncertainty` what is missing; a refusal is a valid, useful answer.

## Boundary (directive §五)
You may freely *describe* a page that sells things -- gems, speed-ups, packs -- and your `note`,
`uncertainty` and `expected_result` may name them. What you may not propose is *pressing* such a
thing: an action whose own target is a purchase, a recharge, a currency spend, or an irreversible
or high-value operation is refused outright. Low-risk actions (close / back / view / claim) are
allowed **even on a page that offers purchases**, and that is exactly the judgement being asked for.

## The answer (these keys exactly; the runtime rejects anything else)
    unknown_type        "CONTROL"
    candidate_semantics ["what this element is", ...]
    proposed_action     one of A/B/C above
    expected_result     what should be observable after it happens
    uncertainty         how sure you are, in your own words (kept verbatim)
optional: `target_point` `[x, y]` · `target_bbox` `{{x_norm,y_norm,w_norm,h_norm}}` ·
`target_anchor` · `action_kind` (`SKILL` | `L1` | `ORDINARY_CONTROL`) · `target_semantics` ·
`grounding_basis` (`OCR_BOX` | `TEMPLATE` | `ANCHORED_TO_TEXT` | `EXPERIENCE`) · `grounding_ref` ·
`alternative_actions` · `note`

## Writing it (one command only -- it validates with the runtime's own parser)
1. write your JSON to a scratch file, e.g. `{root}\\learning\\_answer.json`;
2. run
       {py} tools\\unknown_advisor.py --answer {request.request_id} --answer-file {root}\\learning\\_answer.json
   If it prints `refused: ...`, fix the answer and run it again; a refusal names the field at fault.
   The answer lands in {answers} -- never write that file yourself.

## Report back
The answer file path, the point you chose and why it is on something this frame really drew, and --
if you could not ground one -- say that plainly instead of guessing a coordinate.
"""

    # ------------------------------------------------------------------ plumbing

    def _append(self, row: Mapping[str, Any]) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            record = {"at": _now()}
            record.update({str(k): v for k, v in row.items()})
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - the audit must not break the channel
            pass

    def _record_model_outcome(self, record: Dispatch, *, success: bool, state: str) -> None:
        """Feed the model router its own evidence, so the choice stops being a cold start."""
        try:
            from .workbuddy_model_router import ModelOutcome

            store = getattr(self.router, "store", None)
            if store is None:
                return
            store.append(ModelOutcome(
                model=record.model or "",
                task_type=record.task_type or self._task_type,
                success=bool(success),
                note=f"unknown question {record.request_id}: {state}",
            ))
        except Exception:  # noqa: BLE001
            pass
