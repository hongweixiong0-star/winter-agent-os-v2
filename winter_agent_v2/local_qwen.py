"""The local Qwen, and the one file that knows where it lives.

Operator directive 2026-09-25, section 1 and 4: the WorkBuddy automatic-call channel is
retired, and the model that plans UI actions is the **local** Qwen already deployed on
this machine.  No new service, no new billing, no downloads.

Why one thin client rather than a framework
-------------------------------------------
``tests/test_workbuddy_model_router.py`` keeps every *development* model name inside
``workbuddy_model_router.py`` so the strategy can be swapped without touching V2.  This
module is the same idea for the *runtime* model: the endpoint, the model tag and the
context budget live here and nowhere else, so "which local model" is a one-file question
and the planner, the runtime and the tests read it from one place.

What it deliberately is not
---------------------------
* **Not a dependency.**  ``available()`` is a bounded probe and ``ask_json`` returns a
  result object rather than raising, so a stopped Ollama, a missing model or a slow reply
  all leave the AUTO cycle running on the rules and skills it already had.  This is the
  property ``tests/test_qwen_decoupling.py`` pins.
* **Not a decision maker.**  It sends a prompt and returns text.  Parsing, validating and
  refusing are ``ui_planner``'s job, because a client that improvises about a reply is a
  client that feeds invented actions into a live game.
* **Not a place coordinates can come from.**  The model is asked to name an element id,
  never a pixel; see ``ui_planner.FORBIDDEN_KEYS``.

Measured on this machine 2026-09-25: Ollama on ``127.0.0.1:11434`` serving
``qwen3635bagent-q3:latest`` (35.5B MoE, Q3_K_M, declared context 262144) with
``tools``/``thinking``/``completion`` capabilities.
"""

from __future__ import annotations

import json
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

#: Where the local model server answers.  Loopback only, deliberately: this is the
#: machine's own Oliver deployment, not a network service.
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"

#: The deployed tag.  Not "qwen3.6:35b" (the base) -- the agent-tuned Q3 build is the one
#: that was actually pulled for this project and the smaller of the two 35B tags.
DEFAULT_MODEL = "qwen3635bagent-q3:latest"

#: Section 4: keep the existing 8K context, do not raise it.  A planner step is a table of
#: this screen's own elements plus the goal, and 8K is enough for that by a wide margin --
#: the packet builder caps and truncates rather than letting the prompt grow.
DEFAULT_NUM_CTX = 8192

#: A planner step must not become the slowest thing in a cycle.  Bounded, and the cycle
#: proceeds without a plan when it expires.
DEFAULT_TIMEOUT_S = 45.0

#: Probe cache.  ``available()`` may be called once per cycle; a TCP connect per call
#: would be a per-cycle syscall for information that changes on the scale of minutes.
PROBE_TTL_S = 30.0

LEDGER_PATH = PROJECT_ROOT / "learning" / "local_qwen_calls.jsonl"
LEDGER_LIMIT = 2000


@dataclass(frozen=True)
class QwenCall:
    """One exchange with the local model, including the ones that produced nothing."""

    ok: bool
    text: str = ""
    error: str = ""
    model: str = ""
    latency_ms: float = 0.0
    prompt_chars: int = 0

    def to_row(self, *, purpose: str = "", element_count: int = 0) -> dict[str, Any]:
        return {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "model": self.model,
            "ok": self.ok,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "prompt_chars": self.prompt_chars,
            "reply_chars": len(self.text or ""),
            "element_count": element_count,
        }


class LocalQwen:
    """A JSON-mode chat call to the machine's own Qwen, with every failure bounded."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        num_ctx: int = DEFAULT_NUM_CTX,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        ledger_path: Path | str | None = None,
    ) -> None:
        self.endpoint = str(endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.model = str(model or DEFAULT_MODEL)
        self.num_ctx = int(num_ctx)
        self.timeout_s = float(timeout_s)
        self.ledger_path = Path(ledger_path) if ledger_path else LEDGER_PATH
        self._probe: tuple[float, bool, str] | None = None

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
            verdict = (False, f"LOCAL_QWEN_UNREACHABLE {host}:{port} ({type(exc).__name__})")
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
        timeout_s: float | None = None,
    ) -> QwenCall:
        """One ``/api/chat`` in JSON mode.  Never raises; a failure is a ``QwenCall``."""
        prompt_chars = len(system) + len(user)
        ok, reason = self.available()
        if not ok:
            # Recorded, not just returned.  A client that is simply absent is the *most* common
            # failure of a local model -- Ollama not started, model swapped out -- and a helper
            # that answered ``False`` without a row would make the ledger show "no calls" while
            # every cycle was failing, which is the quietest possible way for a feature to die.
            call = QwenCall(False, error=reason, model=self.model, prompt_chars=prompt_chars)
            self.record(call, purpose=purpose, element_count=element_count)
            return call
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": str(system)},
                {"role": "user", "content": str(user)},
            ],
            "stream": False,
            # The server constrains the reply to parseable JSON.  The planner still
            # validates the *shape*; this only removes the "the model wrapped it in
            # prose" failure, which is not the failure worth spending retries on.
            "format": "json",
            # Section 4: no extra thinking pass.  Recorded as a request, not assumed --
            # ``_post`` retries once without it if this server build rejects the key.
            "think": False,
            "options": {"num_ctx": self.num_ctx, "temperature": 0.0},
        }
        started = time.perf_counter()
        try:
            body = self._post(payload, timeout_s=timeout_s)
        except _RejectedThinkKey:
            payload.pop("think", None)
            try:
                body = self._post(payload, timeout_s=timeout_s)
            except Exception as exc:  # noqa: BLE001 - every failure is data, none is fatal
                return self._failed(exc, prompt_chars, purpose, element_count)
        except Exception as exc:  # noqa: BLE001
            return self._failed(exc, prompt_chars, purpose, element_count)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        text = ""
        if isinstance(body, dict):
            message = body.get("message")
            if isinstance(message, dict):
                text = str(message.get("content") or "")
            if not text:
                # ``/api/generate``-shaped servers answer with ``response``.
                text = str(body.get("response") or "")
        call = QwenCall(
            ok=bool(text.strip()),
            text=text,
            error="" if text.strip() else "LOCAL_QWEN_EMPTY_REPLY",
            model=self.model,
            latency_ms=latency_ms,
            prompt_chars=prompt_chars,
        )
        self.record(call, purpose=purpose, element_count=element_count)
        return call

    def _post(self, payload: dict[str, Any], *, timeout_s: float | None) -> Any:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/api/chat",
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
            if exc.code == 400 and "think" in detail.lower():
                # Older builds do not know the key.  One bounded retry without it, because
                # the alternative -- dropping the probe -- would silently lose the
                # "no extra thinking pass" requirement on exactly those builds.
                raise _RejectedThinkKey() from exc
            raise RuntimeError(f"HTTP {exc.code} {detail[:200]}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"reply is not JSON: {raw[:120]!r}") from exc

    def _failed(self, exc: BaseException, prompt_chars: int, purpose: str,
                element_count: int) -> QwenCall:
        call = QwenCall(
            False,
            error=f"LOCAL_QWEN_{type(exc).__name__.upper()}: {str(exc)[:200]}",
            model=self.model,
            prompt_chars=prompt_chars,
        )
        self.record(call, purpose=purpose, element_count=element_count)
        return call

    # ------------------------------------------------------------------ accounting
    def record(self, call: QwenCall, *, purpose: str = "", element_count: int = 0) -> None:
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


class _RejectedThinkKey(RuntimeError):
    """The server refused ``think``; retry once without it."""


def from_config(config: dict[str, Any] | None, *, root: Path | str | None = None) -> LocalQwen | None:
    """Build a client from ``config/v2.json``, or ``None`` when the planner is off.

    ``None`` is a real answer and not an error: with no planner configured the runtime
    behaves exactly as it did before this module existed.
    """
    section = _planner_section(config)
    if not section.get("enabled", False):
        return None
    base = Path(root) if root else PROJECT_ROOT
    ledger = section.get("ledger") or "learning/local_qwen_calls.jsonl"
    return LocalQwen(
        endpoint=str(section.get("endpoint") or DEFAULT_ENDPOINT),
        model=str(section.get("model") or DEFAULT_MODEL),
        num_ctx=int(section.get("num_ctx") or DEFAULT_NUM_CTX),
        timeout_s=float(section.get("timeout_s") or DEFAULT_TIMEOUT_S),
        ledger_path=base / str(ledger),
    )


def _planner_section(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    section = config.get("local_planner")
    return dict(section) if isinstance(section, dict) else {}
