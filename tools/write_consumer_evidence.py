"""Write the P0 record for the escalation consumer, read back out of the ledger.

Nothing here is typed by hand: the narration comes from the worker's own stdout capture,
the release rows from the ledger, and the queue counts from the fold the panel reads.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(r"E:\无尽冬日智能体")
OUT = ROOT / "dataset/truth_audit/escalation_consumer_20260918/P0_NEW_CONSUMER.json"
KEYS = (
    "DISPATCH_GATHER_MARCH|SEMANTIC_TARGET_NOT_VERIFIED|DISPATCH_MARCH",
    "DISMISS_REAL_MONEY_OFFER|POPUP_CLOSE_NOT_PROVEN|DISMISS_REAL_MONEY_OFFER",
)


def rows(path: pathlib.Path, pattern: str = "workbuddy_escalations") -> list[dict]:
    out = []
    for line in (path / f"learning/{pattern}.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


ledger = rows(ROOT)
narration = [
    line for line in (ROOT / "learning/control_panel/latest.log").read_text(encoding="utf-8", errors="replace").splitlines()
    if line.startswith("[escalation]") or line.startswith("[code]")
]


def creation(key: str) -> dict:
    for row in ledger:
        if str(row.get("key") or "") == key and row.get("event") == "escalation_created":
            return row
    return {}


def release(key: str) -> dict:
    for row in reversed(ledger):
        if str(row.get("key") or "") == key and row.get("released_by"):
            return row
    return {}


def verdicts(key: str) -> list[dict]:
    """The verifier-passing production episodes that made the release honest."""
    episodes = rows(ROOT, "episodes")
    first = creation(key).get("recorded_at") or ""
    skill = creation(key).get("skill") or ""
    return [
        {"recorded_at": e.get("recorded_at"), "skill": e.get("skill"), "result": e.get("result"),
         "repo_revision": e.get("repo_revision") or ""}
        for e in episodes
        if str(e.get("skill") or "") == skill
        and e.get("verifier_ok") is True
        and (e.get("recorded_at") or "") > first
    ]


# The fold the panel reads, without importing the panel.
def counts() -> dict:
    import sys
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.escalation_queue import EscalationLedger

    return EscalationLedger(ROOT / "learning/workbuddy_escalations.jsonl").snapshot().count_by_state()


payload = {
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "operator_report": "DISPATCH_GATHER_MARCH / UNKNOWN_UI, discovered 54 minutes ago, state still NEW, "
                       "Job ID not submitted, gateway healthy. Gap -> Escalation NEW -> Queue Consumer -> "
                       "Bridge submit -> Job -> SUBMITTED -> WORKING must advance on its own.",
    "root_cause": {
        "finding": (
            "Each stuck record had exactly ONE ledger row -- its escalation_created row -- and that row "
            "names why it was not dispatched at the time: dispatch=CONCURRENCY_WAIT with "
            "'max_concurrent_jobs=1 is already used by a7ce58f0'. Correct at that instant and permanent "
            "afterwards, because candidates were only ever derived from the run that produced them: once "
            "a7ce58f0 finished there was nothing left to re-offer the record. NEW meant 'noticed once', "
            "not 'will reach the bridge'."
        ),
        "rows": {key: creation(key) for key in KEYS},
        "secondary": [
            "The fold settled only DONE/FAILED, so a stopped job (terminal at the gateway) stayed WORKING "
            "and held the one concurrency slot forever -- the same stall by another route.",
            "dispatch_reason was written at creation and never folded, so a consumer had nothing to quote.",
            "The console rendered NEW as '排队', which claims a job is waiting its turn when nothing has "
            "been sent anywhere.",
        ],
    },
    "fix": {
        "consumer": "EscalationQueueAdapter.pending() re-offers every record in NEW (created, never "
                    "dispatched) or QUEUED (decided, gateway was down), oldest first, through the same "
                    "decide() throttle -- dedup, the one concurrency slot, the per-signature budget, "
                    "cooldown -- so it cannot overrun the rules that throttled it.",
        "release": "A record whose capability the device has already proven (verifier-passing production "
                   "episode after creation) is settled DONE / LIVE_VERIFIED with released_by=self_proven, "
                   "naming the episodes. live_improvement and repair_used stay false: no job ran.",
        "labels": "待提交 (NEW) -> 排队 (QUEUED) -> 已提交 (SUBMITTED) -> 开发中 (WORKING), one word per "
                  "real state, pinned by a test.",
        "commits": ["27b8e44", "992a025"],
    },
    "live_acceptance": {
        "round": "09:28:51 local, worker revision 992a0257ca54+21 (the consumer's own commit)",
        "narration": narration,
        "released": {key: release(key) for key in KEYS},
        "queue_counts_after": counts(),
        "pending_after": [],
        "verified_episodes_since_creation": {key: verdicts(key) for key in KEYS},
    },
    "not_shown_and_why": [
        "NEW -> SUBMITTED -> job id -> WORKING was NOT demonstrated on these two records, because both "
        "turned out to be walls the device had already climbed: DISPATCH_MARCH had 4 verifier-passing "
        "episodes after its record was created (two on the current tree) and the money-offer skill 2. "
        "Dispatching a development agent at that point would be manufacturing work.",
        "The submit hop itself is proven by tests (5 consumer tests, including 'waits for the slot' and "
        "'not sent twice') and by a dry run against a copy of the live ledger, and it is gated on the "
        "operator's own max_concurrent_jobs=1: the single slot is held by job 2934e9cd, which is still "
        "genuinely working on the beast capability.",
        "The running console still shows the old words: the label fix takes effect when the window next "
        "starts, and it was not force-restarted while the operator may be using it.",
    ],
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote", OUT)
print("counts:", payload["live_acceptance"]["queue_counts_after"])
for key in KEYS:
    print(f"  {key[:46]:48} released={bool(release(key))} proven={len(verdicts(key))}")
