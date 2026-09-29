import json

from PIL import Image

from winter_agent_v2.role_switch_controller import load_role_catalog


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
