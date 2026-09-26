"""LIST_DYNAMIC rally node: the row field set, and the resolver that taps it.

Round brief §九 asks the rally list to be read as rows with ``row_id / leader /
target / members / capacity / full / join_available / timer / row_bbox /
join_button_bbox``, every bbox valid for the frame it was read from and nothing
reused across a refresh or a scroll.  §二十 keeps the JOIN_RALLY path alive, so
the new LIST_DYNAMIC node has to answer the same question the old template did
-- where is the button -- and answer it better: WHICH rally the button belongs
to.

The four frames under ``dataset/raw/bear_live_20260909`` are real client frames,
and every number asserted here was measured off them, so a failure names the
picture that stopped being read rather than a constant that moved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RAW = ROOT / "dataset" / "raw" / "bear_live_20260909"


@pytest.fixture(scope="module")
def backend():
    from winter_agent_v2.ocr import RapidOCRBackend

    return RapidOCRBackend()


@pytest.fixture(scope="module")
def read(backend):
    from PIL import Image
    from winter_agent_v2 import rally

    def _read(name: str):
        image = Image.open(RAW / name).convert("RGB")
        return rally.read_rally_list_image(image, list(backend.recognize(image)))

    return _read


# --------------------------------------------------------------- the field set


def test_a_row_carries_every_list_dynamic_field(read):
    """§九's ten fields, on the frame that draws two joinable bear rallies."""
    row = read("join_list_now.png").rows[0]
    missing = [key for key in ("row_id", "leader", "target", "members", "capacity",
                               "full", "join_available", "timer", "row_bbox",
                               "join_button_bbox") if key not in row.to_dict()]
    assert missing == [], f"the row is missing the fields the brief names: {missing}"
    assert row.members == 8 and row.capacity == 15
    assert row.full is False
    assert row.join_available is True
    assert row.timer == 45
    assert row.leader == "[iio]葬爱·超人强"


def test_the_row_id_is_content_not_position(read):
    """The id survives a scroll (same rally, different place) and changes with content.

    Two rows on one frame must not share an id -- that would be the same confusion
    as one shared join point -- and a row whose leader could not be read gets an
    explicit placeholder rather than the previous row's name.
    """
    reading = read("join_list_now.png")
    ids = [row.row_id for row in reading.rows]
    assert len(set(ids)) == len(ids), f"two rows share a row_id: {ids}"
    assert ids[0] == "等级1变异巨熊@[iio]葬爱·超人强"
    assert "UNKNOWN_LEADER" in ids[2] or "UNKNOWN_TARGET" in ids[2], (
        "a row whose content was not readable must say so in its id, not borrow one"
    )


def test_unreadable_capacity_is_none_not_full(read):
    """§九: ``full`` is a fact about the rally, and an unread count is not one.

    ``join_list_now.png``'s third row is partly scrolled out: no target token, no
    capacity token.  Reporting ``full=False`` there would be a guess that lets an
    unread row be joined.
    """
    third = read("join_list_now.png").rows[2]
    assert third.members is None and third.capacity is None
    assert third.full is None, "unreadable capacity is unknown, not 'not full'"
    assert third.join_available is False
    assert third.join_button_bbox is None


def test_an_already_joined_list_offers_no_button(read):
    """After this role joined, the rows are still drawn but none offers a join.

    This is the 2026-09-09 frame that the shared-green-plus failure would have
    joined a second time.
    """
    reading = read("joined_with_jesse.png")
    assert reading.has_rows
    assert [row.join_available for row in reading.rows] == [False, False]
    assert all(row.join_button_bbox is None for row in reading.rows)
    assert reading.best_joinable() is None


def test_bboxes_are_inside_the_row_they_belong_to(read):
    """A row's own button must fall inside that row's own rectangle.

    If a button bbox could sit in another row's band, the tap would join a rally
    the reader did not choose -- the exact failure this reader replaces.
    """
    for row in read("join_list_now.png").rows:
        if not row.join_button_bbox:
            continue
        x0, y0, x1, y1 = row.join_button_bbox
        top, bottom = row.row_bbox[1], row.row_bbox[3]
        assert top <= y0 <= y1 <= bottom, (
            f"row {row.row_id}'s button {row.join_button_bbox} is outside its band "
            f"{row.row_bbox}"
        )
        assert 0.0 <= x0 < x1 <= 1.0


def test_the_row_rectangle_comes_from_the_frame_not_a_constant(read):
    """Two frames place their rows differently; their rectangles differ too."""
    a = read("join_list_now.png").rows[0]
    b = read("join_list_after_detail.png").rows[0]
    assert a.row_bbox != b.row_bbox, (
        "a stored row rectangle would be the same on both frames -- these are not"
    )


# ----------------------------------------------------------------- the node


def test_the_wired_node_is_declared_list_dynamic():
    """Routing must say LIST_DYNAMIC, or the resolver sends it to the template path."""
    from winter_agent_v2.pipeline_autogen import dispatch_hint

    routing = json.loads(
        (ROOT / "knowledge" / "execution" / "backend_routing.json").read_text(encoding="utf-8")
    )
    node = routing["skills"]["JOIN_RALLY"]["recognition"]["RALLY_ROW_JOIN_BUTTON"]
    assert node["kind"] == "LIST_DYNAMIC"
    assert dispatch_hint(node) == "LIST_DYNAMIC"
    assert node["fallback_semantic"] == "BTN_JOIN_ROW", (
        "the previously working template must stay reachable when the frame is not a list"
    )


class _StubOutcome:
    def center_norm(self):
        return (0.5, 0.5)


class _StubAdapter:
    """Just enough of the MAA adapter for ``maa_resolver``: a frame and a size."""

    def __init__(self, frame):
        self._frame = frame
        self.last_frame = frame

    def frame(self):
        return self._frame

    def find(self, *args, **kwargs):
        return _StubOutcome()


def _resolver_for(frame):
    from winter_agent_v2.executor_router import ExecutorRouter

    router = ExecutorRouter.__new__(ExecutorRouter)
    router.maa_adapter = _StubAdapter(frame)
    router.routing = type("R", (), {})()
    from winter_agent_v2.executor_router import RoutingTable

    router.routing = RoutingTable.load()
    router.adb_resolver = None
    router.last_outcome = None
    router.last_recognition_error = None
    return router


def _frame_of(name: str):
    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(RAW / name).convert("RGB"))


def test_the_resolver_taps_the_chosen_row_not_a_fixed_point():
    """Production path: the node resolves to the joinable row's own button."""
    router = _resolver_for(_frame_of("join_list_now.png"))
    point = router.maa_resolver("RALLY_ROW_JOIN_BUTTON", "JOIN_RALLY")
    assert point is not None
    # Measured on this frame: row 1's own green affordance, and row 2's is lower.
    assert point == pytest.approx((0.8889, 0.3051), abs=0.01), (
        f"the tap must be the chosen row's button, got {point}"
    )
    assert router.last_recognition_error is None


def test_a_frame_that_is_not_a_rally_list_falls_back_to_the_template():
    """No 集结中 header -> the reader says nothing, so the old node still answers."""
    router = _resolver_for(_frame_of("special_buildings.png"))
    point = router.maa_resolver("RALLY_ROW_JOIN_BUTTON", "JOIN_RALLY")
    assert router.last_recognition_error == "LIST_DYNAMIC:NO_ROWS"
    assert point == (0.5, 0.5), (
        "with no rows read the previously working template path must decide, not a refusal"
    )


def test_a_list_with_nothing_joinable_refuses_instead_of_falling_back():
    """Rows read, none joinable: an answer, not a miss.

    Falling back here is what the reader exists to prevent -- a green + drawn on
    some other row would then be tapped even though the list said no.
    """
    router = _resolver_for(_frame_of("joined_with_jesse.png"))
    point = router.maa_resolver("RALLY_ROW_JOIN_BUTTON", "JOIN_RALLY")
    assert point is None
    assert router.last_recognition_error == "LIST_DYNAMIC:NO_JOINABLE_ROW"
