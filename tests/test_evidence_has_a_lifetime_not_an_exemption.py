"""Evidence needs a lifetime, not an exemption.

Measured 2026-10-03: dataset/raw/control_panel held 50,051 frames / 33 GB.  Two separate
causes, and this file covers the second:

  * the drain rate was below the production rate (10 deleted per round against ~28 written),
    which is the rate fix in 92fe5155;
  * a frame any episode cited was excluded from pruning *outright*, so "referenced" was a set
    that could only grow.  Even a correct rate cannot drain a set the policy refuses to touch
    -- 20,340 frames were held that way.

The operator's rule gives the two tiers: 3 days for a working frame, 30 for one a Verifier or
Candidate points at.  Both directions are pinned here, and so is the old behaviour, because a
config written before the tier existed must not silently adopt a shorter retention.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.retention import select_prunable_screenshots  # noqa: E402

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _frame(tmp_path: Path, name: str, age_days: float) -> Path:
    path = tmp_path / name
    path.write_bytes(b"x")
    stamp = (NOW - timedelta(days=age_days)).timestamp()
    import os

    os.utime(path, (stamp, stamp))
    return path


class EvidenceHasALifetimeTests:
    def test_a_cited_frame_inside_its_window_is_kept(self, tmp_path):
        """The evidence rule still holds for the 30 days the operator allowed."""
        fresh = _frame(tmp_path, "cited_recent.png", 5)
        kept = select_prunable_screenshots(
            [fresh], max_count=500, ttl_days=3, now=NOW,
            referenced={fresh}, referenced_ttl_days=30)
        assert kept == [], "a cited frame 5 days old is inside its 30-day window"

    def test_a_cited_frame_past_its_window_becomes_prunable(self, tmp_path):
        """The half the old rule got wrong: 'cited' cannot mean 'for ever'."""
        stale = _frame(tmp_path, "cited_stale.png", 45)
        kept = select_prunable_screenshots(
            [stale], max_count=500, ttl_days=3, now=NOW,
            referenced={stale}, referenced_ttl_days=30)
        assert stale in kept, (
            "a cited frame 45 days old is past its reference window; keeping it for ever is "
            "how 20,340 frames accumulated"
        )

    def test_an_uncited_frame_follows_the_short_ttl(self, tmp_path):
        fresh = _frame(tmp_path, "uncited_recent.png", 1)
        stale = _frame(tmp_path, "uncited_stale.png", 5)
        kept = select_prunable_screenshots(
            [fresh, stale], max_count=500, ttl_days=3, now=NOW,
            referenced=set(), referenced_ttl_days=30)
        assert fresh not in kept, "1 day old is inside the 3-day working window"
        assert stale in kept, "5 days old and uncited is past the 3-day working window"

    def test_the_reference_window_is_independent_of_the_working_window(self, tmp_path):
        """A frame cited 10 days ago survives a 3-day TTL -- otherwise the tiers are one tier."""
        cited = _frame(tmp_path, "cited_mid.png", 10)
        uncited = _frame(tmp_path, "uncited_mid.png", 10)
        kept = select_prunable_screenshots(
            [cited, uncited], max_count=500, ttl_days=3, now=NOW,
            referenced={cited}, referenced_ttl_days=30)
        assert cited not in kept
        assert uncited in kept


class AnOlderConfigKeepsTheOlderRuleTests:
    def test_no_reference_window_means_cited_frames_are_never_pruned(self, tmp_path):
        """Absent config must not silently shorten retention -- that would delete evidence."""
        ancient = _frame(tmp_path, "cited_ancient.png", 400)
        kept = select_prunable_screenshots(
            [ancient], max_count=500, ttl_days=3, now=NOW,
            referenced={ancient}, referenced_ttl_days=None)
        assert kept == [], (
            "with no referenced_ttl_days the previous behaviour is kept: a cited frame is "
            "excluded outright"
        )

    def test_the_count_budget_still_applies(self, tmp_path):
        """max_count rotates unreferenced captures regardless of age."""
        frames = [_frame(tmp_path, "f%02d.png" % i, 1) for i in range(6)]
        kept = select_prunable_screenshots(
            frames, max_count=2, ttl_days=999, now=NOW,
            referenced=set(), referenced_ttl_days=30)
        assert len(kept) == 4, kept


class TheOperatorValuesAreConfiguredTests:
    def test_the_shipped_config_carries_both_tiers(self):
        import json

        config = json.loads(
            (Path(__file__).resolve().parents[1] / "config/v2.json").read_text(encoding="utf-8"))
        retention = config.get("retention") or {}
        assert retention.get("screenshot_ttl_days") == 3, retention
        assert retention.get("referenced_ttl_days") == 30, retention
        assert retention.get("auto_prune") is True, retention
