from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.verifier import (
    verify_alliance_tech_contribution,
    verify_alliance_tech_details_closed,
    verify_alliance_tech_node_opened,
)


def test_recommended_node_must_open_the_live_meat_contribution_option():
    before = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "status": "UNKNOWN",
        "recommended_tech_visible": True,
    })
    after = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "status": "AVAILABLE", "resource": "MEAT",
        "cost": 10000, "attempts_remaining": 25,
    })

    assert verify_alliance_tech_node_opened(before, after).ok
    assert not verify_alliance_tech_node_opened(before, before).ok


def test_donation_detail_closure_requires_the_tree_to_return():
    before = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "donation_detail_open": True,
    })
    after = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "status": "UNKNOWN",
        "recommended_tech_visible": True,
    })

    assert verify_alliance_tech_details_closed(before, after).ok
    assert not verify_alliance_tech_details_closed(before, before).ok


def test_consumed_attempt_and_client_result_cover_a_lagging_contribution_header():
    before = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "status": "AVAILABLE", "resource": "MEAT",
        "cost": 10000, "personal_contribution": 480, "attempts_remaining": 25,
    })
    result = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "status": "CONTRIBUTED",
        "contribution": 120, "attempts_remaining": 24,
    })
    after = WorldState(page=Page.ALLIANCE, alliance={
        "section": "TECHNOLOGY", "status": "AVAILABLE",
        "personal_contribution": 480, "attempts_remaining": 24,
    })

    check = verify_alliance_tech_contribution(before, result, after)

    assert check.ok, check.evidence
    assert check.evidence["contribution_header_lagged"]
