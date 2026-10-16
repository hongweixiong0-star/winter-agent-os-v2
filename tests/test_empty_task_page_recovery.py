"""The single AUTO cycle leaves a known task page when it has no runnable Goal."""

from tests.test_live_runtime import FakeDevice, FakeSemantic, FakeVision
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


def test_mail_all_clear_returns_to_home_when_no_goal_is_selectable(tmp_path):
    mail = WorldState(
        page=Page.MAIL,
        mail={"status": "CLAIMED", "badge_count": 0, "tab_badges": {}},
        confidence=0.99,
    )
    home = WorldState(page=Page.HOME, confidence=0.99)
    device = FakeDevice()
    runtime = LiveRuntime(
        device=device,
        vision=FakeVision([mail, home]),
        semantic_vision=FakeSemantic(),
        capture_dir=tmp_path,
        brain=RuleBrain(),
        sleeper=lambda _: None,
    )

    result = runtime.run(max_actions=1)

    assert result.steps[0].decision.skill == "BACK"
    assert result.steps[0].verification.ok
    assert result.steps[0].after.page is Page.HOME
    assert len(device.backs) == 1
