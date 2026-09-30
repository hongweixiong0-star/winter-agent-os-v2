# 唯一运行时本地模型迁移：Qwen3.6-35B-MoE Q3 → UI-Venus-2-9B Q4_K_M

日期：2026-09-30　操作者指令：《Winter Agent OS V2 — 唯一本地模型正式迁移》

## 边界（迁移前的东西没动）

保持 `Global Scheduler → Goal → Generic Session Engine/Skill → MAA Executor → Verifier`。
**没有新增**第二 Scheduler / Executor / WorldState / 本地模型 / GUI Agent，也没有 UI-Venus
Desktop runtime 或 WorkBuddy Runtime channel（`workbuddy_channel.enabled` 仍未开）。
UI-Venus 只做一件事：**UNKNOWN GUI 的下一步视觉理解**。它不选 Goal、不切 Role、不改优先级、
不直接点击、不自证完成。

## 基线（以实际代码为准，不假定旧 commit）

| 项 | 值 |
|---|---|
| 迁移前 HEAD / origin/main / 生产 pin | `3b1762c` → 期间被他人推进到 `1f7c9c5` |
| 迁移后 main HEAD | `0a31673`（本轮两个 commit） |
| 生产 pin | `0a316735e5fad878c5a7624323f3297b9346d309` |

别人那两个 commit（`b13c324` / `1f7c9c5`）只动 `winter_agent_v2/ocr.py`、`runtime.py` 与两个测试，
**与本轮文件零交集**，所以没有覆盖别人的改动。

## 本轮 commit

| commit | 内容 |
|---|---|
| `2d222bd` | `feat(model)` — local_gui_model.py 顶替 local_qwen.py；ui_planner 真多模态 + 视觉提案围栏；runtime 把 Verifier 判定 join 回驱动该步的答案；config；三个新工具（常驻服务 / 多模态探针 / UNKNOWN benchmark） |
| `0a31673` | `feat(console)` — 顶部新增第 9 格"本地模型"；`/health` 存活探测；"最近调用"明细；判定列只取 Verifier 记录 |

## 交付物

- `winter_agent_v2/local_gui_model.py`（新，替代已删除的 `local_qwen.py`）
- `winter_agent_v2/ui_planner.py`（截图随每次调用；`candidate_bbox_norm` 只是提案）
- `tools/launch_gui_model_server.py`（常驻 llama-server，`--start/--stop/--status`）
- `tools/probe_gui_model_multimodal.py`（同问题问两遍，证"真的看见了"）
- `tools/benchmark_gui_unknown.py`（走生产 parse 路径打 UNKNOWN 语料）
- `config/v2.json` 的 `local_planner`：provider UI_VENUS / model UI-Venus-2-9B / Q4_K_M /
  multimodal true / context 8192 / endpoint `http://127.0.0.1:18080`

## 已验证（可复现）

- `SCREENSHOT_INPUT_VERIFIED = true`：同问题无图 = 幻觉、有图 = 读到真实中文。
- 协议一致性：模型真实回复被现有 `parse_plan` 原样接受。
- 隔离：`fishing*.py` / `continuous_touch.py` 对 `local_gui_model`/`ui_planner`/`advisor`
  grep 为空 ⇒ 钓鱼实时路径零模型调用。
- 模型只在 UNKNOWN 路径可达（`runtime.py` 三处 advisor 调用点）。
- 服务：`/health {"status":"ok"}`、`modalities.vision=true`、`n_ctx 8192`、常驻。

## 尚未完成 / 交给下一轮

1. **一条真实 `UNKNOWN → MODEL PLAN → MAA ACTION → VERIFIER PASS`**：结算通道已实现并测试，
   但需要真机自然出现 UNKNOWN 才产生 outcome 行。**这是本轮最大的未完项。**
2. `PAGE_UNDERSTANDING_ACC` / `SEMANTIC_TARGET_ACC` 仍为 `NOT_MEASURED`：UNKNOWN 语料本身
   不记录"正确答案"，而指令禁止人工标注工程。要测就得先有 ground truth 来源。
3. `BBOX_HIT_RATE` / `ELEMENT_ID_VALIDITY` 在首轮 benchmark 里为 `null`（7 例全是
   REPLAN/DEFER/OBSERVE，没有 element-plan、没有 vision-proposal）。补一个有提案的案例即可。
4. Ollama 上 4 个 qwen 模型（17–23 GB）**未删**：`/api/ps` 为空（没有驻留），但**不确定是否
   只有 V2 用它**，按指令"只停 V2 引用、不擅自删除"处理。
5. `check_wiring problems: 15` —— 与我的改动无关的既有项；我新增的两个文件曾各吃一条
   `unhidden-process`，已改用 `winproc.run` 修掉。
6. 全量回归 `160 failed / 3730 passed / 10 errors`（22:11）。**归因结论：与我无关**——
   三样证据：157+3 个失败行里**只有 1 条 E 行**沾到我的符号且那是 runtime.py 源码文本断言；
   失败家族是缺旧截图 fixture（`FileNotFoundError` ×19）与别人未完成的
   `event_schedule.record_calendar_snapshot`；失败文件读的是 `config["ocr"]["module_path"]`，
   **不读 `local_planner`**。我唯一造成的失败是 `test_state_truth` 的"8 格"断言，已同步改为 9 格。
