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

## 二·补：一个**已定到根因**的样例（2026-10-15）—— 不是回归，是"测试早于那次改动"

`test_reward_claim_verifier.py:123` 的 `'SAFE_STOP' != 'OPEN_MAIL'` **根因已查明**：

```python
# winter_agent_v2/brain.py:1246
mail_gate = entry_badges.entry_gate("MAIL_ROUTINE", getattr(world, "red_dots", None))
if mail_gate[0] != entry_badges.PRESENT:
    return Decision("SAFE_STOP", f"mail_entry_badge_{mail_gate[0].lower()}_this_frame", 1.0, "switch_task")
return Decision("OPEN_MAIL", "mail_entry_has_a_badge", world.confidence, "mail_page_open")
```

**代码里那段注释写明这是故意的**（1240–1245 行）：

> UNKNOWN 和缺失台账过去会落到 OPEN_MAIL……但**对一个存在意义就是那个红点的任务，读不出也不是许可**，
> 为了查明而去开页面就是"周期性访问"换了个名字。入口画在 HOME 上，循环常驻那里，读数可以免费重取；
> **这一轮让给别的目标。**

而测试建的状态是 `home = WorldState(page=Page.HOME, confidence=0.99)` —— **没有 `red_dots`**
⇒ `entry_gate` 得 UNKNOWN ⇒ 大脑**正确地** SAFE_STOP。

**⇒ 定性：`AssertionError` 是"测试早于那次有意改动"，不是回归。**
**修法（未做）**：给测试的 `home` 补上 `red_dots`（一个表示邮件入口 PRESENT 的读数）再断言 `OPEN_MAIL`；
**或**把这条改成断言"读不出 ⇒ SAFE_STOP"（那才是现在的契约）。
**两种都行，但必须选一种**——**不能**改成迎合代码的模糊断言。

⚠️ **这个样例给出了可推广的排查法**：
**先在 `brain.py` 里搜那条 `Decision` 的 reason 字符串**（本例 `mail_entry_badge_*`），
**代码往往已经在注释里写明了"这是故意的 + 为什么"** ⇒ 那就不必去找回归了，直接看测试缺了什么字段。

---

## 二·补²：第二个已追到**一半**的样例（2026-10-15）—— 卡在我上下文耗尽，接力点写清楚

`test_stamina_check_without_a_read.py:163`（`test_the_gauge_is_tapped_when_the_number_was_not_read`）：

```
AssertionError: 'OPEN_HOME' != 'OPEN_STAMINA_SOURCES'
```

大脑的对应分支在 `brain.py:2881–2893`，产出 `OPEN_STAMINA_SOURCES` 需要**同时**满足：

```python
if (
        …（**2881 行往上还有若干条我没读到**）…
        and self.current_goal != "SPEND_STAMINA"
        and not self.stamina_panel_checked
        and not world.resource_search_open
        and self._supply_may_be_due()
):
    self.stamina_panel_checked = True
    return Decision("OPEN_STAMINA_SOURCES", "free_stamina_gift_not_yet_checked_this_run", …)
```

**已排除的一条**：`_supply_may_be_due()` —— 它的 docstring 明写
"**Unknown is always due**（未知时钟一律算可能到了；这是优化，未知时钟不能用来跳过礼物）"。⇒ 不是它。

**⇒ 接力点**：读 `brain.py` **2881 行往上那几条 `if (` 条件**，以及**该分支是否嵌在 `world.page is Page.MAP` 里**
（若嵌着，而测试的 `WorldState` 不在 MAP，就会落到 `OPEN_HOME` —— `OPEN_HOME` 正是"回首页"）。
**判断法与 `test_reward_claim_verifier` 那次同源**：先看代码的 reason/注释，
代码常已写明"这是故意的 + 为什么"，然后回去看**测试缺了哪个前置**。

### 已补完（同轮后续）：**门其实都过了** ⇒ 病因在更早的分支或分支顺序

读全之后，该分支是：

```python
if world.page is Page.MAP:                 # ← 嵌在 "page is MAP" 里
    if (
        self.claim_free_stamina            # 默认 False（brain.py:116）…
        and self.current_goal != "SPEND_STAMINA"
        and not self.stamina_panel_checked
        and not world.resource_search_open
        and self._supply_may_be_due()      # 未知即"到期"
    ):
```

而测试侧：`page=Page.MAP`（:87）、`kwargs.setdefault("claim_free_stamina", True)`（:109）、
`RuleBrain(current_goal="INTEL", claim_free_stamina=True)`（:154）——**门都满足**。

⇒ **所以病因不在这个分支的前置**，而在**更早的分支**或**分支顺序**（某个更早的 `if` 先把它截走了，
那条路最终走到 `OPEN_HOME`）。**⇒ 新接力点：从 `decide()` 的入口往下读，
看 MAP 页上有哪些分支排在 `world.page is Page.MAP` 这个块**之前**，哪一条会产出 `OPEN_HOME`。**

---

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
