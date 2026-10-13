# 写入守卫**无法**重定向类属性 —— 所以 `test_learning_loop_wiring.py` 常红（2026-10-14）

> `tests/conftest.py` 的 P0 守卫（`PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS == 0`）只能把
> **模块级常量**重定向进临时目录。`OnlineLedger.PATH` 是**类属性**，
> 所以这份"运行时可变"文件**没有可加的模块常量** —— 守卫自己的报错信息给出的补法是够不着的。

## 一、现象

```
ProductionRuntimeWriteError: PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS != 0
    write_text(learning/ui_venus_online.jsonl)   (manifest verdict: RUNTIME_MUTABLE)
    If this path is not covered, add its module constant to ``_REDIRECTS``;
    do not weaken the guard.
```

后果：`tests/test_learning_loop_wiring.py` 里
`SecondEncounterTests::test_the_second_encounter_does_not_ask_the_model` **FAILED**、
`CompilationEndToEndTests::test_two_verified_steps_in_one_session_compile_into_a_candidate_skill` **ERROR**。
（本轮做 A/B 时撞上，已验证**与我的改动无关**：把我的 `learning.py`+`runtime.py` stash 掉重跑，
复现**完全相同**的报错。）

## 二、为什么报错信息里的补法做不到

`conftest._protect_the_live_learning_assets`（`tests/conftest.py:456-472`）的解析是：

```python
for module_name, attribute, live_relative, seed in _REDIRECTS:
    module = __import__(module_name, fromlist=["_"])
    if not hasattr(module, attribute): continue
    previous[(module, attribute)] = getattr(module, attribute)
    setattr(module, attribute, target)
```

`attribute` 必须是**模块的直接属性名**。而实际写入方是：

```python
# winter_agent_v2/ui_venus_online.py:81
ONLINE_LEDGER_PATH = Path("learning/ui_venus_online.jsonl")
# winter_agent_v2/ui_venus_online.py:988-996
class OnlineLedger(Ledger):
    PATH = ONLINE_LEDGER_PATH          # ← 类定义时求值，绑定在类上
```

⇒ 改 `ui_venus_online.ONLINE_LEDGER_PATH` **不会**改到 `OnlineLedger.PATH`（它在类定义时就绑好了）。
`_REDIRECTS` 的 `(module, attribute, …)` 形状**表达不了** `module.Class.PATH`。

（另注：`learning_funnel.py:52` 另有 `ONLINE_LEDGER = ui_venus_online.ONLINE_LEDGER_PATH` 一份导入期拷贝，
所以哪怕支持点号，这里也可能要补两行。）

## 三、最小修法（**本轮没有做**，理由见下）

让 `_REDIRECTS` 的 `attribute` 支持点号，并把 `previous` 改成按**解析后的持有者**记录：

```python
holder, leaf = _resolve_holder(module, attribute)   # 走 attribute.split(".")
previous[(holder, leaf)] = getattr(holder, leaf)
setattr(holder, leaf, target)                       # 复原时同样用 getattr/setattr(holder, leaf)
```

外加一行：
```python
("winter_agent_v2.ui_venus_online", "OnlineLedger.PATH", "learning/ui_venus_online.jsonl", False),
```

## 四、为什么本轮**不**做它 —— 与"改 schema"那次不是同一个判断

- 改 `Episode` 的字段：**有项目自己的先例**（`WB-1002-11` 对同一个 dataclass 加过字段），
  且**爆炸半径 = 一个字段** ⇒ 做了。
- 改这个守卫：**没有先例**，且**爆炸半径 = 每一个测试的写入保护**（改错会让测试重新能写 AUTO 的
  实时状态，而那正是 P0 指令要禁止的事）⇒ **只诊断，不动手**。

同一个推理，两个相反的结论 —— 决定它的是**先例与爆炸半径**，不是"保守"或"激进"。
