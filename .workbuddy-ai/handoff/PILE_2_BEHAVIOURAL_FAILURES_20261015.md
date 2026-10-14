# pile ②：剩下的失败**不是缺帧，是"行为不符"** —— 6 个已定性 + 怎么接（2026-10-15）

> 承接 `THE_FULL_SUITE_IS_RED_AND_WHY_20261014.md` 与 `MISSING_FIXTURE_IS_A_SKIP_20261015.md`。
> **"缺帧"那一类已经清零**（9 个文件、约 87 个失败 → 诚实 skip，**3 个真失败一个没盖**）。
> 本文件只讲**剩下的**。

---

## 一、结论先说

**剩下的失败全是 `AssertionError` 一类，主要形态是「大脑选了别的技能」**，
不是缺帧、没有可加的守卫。**每个都要读测试 + 读代码才能定**，且相当一部分**要真机对照**。

## 二、已定性的 6 个（可作为判断样例）

| 文件 | 失败首行 | 定性 | 下一步 |
|---|---|---|---|
| `test_navigation_verifier.py` | `assertTrue(result.ok)` → False | 验证器**不认**这两次转场 | 读验证器 + 两次 WorldState；要真机对照 |
| `test_alliance_verifier.py` | `help_state.alliance.get("auto_help_active")` → None | 帧**在**（9-05）但信号读不出 | 期望过期 或 读取器回归；要真机重采 |
| `test_unknown_page_exploration.py` | `IndexError: list index out of range` ×4、`NoneType` ×3 | "某处该有元素却是空的" | 读文件；很可能要真机 |
| `test_stamina_check_without_a_read.py` | `'OPEN_HOME' != 'OPEN_STAMINA_SOURCES'` | 大脑选了别的技能 | 见 §三 |
| `test_reward_claim_verifier.py` | `'SAFE_STOP' != 'OPEN_MAIL'` | 大脑选了别的技能 | 见 §三 |
| `test_building_upgrade_entry_target.py` | `AssertionError: the evidence frame for this change has been rotated away` | **自述缺帧** | **不动它**——它已经把问题说清楚了 |

## 三、判断"大脑选了别的技能"这类的方法（这是剩余工作的主要动作）

以 `test_reward_claim_verifier.py:123` 为例：

```python
self.assertEqual(RuleBrain(current_goal="MAIL").decide(home, v2_registry()).skill, "OPEN_MAIL")
E   AssertionError: 'SAFE_STOP' != 'OPEN_MAIL'
```

**大脑给 HOME + goal=MAIL 的答案是 `SAFE_STOP`。** 两种可能，**必须分开**：

1. **真回归** —— MAIL 路由坏了；
2. **测试的 `home` 状态不完整** —— 大脑后来加了前置条件，状态不足时**正确地**安全停止。

**怎么分**：
- 读测试里 `home = WorldState(...)` 构造了什么；
- 读**大脑该目标的前置条件**（`winter_agent_v2/brain.py` 里 MAIL 分支要什么字段）；
- 若大脑要的字段测试没给 ⇒ **是测试该补状态**（改测试，并把"为什么要这些字段"写进注释）；
- 若测试给全了、大脑仍 `SAFE_STOP` ⇒ **是真回归**，去读那段路由代码。
- ⚠️ **拿不准就停下来问**，别猜——猜错的方向会把真回归改没。

## 四、不要做的事

- **不要**给这批加 `skip`（它们不是缺帧，skip 会把真回归盖掉）；
- **不要**为了"降红"去改断言（那是把测试改成迎合代码）；
- **不要**再找"缺帧"了——**那一类已清零**。

## 五、工具与产出

- `tools/map_pytest_progress.py`：从一次全量 `pytest -q` 的进度流**反推完整失败清单**
  （治"汇总行被吞"）——**先跑一次全量拿到清单，再按失败首行分类**，别一个个文件猜。
- 全量一次约 27 分钟，命令：
  `python -m pytest tests -q --tb=line -p no:cacheprovider --basetemp=<某个空目录> > out.txt 2>&1`
  然后按 `^E ` 行分类。
