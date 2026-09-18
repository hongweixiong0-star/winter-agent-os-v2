# Capability Bootstrap / Preload —— 候选（自动生成）

> 本文件由 `winter_agent_v2/capability_bootstrap.py` 扫描 capability_catalog 生成。
> **Bootstrap 完成 ≠ LIVE_VERIFIED**：这里的最高状态是 `READY_FOR_LIVE_VERIFY`，真机验证仍走统一 Development Validation 流程。

- 总表行数：522　可预载：452　已在流程中（禁止重复 Bootstrap）：70
- 按优先级：{'UNLOCKED_MISSING': 124, 'HIGH_FREQ_FREE_VALUE': 52, 'OTHER_UNLOCKED': 18, 'FUTURE_LOCKED': 322, 'NEAR_UNLOCK': 6}
- 按计划状态：{'NEEDS_LIVE_FRAME': 452, 'IN_FLIGHT': 70}
- 按来源：{'GAME_DB_WIKI': 76, 'SELF_EXPLORATION': 328, 'V2_EVIDENCE': 78, 'EXTERNAL_MAP': 35, 'LEGACY_ASSET': 5}

### CAP-G09 · TROOP_SELECT

- 目标：`PARTICIPATE_BEAR`　技能：`SELECT_TROOP_PRESET`　风险：`T1`
- 分类：有设计草稿但没有实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 749.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：V2 已验收代码 / Knowledge / Episode / Evidence

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | 从 MARCH 出发 | V2_EVIDENCE | 0.50 |
| Navigation | MARCH -> MARCH | V2_EVIDENCE | 0.55 |
| Recognition | TROOP_PRESET | V2_EVIDENCE | 0.30 |
| Action | APPLY_CONTEXT_TROOP_POLICY | V2_EVIDENCE | 0.55 |
| Verifier | troop_policy_applied | V2_EVIDENCE | 0.40 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Recovery']；未注册语义 ['TROOP_PRESET']；verifier 未绑定）

### CAP-E07 · ECONOMY_RESEARCH

- 目标：`-`　技能：`ECONOMY_RESEARCH`　风险：`T1`
- 分类：总表里根本没有实现, 有 Legacy / 内部资产但未接入
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 740.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：Legacy 与内部可复用资产（带真实证据）

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | UNKNOWN | - | 0.00 |
| Recognition | dataset/truth_audit 与 dataset/candidate 中有同名资产，可先量再设计 | LEGACY_ASSET | 0.20 |
| Action | UNKNOWN | - | 0.00 |
| Verifier | UNKNOWN | - | 0.00 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions', 'Navigation', 'Action', 'Verifier', 'Recovery']；未注册语义 -；verifier 未绑定）

### CAP-E08 · GROWTH_RESEARCH

- 目标：`-`　技能：`GROWTH_RESEARCH`　风险：`T1`
- 分类：总表里根本没有实现, 有 Legacy / 内部资产但未接入
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 740.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：Legacy 与内部可复用资产（带真实证据）

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | UNKNOWN | - | 0.00 |
| Recognition | dataset/truth_audit 与 dataset/candidate 中有同名资产，可先量再设计 | LEGACY_ASSET | 0.20 |
| Action | UNKNOWN | - | 0.00 |
| Verifier | UNKNOWN | - | 0.00 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions', 'Navigation', 'Action', 'Verifier', 'Recovery']；未注册语义 -；verifier 未绑定）

### CAP-E09 · BATTLE_RESEARCH

- 目标：`-`　技能：`BATTLE_RESEARCH`　风险：`T1`
- 分类：总表里根本没有实现, 有 Legacy / 内部资产但未接入
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 740.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：Legacy 与内部可复用资产（带真实证据）

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | UNKNOWN | - | 0.00 |
| Recognition | dataset/truth_audit 与 dataset/candidate 中有同名资产，可先量再设计 | LEGACY_ASSET | 0.20 |
| Action | UNKNOWN | - | 0.00 |
| Verifier | UNKNOWN | - | 0.00 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions', 'Navigation', 'Action', 'Verifier', 'Recovery']；未注册语义 -；verifier 未绑定）

### CAP-B09 · CLAIM_VIP_DAILY

- 目标：`-`　技能：`CLAIM_VIP_DAILY`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | tapInside(VIP_MENU_BUTTON (430,48)-(530,85)) -> verify with TemplatesEnum.VIP_MENU; pressBack() to leave | EXTERNAL_MAP | 0.45 |
| Recognition | template VIP_MENU to confirm the panel; OcrSettingsData SINGLE_LINE + charWhitelist('0123456789d') over VIP_EXPIRATION_TIME (273,1170)-(461,1213) accepted by GameTimeUtils.isAcceptedFormat | EXTERNAL_MAP | 0.40 |
| Action | tapInside(DAILY_CHEST_REWARDS (540,813)-(624,835), attempts=3, 300ms) then tapInside(VIP_POINT_REWARDS (602,263)-(650,293), attempts=3, 300ms) | EXTERNAL_MAP | 0.45 |
| Verifier | NONE for the claims — the taps are blind fixed-coordinate, repeated 3x. Only the menu opening is verified (template). | EXTERNAL_MAP | 0.25 |
| Recovery | if the menu template is not found -> log + reschedule; no retry of the panel itself | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-B10 · VIP_FREE_CHEST

- 目标：`-`　技能：`VIP_FREE_CHEST`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | tapInside(VIP_MENU_BUTTON (430,48)-(530,85)) -> verify with TemplatesEnum.VIP_MENU; pressBack() to leave | EXTERNAL_MAP | 0.45 |
| Recognition | template VIP_MENU to confirm the panel; OcrSettingsData SINGLE_LINE + charWhitelist('0123456789d') over VIP_EXPIRATION_TIME (273,1170)-(461,1213) accepted by GameTimeUtils.isAcceptedFormat | EXTERNAL_MAP | 0.40 |
| Action | tapInside(DAILY_CHEST_REWARDS (540,813)-(624,835), attempts=3, 300ms) then tapInside(VIP_POINT_REWARDS (602,263)-(650,293), attempts=3, 300ms) | EXTERNAL_MAP | 0.45 |
| Verifier | NONE for the claims — the taps are blind fixed-coordinate, repeated 3x. Only the menu opening is verified (template). | EXTERNAL_MAP | 0.25 |
| Recovery | if the menu template is not found -> log + reschedule; no retry of the panel itself | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-B12 · CLAIM_ONLINE_REWARD

- 目标：`-`　技能：`CLAIM_ONLINE_REWARD`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | on the daily tab (see above) | EXTERNAL_MAP | 0.45 |
| Recognition | DAILY_MISSION_CLAIMALL_BUTTON; else DAILY_MISSION_CLAIM_BUTTON, with a DISABLED variant discriminator: if DAILY_MISSION_CLAIM_BUTTON_DISABLED is found within 20px (Manhattan) of the claim button, treat the claim as not a | EXTERNAL_MAP | 0.40 |
| Action | tapInside(claimAllResult) or tapNear(claimPoint) then dismissRewardPopupsFlow() = tapInside((10,100)-(600,120), count=3, 150ms) | EXTERNAL_MAP | 0.45 |
| Verifier | no-progress detection: after tapping, re-search; if the button is still at the same point (<=20px) twice, stop and report 'no visual progress' | EXTERNAL_MAP | 0.25 |
| Recovery | bounded loop (20), same-target check, then dismiss and return false so the scheduler can reschedule | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-B15 · CLAIM_IDLE_REWARD

- 目标：`-`　技能：`CLAIM_IDLE_REWARD`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | on the daily tab (see above) | EXTERNAL_MAP | 0.45 |
| Recognition | DAILY_MISSION_CLAIMALL_BUTTON; else DAILY_MISSION_CLAIM_BUTTON, with a DISABLED variant discriminator: if DAILY_MISSION_CLAIM_BUTTON_DISABLED is found within 20px (Manhattan) of the claim button, treat the claim as not a | EXTERNAL_MAP | 0.40 |
| Action | tapInside(claimAllResult) or tapNear(claimPoint) then dismissRewardPopupsFlow() = tapInside((10,100)-(600,120), count=3, 150ms) | EXTERNAL_MAP | 0.45 |
| Verifier | no-progress detection: after tapping, re-search; if the button is still at the same point (<=20px) twice, stop and report 'no visual progress' | EXTERNAL_MAP | 0.25 |
| Recovery | bounded loop (20), same-target check, then dismiss and return false so the scheduler can reschedule | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-B18 · CLAIM_EVENT_REWARD

- 目标：`-`　技能：`CLAIM_EVENT_REWARD`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | on the daily tab (see above) | EXTERNAL_MAP | 0.45 |
| Recognition | DAILY_MISSION_CLAIMALL_BUTTON; else DAILY_MISSION_CLAIM_BUTTON, with a DISABLED variant discriminator: if DAILY_MISSION_CLAIM_BUTTON_DISABLED is found within 20px (Manhattan) of the claim button, treat the claim as not a | EXTERNAL_MAP | 0.40 |
| Action | tapInside(claimAllResult) or tapNear(claimPoint) then dismissRewardPopupsFlow() = tapInside((10,100)-(600,120), count=3, 150ms) | EXTERNAL_MAP | 0.45 |
| Verifier | no-progress detection: after tapping, re-search; if the button is still at the same point (<=20px) twice, stop and report 'no visual progress' | EXTERNAL_MAP | 0.25 |
| Recovery | bounded loop (20), same-target check, then dismiss and return false so the scheduler can reschedule | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-B20 · FREE_SHOP_ITEM

- 目标：`-`　技能：`FREE_SHOP_ITEM`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | open shop -> swipe with calibrated geometry -> confirm the tab by OCR | EXTERNAL_MAP | 0.45 |
| Recognition | ShopTab + OCR header read (attempts=2, retry 300ms) | EXTERNAL_MAP | 0.40 |
| Action | swipe, then select the item | EXTERNAL_MAP | 0.45 |
| Verifier | the tab header is re-read after the swipe; without a confirmed header the navigation is not accepted | EXTERNAL_MAP | 0.25 |
| Recovery | bounded swipes (10) | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-I08 · SEARCH_POLAR_TERROR

- 目标：`-`　技能：`SEARCH_POLAR_TERROR`　风险：`T0`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | combat panel | EXTERNAL_MAP | 0.45 |
| Recognition | PolarSpecialRewardsScanner (scans for special drops) | EXTERNAL_MAP | 0.40 |
| Action | hunt within the mode's rules | EXTERNAL_MAP | 0.45 |
| Verifier | mode + scanner state | EXTERNAL_MAP | 0.25 |
| Recovery | stamina policy decides whether to top up or stop — i.e. 'no stamina' is a policy, not an error | EXTERNAL_MAP | 0.35 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-I12 · CLAIM_BEAST_REWARD

- 目标：`-`　技能：`CLAIM_BEAST_REWARD`　风险：`T1`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | on the daily tab (see above) | EXTERNAL_MAP | 0.45 |
| Recognition | DAILY_MISSION_CLAIMALL_BUTTON; else DAILY_MISSION_CLAIM_BUTTON, with a DISABLED variant discriminator: if DAILY_MISSION_CLAIM_BUTTON_DISABLED is found within 20px (Manhattan) of the claim button, treat the claim as not a | EXTERNAL_MAP | 0.40 |
| Action | tapInside(claimAllResult) or tapNear(claimPoint) then dismissRewardPopupsFlow() = tapInside((10,100)-(600,120), count=3, 150ms) | EXTERNAL_MAP | 0.45 |
| Verifier | no-progress detection: after tapping, re-search; if the button is still at the same point (<=20px) twice, stop and report 'no visual progress' | EXTERNAL_MAP | 0.25 |
| Recovery | bounded loop (20), same-target check, then dismiss and return false so the scheduler can reschedule | EXTERNAL_MAP | 0.35 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-S04 · ALLIANCE_TECH

- 目标：`-`　技能：`ALLIANCE_TECH`　风险：`T1`
- 分类：有外部先验但 V2 未实现, 有 Legacy / 内部资产但未接入
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | alliance panel | EXTERNAL_MAP | 0.45 |
| Recognition | AllianceRankingCaptureSupport (a capture layer for ranking screens) | EXTERNAL_MAP | 0.40 |
| Action | help / donate / claim | EXTERNAL_MAP | 0.45 |
| Verifier | ranking capture implies frame evidence | EXTERNAL_MAP | 0.25 |
| Recovery | helper-level | EXTERNAL_MAP | 0.35 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-S12 · AUTO_JOIN_RALLY

- 目标：`-`　技能：`AUTO_JOIN_RALLY`　风险：`T1`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | RallyFlagCoordinates — rally flags are located in the world map field | EXTERNAL_MAP | 0.45 |
| Recognition | flag coordinates (dedicated class + unit test) | EXTERNAL_MAP | 0.40 |
| Action | open the flag, join | EXTERNAL_MAP | 0.45 |
| Verifier | its own preemption rule implies a state check before interrupting | EXTERNAL_MAP | 0.25 |
| Recovery | preemption + bounded attempts | EXTERNAL_MAP | 0.35 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-Y07 · CLAIM_CRAZY_JOE_REWARD

- 目标：`-`　技能：`CLAIM_CRAZY_JOE_REWARD`　风险：`T1`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 734.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | on the daily tab (see above) | EXTERNAL_MAP | 0.45 |
| Recognition | DAILY_MISSION_CLAIMALL_BUTTON; else DAILY_MISSION_CLAIM_BUTTON, with a DISABLED variant discriminator: if DAILY_MISSION_CLAIM_BUTTON_DISABLED is found within 20px (Manhattan) of the claim button, treat the claim as not a | EXTERNAL_MAP | 0.40 |
| Action | tapInside(claimAllResult) or tapNear(claimPoint) then dismissRewardPopupsFlow() = tapInside((10,100)-(600,120), count=3, 150ms) | EXTERNAL_MAP | 0.45 |
| Verifier | no-progress detection: after tapping, re-search; if the button is still at the same point (<=20px) twice, stop and report 'no visual progress' | EXTERNAL_MAP | 0.25 |
| Recovery | bounded loop (20), same-target check, then dismiss and return false so the scheduler can reschedule | EXTERNAL_MAP | 0.35 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-I09 · START_POLAR_TERROR_RALLY

- 目标：`-`　技能：`START_POLAR_TERROR_RALLY`　风险：`T2`
- 分类：有外部先验但 V2 未实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 726.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | combat panel | EXTERNAL_MAP | 0.45 |
| Recognition | PolarSpecialRewardsScanner (scans for special drops) | EXTERNAL_MAP | 0.40 |
| Action | hunt within the mode's rules | EXTERNAL_MAP | 0.45 |
| Verifier | mode + scanner state | EXTERNAL_MAP | 0.25 |
| Recovery | stamina policy decides whether to top up or stop — i.e. 'no stamina' is a policy, not an error | EXTERNAL_MAP | 0.35 |
| Risk | T2（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-I10 · JOIN_POLAR_TERROR_RALLY

- 目标：`-`　技能：`JOIN_POLAR_TERROR_RALLY`　风险：`T2`
- 分类：有外部先验但 V2 未实现, 有 Legacy / 内部资产但未接入
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 726.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：knowledge/external/external_capability_map.json

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | RallyFlagCoordinates — rally flags are located in the world map field | EXTERNAL_MAP | 0.45 |
| Recognition | flag coordinates (dedicated class + unit test) | EXTERNAL_MAP | 0.40 |
| Action | open the flag, join | EXTERNAL_MAP | 0.45 |
| Verifier | its own preemption rule implies a state check before interrupting | EXTERNAL_MAP | 0.25 |
| Recovery | preemption + bounded attempts | EXTERNAL_MAP | 0.35 |
| Risk | T2（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE + EXTERNAL_MAP（沿用等级 ADAPT_PATTERN，许可证 AGPL-3.0-only） | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions']；未注册语义 -；verifier 未绑定）

### CAP-A01 · LAUNCH_GAME

- 目标：`-`　技能：`LAUNCH_GAME`　风险：`T0`
- 分类：总表里根本没有实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 722.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：游戏数据库 / Wiki / 攻略

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | UNKNOWN | - | 0.00 |
| Recognition | UNKNOWN | - | 0.00 |
| Action | UNKNOWN | - | 0.00 |
| Verifier | UNKNOWN | - | 0.00 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T0（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions', 'Navigation', 'Recognition', 'Action', 'Verifier', 'Recovery']；未注册语义 -；verifier 未绑定）

### CAP-D20 · FIRE_CRYSTAL_BUILDING

- 目标：`-`　技能：`FIRE_CRYSTAL_BUILDING`　风险：`T1`
- 分类：总表里根本没有实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 722.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：游戏数据库 / Wiki / 攻略

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | UNKNOWN | - | 0.00 |
| Recognition | UNKNOWN | - | 0.00 |
| Action | UNKNOWN | - | 0.00 |
| Verifier | UNKNOWN | - | 0.00 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions', 'Navigation', 'Recognition', 'Action', 'Verifier', 'Recovery']；未注册语义 -；verifier 未绑定）

### CAP-D22 · CRYSTAL_LAB

- 目标：`-`　技能：`CRYSTAL_LAB`　风险：`T1`
- 分类：总表里根本没有实现
- 优先级：P1 已解锁的 MISSING / NEVER_TRIED（score 722.0）
- 计划状态：`NEEDS_LIVE_FRAME`　知识来源：游戏数据库 / Wiki / 攻略

| 字段 | 内容 | 来源 | 置信 |
|---|---|---|---:|
| Preconditions | UNKNOWN | - | 0.00 |
| Navigation | UNKNOWN | - | 0.00 |
| Recognition | UNKNOWN | - | 0.00 |
| Action | UNKNOWN | - | 0.00 |
| Verifier | UNKNOWN | - | 0.00 |
| Recovery | UNKNOWN | - | 0.00 |
| Risk | T1（总表判定，资源成本 UNKNOWN） | V2_EVIDENCE | 0.70 |

- Targeted Test：`DESIGN_COMPLETE` → NOT_PROVEN（缺字段 ['Preconditions', 'Navigation', 'Recognition', 'Action', 'Verifier', 'Recovery']；未注册语义 -；verifier 未绑定）
