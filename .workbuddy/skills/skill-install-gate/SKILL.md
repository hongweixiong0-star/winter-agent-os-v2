---
name: skill-install-gate
description: "Winter Agent OS 项目专用：安装与启用任何新 Skill 的强制门禁。市场搜索→防重复→安装→skills-security-check 安全审计→真实测试调用→登记台账。触发词：安装 skill、装个技能、新技能、skill audit、启用技能"
version: 1.0.0
---

# Skill 安装门禁（Winter Agent OS V2）

任何新 Skill 进入本项目的工具链，必须走完以下六步。跳步 = 未启用。

## 1. 市场搜索

用 `workbuddy_marketplace_skill` (action=search) 按能力关键词搜索。
同时用 `find-skills` 交叉确认。结果为空 → 转「自建项目 Skill」分支。

## 2. 防重复检查

对照下方「已登记技能清单」与 `~/.workbuddy/skills/`、
`E:\无尽冬日智能体\.workbuddy\skills\` 的磁盘清单：

- 同一能力已有成熟实现 → **不安装**，复用现有项。
- 疑似重复 → 只保留最成熟的一个；另一个保留文件但标注「关闭不启用」。

## 3. 安装

`workbuddy_marketplace_skill` (action=install, skillId=搜索结果里的 id)。

## 4. 安全审计（强制，装完立即做）

用 `skills-security-check` 审计新技能的目录（纯静态分析，只读）：

- 🔴 Malicious → **立即删除**，登记为「拒绝安装」，不得使用。
- ⚠️ Suspicious → 登记为「存在安全风险」，**必须**列出具体风险点，
  经操作者确认后才能进入第 5 步。
- ✅ Benign → 进入第 5 步。

自建的项目 Skill 同样要过本审计（用本技能的检查清单自查）。

## 5. 真实测试调用（强制）

- 至少一次真实调用，产出一个可核验的结果（审计报告/命令输出）。
- 与真机相关的技能，测试时**不得**触碰：真实货币/购买（永久阻断）、
  账号删除、系统破坏。
- 测试失败 → 保留文件、登记「关闭不启用」，注明失败原因。

## 6. 登记台账

把结果写进 `.workbuddy/skills/SKILL_AUDIT.json`（schema 见该文件）：
skill 名、来源、版本、审计结论、测试证据路径、启用状态、登记时间。
未登记 = 未启用。

## 已登记技能清单（截至 2026-09-14）

- skills-security-check（腾讯云鼎，市场）——安全审计，**已测试**
  （实测审计 winter-os-takeover：Benign 95）。
- agent-browser 1.3.0（官方市场）——浏览器自动化，主用。
- playwright-cli 0.1.0（官方市场）——同能力备选，保留不主用（防重复）。
- find-skills / skill-creator（官方）——发现与自建。
- 11 个项目技能（my-experts/winter-agent-v2-dev）——项目方法论，
  已由 2026-09-14 全量安全审计覆盖（winter-os-takeover 实测 Benign）。
- 明确拒绝：github（项目无远程仓库，原生 git 足够）；
  各类与项目代码重复的 ADB/OCR/日志类市场技能（市场无此类技能，且项目
  代码已覆盖，安装即重复）。
