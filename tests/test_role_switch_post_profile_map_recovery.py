from types import SimpleNamespace

import pytest

from winter_agent_v2.models import Page
from winter_agent_v2.role_switch_controller import RoleSwitchController


def _controller(tmp_path, frames):
    """Replay native UI transitions without a device or persisted role state."""
    now = [0.0]
    captures = []
    actions = []
    worlds = {}
    identities = {}
    controller = RoleSwitchController(
        root=tmp_path,
        device=object(),
        vision=SimpleNamespace(observe=lambda path: worlds[path]),
        state_store=object(),
        role_catalog=[{"role_id": "role-b"}],
        monotonic=lambda: now[0],
        sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
        poll_seconds=0.1,
    )

    def capture(_label):
        index = len(captures)
        page, identity, popup = frames[min(index, len(frames) - 1)]
        path = tmp_path / f"fresh_{index}.png"
        worlds[path] = SimpleNamespace(page=page, popup=popup)
        identities[path] = (identity, 0.99) if identity else None
        captures.append(path)
        return path

    controller._capture = capture
    controller._text = lambda _path: "城镇"
    controller.identify_current_role = lambda path: identities[path]
    controller._click_text = lambda path, *, exact: (
        actions.append((path, exact)) or True
    )
    return controller, captures, actions


def test_post_profile_map_uses_current_city_control_then_verifies_new_home(tmp_path):
    controller, captures, actions = _controller(tmp_path, [
        (Page.MAP, "role-b", None),
        (Page.HOME, "role-b", None),
    ])

    found = controller._wait_for_confirmed_target_home(
        controller.roles["role-b"], timeout=1.0,
    )

    assert found == captures[1]
    assert actions == [(captures[0], ("城镇",))]
    assert found != actions[0][0]


def test_native_formation_transition_is_left_alone_before_map_recovery(tmp_path):
    controller, captures, actions = _controller(tmp_path, [
        (Page.MARCH, None, None),
        (Page.MAP, "role-b", None),
        (Page.HOME, "role-b", None),
    ])

    found = controller._wait_for_confirmed_target_home(
        controller.roles["role-b"], timeout=1.0,
    )

    assert found == captures[2]
    assert actions == [(captures[1], ("城镇",))]


@pytest.mark.parametrize("identity,popup", [
    (None, None),
    ("role-b", SimpleNamespace(kind="UNRECOGNIZED")),
])
def test_map_recovery_requires_confirmed_target_role_and_clean_page(tmp_path, identity, popup):
    controller, _captures, actions = _controller(tmp_path, [
        (Page.MAP, identity, popup),
    ])

    assert controller._wait_for_confirmed_target_home(
        controller.roles["role-b"], timeout=0.3,
    ) is None
    assert actions == []


def test_other_role_avatar_aborts_without_city_action(tmp_path):
    controller, _captures, actions = _controller(tmp_path, [
        (Page.MAP, "role-a", None),
    ])

    assert controller._wait_for_confirmed_target_home(
        controller.roles["role-b"], timeout=1.0,
    ) is None
    assert actions == []


def test_city_clicks_are_bounded_and_relocate_on_distinct_fresh_frames(tmp_path):
    controller, captures, actions = _controller(tmp_path, [
        (Page.MAP, "role-b", None),
    ])

    assert controller._wait_for_confirmed_target_home(
        controller.roles["role-b"], timeout=0.5,
    ) is None
    assert actions == [(captures[0], ("城镇",)), (captures[1], ("城镇",))]
    assert len(captures) > len(actions)
