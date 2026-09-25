"""Read the Bear trap's live cooldown and turn it into a real reservation.

This is the missing link that made the Bear P0 miss its window: learning/timed_event_schedule.json
has `roles: []`, so there is nothing for event_schedule.py to wake on.  A reservation may only
come from a client countdown reading it has actually seen -- never from a table typed by hand.

The arithmetic is timezone-free on purpose: observed UTC + remaining seconds = an absolute
future instant, which needs no IANA zone guess.
"""
from __future__ import annotations

import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.device_lease import DeviceLease
from winter_agent_v2.ocr import OCRService, RapidOCRBackend

ROLE_ID = "1171757165"
EVENT_ID = "BEAR_HUNT"
COOLDOWN_RE = re.compile(r"冷却中[：:]\s*(?:(\d+)天)?\s*(\d{1,2})[::](\d{2})[::](\d{2})")


def main() -> int:
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    lease = DeviceLease(root=ROOT)
    rec, why = lease.request(
        capability_id="BEAR_HUNT", job_id="bear-cooldown-read",
        trace_id="WORKBUDDY_BEAR_P0", reason="read live client cooldown to create a Bear reservation",
    )
    if rec is None:
        print("ABORT device busy:", why)
        return 2
    lease_id = rec.lease_id or ""

    try:
        device = ADBDevice(Path(cfg["device"]["adb_path"]), cfg["device"]["serial"], production=True)
        device.resolve_connection()
        svc = OCRService(RapidOCRBackend(module_path=Path(cfg["ocr"]["module_path"])))
        OUT = ROOT / "dataset/raw/explore"
        OUT.mkdir(parents=True, exist_ok=True)

        # We are currently on the world map. Walk back: 联盟 -> 联盟领地 -> 特殊建筑.
        device.tap(511, 1243)          # bottom nav: 联盟
        import time as _t; _t.sleep(2.5)
        device.tap(246, 804)           # 联盟领地
        _t.sleep(2.5)
        device.tap(510, 123)           # 特殊建筑
        _t.sleep(2.5)

        observed_at = datetime.now(timezone.utc)
        stamp = observed_at.strftime("%Y%m%d_%H%M%S")
        frame = OUT / f"{stamp}_bear_cooldown.png"
        device.screenshot(frame)

        result = svc.recognize(frame)
        hits = [t for t in result.tokens if "冷却中" in t.text]
        if not hits:
            print("cooldown text NOT found. tokens were:")
            for t in result.tokens:
                print("   ", round(t.confidence, 3), repr(t.text))
            return 1
        raw = max(hits, key=lambda t: t.confidence).text
        print("raw client text:", repr(raw))

        m = COOLDOWN_RE.search(raw)
        if not m:
            print("could not parse cooldown from:", repr(raw))
            return 1
        days = int(m.group(1) or 0)
        seconds = days * 86400 + int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
        reserved = observed_at + timedelta(seconds=seconds)
        print(f"observed_at   : {observed_at.isoformat()}")
        print(f"remaining     : {days}d {seconds} s")
        print(f"reserved_start: {reserved.isoformat()}")
        print(f"   (+08:00)   : {reserved.astimezone(timezone(timedelta(hours=8))).isoformat()}")

        # --- persist into learning/timed_event_schedule.json -> roles[] ---
        state_path = ROOT / "learning/timed_event_schedule.json"
        payload = json.loads(io.open(state_path, encoding="utf-8").read())
        roles = payload.get("roles")
        if not isinstance(roles, list):
            roles = []
            payload["roles"] = roles
        roles[:] = [r for r in roles
                    if not (str(r.get("role_id")) == ROLE_ID and str(r.get("event_id")) == EVENT_ID)]
        roles.append({
            "role_id": ROLE_ID,
            "event_id": EVENT_ID,
            "reserved_start": reserved.isoformat(),
            "role": "AUTO",
            "alliance": "zoe",
            "source": "LIVE_CLIENT_COOLDOWN",
            "observed_at": observed_at.isoformat(),
            "live_window_state": "CLOSED",
            "live_window_observed_at": observed_at.isoformat(),
            "live_window_source": "LIVE_CLIENT_OCR",
            "time_zone": None,
            "lead_overrides": {},
            "notes": (
                f"Read live on the client at special buildings: {raw!r}. "
                "Semantics are the TRAP COOLDOWN, i.e. the moment the 狩猎陷阱 stops being 冷却中 and "
                "can be built/started again -- not a separately published activity clock. "
                "Absolute instant = observed UTC + remaining seconds, so no timezone inference is involved. "
                "Participation still requires the open criterion: the trap page showing open, or a "
                "level-1 mutated Bear row appearing in the alliance rally list."
            ),
        })
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(state_path)
        print("\nwrote reservation into learning/timed_event_schedule.json roles[]")

        # --- record the same fact on the readiness ledger ---
        readiness_path = ROOT / "knowledge/events/timed_event_readiness.json"
        readiness = json.loads(io.open(readiness_path, encoding="utf-8").read())
        for ev in readiness.get("events", []):
            if str(ev.get("event_id")) != EVENT_ID:
                continue
            ev["next_open_condition"] = (
                f"LIVE READ {observed_at.isoformat()}: the 特殊建筑 list printed {raw!r}. "
                f"reserved_start recorded in learning/timed_event_schedule.json as {reserved.isoformat()} "
                f"({reserved.astimezone(timezone(timedelta(hours=8))).isoformat()} +08:00). "
                "This is the trap cooldown and not a published start time; re-read the client before acting."
            )
            ev.setdefault("readiness", {})["预约核实"] = True
            ev["readiness"]["时间独立唤醒"] = (
                "WIRED — a real RoleSchedule now exists (source LIVE_CLIENT_COOLDOWN); "
                "event_schedule.seconds_until_next_transition can produce T-30/T-15/T-5/open wakes. "
                "Live-execution evidence still pending."
            )
            ev["last_reviewed"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tmp2 = readiness_path.with_suffix(".json.tmp")
        tmp2.write_text(json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp2.replace(readiness_path)
        print("updated knowledge/events/timed_event_readiness.json")

        # --- sanity: does the schedule module now see a wake? ---
        from winter_agent_v2 import event_schedule
        schedules = event_schedule.load()
        sched = schedules.get(f"{ROLE_ID}|{EVENT_ID}")
        print("\n=== verification through the real module ===")
        print("load() sees  :", sched.event_id if sched else None)
        if sched:
            print("minutes_to_start:", round(sched.minutes_to_start(), 1))
            print("phase_at      :", sched.phase_at().value)
            print("priority_bonus:", sched.priority_bonus())
            print("sleep suggest :", round(event_schedule.seconds_until_next_transition(schedules), 1), "s")
        return 0
    finally:
        lease.release(result="ok", reason="bear cooldown read done", expect_lease_id=lease_id)


if __name__ == "__main__":
    raise SystemExit(main())
