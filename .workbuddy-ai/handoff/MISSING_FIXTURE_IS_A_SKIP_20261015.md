# 把"缺帧"的失败改成诚实的 skip —— 配方、已验证的两个、以及剩下的怎么接（2026-10-15）

> 承接 `THE_FULL_SUITE_IS_RED_AND_WHY_20261014.md`。全量 **301 failed / 29 errors** 里，
> 已确认**最大的一块**是"测试要读的帧不在了"（`dataset/raw/**` 会被 retention 轮转）。
> 帧不在**不是代码缺陷**，但报成 failure 会让下一个人以为代码坏了 —— 而补帧要真机。
> 在补上之前，**skip 是唯一诚实的状态**，这也是项目自己的写法（`tests/test_camp_panel_stamina.py`）。

---

## 一、配方（每个文件 4 步，机械）

1. **找帧常量**：`grep -nE '^[A-Z_]+ *= *ROOT' tests/<file>.py`
   （有的写成 `ROOT / "a" / "b.png"`，有的是 `ROOT / (\n "a"\n "b.png"\n)`，两种都要认。）
2. **确认帧真的不在**（**必须先确认**——见 §三的教训）：
   ```python
   ROOT.joinpath(*re.findall(r'"([^"]+)"', <常量右值>)).is_file()
   ```
3. **加守卫**：
   - **只有个别类用** → 在那个类的 `setUpClass` 里
     `if not FRAME.is_file(): raise unittest.SkipTest(f"missing fixture {FRAME} …")`；
   - **全模块共用一帧**（如 `test_interactive_unknown_element.py`）→ **模块级**
     `pytestmark = pytest.mark.skipif(not FRAME.is_file(), reason=…)`（记得 `import pytest`）。
4. **验证**：跑该文件，必须同时满足 ——
   **失败数下降**、**且没有"真失败被掩盖"**（不依赖帧的用例照常 `passed`）。
   只满足前半条不算修好。

## 二、已完成（都已验证、已提交）

| 文件 | 形状 | 结果 |
|---|---|---|
| `tests/test_entry_badges.py` | 两类各用一个帧子集 → 类级 `setUpClass` | `5 failed, 25 passed` → **`18 passed, 12 skipped`** |
| `tests/test_interactive_unknown_element.py` | 全模块共用 `REAL_FRAME` → 模块级 `pytestmark` | `9 failed` → **`28 skipped`** |

提交：`e103e6a0`、`5ab3f28d`。

## 三、⚠️ 教训：**"引用 dataset/raw/" ≠ "帧不在"**

我按 `grep -l "dataset/raw/"` 数出 **24 个**失败文件"同型"，但抽查发现**高估了**：

- `tests/test_daily_panel_reading.py`：`FRAME = ROOT/"dataset"/"raw"/"live_daily_after_beast.png"` → **存在**；
- `tests/test_alliance_gifts_chain.py`：帧在 `dataset/truth_audit/…`（**5 帧都在**）。

⇒ **这两个的失败是另一类**（真失败 / 期望过期 / order 依赖），**不能给它们加 skip** ——
那会把真问题藏起来。**所以第 2 步"确认帧真的不在"是强制的，不是可选。**

## 四、剩下的怎么接（按这个顺序最省力）

1. 把 24 个文件逐个过 §一 的第 1–2 步（**只做读**：常量 + 存在性），分成两堆：
   **帧不在**（可加 skip）与**帧在**（要另查，多半是真失败）。
2. 先修"帧不在"那堆（机械、可立即验证）；
3. "帧在"那堆交给**逐类归因**：带 traceback 看是 `AssertionError`（期望不符 / 真失败）、
   `IndexError`（真代码错）、还是 `FileNotFoundError` 指向**别的**路径（如 `tmpXXX/episodes.jsonl`
   那族，见 `THE_FULL_SUITE_IS_RED_AND_WHY_20261014.md` §三·补⁴）。
4. 每修一个就跑一遍该文件，**确认"失败→skip 且没掩盖真失败"**再提交。

## 五、预期收益（未量化，别当成结论）

若"帧不在"那堆占总失败的大部分，则修完后 **failed 数会大幅下降、skipped 上升**，
剩下的才是需要看代码的那部分。**具体占比要靠第 1 步读完后数出来** —— 现在还不知道。
