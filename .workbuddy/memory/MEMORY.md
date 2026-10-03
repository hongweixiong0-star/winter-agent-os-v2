# 指针：长期知识的事实源在别处

本目录（.workbuddy/memory/）是 WorkBuddy 宿主注入的会话工作路径，
**只存放当日流水与自动化记忆，不作为长期知识的事实源。**

长期项目知识（架构决定、环境铁律、操作者偏好、蒸馏后的教训）的唯一事实源：

    E://无尽冬日智能体//.workbuddy-ai//memory//MEMORY.md

规则全文见 .workbuddy-ai/handoff/00_MASTER_RULES.md 的「记忆写入路由」。

**2026-10-03 已做的收敛**：本文件原有 21.6 KB 的历史教训正文，其中 6 条当时只存在于本文件、
未进入正式事实源（读者类 `None`、守卫家族 N-1 漏项、实际绑定的 resolver、假阴性两面帧、
留 key 扔 value、教学手势配对），现已全部迁入 `.workbuddy-ai/memory/MEMORY.md`。
**本文件不再承载教训正文。** UI-Venus 在 8GB 卡上的实测数字同样已在事实源中（`n_ctx_train`、
`-ngl 30/f16`、schema 控长度、`-b/-ub 512`、`enable_thinking:false`、`profile_device_impact.py`）。