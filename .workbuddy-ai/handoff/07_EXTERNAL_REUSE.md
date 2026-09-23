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

## 接入台账

2026-09-23 更新：巨熊活动（30 分钟窗口、反复错过）就是 §10 要求的**真实失败驱动**，
针对它的外部研究已完成。完整六字段报告见 **`11_GITHUB_BEAR_SEARCH.md`**。

| 失败驱动 | 目标项目 | 具体实现位置 | 状态 | 实测效果 |
|---|---|---|---|---|
| 巨熊 30 分钟窗口反复错过；`dataset/candidate/templates/` 零 bear/rally 模板 | 本项目真机帧（非外部） | `tools/register_bear_rally_templates.py` → manifest 418→432 | **已接入识别链** | 14/14 离线回放有区分度，0 ambiguous |
| 同上（每队冷却缺失） | `ducker24678/wjdr-helper` | `logic/tasks/bear_attack.py` `_team_skip_until` | **仅登记，未接入** | — （无许可证，只取思路） |
| 同上（列表需滚动） | `ducker24678/wjdr-helper` | `_maybe_scroll_rally_page` | **仅登记，未接入** | — |
| 同上（何时开下一车） | `yun-2000/wos-bluestacks-bot` | `tasks/hold_rally.yaml` `loop_until_text: "1/6"` | **仅登记，未接入** | — |
| `SEMANTIC_TARGET_NOT_VERIFIED` x424 | `AminulIslamSifat/whiteout-survival-bot` | `core/core.py` `tap_on_closest_text` + `core/recalibrate.py` | **仅登记，未接入** | — |
| 邮件领取不收敛 | `Shederator/wosbot`(AGPL) | `MailClaimPassPolicy.java` `STOP_NO_PROGRESS` | **仅登记，未接入** | — |

**「已接入」只有第一行**，而且接入的是**本项目自己的真机模板**，不是外部素材 ——
原因是本次查实的 5 个含巨熊相关内容的仓库**全部无可用许可证**（详见 11 号文档第四节）。
**没有任何外部代码或图片被复制进 V2。** 其余各行属于「已定位实现、已读懂做法、尚未落地」，
按 §10 仍是未完成状态。

## 关键外部事实（已核实，可复用）

- `AminulIslamSifat/whiteout-survival-bot` 的 `usecases/bear_trap.py` 是**空壳**：
  `start_bear_rally` / `join_bear_rally` / `remove_wrong_formation` 三函数体全是 `return`，
  且**未被任何 `TASKS` 列表引用**。**不得**把它报告成「外部已有巨熊实现」。
- 该仓库 README 声称 MIT，但**仓库内无 LICENSE 文件** ⇒ 按本文件首条铁律 = REFERENCE_ONLY。
- 该仓库 `references/` 含 **0 个图片文件**，但它有 **35 份文字锚点 + ROI 百分比 JSON**，
  其中 `Home.Alliance.War.json` / `Home.Alliance.War.AutoJoin.json` / `World.Deploy.json` /
  `World.json` **直接对应巨熊页面**（国际版英文）。**是 ROI 知识来源，不是点击坐标来源。**
- `Shederator/wosbot` 的 `MailClaimPassPolicy` 给出一个有界收敛三态策略：
  `COMPLETE` / `RETRY_AFTER_PROGRESS` / `STOP_NO_PROGRESS` / `STOP_BUDGET_EXHAUSTED`，
  与 `knowledge/failure_patterns/vision/BOUNDED_SCAN_THAT_NEVER_CONVERGES.md` 同题，
  可作为邮件领取与任何「扫到停」技能的判据模板。

## 建议的下一个接入点

巨熊模板已就位，但 `JOIN_RALLY` / `START_RALLY` **仍不能派发**
（不在 `VERIFIED_ATOMIC`；`Executor` 不支持其 kind；verifier 三参数签名不匹配）。
**在解决这三个断点之前，外部研究不应继续扩张** —— 见 11 号文档第七节。
