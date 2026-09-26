"""Unit tests for the runtime self-generation hook (``_maybe_autogen_node``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.executor_router import RoutingTable  # noqa: E402


class _HookHarness:
    """Minimal stand-in exposing only what the hook touches.

    The hook is a method on the runtime class, whose constructor wants a device,
    a vision stack and a world. None of that is what the hook exercises, so the
    test binds the real method onto a stub carrying just its inputs -- the same
    trick the failure-type tests next door use.
    """

    def __init__(self, tmp_path: Path, routing: RoutingTable, cn_text: str | None,
                 generated, captured: Path | None):
        from winter_agent_v2.runtime import LiveRuntime

        self._autogen_enabled = True
        self._autogen_attempted = set()
        self.recently_autogen = []
        self.capture_dir = tmp_path / "capture"
        self.capture_dir.mkdir(exist_ok=True)
        self.adb_device = MagicMock()
        self.adb_device.screenshot.return_value = captured
        self.routing = routing
        self._cn = cn_text
        self._generated = generated
        self._captured = captured
        self._wire_calls: list[tuple[str, str]] = []
        self._maybe_autogen_node = LiveRuntime._maybe_autogen_node.__get__(self)
        self._semantic_cn_text = lambda semantic: self._cn or ""

    def _make_gen(self, **_kwargs):
        gen = MagicMock()
        gen.capture.return_value = self._captured

        def _generate(request, **_kw):
            # Built from the request rather than returned verbatim: this is what
            # asserts the hook asked for the semantic it was triggered with,
            # instead of quietly generating a node for whatever the fixture held.
            from winter_agent_v2.pipeline_autogen import GeneratedNode

            return GeneratedNode(
                semantic=request.semantic, skill_id=request.skill_id, kind="TEMPLATE",
                routing_node={"kind": "TEMPLATE", "template": request.semantic},
                pipeline_node={"recognition": "TemplateMatch"},
            )

        gen.generate.side_effect = _generate

        def _wire(node, **_kw):
            self._wire_calls.append((node.semantic, node.skill_id))
            return True, "CREATED"

        gen.wire.side_effect = _wire
        return gen


@pytest.fixture()
def routing(tmp_path):
    path = tmp_path / "backend_routing.json"
    table = RoutingTable(skills={}, path=path)
    table.save()
    return RoutingTable.load(path)


def _node(semantic="BTN_X", skill="SKILL_X", kind="TEMPLATE"):
    from winter_agent_v2.pipeline_autogen import GeneratedNode

    return GeneratedNode(
        semantic=semantic, skill_id=skill, kind=kind,
        routing_node={"kind": kind, "template": semantic},
        pipeline_node={"recognition": "TemplateMatch"},
    )


def test_first_failure_generates_and_wires(tmp_path, routing, monkeypatch):
    captured = tmp_path / "frame.png"
    captured.write_bytes(b"png")
    node = _node()
    harness = _HookHarness(tmp_path, routing, "联盟商店", node, captured)
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen",
                        lambda **kw: harness._make_gen())

    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 0,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert harness._wire_calls == [("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP")]
    assert harness.recently_autogen[0]["semantic"] == "BTN_ALLIANCE_SHOP"


def test_second_failure_does_not_rederive(tmp_path, routing, monkeypatch):
    captured = tmp_path / "frame.png"
    captured.write_bytes(b"png")
    harness = _HookHarness(tmp_path, routing, "联盟商店", _node(), captured)
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen",
                        lambda **kw: harness._make_gen())

    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 0,
                                "SEMANTIC_TARGET_NOT_VERIFIED")
    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 1,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert len(harness._wire_calls) == 1


def test_non_resolution_failure_is_ignored(tmp_path, routing, monkeypatch):
    harness = _HookHarness(tmp_path, routing, "联盟商店", _node(), None)
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen",
                        lambda **kw: harness._make_gen())

    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 0,
                                "DEVICE_BUSY")

    assert harness._wire_calls == []


def test_later_real_missing_control_can_generate_after_other_refusal(tmp_path, routing, monkeypatch):
    captured = tmp_path / "frame.png"
    captured.write_bytes(b"png")
    harness = _HookHarness(tmp_path, routing, "联盟商店", _node(), captured)
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen",
                        lambda **kw: harness._make_gen())

    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 0, "DEVICE_BUSY")
    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 1,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert harness._wire_calls == [("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP")]


def test_existing_node_is_not_replaced(tmp_path, routing, monkeypatch):
    """A node that exists but missed is drift, not absence -- never re-derived."""
    entry = {"recognition": {"BTN_ALLIANCE_SHOP": {"kind": "TEMPLATE",
                                                   "template": "BTN_ALLIANCE_SHOP"}}}
    routing.skills["OPEN_ALLIANCE_SHOP"] = entry
    harness = _HookHarness(tmp_path, routing, "联盟商店", _node(), None)
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen",
                        lambda **kw: harness._make_gen())

    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 0,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert harness._wire_calls == []


def test_undeclared_semantic_is_skipped(tmp_path, routing, monkeypatch):
    harness = _HookHarness(tmp_path, routing, None, _node(), None)
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen",
                        lambda **kw: harness._make_gen())

    harness._maybe_autogen_node("BTN_UNKNOWN_THING", "SOME_SKILL", 0,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert harness._wire_calls == []


def test_disabled_hook_never_generates(tmp_path, routing):
    harness = _HookHarness(tmp_path, routing, "联盟商店", _node(), None)
    harness._autogen_enabled = False

    harness._maybe_autogen_node("BTN_ALLIANCE_SHOP", "OPEN_ALLIANCE_SHOP", 0,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert harness._wire_calls == []
    assert harness.recently_autogen == []


def test_v2_calls_the_installed_pipeline_generator_without_second_device_or_file_write():
    """The real Skill CLI emits the node while V2 retains leased capture and registry writes."""
    from winter_agent_v2.pipeline_autogen import PipelineAutoGen

    generator = PipelineAutoGen(project_root=ROOT)
    generated, roi = generator._tool_node_config("训练", [100, 200, 30, 20], 0.99, 20)

    assert generated == {
        "recognition": "OCR",
        "expected": ["训练"],
        "roi": [80, 180, 70, 60],
        "action": "Click",
        "post_delay": 500,
        "timeout": 2000,
    }
    assert roi == generated["roi"]


def test_autogen_keeps_the_generated_pipeline_json_and_wires_the_same_recognition_node(tmp_path):
    from winter_agent_v2.pipeline_autogen import GeneratedNode, PipelineAutoGen

    routing_path = tmp_path / "backend_routing.json"
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=routing_path)
    node = GeneratedNode(
        semantic="BTN_SAMPLE",
        skill_id="OPEN_SAMPLE",
        kind="OCR",
        routing_node={"kind": "OCR", "expected": ["训练"], "roi": [80, 180, 70, 60]},
        pipeline_node={"recognition": "OCR", "expected": ["训练"], "roi": [80, 180, 70, 60],
                       "action": "Click", "post_delay": 500, "timeout": 2000},
    )

    ok, verdict = generator.wire(node)

    assert ok and verdict == "CREATED"
    artifact = tmp_path / node.evidence["pipeline_node_path"]
    assert json.loads(artifact.read_text(encoding="utf-8")) == node.pipeline_node
    written = RoutingTable.load(routing_path)
    assert written.recognition_node("OPEN_SAMPLE", "BTN_SAMPLE") == node.routing_node


def test_runtime_autogen_retains_tool_ocr_and_uses_maafriendly_template(tmp_path, routing, monkeypatch):
    """Keep the Skill output while routing a node the configured MAA can execute."""
    captured = tmp_path / "frame.png"
    captured.write_bytes(b"png")
    harness = _HookHarness(tmp_path, routing, "联盟科技", _node(kind="OCR"), captured)
    requested = []
    generated_from = []
    gen = harness._make_gen()

    def record_request(request, **kwargs):
        from winter_agent_v2.pipeline_autogen import GeneratedNode

        requested.append(request.want)
        generated_from.append(kwargs.get("frame"))
        return GeneratedNode(
            semantic=request.semantic, skill_id=request.skill_id, kind="OCR",
            routing_node={"kind": "OCR", "expected": [request.cn_text], "roi": [80, 180, 70, 60]},
            pipeline_node={"recognition": "OCR", "expected": [request.cn_text], "roi": [80, 180, 70, 60]},
        )

    gen.generate.side_effect = record_request
    monkeypatch.setattr("winter_agent_v2.pipeline_autogen.PipelineAutoGen", lambda **kw: gen)

    harness._maybe_autogen_node("BTN_ALLIANCE_TECH", "OPEN_ALLIANCE_TECH_FROM_HOME", 0,
                                "SEMANTIC_TARGET_NOT_VERIFIED")

    assert requested == ["auto"]
    assert generated_from == [captured]
    assert harness._wire_calls == [("BTN_ALLIANCE_TECH", "OPEN_ALLIANCE_TECH_FROM_HOME")]


def test_runtime_button_semantic_can_reuse_matching_page_label():
    from winter_agent_v2.runtime import LiveRuntime

    assert LiveRuntime._semantic_cn_text(object(), "BTN_ALLIANCE_TECH") == "联盟科技"


def test_wire_keeps_tool_ocr_candidate_separate_from_active_template(tmp_path):
    from winter_agent_v2.pipeline_autogen import GeneratedNode, PipelineAutoGen

    routing_path = tmp_path / "backend_routing.json"
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=routing_path)
    tool_node = {
        "recognition": "OCR", "expected": ["联盟科技"], "roi": [500, 890, 170, 95],
        "action": "Click", "post_delay": 500, "timeout": 2000,
    }
    active_node = {
        "recognition": "TemplateMatch", "template": ["BTN_ALLIANCE_TECH"],
        "roi": [500, 890, 170, 95], "threshold": [0.7],
    }
    node = GeneratedNode(
        semantic="BTN_ALLIANCE_TECH", skill_id="OPEN_ALLIANCE_TECH_FROM_HOME",
        kind="TEMPLATE",
        routing_node={"kind": "TEMPLATE", "template": "BTN_ALLIANCE_TECH",
                      "source_template": "dataset/candidate/autogen/btn_alliance_tech.png"},
        pipeline_node=active_node,
        evidence={"tool_generated_node": tool_node, "active_node_source": "V2_NATIVE_TEMPLATE"},
    )

    ok, verdict = generator.wire(node)

    assert ok and verdict == "CREATED"
    tool_artifact = tmp_path / node.evidence["tool_candidate_path"]
    active_artifact = tmp_path / node.evidence["pipeline_node_path"]
    assert json.loads(tool_artifact.read_text(encoding="utf-8")) == tool_node
    assert json.loads(active_artifact.read_text(encoding="utf-8")) == active_node
    assert RoutingTable.load(routing_path).recognition_node(
        "OPEN_ALLIANCE_TECH_FROM_HOME", "BTN_ALLIANCE_TECH"
    ) == node.routing_node
