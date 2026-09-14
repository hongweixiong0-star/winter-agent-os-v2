import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.ocr import HybridVision, OCRPageClassifier, OCRResult, OCRService, OCRToken


class FakeBackend:
    name = "fake"

    def __init__(self, tokens):
        self.tokens = tuple(tokens)
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return self.tokens


class UnknownTemplateVision:
    def observe(self, _):
        return WorldState()


class KnownTemplateVision:
    def observe(self, _):
        return WorldState(page=Page.MAP, confidence=0.99)


class AllianceTemplateVision:
    def observe(self, _):
        return WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"UNKNOWN"}, confidence=0.99)


class ResearchTemplateVision:
    def observe(self, _):
        return WorldState(page=Page.RESEARCH, research={"node":"WARD_EXPANSION_VII","status":"IN_PROGRESS","timer":"VISIBLE","queue_available":False}, confidence=0.99)


class IntelTemplateVision:
    def observe(self, _):
        return WorldState(page=Page.INTEL, intel={"status":"CLAIMABLE", "claimable_count":1}, confidence=0.99)


class OCRTests(unittest.TestCase):
    def test_hybrid_reads_current_intel_stamina_without_stale_template_number(self):
        backend = FakeBackend([
            OCRToken("200", 1.0, ((606, 30), (654, 30), (654, 56), (606, 56))),
            OCRToken("next 06 xx 21:16", 0.94, ((252, 115), (472, 115), (472, 144), (252, 144))),
        ])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "intel.png"
            Image.new("RGB", (720, 1280), "white").save(path)
            state = HybridVision(IntelTemplateVision(), OCRService(backend)).observe(path)
        self.assertEqual(state.intel["stamina"], 200)
        self.assertEqual(state.intel["refresh"], "06:21:16")

    def test_hybrid_uses_ocr_for_dynamic_map_march_count_and_status(self):
        backend = FakeBackend([
            OCRToken("行军", 0.99, ((40, 200), (90, 200), (90, 230), (40, 230))),
            OCRToken("3/6", 0.99, ((197, 204), (242, 204), (242, 232), (197, 232))),
            OCRToken("采集中", 0.99, ((60, 311), (118, 311), (118, 336), (60, 336))),
            OCRToken("00:00:58", 0.99, ((89, 396), (162, 396), (162, 416), (89, 416))),
        ])

        class MapVision:
            def observe(self, _):
                return WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99)

        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (720, 1280), "white").save(path)
            state = HybridVision(MapVision(), OCRService(backend)).observe(path)
        self.assertEqual((state.march_used, state.march_max), (3, 6))
        self.assertIn("GATHERING", [item.value for item in state.marches])
        self.assertIn("MARCHING", [item.value for item in state.marches])

    def test_hybrid_preserves_semantic_beast_march_when_ocr_sees_gathering(self):
        backend = FakeBackend([
            OCRToken("6/6", 0.99, ((197, 204), (242, 204), (242, 232), (197, 232))),
            OCRToken("采集中", 0.99, ((60, 311), (118, 311), (118, 336), (60, 336))),
        ])

        class BeastOutboundVision:
            def observe(self, _):
                return WorldState(
                    page=Page.MAP,
                    marches=(MarchState.MARCHING,),
                    march_used=6,
                    march_max=6,
                    beast={"name":"麝牛", "level":9, "status":"MARCHING"},
                    confidence=0.99,
                )

        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (720, 1280), "white").save(path)
            state = HybridVision(BeastOutboundVision(), OCRService(backend)).observe(path)
        self.assertEqual([item.value for item in state.marches], ["MARCHING", "GATHERING"])

    def test_resource_detail_reads_global_march_capacity_before_gather(self):
        backend = FakeBackend([
            OCRToken("6/6", 0.99, ((197, 204), (242, 204), (242, 232), (197, 232))),
        ])

        class ResourceDetailVision:
            def observe(self, _):
                return WorldState(page=Page.RESOURCE_DETAIL, resource_available=True, confidence=0.99)

        with TemporaryDirectory() as temp:
            path = Path(temp) / "resource.png"
            Image.new("RGB", (720, 1280), "white").save(path)
            state = HybridVision(ResourceDetailVision(), OCRService(backend)).observe(path)
        self.assertEqual((state.march_used, state.march_max), (6, 6))
        self.assertEqual(state.idle_marches, 0)

        decision = __import__("winter_agent_v2.brain", fromlist=["RuleBrain"]).RuleBrain(
            current_goal="GATHER_RESOURCE"
        ).decide(state, __import__("winter_agent_v2.skills", fromlist=["v2_registry"]).v2_registry())
        self.assertEqual(decision.reason, "no_idle_march")

    def test_existing_gathering_row_does_not_complete_new_resource_target(self):
        state = WorldState(
            page=Page.RESOURCE_DETAIL,
            resource_available=True,
            resource_target="WOOD",
            marches=(MarchState.GATHERING,),
            march_used=2,
            march_max=6,
            confidence=0.99,
        )
        decision = __import__("winter_agent_v2.brain", fromlist=["RuleBrain"]).RuleBrain(
            current_goal="GATHER_RESOURCE", reserve_marches=1
        ).decide(state, __import__("winter_agent_v2.skills", fromlist=["v2_registry"]).v2_registry())
        self.assertEqual(decision.skill, "START_GATHER")
    def test_hash_cache_and_normalized_roi(self):
        backend = FakeBackend([OCRToken("联盟科技", 0.99)])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (200, 100), "white").save(path)
            service = OCRService(backend)
            roi = {"x_norm":0.1,"y_norm":0.2,"w_norm":0.5,"h_norm":0.5}
            self.assertFalse(service.recognize(path, roi).cached)
            self.assertTrue(service.recognize(path, roi).cached)
            self.assertEqual(backend.calls, 1)

    def test_alliance_counter_is_structured(self):
        result = OCRResult((OCRToken("联盟科技",1.0), OCRToken("您的捐献：49,680",0.938)), "fake")
        state = OCRPageClassifier().classify(result)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance["personal_contribution"], 49680)

        spaced = OCRResult((OCRToken("联盟科技",1.0), OCRToken("您的捐献：49, 680",0.938)), "fake")
        self.assertEqual(OCRPageClassifier().classify(spaced).alliance["personal_contribution"], 49680)

    def test_alliance_contribution_result_is_structured(self):
        result = OCRResult((
            OCRToken("联盟永续", 0.99),
            OCRToken("240", 0.99),
            OCRToken("次数：23/25", 0.99),
            OCRToken("00:09:33后恢复1次捐献次数", 0.99),
        ), "fake")
        state = OCRPageClassifier().classify(result)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance["status"], "CONTRIBUTED")
        self.assertEqual(state.alliance["contribution"], 240)
        self.assertEqual(state.alliance["attempts_remaining"], 23)

    def test_alliance_gifts_counters_are_structured(self):
        result = OCRResult((
            OCRToken("联盟宝箱", 0.99),
            OCRToken("93,734/150,000", 0.99),
            OCRToken("战利品宝箱", 0.99),
            OCRToken("已领取", 0.99),
            OCRToken("每日战利品宝箱上限：61/500", 0.99),
        ), "fake")
        state = OCRPageClassifier().classify(result)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance["section"], "GIFTS")
        self.assertEqual(state.alliance["gift_progress"], 93734)
        self.assertEqual((state.alliance["daily_claimed"], state.alliance["daily_limit"]), (61, 500))
        self.assertEqual(state.alliance["status"], "CLAIMED")

    def test_daily_alliance_task_is_structured(self):
        result = OCRResult((
            OCRToken("每日任务", 0.99),
            OCRToken("40", 0.99), OCRToken("120", 0.99), OCRToken("215", 0.99), OCRToken("325", 0.99),
            OCRToken("65", 0.99), OCRToken("80", 0.99),
            OCRToken("完成联盟捐献5次（5/5）", 0.99),
            OCRToken("领取", 0.99), OCRToken("一键领取", 0.99),
        ), "fake")
        state = OCRPageClassifier().classify(result)
        self.assertIs(state.page, Page.DAILY)
        self.assertEqual(state.daily["task_id"], "ALLIANCE_CONTRIBUTE_5")
        self.assertEqual((state.daily["progress"], state.daily["goal"]), (5, 5))
        self.assertEqual(state.daily["activity"], 65)
        self.assertEqual(state.daily["status"], "CLAIMABLE")

    def test_ambiguous_or_low_confidence_stays_unknown(self):
        ambiguous = OCRResult((OCRToken("联盟科技",0.99), OCRToken("每日任务",0.99)), "fake")
        low = OCRResult((OCRToken("联盟科技",0.5),), "fake")
        self.assertIs(OCRPageClassifier().classify(ambiguous).page, Page.UNKNOWN)
        self.assertIs(OCRPageClassifier().classify(low).page, Page.UNKNOWN)

    def test_training_requires_status_and_camp_semantics(self):
        training = OCRResult((OCRToken("训练中",0.99), OCRToken("盾兵营",0.99), OCRToken("10:03:12",0.99), OCRToken("正在训练806位王牌盾兵",0.99)), "fake")
        status_only = OCRResult((OCRToken("训练中",0.99),), "fake")
        self.assertIs(OCRPageClassifier().classify(training).page, Page.TRAINING)
        state = OCRPageClassifier().classify(training)
        self.assertEqual(state.training["troop_type"], "INFANTRY")
        self.assertEqual(state.training["timer"], "10:03:12")
        self.assertEqual(state.training["batch_count"], 806)
        self.assertIs(OCRPageClassifier().classify(status_only).page, Page.UNKNOWN)

    def test_research_node_progress_and_timer_are_structured(self):
        result = OCRResult((
            OCRToken("科技研究", 0.99),
            OCRToken("病房扩建VII", 0.99),
            OCRToken("2/3", 0.99),
            OCRToken("5天00:55:44", 0.99),
        ), "fake")
        state = OCRPageClassifier().classify(result)
        self.assertIs(state.page, Page.RESEARCH)
        self.assertEqual(state.research["node"], "WARD_EXPANSION_VII")
        self.assertEqual(state.research["level_progress"], "2/3")
        self.assertEqual(state.research["timer"], "5d00:55:44")
        self.assertFalse(state.research["queue_available"])

    def test_hybrid_is_template_first(self):
        """Pages the template layer fully resolves are not OCR'd.

        The world map is deliberately *not* one of those pages any more: the
        stamina gauge has to be read there, or "stamina is full" stays
        unobservable and AUTO can never choose to spend it.  That exception is
        pinned by test_hybrid_reads_the_map_hud_stamina below.
        """
        backend = FakeBackend([OCRToken("联盟科技", 0.99)])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (10, 10), "white").save(path)
            state = HybridVision(HomeTemplateVision(), OCRService(backend)).observe(path)
            self.assertIs(state.page, Page.HOME)
            self.assertEqual(backend.calls, 0)

    def test_hybrid_reads_the_map_hud_stamina(self):
        backend = FakeBackend([
            OCRToken("200", 0.99, ((30, 101), (68, 101), (68, 119), (30, 119))),
        ])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "map.png"
            Image.new("RGB", (720, 1280), "white").save(path)
            state = HybridVision(MapTemplateVision(), OCRService(backend)).observe(path)
        self.assertIs(state.page, Page.MAP)
        self.assertEqual(state.stamina["current"], 200)
        self.assertEqual(state.stamina["source"], "MAP_HUD")

    def test_hud_stamina_ignores_numbers_outside_its_roi(self):
        """A number drawn elsewhere on the map must never be read as stamina."""
        backend = FakeBackend([
            OCRToken("70,206,322", 0.99, ((131, 58), (268, 58), (268, 87), (131, 87))),
        ])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "map.png"
            Image.new("RGB", (720, 1280), "white").save(path)
            state = HybridVision(MapTemplateVision(), OCRService(backend)).observe(path)
        self.assertNotIn("current", state.stamina)

    def test_hybrid_uses_ocr_for_unknown_template(self):
        backend = FakeBackend([OCRToken("联盟科技", 0.99)])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (10, 10), "white").save(path)
            state = HybridVision(UnknownTemplateVision(), OCRService(backend)).observe(path)
            self.assertIs(state.page, Page.ALLIANCE)

    def test_hybrid_enriches_known_alliance_without_overriding_template_state(self):
        backend = FakeBackend([OCRToken("联盟科技",1.0), OCRToken("您的捐献：49.680",0.99)])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (10, 10), "white").save(path)
            state = HybridVision(AllianceTemplateVision(), OCRService(backend)).observe(path)
            self.assertEqual(state.alliance["status"], "UNKNOWN")
            self.assertEqual(state.alliance["personal_contribution"], 49680)

    def test_hybrid_enriches_research_visible_timer(self):
        backend = FakeBackend([
            OCRToken("科技研究", 1.0),
            OCRToken("病房扩建VII", 0.99),
            OCRToken("2/3", 0.99),
            OCRToken("5天00:55:44", 0.99),
        ])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "screen.png"
            Image.new("RGB", (10, 10), "white").save(path)
            state = HybridVision(ResearchTemplateVision(), OCRService(backend)).observe(path)
            self.assertEqual(state.research["timer"], "5d00:55:44")
            self.assertEqual(state.research["node"], "WARD_EXPANSION_VII")

    def test_current_event_page_reads_live_progress_timer_and_visible_tiers(self):
        result = OCRResult((
            OCRToken("常规活动", 1.0), OCRToken("最强王国", 1.0),
            OCRToken("击败野兽 12:03:29", .99), OCRToken("我的积分：0", 1.0),
            OCRToken("80,000", .99), OCRToken("150,000", .99), OCRToken("300,000", .99),
            OCRToken("联盟积分：36,436,030", .99), OCRToken("5,550,000", .99),
        ), "fake")
        state = OCRPageClassifier().classify(result)
        minimum = state.events["minimum_guarantee"]
        self.assertIs(state.page, Page.EVENT)
        self.assertEqual(minimum["current_points"], 0)
        self.assertEqual(minimum["target_points"], 80000)
        self.assertEqual(minimum["points_missing"], 80000)
        self.assertEqual(minimum["remaining_seconds"], 12 * 3600 + 3 * 60 + 29)
        self.assertEqual(minimum["scoring_stage"], "击败野兽")


if __name__ == "__main__":
    unittest.main()
