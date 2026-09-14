import unittest

from winter_agent_v2.production_gate import P0Evidence, evaluate_p0_production_gate


class ProductionGateTests(unittest.TestCase):
    def test_observation_only_device_is_not_production_ready(self) -> None:
        result = evaluate_p0_production_gate(P0Evidence(
            adb_connected=True,
            foreground_package_ok=True,
            screenshot_ok=True,
            replay_chain_ok=False,
            live_vision_verified=False,
            live_executor_verified=False,
            live_verifier_verified=False,
            consecutive_live_successes=0,
        ))
        self.assertFalse(result.ready)
        self.assertIn("REPLAY_CHAIN_INCOMPLETE", result.blockers)
        self.assertIn("GATHER_LIVE_SUCCESSES_LT_3", result.blockers)

    def test_gate_requires_three_consecutive_live_successes(self) -> None:
        baseline = dict(
            adb_connected=True,
            foreground_package_ok=True,
            screenshot_ok=True,
            replay_chain_ok=True,
            live_vision_verified=True,
            live_executor_verified=True,
            live_verifier_verified=True,
        )
        self.assertFalse(evaluate_p0_production_gate(P0Evidence(**baseline, consecutive_live_successes=2)).ready)
        self.assertTrue(evaluate_p0_production_gate(P0Evidence(**baseline, consecutive_live_successes=3)).ready)


if __name__ == "__main__":
    unittest.main()
