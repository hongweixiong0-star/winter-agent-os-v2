"""The launcher must not overwrite a working credential with a stale one.

Measured 2026-09-19, and it cost a launch: this shell's ``CODEBUDDY_GATEWAY_PASSWORD`` answered
200 while the Windows user environment held an older value that answered 401.  ``panel_restart.py
--start`` read the registry **first**, so it handed the child the stale copy and the panel came up
with ``AUTH_REJECTED`` -- a healthy gateway reported as broken.

``workbuddy_bridge.gateway_password()`` reads the process environment first and falls back to the
registry, so the launcher now follows the same order: the inherited value is what the bridge would
have used anyway, and the registry is consulted only when the process has nothing (which is what
the injection was for).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import panel_restart as launcher  # noqa: E402


def test_an_inherited_credential_wins_over_the_persisted_copy():
    """The regression itself: a working value must survive the launcher."""
    value = launcher.user_env(
        "CODEBUDDY_GATEWAY_PASSWORD",
        environ={"CODEBUDDY_GATEWAY_PASSWORD": "current-works"},
        persisted=lambda name: "stale-401",
    )
    assert value == "current-works"


def test_the_persisted_copy_is_still_used_when_the_process_has_nothing():
    """The original purpose of the injection, kept: a bare shell can still launch."""
    value = launcher.user_env(
        "CODEBUDDY_GATEWAY_PASSWORD",
        environ={},
        persisted=lambda name: "from-the-registry",
    )
    assert value == "from-the-registry"


def test_a_blank_inherited_value_falls_back_rather_than_shadowing():
    value = launcher.user_env(
        "CODEBUDDY_GATEWAY_PASSWORD",
        environ={"CODEBUDDY_GATEWAY_PASSWORD": "   "},
        persisted=lambda name: "from-the-registry",
    )
    assert value == "from-the-registry"


def test_the_bridge_and_the_launcher_agree_on_the_order():
    """Two components, one credential, one precedence -- otherwise the launcher is a trap."""
    from winter_agent_v2.workbuddy_bridge import gateway_password

    source = (ROOT / "winter_agent_v2/workbuddy_bridge.py").read_text(encoding="utf-8")
    body = source[source.find("def gateway_password("):source.find("def persisted_password(")]
    # The *code lines*, not any mention: a docstring that names persisted_password() earlier
    # would satisfy a naive search while the code did the opposite (which is how this assertion
    # failed the first time it ran).
    assert (body.index("value = os.environ.get(ENV_PASSWORD")
            < body.index("return value.strip() or persisted_password()")), (
        "the bridge reads the process first; the launcher must not disagree"
    )
    launcher_source = (ROOT / "tools/panel_restart.py").read_text(encoding="utf-8")
    fn = launcher_source[launcher_source.find("def user_env("):]
    fn = fn[:fn.find("\ndef ", 1)]
    assert fn.index("env.get(name") < fn.index("lookup(name)"), (
        "the launcher must read the inherited value before the persisted one"
    )
    assert callable(gateway_password)
