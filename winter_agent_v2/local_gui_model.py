"""The local GUI model, and the one file that knows where it lives.

Operator directive 2026-09-30: the single runtime local model is **UI-Venus-2-9B Q4_K_M**
served locally.  This module replaces ``local_qwen.py`` and is the same idea under a
provider-neutral name: the endpoint, the model tag, the quantisation and the context budget
live here and nowhere else, so "which local model" stays a one-file question and the
planner, the runtime and the tests read it from one place.

Why the rename is not cosmetic
------------------------------
The old module was named for a model *family*, and the name leaked: the constant
``SOURCE_LOCAL_QWEN`` was written into advice records, the failure prefixes said
``LOCAL_QWEN_``, and the ledger file was ``local_qwen_calls.jsonl``.  Swapping the weights
without renaming would have left every record in the tree describing a model that is no
longer running -- the exact "plausible-looking source of truth that nothing reads" the
constitution forbids.  So the identifiers move with the model.

One protocol, no router
-----------------------
The directive forbids a second model framework, and none is needed: **llama-server, vLLM and
Ollama all expose the same OpenAI-compatible ``/v1/chat/completions`` shape**, images
included.  One wire format therefore serves any of them, which is why there is a ``provider``
tag recorded in the ledger but no branching on it here.  Adding a second model later means
adding a config section, not a class.

What it deliberately is not
---------------------------
* **Not a dependency.**  ``available()`` is a bounded probe and ``ask_json`` returns a result
  object rather than raising, so a stopped server, a missing model or a slow reply all leave
  the AUTO cycle running on the rules and skills it already had.
* **Not a decision maker.**  It sends a prompt and returns text.  Parsing, validating and
  refusing are ``ui_planner``'s job, because a client that improvises about a reply is a
  client that feeds invented actions into a live game.
* **Not a place coordinates can come from.**  The model may *propose* a region, but the reply
  is validated against the current frame by ``ui_planner`` and grounded by the executor; see
  the ``candidate_bbox_norm`` contract there.

The screenshot is mandatory
---------------------------
``multimodal`` is on by default and ``ask_json`` **refuses to send a text-only turn when it
is**.  The P0 defect this migration fixes is precisely that: the planner used to send a goal,
a page name and an OCR table and no picture, so the model answered about a screen it could
not see.  A missing frame is therefore recorded as ``LOCAL_GUI_MODEL_NO_SCREENSHOT`` rather
than quietly degrading to the old, blind behaviour.

Measured on this machine 2026-09-30: llama-server (llama.cpp b11284, CUDA 12.4) serving
``UI-Venus-2-9B-Q4_K_M.gguf`` with ``mmproj-UI-Venus-2-9B-f16.gguf`` on ``127.0.0.1:8080``.
The predecessor was Ollama on ``127.0.0.1:11434`` serving ``qwen3635bagent-q3:latest`` (35.5B
MoE, Q3_K_M), measured at p50 17.9 s / p95 42.9 s per plan and 11 timeouts in 79 calls.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: What kind of model this is.  Recorded, never branched on -- see the module docstring.
DEFAULT_PROVIDER = "UI_VENUS"

#: Where the local model server answers.  Loopback only, deliberately: this is the
#: machine's own deployment, not a network service.  Measured 2026-09-30: port 8080 is
#: already held by another local service on this machine, so the GUI model takes 18080 and
#: the port is stated here rather than discovered, so "which server" stays one line.
DEFAULT_ENDPOINT = "http://127.0.0.1:18080"

#: The served model name.  Deliberately the family name, not the .gguf filename: the name is
#: what the server is asked for and what the ledger records, and the file may be re-quantised
#: without renaming the model.
DEFAULT_MODEL = "UI-Venus-2-9B"

DEFAULT_QUANTIZATION = "Q4_K_M"

#: Section 4: keep the existing 8K context.  A planner step is this screen's own element
#: table plus the goal and one image, and 8K covers that -- the packet builder caps and
#: truncates rather than letting the prompt grow.
DEFAULT_CONTEXT = 8192

#: A planner step must not become the slowest thing in a cycle.  Bounded, and the cycle
#: proceeds without a plan when it expires.  60 s rather than the old 45 s because the first
#: call also has to run the vision tower; the steady state is far below it either way.
DEFAULT_TIMEOUT_S = 60.0

#: A one-screen decision is short.  Capping the reply is what keeps a chatty model from
#: spending the cycle's time on prose the planner will only reject.
DEFAULT_MAX_TOKENS = 400

#: Probe cache.  ``available()`` may be called once per cycle; a TCP connect per call
#: would be a per-cycle syscall for information that changes on the scale of minutes.
PROBE_TTL_S = 30.0

LEDGER_PATH = PROJECT_ROOT / "learning" / "local_gui_model_calls.jsonl"
LEDGER_LIMIT = 2000


@dataclass(frozen=True)
class GUIModelCall:
    """One exchange with the local model, including the ones that produced nothing."""

    ok: bool
    text: str = ""
    error: str = ""
    model: str = ""
    provider: str = ""
    quantization: str = ""
    latency_ms: float = 0.0
    prompt_chars: int = 0
    #: Whether a fresh frame actually travelled with this call, and what it was.  Recorded so
    #: ``SCREENSHOT_INPUT_VERIFIED`` is a measurement rather than a claim: a row with
    #: ``image_sent: false`` is the old blind behaviour, and it should never appear again.
    image_sent: bool = False
    image_bytes: int = 0
    image_digest: str = ""

    def to_row(self, *, purpose: str = "", element_count: int = 0) -> dict[str, Any]:
        return {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "provider": self.provider,
            "model": self.model,
            "quantization": self.quantization,
            "ok": self.ok,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "prompt_chars": self.prompt_chars,
            "reply_chars": len(self.text or ""),
            "element_count": element_count,
            "image_sent": self.image_sent,
            "image_bytes": self.image_bytes,
            "image_digest": self.image_digest,
        }


class LocalGUIModel:
    """An OpenAI-shaped chat call to the machine's own GUI model, every failure bounded."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        provider: str = DEFAULT_PROVIDER,
        quantization: str = DEFAULT_QUANTIZATION,
        context: int = DEFAULT_CONTEXT,
        multimodal: bool = True,
        think: bool = False,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        ledger_path: Path | str | None = None,
    ) -> None:
        self.endpoint = str(endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.model = str(model or DEFAULT_MODEL)
        self.provider = str(provider or DEFAULT_PROVIDER)
        self.quantization = str(quantization or DEFAULT_QUANTIZATION)
        self.context = int(context)
        self.multimodal = bool(multimodal)
        #: Whether the model is allowed its reasoning pass.  Off by default: a GUI control
        #: loop wants the decision, not the deliberation, and the deliberation is what made
        #: the reply come back empty.  See the payload comment in ``ask_json``.
        self.think = bool(think)
        self.timeout_s = float(timeout_s)
        self.max_tokens = int(max_tokens)
        self.ledger_path = Path(ledger_path) if ledger_path else LEDGER_PATH
        self._probe: tuple[float, bool, str] | None = None

    #: The old name, kept because "context window" and "num_ctx" are the same quantity and a
    #: second attribute spelling it differently is how two sources of truth start.
    @property
    def num_ctx(self) -> int:
        return self.context

    # ------------------------------------------------------------------ availability
    def _host_port(self) -> tuple[str, int]:
        parsed = urllib.parse.urlsplit(self.endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return host, int(port)

    def available(self, *, force: bool = False) -> tuple[bool, str]:
        """Whether the server answers.  Cached, and a refusal says which step failed."""
        now = time.monotonic()
        if not force and self._probe is not None and now - self._probe[0] < PROBE_TTL_S:
            return self._probe[1], self._probe[2]
        host, port = self._host_port()
        verdict: tuple[bool, str]
        try:
            with socket.create_connection((host, port), timeout=2.0):
                verdict = (True, f"reachable at {self.endpoint}")
        except OSError as exc:
            verdict = (False,
                       f"LOCAL_GUI_MODEL_UNAVAILABLE {host}:{port} ({type(exc).__name__})")
        self._probe = (now, verdict[0], verdict[1])
        return verdict

    # ------------------------------------------------------------------ the call
    def ask_json(
        self,
        *,
        system: str,
        user: str,
        purpose: str = "ui_plan",
        element_count: int = 0,
        image_path: Path | str | None = None,
        timeout_s: float | None = None,
    ) -> GUIModelCall:
        """One ``/v1/chat/completions`` turn, with the frame attached.  Never raises.

        ``image_path`` is required while ``multimodal`` is on: a call without a picture would
        reproduce exactly the defect this module exists to fix, so it is refused by name.
        """
        prompt_chars = len(system) + len(user)
        image_bytes, image_digest, image_error = self._read_image(image_path)
        if self.multimodal and image_error:
            call = GUIModelCall(False, error=image_error, model=self.model,
                                provider=self.provider, quantization=self.quantization,
                                prompt_chars=prompt_chars)
            self.record(call, purpose=purpose, element_count=element_count)
            return call

        ok, reason = self.available()
        if not ok:
            # Recorded, not just returned.  A client that is simply absent is the *most*
            # common failure of a local model -- server not started, model swapped out -- and
            # a helper that answered ``False`` without a row would make the ledger show "no
            # calls" while every cycle was failing, the quietest possible way to die.  The
            # frame's own evidence travels with the failure too, so "was a screenshot
            # attached" stays answerable on the rows that failed and not only on the ones
            # that succeeded.
            call = GUIModelCall(False, error=reason, model=self.model, provider=self.provider,
                                quantization=self.quantization, prompt_chars=prompt_chars,
                                image_sent=bool(image_bytes), image_bytes=len(image_bytes),
                                image_digest=image_digest)
            self.record(call, purpose=purpose, element_count=element_count)
            return call

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": str(system)},
                {"role": "user", "content": self._user_content(str(user), image_path)},
            ],
            "stream": False,
            # UI-Venus-2 is a *reasoning* model.  Measured 2026-09-30: with the shipped
            # template it spends its whole token budget in ``reasoning_content`` and returns
            # an empty ``content`` with ``finish_reason: "length"``, so a client that reads
            # only ``content`` sees a blank reply and blames the model.  Asking the template
            # to skip the pass is also the model card's own guidance -- "GUI grounding:
            # disable reasoning and use temperature 0" -- and it is what turns a one-screen
            # decision back into a sub-second decode.  Requested, not assumed: the reply
            # reader below still accepts either field if a template ignores the flag.
            "chat_template_kwargs": {"enable_thinking": bool(self.think)},
            # The planner validates the shape, so the server is asked only to remove the
            # "wrapped it in prose" failure, which is not the failure worth spending retries
            # on.  Recorded as a request, not assumed: ``_post`` retries once without it if
            # this build rejects the key.
            "response_format": {"type": "json_object"},
            # GUI planning is a control loop, not a chat: the same screen should produce the
            # same proposal, so the sampler is pinned to greedy.
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
        }
        started = time.perf_counter()
        try:
            body = self._post(payload, timeout_s=timeout_s)
        except _RejectedKey as exc:
            payload.pop("response_format", None)
            if exc.key == "temperature":
                payload.pop("temperature", None)
            try:
                body = self._post(payload, timeout_s=timeout_s)
            except Exception as exc2:  # noqa: BLE001 - every failure is data, none is fatal
                return self._failed(exc2, prompt_chars, purpose, element_count,
                                    image_bytes, image_digest)
        except Exception as exc:  # noqa: BLE001
            return self._failed(exc, prompt_chars, purpose, element_count,
                                image_bytes, image_digest)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        text = self._reply_text(body)
        call = GUIModelCall(
            ok=bool(text.strip()),
            text=text,
            error="" if text.strip() else "LOCAL_GUI_MODEL_EMPTY_REPLY",
            model=self.model,
            provider=self.provider,
            quantization=self.quantization,
            latency_ms=latency_ms,
            prompt_chars=prompt_chars,
            image_sent=bool(image_bytes),
            image_bytes=len(image_bytes),
            image_digest=image_digest,
        )
        self.record(call, purpose=purpose, element_count=element_count)
        return call

    # ------------------------------------------------------------------ image
    def _user_content(self, text: str, image_path: Path | str | None) -> Any:
        """A plain string when there is no picture, the multimodal parts list when there is.

        The bytes are inlined as a data URL.  The directive's P0 is explicit that a path or a
        filename is not a screenshot, so nothing here passes a path through as text.
        """
        if not image_path:
            return text
        path = Path(image_path)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]

    def _read_image(self, image_path: Path | str | None) -> tuple[bytes, str, str]:
        """The frame's bytes and a short digest, or an error naming what was missing."""
        if not image_path:
            if self.multimodal:
                return b"", "", "LOCAL_GUI_MODEL_NO_SCREENSHOT"
            return b"", "", ""
        path = Path(image_path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            return b"", "", f"LOCAL_GUI_MODEL_SCREENSHOT_UNREADABLE: {type(exc).__name__}"
        if not data:
            return b"", "", "LOCAL_GUI_MODEL_SCREENSHOT_EMPTY"
        return data, hashlib.sha256(data).hexdigest()[:16], ""

    # ------------------------------------------------------------------ transport
    def _post(self, payload: dict[str, Any], *, timeout_s: float | None) -> Any:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=float(timeout_s if timeout_s is not None else self.timeout_s)
            ) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                detail = ""
            lowered = detail.lower()
            if exc.code in (400, 422) and "response_format" in lowered:
                # Older builds do not accept the key.  One bounded retry without it, because
                # the alternative -- dropping the probe -- would silently lose the
                # "JSON mode" requirement on exactly those builds.
                raise _RejectedKey("response_format") from exc
            if exc.code in (400, 422) and "temperature" in lowered:
                raise _RejectedKey("temperature") from exc
            raise RuntimeError(f"HTTP {exc.code} {detail[:200]}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"reply is not JSON: {raw[:120]!r}") from exc

    @staticmethod
    def _reply_text(body: Any) -> str:
        """Read the assistant text out of the reply, reasoning field included.

        ``message.content`` may be a string or a list of parts depending on the build, and a
        server that speaks the older ``/api/chat`` shape answers with ``message`` or
        ``response``.  Reading all of them is tolerant parsing, not a second client.

        ``reasoning_content`` is the last resort rather than the first: it is the *thinking*,
        not the answer, so it is used only when the model produced nothing else.  That case
        is real -- it is what a reasoning model does when its budget runs out -- and
        returning it lets the planner report "the model only reasoned" instead of an
        indistinguishable empty reply.
        """
        if not isinstance(body, dict):
            return ""
        choices = body.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    joined = " ".join(
                        str(part.get("text", "")) for part in content if isinstance(part, dict)
                    ).strip()
                    if joined:
                        return joined
                elif content:
                    return str(content)
                if message.get("reasoning_content"):
                    return str(message["reasoning_content"])
        message = body.get("message")
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"])
        return str(body.get("response") or "")

    def _failed(self, exc: BaseException, prompt_chars: int, purpose: str,
                element_count: int, image_bytes: bytes = b"", image_digest: str = "") -> GUIModelCall:
        name = type(exc).__name__
        if isinstance(exc, (TimeoutError, socket.timeout)):
            error = f"LOCAL_GUI_MODEL_TIMEOUT: {str(exc)[:160]}"
        else:
            error = f"LOCAL_GUI_MODEL_{name.upper()}: {str(exc)[:200]}"
        call = GUIModelCall(
            False,
            error=error,
            model=self.model,
            provider=self.provider,
            quantization=self.quantization,
            prompt_chars=prompt_chars,
            image_sent=bool(image_bytes),
            image_bytes=len(image_bytes),
            image_digest=image_digest,
        )
        self.record(call, purpose=purpose, element_count=element_count)
        return call

    # ------------------------------------------------------------------ accounting
    def record(self, call: GUIModelCall, *, purpose: str = "", element_count: int = 0) -> None:
        """Append-only, bounded, and never allowed to break a cycle."""
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            rows = (
                self.ledger_path.read_text(encoding="utf-8").splitlines()
                if self.ledger_path.exists() else []
            )
            rows.append(json.dumps(
                call.to_row(purpose=purpose, element_count=element_count),
                ensure_ascii=False, default=str,
            ))
            self.ledger_path.write_text("\n".join(rows[-LEDGER_LIMIT:]) + "\n", encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass


class _RejectedKey(RuntimeError):
    """The server refused an optional key; retry once without it."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def from_config(config: dict[str, Any] | None,
                *, root: Path | str | None = None) -> LocalGUIModel | None:
    """Build a client from ``config/v2.json``, or ``None`` when the planner is off.

    ``None`` is a real answer and not an error: with no planner configured the runtime
    behaves exactly as it did before this module existed.
    """
    section = _planner_section(config)
    if not section.get("enabled", False):
        return None
    base = Path(root) if root else PROJECT_ROOT
    ledger = section.get("ledger") or "learning/local_gui_model_calls.jsonl"
    return LocalGUIModel(
        endpoint=str(section.get("endpoint") or DEFAULT_ENDPOINT),
        model=str(section.get("model") or DEFAULT_MODEL),
        provider=str(section.get("provider") or DEFAULT_PROVIDER),
        quantization=str(section.get("quantization") or DEFAULT_QUANTIZATION),
        context=int(section.get("context") or DEFAULT_CONTEXT),
        multimodal=bool(section.get("multimodal", True)),
        think=bool(section.get("think", False)),
        timeout_s=float(section.get("timeout_s") or DEFAULT_TIMEOUT_S),
        max_tokens=int(section.get("max_tokens") or DEFAULT_MAX_TOKENS),
        ledger_path=base / str(ledger),
    )


def _planner_section(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    section = config.get("local_planner")
    return dict(section) if isinstance(section, dict) else {}
