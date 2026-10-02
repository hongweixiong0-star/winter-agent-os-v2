"""Read-only: today's real failure distribution from the production episode ledger.

Schema (verified by inspecting a real row, not assumed):
  result / verifier_ok / session_outcome / observed_change / failure_type /
  skill / goal_id / capability / recorded_at / verifier_evidence
"""
import json, collections, pathlib

root = pathlib.Path(__file__).resolve().parent
p = root / "learning" / "episodes.jsonl"

size = p.stat().st_size
chunk = min(size, 24 * 1024 * 1024)
with p.open("rb") as f:
    f.seek(size - chunk)
    blob = f.read().decode("utf-8", "replace")
lines = blob.splitlines()
if size > chunk:
    lines = lines[1:]

rows = []
for line in lines:
    line = line.strip()
    if line.startswith("{"):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass

print("rows read:", len(rows), "| ledger %.1f MB, window %.1f MB" % (size / 1e6, chunk / 1e6))

by_day = collections.Counter(str(r.get("recorded_at") or "")[:10] for r in rows)
print("days in window:", dict(sorted(by_day.items())))

today = sorted(by_day)[-1]
todays = [r for r in rows if str(r.get("recorded_at") or "").startswith(today)]
print("\ntoday =", today, "rows:", len(todays))

print("\n-- result --")
for k, v in collections.Counter(r.get("result") for r in todays).most_common():
    print("   %-24s %d" % (k, v))

print("\n-- verifier_ok --")
for k, v in collections.Counter(r.get("verifier_ok") for r in todays).most_common():
    print("   %-24s %d" % (k, v))

failed = [r for r in todays if r.get("verifier_ok") is False or r.get("result") in ("FAILED", "FAILURE")]
print("\nFAILED-ish:", len(failed))

print("\n-- FAILED by failure_type --")
for k, v in collections.Counter((r.get("failure_type") or "(none)") for r in failed).most_common(20):
    print("   %-58s %d" % (k, v))

print("\n-- FAILED by skill --")
for k, v in collections.Counter((r.get("skill") or "?") for r in failed).most_common(15):
    print("   %-44s %d" % (k, v))

print("\n-- FAILED by goal --")
for k, v in collections.Counter((r.get("goal_id") or "?") for r in failed).most_common(15):
    print("   %-44s %d" % (k, v))

print("\n-- FAILED observed_change --")
for k, v in collections.Counter(str(r.get("observed_change")) for r in failed).most_common(8):
    print("   %-44s %d" % (k, v))

print("\n-- recognition_error field present on failed rows? --")
print("   ", sum(1 for r in failed if r.get("recognition_error")), "/", len(failed))

print("\n-- last 6 failed rows --")
for r in failed[-6:]:
    print("   %s | %-28s | %-26s | %-38s | exp=%s | act=%s" % (
        (r.get("recorded_at") or "")[11:19], r.get("skill"), r.get("failure_type"),
        str(r.get("decision_reason"))[:38], str(r.get("expected_result"))[:24],
        str(r.get("action"))[:28]))
