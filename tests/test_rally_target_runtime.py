import unittest

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.rally import RallyTarget, live_rally_join_point
from winter_agent_v2.runtime import LiveRuntime, _verify_rally_action


class RallyTargetRuntimeTests(unittest.TestCase):
    def _frame(self):
        return WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "RALLY_LIST", "rally_list_visible": True},
            rally={
                "source": "LIVE_CLIENT_RALLY_LIST",
                "rows": [
                    {"target_type": "BEAR", "state": "JOINABLE", "join_norm": [0.81, 0.25],
                     "remaining_seconds": 12, "capacity_used": 1, "capacity_max": 15},
                    {"target_type": "POLAR_TERROR", "state": "JOINABLE", "join_norm": [0.72, 0.43],
                     "remaining_seconds": 30, "capacity_used": 2, "capacity_max": 15},
                    {"target_type": "POLAR_TERROR", "state": "JOINABLE", "join_norm": [0.76, 0.51],
                     "remaining_seconds": 10, "capacity_used": 4, "capacity_max": 15},
                ],
            },
        )

    def test_adb_semantic_resolver_uses_current_goal_target(self):
        runtime = LiveRuntime.__new__(LiveRuntime)
        frame = self._frame()

        point = runtime._resolve_semantic_target(
            "RALLY_ROW_JOIN_BUTTON", frame, rally_target=RallyTarget.POLAR_TERROR
        )

        self.assertEqual(point, (0.76, 0.51))

    def test_legacy_bear_goal_does_not_select_polar_row(self):
        frame = self._frame()
        self.assertEqual(live_rally_join_point(frame, RallyTarget.BEAR), (0.81, 0.25))
        self.assertIsNone(live_rally_join_point(frame, RallyTarget.UNKNOWN))

    def test_non_bear_verifier_checks_the_requested_target(self):
        before = WorldState(march_used=2)
        after = WorldState(
            march_used=3,
            alliance={"rally": {"target_type": "POLAR_TERROR", "member_state": "JOINED"}},
        )

        self.assertTrue(_verify_rally_action("JOIN_RALLY", before, after, "POLAR_TERROR").ok)
        self.assertFalse(_verify_rally_action("JOIN_RALLY", before, after, "BEAR").ok)
        self.assertFalse(_verify_rally_action("JOIN_RALLY", before, after, "UNKNOWN").ok)

    def test_join_resolver_refuses_stale_or_non_list_state(self):
        runtime = LiveRuntime.__new__(LiveRuntime)
        stale = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "RALLY_LIST", "rally_list_visible": True},
            rally={"source": "OLD_FRAME", "rows": self._frame().rally["rows"]},
        )
        self.assertIsNone(
            runtime._resolve_semantic_target(
                "RALLY_ROW_JOIN_BUTTON", stale, rally_target=RallyTarget.POLAR_TERROR
            )
        )

        outside_list = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "MAIL", "rally_list_visible": False},
        )
        self.assertIsNone(
            runtime._resolve_semantic_target(
                "RALLY_ROW_JOIN_BUTTON", outside_list,
                frame_path="unused.png", rally_target=RallyTarget.POLAR_TERROR,
            )
        )


if __name__ == "__main__":
    unittest.main()
