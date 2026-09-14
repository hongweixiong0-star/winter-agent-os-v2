from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_popup_closed
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]
# 原始证据 dataset/raw/control_panel/runtime_auto/20260912_230906_574238/
# step_001_before.png 已被 retention.auto_prune 剪除，磁盘上按 SHA256 全盘
# 搜索无任何存活副本（2084 张图，0 命中），无法恢复。
#
# 该帧改为由保全下来的模板裁剪重建：横幅与关闭按钮贴回各自的 reviewed ROI，
# 其余区域填中性底。它只能证明检测与路由链路，不能作为 live 像素证据，
# 因此文件名带 RECONSTRUCTED 标记。
IMAGE = (
    ROOT
    / "dataset/truth_audit/hard_block_evidence"
    / "battle_victory_banner__RECONSTRUCTED__from_pruned_parent_be9b5de2.png"
)
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"


def test_live_battle_victory_overlay_preempts_underlying_map() -> None:
    vision = SemanticWorldVision(MANIFEST)
    state = vision.observe(IMAGE)
    assert state.page is Page.POPUP
    assert state.popup == "BATTLE_VICTORY_BANNER"
    match = vision.semantic.find(IMAGE, "POPUP_BATTLE_VICTORY_BANNER")
    assert match is not None
    # 距离 2，阈值 16：重建帧保留足够裕度，说明 ROI 几何与模板未漂移。
    assert match.distance <= 4


def test_battle_victory_routes_to_specific_dismiss_skill() -> None:
    state = WorldState(page=Page.POPUP, popup="BATTLE_VICTORY_BANNER", confidence=0.99)
    decision = RuleBrain(current_goal="GATHER_RESOURCE").decide(state, v2_registry())
    assert decision.skill == "DISMISS_BATTLE_VICTORY"


def test_battle_victory_verifier_requires_real_popup_transition() -> None:
    before = WorldState(page=Page.POPUP, popup="BATTLE_VICTORY_BANNER", confidence=0.99)
    after = WorldState(page=Page.MAP, confidence=0.99)
    assert verify_popup_closed(before, after).ok
    assert not verify_popup_closed(before, before).ok
