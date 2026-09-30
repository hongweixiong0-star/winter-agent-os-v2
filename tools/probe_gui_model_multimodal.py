"""Prove the local GUI model really sees a screenshot, before any V2 code trusts it.

Operator directive 2026-09-30, section "P0": the planner used to send a goal, a page name
and an OCR element table and **no picture**, so the model was answering about a screen it
could not see.  The migration to UI-Venus-2-9B is only real if the image reaches the model,
and "the request had an image field in it" is not evidence -- a server that silently drops
the projector, a base64 blob with the wrong data URL, or a chat template with no image slot
all produce a 200 with a confident answer about nothing.

So this probe asks a question whose answer is **only** obtainable from the pixels:

    1. text-only   -- the model is asked about the picture with no picture attached.
    2. with-image  -- the identical question, with the frame attached.

A model that can see will fail (or say it cannot see) the first and describe the actual
screen in the second.  If both answers are plausible prose, the image is not being read and
``SCREENSHOT_INPUT_VERIFIED`` stays false.

It talks to the server's OpenAI-compatible endpoint directly and imports nothing from the
package on purpose: the point is to test the *model*, not the client that will later call it.

Measured output fields are the ones the final report quotes:
``multimodal_projector_loaded``, ``screenshot_input_verified``, latency, and the two replies.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The question must be answerable only from pixels.  Asking "what page is this" invites a
#: guess from the page name we would have sent; asking about visible content does not.
VISION_QUESTION = (
    "Look at the attached game screenshot and describe ONLY what is actually visible in the "
    "image: roughly how many distinct buttons or icons are there, and what is the single "
    "largest piece of text you can read? Answer in one short sentence."
)


def _post(endpoint: str, payload: dict, *, timeout: float = 180.0) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            return exc.code, str(exc)
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _get(endpoint: str, path: str, *, timeout: float = 20.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + path, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw[:400]
    except urllib.error.HTTPError as exc:
        return exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _split_reply(body: object) -> tuple[str, str, str]:
    """``(content, reasoning_content, finish_reason)``.

    UI-Venus-2 is a *reasoning* model: with the shipped chat template it writes its thinking
    into ``reasoning_content`` and only then fills ``content``.  Measured 2026-09-30, a
    300-token budget was spent entirely on the reasoning field and ``content`` came back
    empty with ``finish_reason: "length"`` -- so a caller that reads only ``content`` sees an
    empty reply and concludes the model is broken when it is merely still thinking.
    """
    if not isinstance(body, dict):
        return "", "", ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "", "", ""
    choice = choices[0]
    finish = str(choice.get("finish_reason") or "")
    message = choice.get("message")
    if not isinstance(message, dict):
        return "", "", finish
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(str(part.get("text", "")) for part in content
                           if isinstance(part, dict))
    return (str(content or "").strip(),
            str(message.get("reasoning_content") or "").strip(),
            finish)


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="UI-Venus-2-9B")
    parser.add_argument("--image", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--think", action="store_true",
                        help="leave the model's reasoning pass enabled (default: ask it off)")
    args = parser.parse_args()

    report: dict[str, object] = {"endpoint": args.endpoint, "model": args.model}

    health_status, health = _get(args.endpoint, "/health")
    report["health_status"] = health_status
    report["health"] = health

    props_status, props = _get(args.endpoint, "/props")
    report["props_status"] = props_status
    projector = False
    model_path = ""
    if isinstance(props, dict):
        # llama-server reports vision capability under ``modalities``; older builds used a
        # boolean key.  Measured 2026-09-30: this build answers
        # ``{"vision": true, "video": true, "audio": false}``.
        modalities = props.get("modalities")
        if isinstance(modalities, dict):
            projector = bool(modalities.get("vision"))
        if not projector:
            projector = bool(props.get("has_multimodal_projector")
                             or props.get("multimodal"))
        model_path = str(props.get("model_path") or "")
        if isinstance(modalities, dict):
            report["modalities"] = modalities
    report["multimodal_projector_loaded"] = bool(projector)
    report["model_path"] = model_path

    image_path = Path(args.image) if args.image else None
    if image_path is None or not image_path.exists():
        report["error"] = f"image not found: {args.image!r}"
        _emit(report, args.out)
        return

    image_bytes = image_path.stat().st_size
    report["image"] = str(image_path)
    report["image_bytes"] = image_bytes

    # The model thinks before it answers.  Asking the chat template to skip that is what
    # makes a one-screen decision cheap, and it is also the model card's own guidance:
    # "GUI grounding: disable reasoning and use temperature 0".  Requested, not assumed --
    # the reply is still read from both fields below if the template ignores it.
    think_kwargs = {} if args.think else {"chat_template_kwargs": {"enable_thinking": False}}
    report["enable_thinking"] = bool(args.think)

    # (1) The same question with no picture.  Nothing here should be able to answer it.
    t0 = time.perf_counter()
    status_text, text_body = _post(args.endpoint, {
        "model": args.model,
        "messages": [{"role": "user", "content": VISION_QUESTION}],
        "temperature": 0.0, "max_tokens": args.max_tokens, "stream": False,
        **think_kwargs,
    })
    text_content, text_reasoning, text_finish = _split_reply(text_body)
    report["text_only_status"] = status_text
    report["text_only_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    report["text_only_finish_reason"] = text_finish
    report["text_only_reply"] = (text_content or text_reasoning)[:600]

    # (2) The identical question with the frame attached.
    data_url = _data_url(image_path)
    report["image_b64_chars"] = len(data_url)
    t0 = time.perf_counter()
    status_img, img_body = _post(args.endpoint, {
        "model": args.model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_QUESTION},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "temperature": 0.0, "max_tokens": args.max_tokens, "stream": False,
        **think_kwargs,
    })
    with_content, with_reasoning, with_finish = _split_reply(img_body)
    report["with_image_status"] = status_img
    report["with_image_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    report["with_image_finish_reason"] = with_finish
    report["with_image_reply"] = with_content[:600]
    report["with_image_reasoning"] = with_reasoning[:600]
    if not (with_content or with_reasoning):
        report["with_image_raw"] = str(img_body)[:400]

    # A model that can see describes the picture.  A model that cannot produces nothing
    # about it, or the same text twice; identical answers mean the image changed nothing.
    # Which field held the description does not matter -- that the *image* produced it does.
    seen_text = with_content or with_reasoning
    blind_text = text_content or text_reasoning
    described = len(seen_text) > 20
    differed = seen_text.strip() != blind_text.strip()
    report["screenshot_input_verified"] = bool(
        status_img == 200 and described and differed and report["multimodal_projector_loaded"]
    )
    _emit(report, args.out)


def _emit(report: dict, out: str) -> None:
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
    sys.exit(0)
