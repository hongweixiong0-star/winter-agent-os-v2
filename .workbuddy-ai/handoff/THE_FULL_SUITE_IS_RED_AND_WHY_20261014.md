# ⚠️ 全量测试**不绿**：299 failed / 29 errors —— 而且这个数字**此前看不到**（2026-10-14）

> 本轮用 `--basetemp` 绕开宿主删除守卫，**第一次拿到全量汇总行**。
> 项目记录里长期写着"**本机 pytest 全量跑不出汇总行**" ⇒ **全量的真实状态此前是未知的**。
> 现在它露出来了，而且**不是绿**。**本文件只报事实与已定位的部分，不粉饰。**

---

## 一、数字（原样，2026-10-14 13:38 起跑，27:10 结束）

```
299 failed, 5403 passed, 71 skipped, 9 warnings, 29 errors, 1013 subtests passed
in 1630.05s (0:27:10)
```

用数据根 `.venv`，命令：
`python -m pytest tests -q --basetemp="E:/无尽冬日智能体/tools/_pt_tmp" -p no:cacheprovider`

## 二、29 个 `errors` **已定位**（是守卫**拒绝**，不是漏进生产）

错误原文：

```
conftest.ProductionRuntimeWriteError: PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS != 0 -- 1 write(s)
    write_text(learning/control_panel/gui_model_service.json)
```

**机制**（读 `tests/conftest.py`）：`_REDIRECTS`（`:97`）把一批**模块常量**在整个 session 里
`setattr` 到 `TEST_RUNTIME_ROOT` 下的临时路径；写入守卫（`:346`）**拒绝**任何对
`GUARDED_TREES = ("learning","config")` 下、**没有被重定向覆盖**的写入（`raise` **在写之前**）。

⇒ 所以 `gui_model_service.json` 的写入被**拒绝**（生产没被污染，守卫干得对），但它被记进
`PRODUCTION_WRITES` ⇒ session teardown **把这 29 条报成 error**。

**为什么它没被重定向**：`winter_agent_v2/gui_model_service.py` 里该路径是**内联默认值**
（`:184-186` `self.state_path = state_path or (self.root / "learning/control_panel/gui_model_service.json")`），
**模块里没有对应常量**，而 `_REDIRECTS` 只能重定向**模块常量**。守卫自己的报错就写了补救法：
> "If this path is not covered, add its module constant to `_REDIRECTS`; **do not weaken the guard**."

**两条候选修法（都**未做**）**：
1. **按守卫的原话**：把那条内联路径**提升为模块常量**（`gui_model_service.py`），再加进 `_REDIRECTS`
   —— 效果**只在测试期**（同一 fixture 会在 teardown 还原），**不影响生产**；
2. 找出那个**没传 `state_path`/`root` 隔离**的测试，让它传临时路径 —— 治标，但更窄。

## 三、299 个 `failed` **尚未定性**（不猜）

已后台重跑并保留**完整清单**（`--tb=no`，输出到 `E:/tmp/wb_pytest_full.txt`），
跑完看"**按文件的失败分布**"再判断：

- 若**集中在少数文件** → 逐个看是环境性（Tk 无显示 / 需要设备 / fixture）还是真因；
- 若**散在所有文件** → 先查是否"**测试写坏了活运行态导致级联**"
  （`learning/`/`config/` 是**junction**，与 pin 树共享同一份 —— 这一点本会话已确证）。

**在分布出来之前，本文件不把 299 说成"回归"，也不说成"环境性"** —— 两者都还没证据。

### 三·补：重跑进行中的**实时进度**（已有证据）

后台重跑用 `-q`（一测一字符）。跑到 **~26%** 时读了一次输出：

```
字符直方图： 1437 个 '.'  63 个 'F'  5 个 's'（跳过）
开头片段：  .........F...F..........[1%] .....FFFF..F....[2%] .........Fsss.....[3%]
            ..........F....F......[4%] ....FFFFF....FFF....[6%] ......F.....[7%] ...
```

⇒ **63 个失败散布在整段里，不是堆在开头** ⇒ **可以排除"单个早期失败引发级联"**。
（这也与总数相符：`63/≈1500 ≈ 4.2%`，而全量是 `299/5753 ≈ 5.2%`。）

**未定性的部分不变**：还要等**收尾时的那份完整失败清单**（`-q --tb=no` 会在末尾列出），
才能按文件归组、判断是"若干文件的系统性失败"还是"环境性"。

⚠️ **重跑期间不改动被它测试的代码**（`winter_agent_v2/`、`tests/`）—— 免得污染这次测量。
`gui_model_service.py` 那条修法**等重跑结束再做**。

## 四、能说 / 不能说

- **能说**：① 全量当前 **299 failed / 29 errors / 5403 passed**（这是**第一次**有汇总行）；
  ② 29 个 error 的**机制已定位**（内联路径未被 `_REDIRECTS` 覆盖，守卫拒绝并记账）；
  ③ 补救法**守卫自己写了**，且**只在测试期生效**。
- **不能说**：299 是不是回归、是不是环境性、有没有长期存在（**都没有证据**）；
  也不能说"pin 树跑就会绿"（**那个假设现在必须被检验，不能假定**）。

## 五、未做

**没改任何测试或代码**（先量）；没修 `_REDIRECTS`；没改 `gui_model_service.py`；
没动 `learning/`（junction，不该被"复原"）；**299 的清单在后台重跑中**。
