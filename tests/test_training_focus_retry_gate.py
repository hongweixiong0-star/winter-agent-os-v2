from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.verifier import can_reobserve_focused_training_camp_after_nonmenu_tap


def test_training_focus_retry_requires_same_safe_home_surface():
    before = WorldState(
        page=Page.HOME,
        training={"navigation": "PANEL_CAMP_FOCUSED", "camp_focus_tap_norm": [0.50, 0.46]},
    )
    safe_after = WorldState(page=Page.HOME, quick_panel={"open": False})
    assert can_reobserve_focused_training_camp_after_nonmenu_tap(
        before, safe_after, camp="LANCER"
    ).ok

    assert not can_reobserve_focused_training_camp_after_nonmenu_tap(
        before, WorldState(page=Page.MAP), camp="LANCER"
    ).ok
    assert not can_reobserve_focused_training_camp_after_nonmenu_tap(
        before, WorldState(page=Page.POPUP, popup="PURCHASE_POPUP"), camp="LANCER"
    ).ok
    assert not can_reobserve_focused_training_camp_after_nonmenu_tap(
        before,
        WorldState(page=Page.HOME, training={"menu_open": True, "camp": "LANCER_CAMP"}),
        camp="LANCER",
    ).ok
    assert not can_reobserve_focused_training_camp_after_nonmenu_tap(
        before,
        WorldState(page=Page.HOME, training={"camp": "MARKSMAN_CAMP"}),
        camp="LANCER",
    ).ok
