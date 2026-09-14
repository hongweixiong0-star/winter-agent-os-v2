# 07 — EXTERNAL REUSE

外部项目在这里只有两种身份：**REFERENCE_ONLY** 或**已审计可复用的纯工具代码**。
默认是前者。**未知许可证 = REFERENCE_ONLY。**

规则（细则见 `00_MASTER_RULES.md` §10）：

- 外部研究必须**由真实失败驱动**：先看 Top Failure / Top Failed Skill / Top Goal Blocker，
  再问「别人是否已经解决这个问题」。不要漫无目的爬 GitHub。
- 认真研究 ≠ 看 README。必须定位到实际源码中的：
  `Navigation / Recognition / OCR / Template / ROI / Relative Coordinate / Action /
  Verifier / Recovery / Retry / Timeout / Completion Tracking / Emulator Recovery`。
- 统一流程：`Discover → Locate Implementation → Extract → Normalize → Compare V2 →
  Adapt → Replay → Live Try → Verify → Promote / Rollback`。
  不是 `Read → Write Report → End`。
- 允许 Best-of-Breed（A 导航 + B OCR + C Verifier + Legacy MuMu Recovery + V2 Goal/Scheduler），
  **不得整套照搬别人架构**。
- 代码复用必须保留 `Source / License / Version·Commit / Provenance`。
- 成果定义（至少满足一条）：新增 Live Verified 能力 / 提高成功率 / 降低 latency /
  提高 Recovery / 消除高频 Failure Pattern。
  只增加报告或只下载 repo → **NO_PRODUCT_VALUE**。

---

## 本地已有的外部参考（`dataset/external/repositories/`，**不进 git**）

| 仓库 | 文件数 | 身份 |
|---|---:|---|
| `whiteout-survival-bot` | 28 | 嵌套 git repo，REFERENCE_ONLY |
| `wosbot-sparse` | 62 | 嵌套 git repo，REFERENCE_ONLY |

> 这两个目录被 `.gitignore` 排除（嵌套仓库），**不要**当作本项目代码。
> 在里面 `git` 操作前先确认当前工作目录。

## 已登记项目（`knowledge/external/projects.json`）

| 项目 | 许可证 | 分类 | 允许借鉴 | 明确拒绝 |
|---|---|---|---|---|
| `AminulIslamSifat/wos` | README 声明 MIT（**复用前必须核对 LICENSE**） | DEVICE_UI_AUTOMATION | template+OCR 混合、语义任务分离、ADB 抽象、逐步验证思路 | 1080×2460 坐标锁、外部账号数据、自动购买 VIP、整套架构抄写、未验证模板 |
| `whiteout-project/bot` | VERIFY_REQUIRED | DISCORD_ALLIANCE_BOT | 仅在深入审计后参考活动登记思路 | 当作游戏画面自动化、整套抄写、token/cookie/账号数据 |
| `Shederator/wosbot` | AGPL-3.0 | DEVICE_UI_AUTOMATION | 能力分解与失败分类 | 把代码复制进 V2、抄架构、外部模板未经验证就用 |
| `batazor/whiteout-survival-autopilot` | UNKNOWN | DEVICE_UI_AUTOMATION_REFERENCE | 仅 OCR / 证据工作流思路 | 许可证核实前不得使用任何代码或媒体、固定坐标、抄架构 |

## 接入台账（**当前为空**）

| 失败驱动 | 目标项目 | 具体实现位置 | 状态 | 实测效果 |
|---|---|---|---|---|
| — | — | — | — | — |

**这张表为空是诚实的现状**：目前只完成了 Discover + 登记，
**没有任何外部实现真正接入并产生实测收益**。
按 §10，此阶段的 external mining 属于 `NO_PRODUCT_VALUE`，需要在补齐缺失技能之后再投入。

## 建议的第一个接入点（不是现在做）

`DISPATCH_NOT_PROVEN` x28 与 `MARCH_PAGE_NOT_OPEN` 都是「行军编排/页面识别」类问题。
若自行定位失败，应优先研究其他项目**如何进入行军流程、如何判断行军已派出**——
这正是 §10 要求的失败驱动研究，而不是漫游。
