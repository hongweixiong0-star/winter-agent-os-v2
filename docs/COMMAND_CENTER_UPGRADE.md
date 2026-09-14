# Winter Agent OS V2 — Desktop Command Center Upgrade

## 交付状态

- 技术框架：Python 3.12、Tkinter/ttk、Pillow。
- 页面：总览、任务、能力、知识、学习、日志、设置。
- 桌面入口：`Winter Agent OS V2` 快捷方式与 `Start-Winter-Agent-V2.cmd`。
- 主界面截图：`docs/assets/COMMAND_CENTER.png`。
- 中文化：主界面状态、页面名、常用 Skill、错误和 Verifier 摘要均优先显示中文；内部 Skill ID 仅作为辅助信息。
- 实时截图：通过现有 `ADBDevice.screenshot` 获取，并在后台线程更新，不阻塞 GUI 主线程。
- 任务开关：只表达允许范围，不执行排序、不创建第二个 Scheduler。当前桌面真实运行入口仍仅开放 `GATHER_RESOURCE`。
- 安全边界：真实支付、账号/角色删除、账号安全设置始终禁止。

## 数据绑定

| 界面区域 | 真实数据来源 |
|---|---|
| MuMu、游戏前台 | `ADBDevice.status / DeviceStatus` |
| 页面、置信度、行军、队列 | `WorldState` |
| 当前任务、原因、下一步、验证结果 | `LiveRuntime` 最终结构化结果中的 `Decision / VerificationResult` |
| 能力目录 | 唯一 `v2_registry()` |
| 知识统计 | `knowledge/` 与 `dataset/` 文件 |
| 学习统计 | `learning/episodes.jsonl` |
| 完整日志 | `learning/control_panel/latest.log` 与本次 GUI 事件 |

## 解耦说明

Agent 长任务运行在独立 Python 子进程，GUI 主线程只消费线程安全事件队列；截图与手动状态刷新也在后台线程执行。GUI 不包含 Brain、Scheduler、Skill 或 Verifier 业务判断。当前 Runtime 只在结束时输出完整结构化结果，因此执行期间的逐步决策快照仍是后续主线需要补齐的观测接口；界面不会为此伪造中间状态。

## 性能与测试

- 时钟每秒更新；截图只在启动、手动刷新或一轮结束时更新。
- 不逐帧运行 OCR，不从 GUI 高频调用 Qwen。
- 控制台专项测试：5/5 通过。
- V2 完整回归测试：151/151 通过。
