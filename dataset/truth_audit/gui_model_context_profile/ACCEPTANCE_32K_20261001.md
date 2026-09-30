# UI-Venus-2-9B Runtime 32K 配置 — 验收报告

日期 2026-10-01 · 提交 `99a2536` · 机器 RTX 4060 Laptop 8188 MiB / Ryzen 7 7840H 8C16T / 31.2 GB DDR5-5600 / Win11 26200

## 一、生产验收字段

| 字段 | 值 | 来源 |
|---|---|---|
| `MODEL_CONTEXT_MAX` | **32768** | 服务端 `/props` 回报 `n_ctx=32768`；`context_budget.MAX_MODEL_CONTEXT` |
| `MAX_INPUT_BUDGET` | **28672** | `32768 − 4096`，`ContextBudgetManager.max_input_budget` |
| `OUTPUT_TOKEN_RESERVE` | **4096** | `context_budget.OUTPUT_RESERVE` |
| `ACTUAL_PROMPT_P50` | **3314** tok | 服务端 `usage.prompt_tokens`，生产客户端 n=3 |
| `ACTUAL_PROMPT_P95` | **3669** tok | 同上 |
| `ACTUAL_PROMPT_MAX` | **3708** tok | 同上（占窗口 11.3%，远未贴近 28672） |
| `VRAM_IDLE` | 7693 MiB used / **265 MiB free** | nvidia-smi，游戏+MAA 运行中 |
| `VRAM_PEAK` | 7839 MiB used / **213 MiB free** | 同上 |
| `RAM_IDLE` | 27327 MiB used (85%) / 4635 free | psutil |
| `RAM_PEAK` | 28523 MiB used / 3643 free | 同上 |
| `MODEL_LATENCY_P50` | **17041 ms** | 生产 flag、真实 UNKNOWN 包、n=3 |
| `MODEL_LATENCY_P95` | **21443 ms** | 同上（min 13225 / max 21932） |
| `KV_CACHE_TYPE` | **f16** | `-ctk f16 -ctv f16` |
| `GPU_OFFLOAD_LAYERS` | **30**（共 33 层） | `-ngl 30` |
| `CUDA_OOM_COUNT` | **0** | 10 个档位全部启动+作答，0 次 OOM |
| `MUMU_IMPACT` | 无截图失败、无掉帧证据 | 见下 §四 |
| `MAA_CAPTURE_IMPACT` | 基线 21.30 ms → ngl16 **21.02**、20 **24.91**、18 **28.73**、24 **29.77–31.90** | 见下 §四 |
| `32K_PRODUCTION_READY` | **NO**（阻塞项：生产工作树未 repin） | 见下 §五 |

## 二、32K 验证阶梯（A/B/C/D）

| 档 | 目标输入 | 估算 | 实测 | 比值 | 延迟 | 图片 | OOM | 被裁 |
|---|---|---|---|---|---|---|---|---|
| real | 真实包 | 5184 | **3781** | 0.729 | 15973 ms | ✓ | 无 | — |
| A | 8192 | 12209 | **9205** | 0.754 | 18614 ms | ✓ | 无 | — |
| B | 16384 | 20869 | **15888** | 0.761 | 30060 ms | ✓ | 无 | — |
| C | 24576 | 5878 | **4309** | 0.733 | 15776 ms | ✓ | 无 | `history:272->8`、world_state 附加项 |
| D | 28672 | 5878 | **4309** | 0.733 | 14768 ms | ✓ | 无 | `history:320->8`、world_state 附加项 |

**必须指出的缺口：C 档与 D 档没有真正跑出来。** 它们的目标输入是 24K / 接近 32K，但实测只发了
4309 token —— 增长器把历史堆到 272 行后估计值越过 28672，预算管理器一次性把历史砍回 8 行
（历史裁剪是 8/4/0 的粗阶梯），于是高档位退化成小档位。**所以「32K 大输入」只验证到 16K
（实测 15888 token），24K–28K 区间尚未被真实发送过。** 这不是安全风险（预算管理器正确地
拒绝了超限），是**验证覆盖的缺口**，修法是让增长器二分找「fit 后不被裁剪」的最大深度。

估算器方向正确：比值 0.73–0.76 表示**始终高估 31–37%**，从不低估，因此不会撞窗口。

## 三、三个改变结论的实测

1. **32K 几乎不花显存。** 混合线性注意力：`-lv 4` 账本在 32768 下报 `CPU KV 272.00 MiB`、
   `CUDA0 KV 272.00 MiB`、`CUDA0 RS 23.03 MiB`。原计划假设 q8_0 +1536 MiB / f16 +3584 MiB，
   因此要降 `-ngl` —— 前提不成立。模型自身 `n_ctx_train = 262144`。
2. **拉满最慢。** `-ngl 24…33` 延迟 p50 依次 16878 / 18209 / 18902 / 17041 / 21011 / 21183 /
   **39935** ms，99 层 59325 ms。全部启动成功、0 次 OOM。33 层只剩 70 MiB，WDDM 换页导致 GPU 干等；
   拐点**只有一层宽**（32 层 21183 ms → 33 层 39935 ms），可用下限约剩余 100–200 MiB。
3. **输出长度按 tok/s 直接折算成延迟。** 一条 plan 约 147 token，解码 14–16 tok/s。

## 四、设备影响（MUMU / MAA capture）

方法：三阶段（不挂模型 / 挂载空闲 / 推理负载中）各采样同一时间窗，MAA `capture()` 计时。

- **MAA capture p95**：基线 21.30 ms → ngl16 **21.02**（无统计差异）→ 20 **24.91** → 18 **28.73**
  → 24 **29.77–31.90**。ngl18 出现单次 **24636 ms** 的极端停顿，ngl20 出现 383 ms。
- **无任何一次截图失败**（所有档位、所有阶段 failures = 0），**无 CUDA OOM**。
- **ADB 往返是噪声，已排除出判据**：它计时的是 adb.exe 进程启动，在负载完全不变时自己从
  24.5 ms 飘到 163 ms（3.7×）。早期版本因此误判过一个健康档位，已修正。
- ngl 30 未做设备影响采样（该轮只覆盖 16/18/20/24），其位置由 24 与 32 的结果夹逼，
  **这是有意折中而非任一测量的最优点**：更多 offload 让模型更快、让截图尾巴更差。

## 五、阻塞项与未完成

1. **repin 未做 → `32K_PRODUCTION_READY = NO`。** 生产面板实际运行在工作树
   `C:\Users\xhw\.codex\worktrees\winter-prod-pinned`，其 HEAD 仍是 `de38da0`：
   **没有 `context_budget.py`，`DEFAULT_CONTEXT` 仍是 8192**。`PRODUCTION_PIN.json` 的
   `data_root` 挂载了主树的 `config/`，所以配置改了、**代码没改**。
   需：更新该工作树到 `99a2536` → 同步 `expected_commit` → 用净化环境
   （`unset PYTHONPATH CODEBUDDY_*`，并确认 `'sitecustomize' in sys.modules == False`）重启面板。
2. **阶梯 C/D 档未真正覆盖**（§二）。
3. **输出契约只买到约 6%**：80 → 73 token。保留校验器要读的 `expected` / `action` 是关键约束；
   去掉 `expected` 实测 42 token / 生成 −38%，但需先改校验器取期望值的来源。
4. **面板「预载 降级」**琥珀告警未查，与速度无关。
5. 游戏会话曾被其他设备踢下线（`账号已经在其他设备登录`）；`RECONNECT_SESSION` 仍是 CANDIDATE，
   缺 `POPUP_SESSION_DISCONNECTED` / `BTN_RECONNECT_SESSION` 模板，不会触发。

## 六、证据文件

```
dataset/truth_audit/gui_model_context_profile/
  device_impact.json            设备影响（16/18/20/24，两轮）
  device_impact_tiebreak.json   18 档复测，含 24636 ms 停顿
  sweep_full_offload.json       33 / 99 层（拉满）
  sweep_cliff.json              26/28/30，拐点定位
  sweep_edge.json               31/32，拐点收窄到一层
  ladder_32k.json               32K 输入阶梯
  profile.json / profile_32k.json   KV A/B 与首轮阶梯
```
工具：`tools/profile_device_impact.py`（新）、`tools/profile_gui_model_context.py`（新）。
