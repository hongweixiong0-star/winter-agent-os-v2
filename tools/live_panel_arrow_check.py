"""Verify on the device that a 快捷面板 row's tap point lands on that row's own control.

Why this exists.  A row's arrow point is what the executor taps, and it had been computed by taking
the min..max of "blue" inside a band that reached past the panel's own right edge into the city --
which is why the point came out at x 0.5979-0.6667 while the button's own cyan spans x 384-425
(issue #98).  The repair locates the button by the white chevron the client draws inside it, and the
verification that matters cannot be done offline: whether the tap *lands on the control* is a fact
about the device.

What it does, every coordinate taken from the frame it is about to tap:

    1. reach HOME by the client's own controls (never by BACK, which opens 退出确认 on the map);
    2. locate the 快捷面板 handle with ``ocr.find_quick_panel_handle`` on THIS frame and tap its
       own point -- a handle point remembered from another frame is what opened a 军师 card page once;
    3. read the open panel with the production reader, list every row's status / control / basis /
       point, and tap the point of the first row the reader says carries an enter-arrow;
    4. read the result and report whether the row's own control responded (the camp's radial menu,
       for a barracks row), writing the three frames and a JSON record.

It refuses rather than guesses: no handle on the frame, no panel after the tap, or no row with a
located arrow each end the run with the reason printed, because "the control was not on this frame"
is a real answer and a tap issued anyway is how wrong coordinates get published as measurements.

Bounded and lease-respecting: it takes the same device lease the runtime and the tap probe take, so
it cannot run at the same time as the AUTO loop, and it releases on every exit path.

The callout -- the next hop for reward collection, and one this vehicle MEASURES but deliberately does
not tap.  Tapping a 已完成 row's body is what draws it (controlled pair, 2026-09-23: no marker on the
city before the tap, no marker with the panel open, 891 px at x 0.4514-0.4958 y 0.3891-0.4437 after it,
still drawn 4 minutes later with the camera unmoved).  The locator's numbers, so the next round starts
from measurements rather than from a guess:

    city before the tap (20:02, 20:03)          nothing at all
    panel open, before the tap (20:03)          270 px -- the EXPANDED HANDLE, centre (0.6431, 0.4301)
    warehouse callout after the tap (20:04)     891 px, a 33x71 FRAGMENT (the crate icon and the hand
                                                split the white frame)
    the same marker 4 minutes later (20:08)     733 px, same box
    a barracks callout after the same tap (19:08)  519 px, same shape

So there is a usable gap -- 270 px (the handle, and only while the panel is open) versus 519-891 px (a
real callout) -- and a floor near 400 px would separate them.  It is still not enough to tap on: the
fragment's size moves with the hand's position, and only one barracks frame puts a callout that small.
The mode therefore reports the blob and what it would have tapped, and refuses to tap, until either more
frames or an icon-based basis (the crate inside, the soldier's bust) makes the floor a measurement
instead of a taste.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "dataset" / "truth_audit" / "live_panel_arrow_20260923"


#: Where the client draws its callout: above the building it is pointing at.  Measured on the two
#: live frames where it is drawn (barracks 2026-09-23 19:08 and the warehouse 20:04), its own box
#: falls inside this window.
CALLOUT_WINDOW_NORM = (0.28, 0.26, 0.66, 0.54)


def _largest_bright_blob(frame: Path):
    """The callout's own box in normalised coordinates, or ``None``.

    It is a white rounded box with an opaque icon inside, so the three channels are all very high --
    while the palest pixel of the snow behind the panel is 200-227.  But the icon and the hand split
    that white frame into pieces, so what this returns is the largest PIECE (891 px of a callout whose
    whole frame is larger), not the callout's own extent: that is why it is reported and not tapped.
    Nearby white things exist (the hand is cream, the ring is gold), so the component also has to be
    dense and above a floor, not merely a bright pixel count.
    """
    from collections import deque

    from PIL import Image

    try:
        with Image.open(frame) as source:
            image = source.convert("RGB")
            width, height = image.size
    except (OSError, ValueError):
        return None
    x0 = int(CALLOUT_WINDOW_NORM[0] * width)
    y0 = int(CALLOUT_WINDOW_NORM[1] * height)
    x1 = int(CALLOUT_WINDOW_NORM[2] * width)
    y1 = int(CALLOUT_WINDOW_NORM[3] * height)
    seen: set[tuple[int, int]] = set()
    best = None

    def bright(px) -> bool:
        r, g, b = px
        return r >= 235 and g >= 235 and b >= 235 and (b - r) <= 15

    for cy in range(y0, y1):
        for cx in range(x0, x1):
            if (cx, cy) in seen or not bright(image.getpixel((cx, cy))):
                continue
            queue, comp = deque([(cx, cy)]), []
            seen.add((cx, cy))
            while queue:
                px, py = queue.popleft()
                comp.append((px, py))
                for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                    if (x0 <= nx < x1 and y0 <= ny < y1 and (nx, ny) not in seen
                            and bright(image.getpixel((nx, ny)))):
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(comp) < 800:
                continue
            xs = [q[0] for q in comp]
            ys = [q[1] for q in comp]
            if best is None or len(comp) > best[4]:
                best = (min(xs), min(ys), max(xs), max(ys), len(comp))
    if best is None:
        return None
    return (round(best[0] / width, 4), round(best[1] / height, 4),
            round(best[2] / width, 4), round(best[3] / height, 4), best[4])


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    #: How many times to swipe the panel's own list before choosing a row.  The rows the directive
    #: names (联盟捐献 / 英雄招募 / 我的奖励) are below the first screen.
    parser.add_argument("--scroll", type=int, default=0)
    #: Act on a NAMED row instead of the first one that carries a located arrow.
    parser.add_argument("--row", default="")
    #: What to tap on that row: the enter-arrow's own point, or the row's body (its label).
    parser.add_argument("--on", choices=("arrow", "body"), default="arrow")
    #: Measure the client's own callout on the resulting frame -- and do NOT tap it.  The tap is the
    #: hop the project has never tried (the client draws the callout above the building it wants looked
    #: at, and every historical tap went to the ring on the ground), but the locator is not sound yet:
    #: see ``_largest_bright_blob`` for the four frames that say so.  Naming it "measure" keeps the
    #: vehicle honest -- it reports the blob and what it would have tapped, and refuses to tap.
    parser.add_argument("--measure-callout", action="store_true")
    args = parser.parse_args()

    from winter_agent_v2.ocr import find_quick_panel_handle, read_quick_panel
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    #: the probe's own build/lease helpers, so this vehicle cannot drift from the runtime's device
    #: setup or from the lease discipline (``tools`` is not a package: import it the way the library
    #: finds it)
    sys.path.insert(0, str(ROOT / "tools"))
    from cq_nav_tap_probe import build, take_the_lease

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    record: dict = {"recorded_at": datetime.now(timezone.utc).isoformat(), "steps": []}

    lease = take_the_lease("panel_arrow")
    if lease is None:
        return 3
    device, hybrid, template = build()
    status = device.status()
    print(f"device: {status.resolution} focus={status.foreground_package}")

    # the OCR service the panel reader needs, built exactly as the probe builds one
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

    def look(tag: str):
        path = OUT_DIR / f"{stamp}_{tag}.png"
        device.screenshot(path)
        return path, hybrid.observe(path)

    try:
        # ---- 1. HOME, by the client's own controls -------------------------------------------------
        path, state = look("00_start")
        for attempt in range(4):
            state = hybrid.observe(path)
            print(f"  start: page={state.page.value} conf={state.confidence:.2f} ({path.name})")
            if state.page.value == "HOME":
                break
            if state.page.value == "UNKNOWN":
                time.sleep(2.5)
                path, state = look(f"00_start_retry{attempt}")
                if state.page.value == "UNKNOWN":
                    print("ABORT: the frame reads UNKNOWN twice; not navigating on it")
                    record["aborted"] = "start_frame_unreadable"
                    return 4
                if state.page.value == "HOME":
                    break
            semantic = {"MAP": "BTN_OPEN_HOME", "POPUP": "BTN_CLOSE"}.get(state.page.value)
            hop = template.semantic.find(path, semantic) if semantic else None
            if hop is None:
                print(f"ABORT: on {state.page.value} with no registered way home")
                record["aborted"] = f"stuck_on_{state.page.value}"
                return 4
            roi = hop[2]
            point = (round((roi["x_norm"] + roi["w_norm"] / 2) * status.resolution[0]),
                     round((roi["y_norm"] + roi["h_norm"] / 2) * status.resolution[1]))
            print(f"  recovering: {semantic} on this frame -> tap {point}")
            device.tap(*point)
            time.sleep(2.5)
            path, state = look(f"00_recover{attempt}")
        record["steps"].append({"what": "reached HOME", "frame": str(path)})

        # ---- 2. the handle, located on this frame -------------------------------------------------
        handle = find_quick_panel_handle(path, panel_open=False)
        print(f"  handle on this frame: {json.dumps(handle, ensure_ascii=False) if handle else None}")
        record["handle"] = handle
        if handle is None:
            print("ABORT: this frame draws no 快捷面板 handle; not tapping a remembered point")
            record["aborted"] = "handle_not_drawn_on_this_frame"
            return 4
        hp = (round(handle["point_norm"][0] * status.resolution[0]),
              round(handle["point_norm"][1] * status.resolution[1]))
        print(f"  tapping the handle at its own point {hp}")
        device.tap(*hp)
        time.sleep(2.5)
        path, state = look("01_after_handle")
        panel = state.quick_panel or {}
        print(f"  after handle: page={state.page.value} panel_open={panel.get('open')} "
              f"rows={len(panel.get('rows') or [])} ({path.name})")
        record["steps"].append({"what": "tapped handle at its own point", "tap": list(hp),
                                "panel_open_after": bool(panel.get("open")), "frame": str(path)})
        if not panel.get("open"):
            print("ABORT: the panel did not open; nothing to verify a row point against")
            record["aborted"] = "panel_did_not_open"
            return 4

        def read_rows(tag: str):
            """This frame's rows, printed and returned -- the panel is re-read after every scroll."""
            snap, snap_state = look(tag)
            snap_panel = snap_state.quick_panel or {}
            found = []
            for row in snap_panel.get("rows") or []:
                found.append({k: row.get(k) for k in
                              ("key", "label", "status", "source_word", "control", "arrow_basis",
                               "arrow_norm", "arrow_box_norm", "done_norm", "badge", "y_norm")})
                print(f"    {str(row.get('key')):34} status={str(row.get('status')):12} "
                      f"control={str(row.get('control')):6} basis={str(row.get('arrow_basis')):22} "
                      f"point={row.get('arrow_norm')} box={row.get('arrow_box_norm')}")
            return snap, found

        # ---- 3. the rows, and the first one that draws an enter-arrow ------------------------------
        #: how far a swipe travels inside the panel's own list (the panel occupies the left ~0.58 of
        #: the frame; the swipe stays well inside it and away from every row's control column)
        SWIPE_X = 0.30
        Y_FROM, Y_TO = 0.62, 0.30
        for step in range(max(0, args.scroll)):
            x = round(SWIPE_X * status.resolution[0])
            print(f"  scrolling the panel's list ({step + 1}/{args.scroll}): swipe "
                  f"({x},{round(Y_FROM * status.resolution[1])}) -> ({x},{round(Y_TO * status.resolution[1])})")
            device.swipe(x, round(Y_FROM * status.resolution[1]),
                         x, round(Y_TO * status.resolution[1]), duration_ms=600)
            time.sleep(1.5)
            frame, rows = read_rows(f"01_scroll{step + 1}")
            record.setdefault("scrolls", []).append({"step": step + 1, "rows": rows, "frame": str(frame)})
        if not args.scroll:
            frame, rows = read_rows("01_rows")
        record["panel_rows"] = rows

        if args.row:
            target = next((r for r in rows if str(r.get("key")) == args.row), None)
            if target is None:
                print(f"ABORT: this frame's panel shows no row keyed {args.row!r} "
                      f"(keys: {[r.get('key') for r in rows]})")
                record["aborted"] = f"row_{args.row}_not_on_this_frame"
                return 4
        else:
            target = next((r for r in rows
                           if str(r.get("control")) == "ARROW"
                           and str(r.get("arrow_basis")) == "ROW_BUTTON_SCAN"
                           and r.get("arrow_norm")), None)
            if target is None:
                print("ABORT: no row on this frame carries a located enter-arrow")
                record["aborted"] = "no_row_with_a_located_arrow"
                return 4

        if args.on == "body":
            # The row's body is its label, and the only honest source for its position is the frame:
            # the label is an OCR token this frame drew, and the row's own y_norm is where the reader
            # puts that row.  The registered QUICK_PANEL_ROW_* ROIs cannot be used here -- all three
            # were measured with the panel at its top offset.
            token = None
            for tok in ocr.recognize(frame).tokens:
                text = str(getattr(tok, "text", "")).strip()
                if not text or text != str(target.get("label") or ""):
                    continue
                ys = [pt[1] for pt in tok.box]
                cy = (min(ys) + max(ys)) / 2 / status.resolution[1]
                if abs(cy - float(target.get("y_norm") or 0)) <= 0.02:
                    xs = [pt[0] for pt in tok.box]
                    token = (min(xs), max(xs), min(ys), max(ys))
                    break
            if token is None:
                print(f"ABORT: this frame draws no text token equal to {target.get('label')!r} "
                      f"on that row; not tapping a remembered box")
                record["aborted"] = "row_label_not_read_on_this_frame"
                return 4
            point = (round((token[0] + token[1]) / 2), round((token[2] + token[3]) / 2))
            print(f"  tapping row {target['key']}'s BODY: label {target.get('label')!r} at "
                  f"x {token[0]}-{token[1]} y {token[2]}-{token[3]} -> {point}")
        else:
            if not target.get("arrow_norm"):
                print(f"ABORT: row {target['key']} carries no located arrow "
                      f"(control={target.get('control')}, basis={target.get('arrow_basis')})")
                record["aborted"] = f"row_{target['key']}_has_no_located_arrow"
                return 4
            point = (round(target["arrow_norm"][0] * status.resolution[0]),
                     round(target["arrow_norm"][1] * status.resolution[1]))
            print(f"  tapping row {target['key']}'s own point {point} "
                  f"(box x {target['arrow_box_norm']['x_norm']}-"
                  f"{target['arrow_box_norm']['x_norm'] + target['arrow_box_norm']['w_norm']:.4f} "
                  f"w={target['arrow_box_norm']['w_norm']})")
        device.tap(*point)
        time.sleep(2.5)
        path, state = look("02_after_row")
        training = (state.training or {}) if isinstance(state.training, dict) else {}
        template_state = template.observe(path)
        ttraining = (template_state.training or {}) if isinstance(template_state.training, dict) else {}
        print(f"  after row: page={state.page.value} | training={json.dumps(training, ensure_ascii=False)}")
        print(f"             template-only page={template_state.page.value} "
              f"training={json.dumps(ttraining, ensure_ascii=False)}")
        print(f"             frame {path.name}")
        record["steps"].append({
            "what": f"tapped a row's own {'body' if args.on == 'body' else 'located point'}",
            "row": target["key"], "on": args.on, "tap": list(point),
            "arrow_norm": target["arrow_norm"], "arrow_box_norm": target["arrow_box_norm"],
            "page_after": state.page.value, "training_after": training,
            "template_training_after": ttraining, "frame": str(path),
        })
        if args.measure_callout:
            callout = _largest_bright_blob(frame)
            print(f"  callout blob on this frame: {callout}")
            record["callout"] = callout
            if callout is None:
                print("  nothing near-white and dense enough in the callout window on this frame")
            else:
                cbox = (round(callout[0] * status.resolution[0]), round(callout[1] * status.resolution[1]),
                        round(callout[2] * status.resolution[0]), round(callout[3] * status.resolution[1]))
                print(f"  its centre would be {((cbox[0] + cbox[2]) // 2, (cbox[1] + cbox[3]) // 2)} "
                      f"px, in a box {cbox} -- NOT tapped: the locator is unsound (see the docstring)")
            record["callout_tap"] = ("withheld: the largest near-white blob is the panel's own handle on "
                                     "a panel frame (270px at 0.6431,0.4301) and a 33x71 fragment of a "
                                     "real callout (891px) on another, so no single threshold is a basis")
            print(f"  callout tap withheld: {record['callout_tap']}")

        record["verdict"] = (
            "the row's own control responded: the camp menu opened"
            if training.get("menu_open") or ttraining.get("menu_open")
            else f"the row's control did NOT respond (page={state.page.value}); "
                 "the tap point did not reach it"
        )
        print(f"VERDICT: {record['verdict']}")
        # and the panel state after, so the next reader knows whether it closed or stayed
        print(f"  panel_open_after={((state.quick_panel or {}).get('open'))}")
        return 0
    finally:
        (OUT_DIR / f"panel_arrow_{stamp}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        lease.release(result="OK", reason="panel row point verification")


if __name__ == "__main__":
    raise SystemExit(main())
