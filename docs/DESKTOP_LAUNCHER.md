# Winter Agent OS V2 桌面启动

双击桌面上的 `Winter Agent OS V2` 会打开深色 SLG 风格的《无尽冬日 AI 指挥中心》。总览会直接显示 MuMu、游戏、页面、Vision、当前任务、决策原因、下一步、Verifier、队列摘要、实时截图和最近事件。

主控制区提供 `开始自动运行`、`暂停`、`停止`、`刷新状态` 和 `截图`。控制台页面包括：

- 总览：角色、今日任务、实时游戏画面、当前决策和队列；
- 任务：任务类型开关，不取代 Scheduler；
- 能力：读取唯一 Skill Registry 的真实能力状态；
- 知识：读取 Knowledge 与 Dataset 的真实统计；
- 学习：读取 Episode 的失败分类；
- 日志：完整的本次控制台运行记录；
- 设置：连续运行和简化的游戏资源策略。

开始后会：

1. 检查 MuMu 与 ADB；
2. 必要时启动 MuMu，并等待设备连接；
3. 打开《无尽冬日》；
4. 启动当前 Verifier 保护下的邮件 → Intel → 野怪 → 采集单通道主循环；
5. 将运行日志写入 `learning/control_panel/`，截图写入 `dataset/raw/control_panel/`。

项目内备用入口是 `Start-Winter-Agent-V2.cmd`。无面板的命令行模式仍可执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\无尽冬日智能体\Start-Winter-Agent-V2.ps1" -Mode observe
```

当前桌面入口可启动已经进入有界 LiveRuntime 的邮件、Intel、普通野怪与 `GATHER_RESOURCE`；其余真实 Skill 会在能力页展示，但不会被 GUI 伪装成可运行入口。控制台使用单实例、单执行通道，ADB 与 Runtime 子进程在后台无窗口运行。遇到未知页面、满行军队列或 Verifier 失败时会安全停止，不会猜测点击。GUI 只消费现有 World State、Runtime、Skill Registry、Knowledge 和 Learning 数据，不承担 Brain 或 Scheduler 逻辑。
