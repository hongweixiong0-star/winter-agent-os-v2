# 产品定义落地：One Agent / Multiple Role States

> 本文件记录操作者 2026-09-16 的**最高层产品定义**，以及它在 `winter_agent_v2` 里的
> 落地现状。它是冻结级约束：后续会话不得把它读成"给每个角色写一套脚本"。
>
> 上一份（同一天更早）的能力建模指令见 `docs/ROLE_SCOPED_CAPABILITY_AUDIT.md`
> 与 `docs/ROLE_SCOPED_CAPABILITY_PLAN.md`。

## 一、定义（操作者原文要点）

目标不是"为每个角色做一套脚本"，而是**一个真正会玩《无尽冬日》的智能体**：

```
登录到哪个角色
  → 识别当前角色
  → 读取当前角色的发展状态
  → 判断已经解锁哪些功能
  → 读取资源 / 行军 / 建筑 / 科技 / 英雄 / 活动状态
  → 生成当前最合适的 Goal
  → 调用同一套 Universal Skills
  → 执行 → Verifier 验证 → 持续玩下去
```

架构是 **Shared Game Intelligence + Current Role State**：

| 共享（不随角色变化） | 角色独立（role-scoped） |
|---|---|
| Game Knowledge / UI Knowledge / Navigation | Progression / Furnace Level / Generation |
| Universal Skills / Goal Types | Feature Availability / March Capacity |
| Verifier / Recovery | Resources / Buildings / Technology / Heroes / Troops |
| MAA Recognition + Action / Strategy Framework | Queues / Cooldowns / Events / Runtime Goal State |

**明确禁止**：`Role1` 专用 Skill、低炉脚本 / 高炉脚本、2 行军脚本 / 6 行军脚本，
以及为不同角色复制 `GATHER / BUILD / RESEARCH / TRAIN / INTEL / BEAST / BEAR / RECALL`。
正确做法是同一个技能只换参数与 `WorldState`：2 队角色按 2 队调度，换到 6 队角色时
**同一 Scheduler 自动扩大并发**，而不是换一套代码。

一句话原则：**不同角色不是不同游戏，而是同一个《无尽冬日》在不同发展阶段的存档状态。**

## 二、对既有冻结架构意味着什么

**没有任何一处需要新增引擎。** 这份定义与 §2「V2 顶层架构冻结」及 §26
（禁止新建第二 WorldState / 第二 Scheduler / 第二 Goal Engine / 新的 Progression Manager）
完全一致——它要求的恰好是把**已经存在的那些 role-scoped 字段真正填上**，而不是再造一层。

已有的承载点：

- `WorldState.account_stage: dict` —— 字段已存在，**恒为 `{}`、零写入方**（审计结论 Q6）。
- `WorldState.march_used / march_max / normal_march_slots / normal_idle_slots` —— 容量与占用位的承载点。
- 知识层 `knowledge/` —— 炉子/世代/功能解锁属于**知识**，不属于技能逻辑（§19）。

⇒ 落地方式是**填字段 + 加一个身份观测**，不是新框架。

## 三、已证实的多角色事实（本轮新增证据）

语料事实上已经跨了两个账号，此前无人察觉：

| | 2026-09-14 13:41 | 2026-09-16 18:37 |
|---|---|---|
| 战力 | **70,206,322** | **542,443** |
| 统帅 | 统帅9 | 统帅2 |
| 行军 | **行军 6/6** | **行军 1/2** |
| 肉 / 钻石 | 1.9亿 / 13.1万 | 254.2万 / 32,797 |

同服务器 **#4298**。证据帧见 `dataset/truth_audit/march_queue_20260914_134158/`
（面板 `行军 6/6`）与 `dataset/truth_audit/role_identity_20260916/`（面板 `1/2`）。
**行军容量差 3 倍**，正是操作者所说"不要硬编码 2 队或 6 队"的实证。

⚠ 由此产生的后果：`learning/episodes.jsonl` 里的历史指标**混合了两个角色**，
任何"该技能的容量假设"都必须先问"这是哪个角色的 episode"。

## 四、身份来源：已找到，且只需一次点击

**HUD 上没有名字。** 这是先测量后结论：城市视图与世界地图顶部只有头像画像 / 战力 /
体力 / 统帅N / 日期（三张帧核实），没有名字。

**名字在 `领主档案` 面板里**：从 HOME 或 MAP **点击左上头像**即可打开，
OCR 直接给出 `[zoe]xhw小号`、`账号：1171757165`、`所在王国：4298`。
一次 Back 可回到 MAP（实测 0.99），所以这是一步可逆、可自恢复的观测。

### 本轮已落地的部分

- 已实现：`ocr.py` 的 ROI 常量 + `read_role_identity_rows()` + `parse_role_identity()`，
  以及 `HybridVision.read_role_identity(image_path) -> RoleIdentity | None`。
- 已实现：`models.RoleIdentity`（`role_id / role_name / alliance_tag / kingdom / power_text / confidence`）。
- 已实现：`tools/role_identity_probe.py`（有界探针）与 `tools/cq_role_identity_verify.py`（双向验证）。
- 已实现：`tests/test_role_identity.py`（20 项，含 4 个负向帧）。
- 证据：`dataset/truth_audit/role_identity_20260916/`。

**未实现（下一步）**：`IDENTIFY_ROLE` 作为正式 Skill（§15 风格：Precondition / Action /
Verifier）+ 运行序言里"身份未知或过期则识别一次"+ 按 `role_id` 分文件的 role state
+ 每条 episode 带 `role_id`。

## 五、硬边界（不可协商）

1. **永不点击 `领主档案` 面板内的任何控件。** 该面板底部有 `设置` 页签，而
   `config.risk.block_account_or_role_delete` 保护的正是账号/角色管理路径。
   识别步骤只做「点头像 → 取帧 → 读 → Back」。
2. **`role_id` 只来自客户端。** 没有配置声明、没有默认值、没有从等级推出来的键。
   读不到就是 `None`，宁可没有身份，也不能把状态键到一个没人观测过的角色上。
3. **容量只来自观测。** 炉子等级、世代、科技只能提供 **Prior**；`march_max` 必须来自
   计数器 `/` 的读数。`read_march_count` 本轮已收紧：一个碎片 token（`3/`）不能再改写
   真读数（`3/6`）。
4. **`power_text` 保持文本。** 面板显示 `54.2万`（HUD 同帧是 542,443），转成整数等于
   宣称客户端没画过的精度。
