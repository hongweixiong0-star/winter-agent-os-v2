from __future__ import annotations

"""维护后资源面板的真机识别回归测试。

2026-09-14 游戏维护后，资源搜索面板的结构被改版：
- tab 行不再是 MEAT/WOOD/COAL/IRON 四个固定位置，而是野兽类目标 +
  基础资源 共享同一行水平滚动
- 等级滑条范围由 1~8 改为 1~27
- 选中态视觉样式完全变了：tab 内部是纯蓝色背景（不再是六边形 +
  蓝色 L 框），周围白色描边

本测试用真机采集的 4 张面板状态图，验证 ``selected_resource`` 在
改版后的面板上仍能正确读出当前选中的资源类型。
"""

from pathlib import Path

import pytest

from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

PANEL_FRAMES = {
    "MEAT": "dataset/truth_audit/panel_redesign/panel_meat_selected.png",
    "WOOD": "dataset/truth_audit/panel_redesign/panel_wood_reselect.png",
    "COAL": "dataset/truth_audit/panel_redesign/panel_coal_selected.png",
    "IRON": "dataset/truth_audit/panel_redesign/panel_iron_selected.png",
}


@pytest.fixture(scope="module")
def vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


@pytest.mark.parametrize("resource,rel_path", list(PANEL_FRAMES.items()))
def test_selected_resource_matches_each_live_tab(
    vision: SemanticWorldVision, resource: str, rel_path: str
) -> None:
    """每个真机面板帧对应的资源应当被无歧义识别。

    每个 panel_redesign/*_selected.png 都是在该 tab 被点击后抓的真机全帧。
    在该面板状态下，selected_resource() 必须返回对应的 RESOURCE_*_SELECTED，
    且 pHash 距离 ≤ 32（几何 + 模板重采后的实测值）。
    """
    p = ROOT / rel_path
    if not p.is_file():
        pytest.skip(f"missing live evidence: {rel_path}")
    match = vision.semantic.selected_resource(p)
    assert match is not None, f"no tab selected in {rel_path}"
    assert match.semantic == f"RESOURCE_{resource}_SELECTED"
    assert match.distance <= 32, (
        f"distance too high for {resource}: {match.distance}; "
        "panel redesign or pHash wobble suggests the live template needs "
        "another sample"
    )


def test_panel_geometry_band_matches_live_measurement(vision: SemanticWorldVision) -> None:
    """band / pitch / cell 必须与 2026-09-14 真机测量一致。

    实测：tab 行 y∈[860, 1010]（即 0.672~0.789），间距 157px（≈0.2181×720），
    选中格宽 145px（≈0.2014×720）。

    这里刻意 *不* 断言四个资源的固定 x 中心：客户端会把当前选中的 tab
    重新居中，因此整条 tab 带的滚动偏移在不同会话之间会变化（实测偏移
    分别为 0 与 +400px）。固定中心只对某一种偏移成立，之前的标定就是这样
    导致 SELECT_RESOURCE 点错 tab。滚动偏移由白色选中框实时读出。
    """
    geom = vision.semantic
    assert geom.resource_tab_band == (0.672, 0.789), (
        "维护后实测的 band 偏离, 需要重新截 frame 重测"
    )
    assert abs(geom.resource_tab_pitch - 157 / 720) < 0.002, geom.resource_tab_pitch
    assert abs(geom.resource_tab_cell - 145 / 720) < 0.002, geom.resource_tab_cell
    assert geom.resource_tab_order[-4:] == ("MEAT", "WOOD", "COAL", "IRON")


def test_resource_level_reader_survives_panel_redesign(vision: SemanticWorldVision) -> None:
    """即使等级范围扩大到 27，resource_level 仍能正确读出 1。

    维护前滑条范围 1~8，新版本范围 1~27，但 V2 的 ``resource_level()``
    只依赖绿条右缘几何，读出 1 仍然正确（之前已经过 12 帧实测）。
    """
    p = ROOT / "dataset/truth_audit/panel_redesign/panel_wood_reselect.png"
    if not p.is_file():
        pytest.skip("missing live evidence")
    level = vision.semantic.resource_level(p)
    assert level == 1