"""Two ways the gateway bridge used to say the wrong thing about a working server.

Both were measured live on 2026-09-18 evening against the gateway running as pid 11304, and
both had the same consequence: the GUI displayed 异常 while the gateway was healthy, and the
lifecycle owner killed and restarted a process that had done nothing wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.workbuddy_bridge import (  # noqa: E402
    Availability, GatewayUnavailable, JobLost, WorkBuddyBridge, MISSING_MARKER,
    REQUEST_MARKER_HEADER,
)


class _Recorder:
    """A transport seam that records the request and replays one canned answer."""

    def __init__(self, code: int, body: dict):
        self.code = code
        self.body = body
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, path, payload=None, timeout=None):
        self.calls.append((method, path, dict(payload or {})))
        return self.code, self.body


def _bridge(seam: _Recorder) -> WorkBuddyBridge:
    bridge = WorkBuddyBridge(password="x")
    bridge._request = seam  # the single documented seam over HTTP
    return bridge


def _sent_headers(seam_body: dict) -> dict:
    """Run one real request through a stub that captures the headers actually sent.

    Deliberately does *not* install the ``_request`` seam: that seam replaces the transport,
    so a test built on it observes the stub's arguments and never the wire.  The first
    version of this test did exactly that and asserted against an empty header set.
    """
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured.update({k.lower(): v for k, v in request.header_items()})

        class _Response:
            status = 200
            def read(self_inner):
                return json.dumps(seam_body).encode()
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *a):
                return False
        return _Response()

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        WorkBuddyBridge(password="x").is_available()
    finally:
        urllib.request.urlopen = original
    return captured


def test_every_request_carries_the_marker_the_gateway_now_requires():
    """Measured: no header -> 403 "Missing required header: x-codebuddy-request".

    The recorded contract said a bare ``Authorization: Bearer`` sufficed, and it did against
    the build measured on 2026-09-17.  This build added a request marker, so the bridge
    looked unreachable against a gateway that was answering on every request.
    """
    headers = _sent_headers({"data": {"status": "ok"}})
    assert REQUEST_MARKER_HEADER in headers
    assert headers[REQUEST_MARKER_HEADER], "the marker only has to be present, but not empty"
    assert headers.get("authorization", "").startswith("Bearer ")


def test_a_missing_marker_is_named_rather_than_flattened_into_unreachable():
    """403 because of the header is a specific misconfiguration, and it says so."""
    seam = _Recorder(403, {"error": "Missing required header: x-codebuddy-request"})
    probe = _bridge(seam).is_available()
    assert probe.available is False
    assert probe.reason == MISSING_MARKER
    assert "x-codebuddy-request" in json.dumps(dict(probe.detail))


def test_a_job_the_gateway_says_is_gone_is_lost_not_unreachable():
    """Measured: ``GET /api/v1/jobs/d8ea0e44`` -> 404 {"code":"JOB_NOT_FOUND"}.

    Jobs do not survive their gateway instance, so a restart strands the ledger on work that
    can never finish.  Raising the same error used for a dead port meant the record stayed
    WORKING forever and held the single concurrency slot.
    """
    seam = _Recorder(404, {"code": "JOB_NOT_FOUND", "message": "Job not found: d8ea0e44"})
    with pytest.raises(JobLost) as excinfo:
        _bridge(seam).status("d8ea0e44")
    assert isinstance(excinfo.value, GatewayUnavailable), (
        "JobLost must remain catchable as GatewayUnavailable so no existing handler breaks"
    )


def test_a_server_error_is_still_merely_unavailable():
    """A 500 is not a lost job: the work may still be there, so retry rather than re-submit."""
    seam = _Recorder(500, {"error": {"code": "INTERNAL"}})
    with pytest.raises(GatewayUnavailable) as excinfo:
        _bridge(seam).status("abc")
    assert not isinstance(excinfo.value, JobLost)


def test_a_lost_job_is_reported_by_the_gateway_not_inferred_from_a_timeout():
    """Only an explicit answer counts.  A timeout must never be read as JOB_LOST."""
    def exploding(method, path, payload=None, timeout=None):
        raise GatewayUnavailable("timed out after 15s")

    bridge = _bridge(_Recorder(200, {}))
    bridge._request = exploding
    with pytest.raises(GatewayUnavailable) as excinfo:
        bridge.status("abc")
    assert not isinstance(excinfo.value, JobLost)
