from __future__ import annotations

"""Retention 不得剪除被测试或已审核证据引用的截图。

背景：`runtime_auto` 下的历史 episode 目录会被 control panel 的
`auto_prune` 轮转删除。一旦某个测试硬编码了其中的路径，套件就会随着
磁盘状态间歇性失败——不是代码回退，而是证据消失。这里把"引用即受保护"
变成可执行的约束：

1. 所有 tests/*.py 里出现的 png/jpg 字面路径都必须真实存在；
2. 这些路径所在的目录不得位于 retention 的可剪除区域；
3. `_is_protected` 必须保护 truth_audit / candidate / seed / evidence。
"""

import json
import re
from pathlib import Path

import pytest

from winter_agent_v2.retention import _is_protected, referenced_evidence, select_prunable_screenshots

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 匹配测试源码里写死的图片路径片段，例如
# ROOT / "dataset/raw/xxx/y.png" 或 Path("dataset/truth_audit/a.png")
IMAGE_LITERAL = re.compile(r'"([^"\n]+\.(?:png|jpg|jpeg))"', re.IGNORECASE)


def _referenced_images() -> dict[str, list[Path]]:
    references: dict[str, list[Path]] = {}
    for source in sorted(TESTS.glob("test_*.py")):
        if source.name == Path(__file__).name:
            # 本文件的注释里带有示意路径，扫描它会误报自己。
            continue
        text = source.read_text(encoding="utf-8")
        for literal in IMAGE_LITERAL.findall(text):
            references.setdefault(literal, []).append(source)
    return references


def test_every_image_literal_in_the_suite_resolves_to_a_file() -> None:
    missing: list[str] = []
    for literal, sources in _referenced_images().items():
        # 允许测试内部构造的绝对路径片段（如 Path(folder)/"x.png"）——
        # 这些片段本身不是完整路径，只有当它能在仓库内解析为真实文件时才算证据。
        candidate = (ROOT / literal).resolve()
        if candidate.is_file():
            continue
        # 不含目录分隔符的裸文件名通常来自 TemporaryDirectory，不算仓库证据。
        if "/" not in literal and "\\" not in literal:
            continue
        missing.append(f"{literal}  (被 {', '.join(p.name for p in sources)} 引用)")
    assert not missing, "测试引用的证据文件缺失:\n" + "\n".join(missing)


def test_referenced_evidence_sits_outside_the_prunable_area() -> None:
    prunable: list[str] = []
    for literal, sources in _referenced_images().items():
        candidate = (ROOT / literal).resolve()
        if not candidate.is_file():
            continue
        if _is_protected(candidate):
            continue
        # dataset/raw/stamina_emergency 等固定样本目录不在 retention 的
        # 剪除根下（剪除只作用于 control_panel），因此仍然安全。
        if "control_panel" in candidate.parts:
            prunable.append(f"{literal}  (被 {', '.join(p.name for p in sources)} 引用)")
    assert not prunable, (
        "以下测试直接引用了会被 retention 剪除的文件，应改为受保护目录下的证据副本:\n"
        + "\n".join(prunable)
    )


@pytest.mark.parametrize(
    "relative",
    [
        "dataset/truth_audit/hard_block_evidence/real_money_offer__live_offer_dismiss_20260913__step_001_before.png",
        "dataset/candidate/template_manifest.json",
    ],
)
def test_protected_evidence_survives_every_prune_policy(relative: str) -> None:
    path = ROOT / relative
    assert path.is_file(), f"受保护证据不存在: {relative}"
    assert _is_protected(path)
    # 即使 max_count=0 且 ttl_days=0（最激进的剪除策略）也不能选中它。
    selected = select_prunable_screenshots([path], max_count=0, ttl_days=0)
    assert selected == []


def test_runtime_captures_are_still_prunable() -> None:
    """保护证据不能把整个剪除机制变成空转。"""
    capture = ROOT / "dataset/raw/control_panel/runtime_auto"
    if not capture.is_dir():
        pytest.skip("本地没有 runtime 截图目录")
    images = [p for p in capture.rglob("*.png") if p.is_file()]
    if not images:
        pytest.skip("runtime 目录下当前没有截图")
    assert not any(_is_protected(p) for p in images)
    selected = select_prunable_screenshots(images, max_count=0, ttl_days=10_000)
    assert selected, "最激进策略下应当至少选中一些 runtime 截图"


def test_every_referenced_production_screenshot_exists() -> None:
    """Section 13: 任何被引用证据不存在 -> FAIL。

    An episode that carries ``before_screenshot``/``after_screenshot`` is making
    an auditable claim.  如果那个文件不在磁盘上，episode 就不是证据。
    Rows written before screenshot tracking was added carry no paths and are
    reported as untraceable rather than treated as broken.
    """
    stream = ROOT / "learning/episodes.jsonl"
    if not stream.is_file():
        pytest.skip("no production episode stream yet")
    missing: list[str] = []
    referenced = 0
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("before_screenshot", "after_screenshot"):
            value = row.get(key)
            if not isinstance(value, str) or not value:
                continue
            referenced += 1
            if not Path(value).is_file():
                missing.append(f"{key}={value} (skill={row.get('skill')})")
    assert not missing, "被引用的生产证据缺失:\n" + "\n".join(missing[:20])
    assert referenced >= 0  # referenced==0 means the stream predates traceability


def test_referenced_production_frames_survive_the_harshest_prune() -> None:
    """被 episode 引用的帧即使位于轮转目录内也不得被剪除。"""
    stream = ROOT / "learning/episodes.jsonl"
    if not stream.is_file():
        pytest.skip("no production episode stream yet")
    referenced = referenced_evidence(ROOT)
    if not referenced:
        pytest.skip("no episode carries a screenshot reference yet")
    existing = [p for p in referenced if p.is_file()]
    if not existing:
        pytest.skip("referenced frames are absent from disk; the other test reports that")
    rotation_only = [p for p in existing if "control_panel" in p.parts]
    if not rotation_only:
        pytest.skip("no referenced frame lives inside a rotating capture directory")
    selected = select_prunable_screenshots(
        rotation_only, max_count=0, ttl_days=0, referenced=referenced
    )
    assert selected == [], (
        "referenced production frames must never be prune candidates: "
        f"{[str(p) for p in selected][:5]}"
    )
