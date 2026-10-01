from winter_agent_v2.event_calendar import read_regular_event_hub
from winter_agent_v2.ocr import OCRToken


def token(label, x, y, w=100, h=24, confidence=0.99):
    return OCRToken(label, confidence, ((x, y), (x+w, y), (x+w, y+h), (x, y+h)))


def hub_tokens(*, calendar=False, one_tab=False, dx=0, dy=0):
    # Geometry measured from the real 03:34 regular-event/联盟总动员 frame.
    rows = [token("常规活动", 95, 22, 135, 38),
            token("兵工厂争夺战", 493+dx, 159+dy, 134, 23),
            token("联盟总动员", 39, 211+dy, 211, 48),
            token("积分：2,550", 526, 273+dy, 128, 27),
            token("可接次数：8/13", 57, 533+dy, 177, 29)]
    if not one_tab:
        rows.append(token("日历" if calendar else "峡谷会战", 115+dx, 159+dy, 100, 23))
    return rows


def test_regular_hub_has_no_date_requirement_and_derives_rightward_tab_swipe():
    result = read_regular_event_hub(hub_tokens(), frame_size=(720, 1280))
    assert result["recognized"]
    assert result["kind"] == "REGULAR_EVENT_HUB"
    assert result["display_name"] == "联盟总动员"
    assert result["source"] == "CURRENT_FRAME_OCR"
    assert not result["calendar_tab_visible"]
    start_x, start_y, end_x, end_y = result["scroll_to_start_norm"]
    assert 115/720 < start_x < end_x < 627/720
    assert start_y == end_y == round(170.5/1280, 5)
    assert "峡谷会战:" in result["tab_signature"]
    assert result["tab_positions_norm"]["兵工厂争夺战"] == [round(560/720, 5), round(170.5/1280, 5)]
    assert "preview_start_raw" not in result and "entries" not in result


def test_single_ocr_tab_recognizes_hub_but_does_not_authorize_scroll():
    result = read_regular_event_hub(hub_tokens(one_tab=True), frame_size=(720, 1280))
    assert result["recognized"]
    assert result["scroll_to_start_norm"] is None
    roi = result["tabstrip_roi_norm"]
    assert roi["y_norm"] > 60/1280
    assert roi["y_norm"]+roi["h_norm"] < 211/1280
    assert roi["x_norm"] == 0 and roi["w_norm"] == 1


def test_calendar_target_is_the_visible_current_tab_not_a_body_label():
    rows = hub_tokens(calendar=True) + [token("日历", 200, 900)]
    result = read_regular_event_hub(rows, frame_size=(720, 1280))
    assert result["calendar_tab_visible"]
    assert result["calendar_tab_tap_norm"] == [round(165/720, 5), round(170.5/1280, 5)]
    assert result["scroll_to_start_norm"] is None


def test_current_geometry_changes_signature_roi_and_swipe():
    before = read_regular_event_hub(hub_tokens(), frame_size=(720, 1280))
    after = read_regular_event_hub(hub_tokens(dx=-25, dy=35), frame_size=(720, 1280))
    assert after["recognized"]
    assert after["scroll_to_start_norm"] != before["scroll_to_start_norm"]
    assert after["tab_signature"] != before["tab_signature"]
    assert after["tabstrip_roi_norm"] != before["tabstrip_roi_norm"]
    assert abs(after["tab_positions_norm"]["峡谷会战"][0]
               - before["tab_positions_norm"]["峡谷会战"][0]) >= 0.03


def test_small_home_navigation_label_cannot_establish_regular_hub():
    rows = [r for r in hub_tokens() if r.text != "常规活动"]
    rows.append(token("常规活动", 620, 420, 80, 20))
    result = read_regular_event_hub(rows, frame_size=(720, 1280))
    assert not result["recognized"]
    assert result["calendar_tab_tap_norm"] is None
    assert result["scroll_to_start_norm"] is None
    assert result["tabstrip_roi_norm"] is None


def test_other_event_hub_heading_is_not_the_regular_event_shell():
    rows = [r for r in hub_tokens() if r.text != "常规活动"]
    rows.append(token("联盟活动", 95, 22, 135, 38))
    result = read_regular_event_hub(rows, frame_size=(720, 1280))
    assert not result["recognized"] and result["scroll_to_start_norm"] is None


def test_heading_and_tabs_without_event_body_are_not_an_actionable_hub():
    rows = [r for r in hub_tokens() if not r.text.startswith(("积分", "可接次数"))]
    result = read_regular_event_hub(rows, frame_size=(720, 1280))
    assert not result["recognized"] and result["scroll_to_start_norm"] is None


def test_duplicate_tab_ocr_does_not_authorize_a_scroll():
    rows = hub_tokens(one_tab=True)
    rows.append(token("兵工厂争夺战", 495, 159, 134, 23))
    result = read_regular_event_hub(rows, frame_size=(720, 1280))
    assert result["recognized"] and result["scroll_to_start_norm"] is None


def test_no_frame_geometry_or_outside_frame_tokens_are_not_actionable():
    assert not read_regular_event_hub(hub_tokens(), frame_size=None)["recognized"]
    rows = hub_tokens()
    rows[1] = token("兵工厂争夺战", 710, 159, 134, 23)
    assert read_regular_event_hub(rows, frame_size=(720, 1280))["scroll_to_start_norm"] is None


def test_token_geometry_scales_with_the_current_frame():
    original = hub_tokens()
    scaled = [OCRToken(r.text, r.confidence, tuple((x*2, y*2) for x, y in r.box)) for r in original]
    before = read_regular_event_hub(original, frame_size=(720, 1280))
    after = read_regular_event_hub(scaled, frame_size=(1440, 2560))
    assert after["recognized"]
    assert after["scroll_to_start_norm"] == before["scroll_to_start_norm"]
    assert after["tabstrip_roi_norm"] == before["tabstrip_roi_norm"]


def test_micro_ocr_shift_does_not_hide_the_numeric_position_for_progress_verifier():
    before = read_regular_event_hub(hub_tokens(), frame_size=(720, 1280))
    after = read_regular_event_hub(hub_tokens(dx=1), frame_size=(720, 1280))
    assert after["tab_signature"] != before["tab_signature"]
    assert abs(after["tab_positions_norm"]["峡谷会战"][0]
               - before["tab_positions_norm"]["峡谷会战"][0]) < 0.03


def test_missing_tab_ocr_requests_strip_read_without_treating_timers_as_tabs():
    rows = [row for row in hub_tokens() if row.text not in ("兵工厂争夺战", "峡谷会战")]
    rows.extend([token("1天20:06:00", 81, 273, 150, 30),
                 token("排名：82", 526, 302, 130, 28)])
    result = read_regular_event_hub(rows, frame_size=(720, 1280))
    assert result["recognized"] and result["display_name"] == "联盟总动员"
    assert result["tabs"] == [] and result["scroll_to_start_norm"] is None
    assert result["tabstrip_roi_norm"]
