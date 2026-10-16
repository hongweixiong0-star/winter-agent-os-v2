"""Tests for the event card face reader -- every case is a string the client printed live.

The samples are verbatim from 2026-10-16 r209-r210 (see the module docstring); synthetic text
would not have caught the full-width colon or the parenthesis inside a task description.
"""

from winter_agent_v2.event_card_reader import (
    read_event_card,
    read_my_score,
    read_phase_timer,
    read_task_rows,
    read_tiers,
)


def test_my_score_zero_is_a_reading_not_an_absence():
    assert read_my_score("我的积分：0") == 0


def test_my_score_none_when_the_row_is_absent():
    assert read_my_score("奖励预览 等级1 前往侦察") is None


def test_my_score_with_thousands_separators():
    assert read_my_score("我的积分：12,500") == 12500


def test_phase_timer_keeps_the_phase_word_and_never_converts():
    assert read_phase_timer("侦察阶段 13:27:18") == ("侦察阶段", "13:27:18")


def test_phase_timer_absent_on_a_card_without_one():
    assert read_phase_timer("我的积分：0") is None


def test_task_rows_keep_the_parenthetical_verbatim():
    text = (
        "护送1次任意品质商旅 10,000点积分\n"
        "拦截1次任意品质商旅 10,000点积分\n"
        "领主装备最高评分提升1点（不包含领主宝石） 22点积分\n"
    )
    rows = read_task_rows(text)
    assert len(rows) == 3
    assert rows[0] == {"description": "护送1次任意品质商旅", "points": 10000}
    assert rows[2]["points"] == 22
    assert "（不包含领主宝石）" in rows[2]["description"]


def test_tiers_ascending_ladder_is_returned():
    text = "100 37,500 75,000 125,000 187,500"
    assert read_tiers(text) == [100, 37500, 75000, 125000, 187500]


def test_tiers_non_ascending_is_withheld_not_guessed():
    # A half-read or shuffled set must not become a fabricated ladder.
    assert read_tiers("187,500 100 75,000") == []


def test_tiers_single_value_is_not_a_ladder():
    assert read_tiers("37,500") == []


def test_full_card_combines_what_the_text_supports():
    text = (
        "我的积分：0\n"
        "押送阶段 02:11:05\n"
        "100 37,500 75,000\n"
        "护送1次任意品质商旅 10,000点积分\n"
    )
    card = read_event_card(text)
    assert card["my_score"] == 0
    assert (card["phase"], card["remaining"]) == ("押送阶段", "02:11:05")
    assert card["tiers"] == [100, 37500, 75000]
    assert card["tasks"][0]["points"] == 10000


def test_full_card_omits_unsupported_keys_entirely():
    card = read_event_card("常规活动 联盟大作战 凛风攻城战")
    assert card == {}


from winter_agent_v2.event_card_reader import looks_like_event_card


def test_card_gate_accepts_the_measured_alliance_war_card():
    text = (
        "我的积分：0\n"
        "100 37,500 75,000 125,000 187,500\n"
        "护送1次任意品质商旅 10,000点积分\n"
    )
    assert looks_like_event_card(text) is True


def test_card_gate_rejects_a_bare_tab_strip():
    assert looks_like_event_card("常规活动 联盟大作战 雪原商路 凛风攻城战") is False


def test_card_gate_accepts_the_siege_card_without_a_score_row():
    text = "凛风攻城战 侦察阶段 13:27:18 调配部队攻守据点，与对手联盟一决胜负！"
    assert looks_like_event_card(text) is True


def test_card_gate_rejects_single_weak_signal():
    # One card-shaped token is not a card; the gate exists to keep the tail-call rare.
    assert looks_like_event_card("我的积分：0") is False


# --- verifier (verify_regular_event_card_read) ------------------------------------------

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.verifier import verify_regular_event_card_read


def _state(page, events=None):
    return WorldState(page=page, events=events or {})


def test_verifier_passes_on_one_recognised_field():
    after = _state(Page.EVENT, {"regular_event_card": {"phase": "侦查阶段", "remaining": "13:27:18"}})
    result = verify_regular_event_card_read(_state(Page.EVENT), after)
    assert result.ok is True
    assert result.evidence["fields"] == ["phase"]


def test_verifier_rejects_an_empty_card():
    after = _state(Page.EVENT, {"regular_event_card": {}})
    result = verify_regular_event_card_read(_state(Page.EVENT), after)
    assert result.ok is False
    assert result.reason == "EVENT_CARD_READ_NOT_PROVEN"


def test_verifier_rejects_a_card_written_on_the_wrong_page():
    after = _state(Page.MAP, {"regular_event_card": {"my_score": 0}})
    assert verify_regular_event_card_read(_state(Page.EVENT), after).ok is False


def test_verifier_rejects_when_no_card_key_exists():
    after = _state(Page.EVENT, {"regular_events_hub": {"recognized": True}})
    assert verify_regular_event_card_read(_state(Page.EVENT), after).ok is False
