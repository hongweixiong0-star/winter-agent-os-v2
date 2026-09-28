"""Bounded post-action observation cadence for the existing verifier loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class SettlePolicy:
    name: str
    first_wait_s: float
    retry_wait_s: float


SAME_PAGE_FAST = SettlePolicy("SAME_PAGE_FAST", 0.10, 0.25)
PAGE_TRANSITION = SettlePolicy("PAGE_TRANSITION", 0.15, 0.40)
NETWORK_ACTION = SettlePolicy("NETWORK_ACTION", 0.20, 0.50)
ANIMATION_HEAVY = SettlePolicy("ANIMATION_HEAVY", 0.30, 0.60)
P0_EVENT_FAST_MODE = SettlePolicy("P0_EVENT_FAST_MODE", 0.10, 0.20)


class FrameChangeProbe:
    """Cheap thumbnail comparison before repeating a full observation wait."""

    def __init__(self, before_path: Path) -> None:
        try:
            self._before = self._thumbnail(before_path)
        except (OSError, ValueError):
            self._before = None

    @staticmethod
    def _thumbnail(path: Path) -> np.ndarray:
        with Image.open(path) as source:
            pixels = source.convert("RGB").resize((72, 128))
            return np.asarray(pixels, dtype=np.int16)[13:109, 4:68]

    def changed_fraction(self, after_path: Path) -> float | None:
        if self._before is None:
            return None
        try:
            after = self._thumbnail(after_path)
            delta = np.abs(self._before - after).mean(axis=2)
            return float((delta > 40).mean())
        except (OSError, ValueError):
            return None

    def changed(self, after_path: Path) -> tuple[bool, float | None]:
        fraction = self.changed_fraction(after_path)
        # If either screenshot cannot be measured, keep the verifier moving.
        return fraction is None or fraction >= 0.06, fraction


_NETWORK = frozenset({
    "JOIN_RALLY", "START_RALLY", "BEAR_AUTO_JOIN", "TRAIN_TROOPS",
    "START_RESEARCH", "START_BUILDING_UPGRADE", "ALLIANCE_TECH_CONTRIBUTE",
    "DISPATCH_MARCH", "CLAIM_TRAINING", "CLAIM_FREE_STAMINA",
})
_ANIMATION = frozenset({"ATTACK_BEAST", "START_BATTLE", "EXECUTE_INTEL_RESCUE_SURVIVORS"})
_BEAR_FAST = frozenset({
    "OPEN_BEAR_RALLY_LIST", "JOIN_RALLY", "START_RALLY", "BEAR_AUTO_JOIN",
    "REFRESH_RALLY_LIST", "SELECT_TROOP_PRESET", "DISPATCH_MARCH",
})


def choose(
    skill: str,
    *,
    goal: str = "",
    bear_status: str = "",
    rally_list_visible: bool = False,
) -> SettlePolicy:
    """Pick a bounded cadence without changing verifier or action semantics."""
    skill = str(skill or "").upper()
    if (
        str(goal or "").upper() == "PARTICIPATE_BEAR"
        and skill in _BEAR_FAST
        and (str(bear_status or "").upper() in {"ACTIVE", "OPEN"} or rally_list_visible)
    ):
        return P0_EVENT_FAST_MODE
    if skill in _ANIMATION:
        return ANIMATION_HEAVY
    if skill in _NETWORK or skill.startswith("CLAIM_") or skill.startswith("SUBMIT_"):
        return NETWORK_ACTION
    if skill == "BACK" or skill.startswith(("OPEN_", "NAVIGATE_", "LEAVE_", "RETURN_")):
        return PAGE_TRANSITION
    return SAME_PAGE_FAST
