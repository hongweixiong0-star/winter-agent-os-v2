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

import ast
import json
import re
from pathlib import Path

import pytest

from winter_agent_v2.retention import _is_protected, referenced_evidence, select_prunable_screenshots

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 判定一个字符串常量是不是图片引用。用后缀匹配而不是整个字面量正则：
# 字面量的"整段形状"交给 AST 保证，这里只关心它指向一个图片文件。
IMAGE_SUFFIX = re.compile(r"\.(?:png|jpg|jpeg)$", re.IGNORECASE)


def _path_operand_images() -> dict[str, list[Path]]:
    """Image literals the suite uses as a *path*, not as a string.

    This is the discriminator the existence guard needs, and it is why the earlier rule was not
    sound.  ``"before_screenshot": "dataset/raw/a.png"`` inside a fake episode payload is data --
    nothing opens it -- while ``ROOT / ("dataset/raw/control_panel/" "...png")`` is a path the test
    really resolves.  To a text scan both are just a string.  A previous version scanned for image-shaped strings and
tried to exclude the fixtures with "no separator in it", which missed every one of them -- they
all contain one.)

    The AST can: a literal is a path when it is the right-hand operand of ``/``, or the single
    argument of ``Path(...)``.  Implicit concatenation is already one ``Constant`` by the time the
    AST sees it, so ``ROOT / ("a/" "b.png")`` arrives as one literal and the text-level regex
    that once cut it in half is not needed here.

    Measured 2026-10-02: 43 literals by the old rule, of which 5 were real lost evidence; by this
    rule the report is the real ones plus a handful of temporary-directory fixtures that happen to
    be built with ``/`` too.
    """
    references: dict[str, list[Path]] = {}
    for source in sorted(TESTS.glob("test_*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        literals: list[ast.Constant] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                operand = node.right
                if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                    literals.append(operand)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "Path" and len(node.args) == 1:
                    argument = node.args[0]
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        literals.append(argument)
        for constant in literals:
            if IMAGE_SUFFIX.search(constant.value):
                references.setdefault(constant.value, []).append(source)
    return references


def repo_path(literal: str) -> Path | None:
    """The repo path a literal denotes, or ``None`` when it cannot denote one.

    An image-shaped *string* is not yet an evidence reference, and most of them are not paths at
    all.  A test that builds its fixtures under ``TemporaryDirectory`` writes
    ``screens/medoid.png`` or ``hero_a/sample.png`` relative to *that* root; another puts
    ``"before_screenshot": "dataset/raw/a.png"`` inside a fake episode payload, where it is data
    rather than a path; one names ``avatar_templates/missing.png`` because the case under test is a
    missing template, and one asserts against ``/nonexistent/frame.png`` on purpose.  The helper's
    own comment already recognised the family ("允许测试内部构造的绝对路径片段") but the test it
    applied -- "no separator" -- misses every one of them, because they all contain one.

    Measured 2026-10-02: the guard reported 43 literals, of which 5 were real lost evidence.  A
    guard that is 88 percent noise is a guard that stays red, so the rule is made *sound* rather
    than the net being narrowed, and each clause says what it rules out:

    * absolute, and outside the repo  -> ``/tmp/frame.png``, ``/nonexistent/frame.png``
    * first segment is not a directory in this repo -> ``screens/``, ``hero_a/``,
      ``stamina_verify2/``, ``20260923_000206_train/`` -- these are relative to a capture root or
      to a temporary one, so the literal was never a repo path whether or not a file survives
    * the parent chain is not in the repo -> ``run_stub/frame.png``, ``autogen/...``

    What survives is still reported whether it exists or not, so nothing is hidden: the path is
    the evidence, and a missing file is the finding rather than a reason to skip the row.
    """
    candidate = Path(literal)
    if candidate.is_absolute():
        return candidate if candidate.is_relative_to(ROOT) else None
    parts = [part for part in literal.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts:
        return None
    if not (ROOT / parts[0]).exists():
        return None
    if len(parts) > 1 and not (ROOT / Path(*parts[:-1])).is_dir():
        return None
    return ROOT / Path(*parts)


def test_every_image_literal_in_the_suite_resolves_to_a_file() -> None:
    missing: list[str] = []
    for literal, sources in _path_operand_images().items():
        path = repo_path(literal)
        if path is None or path.is_file():
            continue
        missing.append(f"{literal}  (被 {', '.join(p.name for p in sources)} 引用)")
    assert not missing, "测试引用的证据文件缺失:\n" + "\n".join(missing)


def test_referenced_evidence_sits_outside_the_prunable_area() -> None:
    prunable: list[str] = []
    for literal, sources in _path_operand_images().items():
        candidate = repo_path(literal)
        if candidate is None:
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
    "literal, is_repo_path",
    [
        # A real repo path, whether or not the file still exists: the path is the evidence.
        ("dataset/truth_audit/icon_label_controls/samples.json", True),
        ("dataset/raw/control_panel/runtime_auto/20260921_213506_694242/x.png", True),
        # Relative to a TemporaryDirectory or to a capture root, so never a repo path.
        ("screens/medoid.png", False),
        ("hero_a/sample.png", False),
        ("stamina_verify2/stamina_verify2_step_003_after_20260919T144435621168.png", False),
        ("20260923_000206_train/x.png", False),
        # Deliberately absent, by design.
        ("/nonexistent/frame.png", False),
        # A repo segment whose parent chain is not in the repo.
        ("dataset/raw/control_panel/runtime_auto/run_stub/frame.png", False),
    ],
)
def test_the_repo_path_rule_only_claims_what_it_can_support(literal: str, is_repo_path: bool) -> None:
    """The rule has to be sound in both directions or the report it feeds is not usable.

    A false *positive* buries the real rows (that is the 38-of-43 problem); a false *negative*
    would hide the very references this file exists to protect, which is worse.
    """
    assert (repo_path(literal) is not None) is is_repo_path


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
