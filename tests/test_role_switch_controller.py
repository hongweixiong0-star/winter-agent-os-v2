import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from winter_agent_v2.global_scheduler_state import GlobalSchedulerStateStore
from winter_agent_v2.role_switch_controller import RoleSwitchController, load_role_catalog


def test_role_catalog_requires_live_verification_and_current_avatar_template(tmp_path):
    project = tmp_path / "project"
    template = project / "knowledge/ui/role_switch/avatar_templates/ROLE_A.png"
    template.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "blue").save(template)
    inventory = project / "knowledge/roles/role_inventory.json"
    inventory.parent.mkdir(parents=True)

    payload = {
        "schema_version": 1,
        "switch_status": "LIVE_BIDIRECTIONAL_VERIFIED",
        "roles": [{
            "role_key": "ROLE_A",
            "role_id": "role-a",
            "display_name": "Account A",
            "enabled": True,
            "identity_confidence": 0.95,
            "avatar_template": "knowledge/ui/role_switch/avatar_templates/ROLE_A.png",
        }],
    }
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    assert [row["role_id"] for row in load_role_catalog(inventory)] == ["role-a"]

    payload["switch_status"] = "NOT_CONFIGURED"
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    assert load_role_catalog(inventory) == []

    payload["switch_status"] = "LIVE_BIDIRECTIONAL_VERIFIED"
    payload["roles"][0]["avatar_template"] = "knowledge/ui/role_switch/avatar_templates/missing.png"
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    assert load_role_catalog(inventory) == []


def _role_switch_fixture(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "global-state.json")
    store.register_role_catalog([
        {"role_id": "role-a", "role_key": "ROLE_A", "display_name": "Account A"},
        {"role_id": "role-b", "role_key": "ROLE_B", "display_name": "Account B"},
    ], active_role_id="role-a")
    state = store.load()
    state.roles["role-a"].page = "RALLY_LIST"
    state.roles["role-a"].current_goal = "PARTICIPATE_BEAR"
    state.roles["role-a"].current_skill = "JOIN_RALLY"
    state.roles["role-a"].dirty_live_state = False
    state.roles["role-b"].page = "OLD_HOME"
    state.roles["role-b"].current_goal = "KEEP_TRAINING_PRODUCTIVE"
    state.roles["role-b"].current_skill = "TRAIN_TROOPS"
    state.roles["role-b"].dirty_live_state = False
    store.save(state)
    controller = RoleSwitchController(
        root=tmp_path,
        device=object(),
        vision=object(),
        state_store=store,
        role_catalog=[
            {"role_id": "role-a", "display_name": "Account A",
             "avatar_template_path": tmp_path / "role-a.png"},
            {"role_id": "role-b", "display_name": "Account B",
             "avatar_template_path": tmp_path / "role-b.png"},
        ],
        monotonic=lambda: 10.0,
    )
    return store, controller


def _stub_switch_navigation(monkeypatch, controller, tmp_path, *, final_identity="role-b"):
    identity_waits = []

    def frame(label):
        return tmp_path / f"{label}.png"

    monkeypatch.setattr(controller, "_capture", lambda label: frame(label))
    monkeypatch.setattr(controller, "identify_current_role", lambda _path: ("role-a", 0.99))
    monkeypatch.setattr(controller, "_click_template", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(controller, "_read_identity", lambda path: SimpleNamespace(
        role_id="role-a" if Path(path).name == "source_profile.png" else final_identity
    ))
    monkeypatch.setattr(controller, "_click_text", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(controller, "_capture_until_text", lambda label, *_args, **_kwargs: frame(label))
    monkeypatch.setattr(controller, "_capture_until_role_name", lambda label, *_args, **_kwargs: frame(label))
    monkeypatch.setattr(controller, "_click_role_name", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(controller, "_capture_until_role_login_dialog",
                        lambda *_args, **_kwargs: frame("login_confirm"))
    monkeypatch.setattr(controller, "_wait_for_target_home", lambda *_args, **_kwargs: frame("home"))
    def capture_until_identity(label, role_id, *, timeout):
        identity_waits.append((label, role_id, timeout))
        return frame("source_profile" if role_id == "role-a" else "target_profile")

    monkeypatch.setattr(controller, "_capture_until_identity", capture_until_identity)
    controller._identity_wait_calls = identity_waits


def test_capture_until_identity_waits_for_profile_animation(tmp_path):
    _store, controller = _role_switch_fixture(tmp_path)
    now = [0.0]
    observations = [None, None, SimpleNamespace(role_id="role-a")]
    frames = []

    controller.monotonic = lambda: now[0]
    controller.sleeper = lambda seconds: now.__setitem__(0, now[0] + seconds)
    controller.poll_seconds = 0.25
    def capture(label):
        path = tmp_path / f"{label}-{len(frames)}.png"
        frames.append(path)
        return path

    controller._capture = capture
    controller._read_identity = lambda _path: observations.pop(0)

    found = controller._capture_until_identity("source_profile", "role-a", timeout=1.0)

    assert found == tmp_path / "source_profile-2.png"
    assert len(frames) == 3
    assert now[0] == 0.5


def test_verified_role_switch_invalidates_both_roles_live_page_state(tmp_path, monkeypatch):
    store, controller = _role_switch_fixture(tmp_path)
    _stub_switch_navigation(monkeypatch, controller, tmp_path)
    recorded = []

    from winter_agent_v2 import state_truth
    monkeypatch.setattr(state_truth, "record_role", lambda *args, **kwargs: recorded.append(kwargs))

    result = controller.switch_to(
        source_role_id="role-a", target_role_id="role-b", reason="ROLE_B has runnable work",
    )

    state = store.load()
    assert result.ok is True
    assert result.role_id == "role-b"
    assert result.reason == "ROLE_SWITCH_LIVE_PROFILE_VERIFIED"
    assert controller._identity_wait_calls == [
        ("source_profile", "role-a", 8.0),
        ("target_profile", "role-b", 8.0),
    ]
    assert recorded and recorded[0]["verification"] == "LIVE_ROLE_SWITCH_PROFILE_READ"
    assert state.active_role_id == "role-b"
    assert state.role_switch_pending is None
    assert state.role_switch_success_count == 1
    assert state.roles["role-a"].health == "STALE"
    assert state.roles["role-a"].page is None
    assert state.roles["role-a"].current_goal == ""
    assert state.roles["role-a"].current_skill == ""
    assert state.roles["role-b"].health == "NEEDS_FRESH_OBSERVATION"
    assert state.roles["role-b"].page is None
    assert state.roles["role-b"].current_goal == ""
    assert state.roles["role-b"].current_skill == ""
    assert state.roles["role-b"].dirty_live_state is True


def test_role_identity_mismatch_aborts_switch_and_sets_bounded_retry(tmp_path, monkeypatch):
    store, controller = _role_switch_fixture(tmp_path)
    _stub_switch_navigation(monkeypatch, controller, tmp_path, final_identity="wrong-account")
    recorded = []

    from winter_agent_v2 import state_truth
    monkeypatch.setattr(state_truth, "record_role", lambda *args, **kwargs: recorded.append(kwargs))

    result = controller.switch_to(
        source_role_id="role-a", target_role_id="role-b", reason="ROLE_B has runnable work",
    )

    state = store.load()
    target = state.roles["role-b"]
    assert result.ok is False
    assert result.role_id == "role-a"
    assert result.reason == "TARGET_PROFILE_ACCOUNT_ID_MISMATCH"
    assert recorded == []
    assert state.active_role_id == "role-a"
    assert state.role_switch_pending is None
    assert state.role_switch_success_count == 0
    assert state.role_switch_failure_count == 1
    assert target.switch_failure_streak == 1
    assert target.blocked_until is not None
    assert target.last_failure == "TARGET_PROFILE_ACCOUNT_ID_MISMATCH"
    assert state.roles["role-a"].health == "NEEDS_FRESH_OBSERVATION"
    assert state.roles["role-a"].page is None
