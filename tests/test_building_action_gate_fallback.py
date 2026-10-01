from types import SimpleNamespace

from PIL import Image

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import HybridVision, OCRToken


def token(text, box):
    x0, y0, x1, y1 = box
    return OCRToken(text, 0.99, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def setup(tmp_path, tokens, goal="BUILDING"):
    frame = tmp_path / "wall-menu.png"
    Image.new("RGB", (720, 1280)).save(frame)
    calls = []
    semantic = SimpleNamespace(find=lambda *_: None, attention={"goal": goal})
    ocr = SimpleNamespace(recognize=lambda path: calls.append(path) or SimpleNamespace(tokens=tokens))
    return HybridVision(SimpleNamespace(semantic=semantic), ocr), frame, calls


def wall_tokens():
    # Boxes read from the actual 2026-10-01 building-row after frame.
    return [token("8", (293, 535, 313, 558)), token("城墙", (346, 531, 407, 563)),
            token("详情", (210, 877, 261, 906)), token("升级", (333, 905, 387, 939))]


def test_building_route_reads_named_action_bar_when_old_templates_miss(tmp_path):
    vision, frame, _ = setup(tmp_path, wall_tokens())
    state = vision._read_building_identity(frame, WorldState(page=Page.HOME))
    assert state.building["name"] == "城墙"
    assert state.building["level"] == 8
    assert state.building["upgrade_tap_norm"] == [0.5, 0.7203]
    assert "queue_available" not in state.building


def test_unrelated_route_does_not_add_an_ocr_pass(tmp_path):
    vision, frame, calls = setup(tmp_path, wall_tokens(), goal="FISHING")
    assert not vision._building_is_selected(frame)
    assert calls == []


def test_upgrade_word_without_details_and_spatial_level_is_not_a_building(tmp_path):
    for tokens in (wall_tokens()[1:], wall_tokens()[:2] + wall_tokens()[3:]):
        vision, frame, _ = setup(tmp_path, tokens)
        assert not vision._building_is_selected(frame)
