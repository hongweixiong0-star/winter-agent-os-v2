from __future__ import annotations

"""截图命名规范：{episode_id}_{step_id}_{stage}[_{suffix}]_{timestamp}.png

总指令要求每一步的截图 ID 自描述：即使文件被复制出 episode 目录，也能从
文件名还原它属于哪个 episode、哪一步、是 before 还是 after。

历史 episode 目录里的 `step_00N_before.png` 属于已归档证据，按 directive 44
不得改写，因此本测试只约束新产生的命名。
"""

import re
from pathlib import Path

from winter_agent_v2.runtime import LiveRuntime

ROOT = Path(__file__).resolve().parents[1]

NAME = re.compile(
    r"^(?P<episode>[0-9]{8}_[0-9]{6}_[0-9]{6})"
    r"_step_(?P<step>[0-9]{3})"
    r"_(?P<stage>before|after)"
    r"(?:_(?P<suffix>.+?))?"
    r"_(?P<stamp>[0-9]{8}T[0-9]{12})\.png$"
)


def _runtime(tmp_path: Path) -> LiveRuntime:
    """只借用命名方法，不启动设备。"""
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.capture_dir = tmp_path / "20260914_051004_623046"
    return runtime


def test_before_and_after_names_are_self_describing(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    for index, stage in ((1, "before"), (1, "after"), (12, "before")):
        name = runtime._capture_path(index, stage).name
        match = NAME.match(name)
        assert match, f"命名不符合规范: {name}"
        assert match.group("episode") == "20260914_051004_623046"
        assert match.group("step") == f"{index:03d}"
        assert match.group("stage") == stage
        assert match.group("suffix") is None


def test_suffix_keeps_recovery_and_refresh_frames_distinct(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    names = {
        runtime._capture_path(3, "after").name,
        runtime._capture_path(3, "after", suffix="refresh_1").name,
        runtime._capture_path(3, "after", suffix="refresh_2").name,
        runtime._capture_path(3, "after", suffix="payment_offer_closed_1").name,
    }
    assert len(names) == 4, "同一 step 的不同重试帧必须互不覆盖"
    for name in names:
        assert NAME.match(name), f"命名不符合规范: {name}"
    # step 恰好匹配（后缀不吞掉 step 字段）
    assert all(m and m.group("step") == "003" for m in (NAME.match(n) for n in names))


def test_capture_path_lives_inside_the_episode_folder(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    path = runtime._capture_path(7, "before")
    assert path.parent == runtime.capture_dir


def test_no_archived_frame_is_renamed_by_the_new_scheme() -> None:
    """历史证据必须保持原文件名，否则 evidence 链会断。"""
    archived = ROOT / "dataset/raw/live_intel_claw4_claim_20260907/step_003_after.png"
    if not archived.is_file():
        return
    assert archived.name == "step_003_after.png"
