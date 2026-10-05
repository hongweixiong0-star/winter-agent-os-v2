# -*- coding: utf-8 -*-
"""Dismiss the client's own 「无网络」 modal by pressing 重新连接 -- and nothing else.

Why this exists
---------------
Measured 2026-10-05. Two independent read-only runs -- the daily-board observer at 07:41 and
the intel-board observer at 08:07 -- both stalled on a frame the production observer reports as
``page=POPUP``, and pressed back five/six times without the picture changing at all. The
screenshots from both runs are byte-identical (486448 bytes) and show the game client's own
modal:

    无网络
    网络连接断开，请检查设备的网络连接是否正常。
    [ 联系客服 ]   [ 重新连接 ]

This is **not** a game screen and back cannot clear it: it is a client-level modality whose only
exits are the two buttons it draws. The earlier reading of that same frame -- written up after
the 07:41 run -- called it "a popup the tool cannot classify" and filed it as a navigation gap in
the observer. That was wrong, and the correction matters more than the tool: the environment was
broken, not the navigator. The evidence for the correction is that the two runs' frames are the
same bytes a minute and a half apart, with the device still answering adb.

What it does
------------
1. capture one frame from the device;
2. read it with the project's own OCR (``ocr_full.read_all`` -- the same reader the runtime uses);
3. find the 重新连接 control by its own drawn text and report its centre;
4. only when ``--tap`` is passed, tap that centre, then re-capture and report whether the modal
   went away.

It never taps 联系客服 (that opens a chat), and it never guesses a coordinate.

Usage
-----
    python tools/recover_no_network_prompt.py            # look only, tap nothing
    python tools/recover_no_network_prompt.py --tap      # press 重新连接 and verify
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The modal's own wording. The button is found by its drawn label, never by a position.
MODAL_TITLE = "无网络"
RECONNECT_LABEL = "重新连接"
SUPPORT_LABEL = "联系客服"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tap", action="store_true", help="press 重新连接 after locating it")
    parser.add_argument("--settle", type=float, default=4.0, help="seconds to wait after tapping")
    args = parser.parse_args()

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))

    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    ad = MaaExecutorAdapter(
        adb_path=cfg["device"]["adb_path"],
        serial=cfg["device"]["serial"],
        production=True,
        template_dir=ROOT / "dataset/candidate/templates",
        log_dir=ROOT / "learning/maa_logs",
    )
    ok, reason = ad.ensure_ready()
    if not ok:
        print(reason)
        return 3

    out = ROOT / "dataset" / "evidence" / f"no_network_recovery_{datetime.now():%Y%m%dT%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    def shot(tag: str) -> Path:
        frame = None
        for _ in range(3):
            frame = ad.capture()
            if frame is not None:
                break
            time.sleep(0.4)
        if frame is None:
            raise RuntimeError("SCREENCAP_FAILED")
        path = out / f"{tag}.png"
        Image.fromarray(np.asarray(frame)).save(path)
        return path

    def tokens(path: Path) -> list[dict]:
        with Image.open(path) as source:
            return list(read_all(source.convert("RGB")))

    before = shot("before")
    toks = tokens(before)
    print(f"frame: {before}")
    print(f"tokens: {len(toks)}")
    for t in toks:
        text = str(t["text"]).strip()
        if text and (MODAL_TITLE in text or RECONNECT_LABEL in text or SUPPORT_LABEL in text):
            print(f"   {t['centre']}  {text!r}")

    def centre_of(label: str) -> tuple[int, int] | None:
        for t in toks:
            if label in str(t["text"]).strip():
                return (int(t["centre"][0]), int(t["centre"][1]))
        return None

    reconnect = centre_of(RECONNECT_LABEL)
    support = centre_of(SUPPORT_LABEL)
    title = centre_of(MODAL_TITLE)
    print()
    print(f"modal title present : {title is not None}  {title}")
    print(f"重新连接 centre      : {reconnect}")
    print(f"联系客服 centre      : {support}  (never tapped)")

    if reconnect is None:
        if title is None:
            print("\nno 无网络 modal on this frame -- nothing to do")
            return 0
        print("\n!! the modal is up but 重新连接 was not read; not guessing a position")
        return 5

    if not args.tap:
        print("\n--tap not passed: located it, tapped nothing")
        return 0

    print(f"\ntap -> {ad.click(reconnect[0], reconnect[1])}")
    time.sleep(args.settle)
    after = shot("after")
    after_toks = tokens(after)
    still_up = any(MODAL_TITLE in str(t["text"]).strip() for t in after_toks)
    print(f"modal still present after tapping: {still_up}")
    (out / "result.json").write_text(json.dumps({
        "reconnect_centre": reconnect,
        "support_centre": support,
        "modal_present_after": still_up,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nEVIDENCE: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
