# ROLE_SWITCH 研究与候选设计（2026-09-22）

> 结论先行：**多角色切换在 V2 里不存在**，本轮也没有实现它 —— 因为实现它需要一次真机确认，
> 而真机本轮归 AUTO（操作者本轮第一优先是让 AUTO 真正跑起来）。
> 本文件的价值是把"要真机发现"压缩成"要真机确认一处文字差异"。

## 一、`docs/ROLE_SCOPED_CAPABILITY_PLAN.md` 记录的阻断前提，本轮复核仍成立

那份文档写着"**当前无法观测'这是哪个角色'**"。本轮重跑了全仓检索，结论不变：

| 检索项 | 结果 |
|---|---|
| `switch_role` / `SWITCH_ROLE` / `switch_character` | 仅出现在**记忆与文档**里，零实现 |
| `SWITCH_CHARACTER` / `SELECT_CHARACTER` / `SELECT_ROLE` / `ROLE_LIST` | 零命中 |
| `ACCOUNT_SWITCH` / `switch_account` | 零命中 |
| `BTN_ROLE` / `BTN_CHARACTER` / `character_select` | 零命中（即：**没有模板**） |
| `learning/episodes.jsonl` 中 skill 含 ROLE/CHARACTER/SWITCH/ACCOUNT | **0 条** |
| `learning/episodes.jsonl` 中出现的 `role_id` | 只有 `1171757165`(2393) 与空(2062)——**从未出现过第二个角色** |

现有"身份"标识都**不是角色**（`config.device.serial` 是模拟器实例；`role_identity.json` 是**读取**，
不是切换）。所以"当前角色没有可推进任务 → 检查其他角色"这条链路**四段全缺**：
无"其他角色"、无切换、无切换后身份确认、无独立 WorldState。

## 二、本轮找到的真实起点（真机帧 + 外部 prior 交叉印证）

### 2.1 真机帧（本项目自己的证据）

`dataset/truth_audit/role_identity_20260916/profile_panel_live_20260916T184004.png`
＝"领主档案"页，720×1280。可读到的字段：

```
账号：1171757165      ← 与 learning/role_identity.json 的 role_id 一致
[zoe]xhw小号  |  战力 54.2万  |  13级  |  联盟 zoe  |  所在王国：4298
底部四格：装扮 | 部队 | 排行榜 | 设置      ← 第四格「设置」，右下角
```

`role_identity.json` 记的就是这一帧（`verification: VISION_READ_REPLAY`）。**所以角色身份读取是
LIVE 的；缺的只是"切换到另一个"。**

### 2.2 外部 prior（`dataset/external/repositories/whiteout-survival-bot`）

`references/TextArea/ChiefProfile.Settings.json` 把**设置页的完整结构**写下来了
（OCR 参考，box 是归一化百分比）。这是目前最具体的线索，逐条列出：

| key | text | box (x1,y1,x2,y2) | 本客户端如何核 |
|---|---|---|---|
| `ChiefProfile.Settings` | `Settings` | 80.2, 96.6, 93.2, 98.7 | **与本项目帧右下「设置」完全吻合** ⇒ 同一入口 |
| `ChiefProfile.Settings.Title` | `Settings` | 12.1, 5.8, 30.7, 8.9 | 设置页标题 |
| `ChiefProfile.Settings.Account` | `Account` | 68.5, 16.6, 84.5, 18.5 | 页签（右侧） |
| `ChiefProfile.Settings.Characters` | `Characters` | 20.6, 24.4, 41.4, 26.3 | **页签（左侧）—— 这就是切换角色的页** |
| `ChiefProfile.Settings.Character.Title` | `Characters` | 38.9, 23.4, 61.3, 25.5 | |
| `ChiefProfile.Settings.Characters.FirstState` | `Server #3429` | 18.7, 38.2, 44.0, 40.3 | **每个角色一行：区服号** |
| `ChiefProfile.Settings.Characters.FirstCharacterName` | `[LAT]Shadow` | 29.6, 42.8, 83.3, 44.5 | 角色名 |
| `ChiefProfile.Settings.Characters.SecondCharacterName` | `[LAT]Shadowy` | 29.6, 52.0, 83.3, 53.9 | 第二行 |
| `ChiefProfile.Settings.Characters.Login.Title` | `Login` | 43.7, 39.4, 56.3, 42.1 | **点角色后的确认框** |
| `ChiefProfile.Settings.Characters.Login.Cancel` | `Cancel` | 21.7, 61.3, 36.6, 63.5 | |
| `ChiefProfile.Settings.Characters.Login.Confirm` | `Confirm` | 61.9, 61.2, 80.3, 63.5 | 确认切换 |
| `ChiefProfile.Settings.Characters.CreateNewCharacter` | `Create new character` | 30.3, 29.3, 64.2, 31.1 | **必须避开**（会新建角色） |
| `ChiefProfile.Settings.Account.ChangeAccount` | `Change Account` | 32.2, 94.2, 68.2, 97.0 | 换**账号**（≠换角色），也须避开 |

推导出的候选路线（**全部 PRIOR，未在任何帧上验证**）：

```
领主档案(已有帧) → 「设置」→ 「Characters」页签 → 点目标角色行
   → Login 对话框 → Confirm → 等待加载 → 重新读身份
```

## 三、这份 prior 与本客户端**必然不同**的地方（真机校准要回答的就是这些）

1. **语言**：prior 来自英文客户端。本客户端是中文，所以 `Settings/Account/Characters/Login/Confirm`
   在真机上是"设置/账号/角色/登录/确定"之类。**布局坐标大概率一致，文字一定不同。**
2. **`Server #3429` vs 本角色 `所在王国：4298`**：两者是否同一含义尚未证实。
   若 `Characters` 列表用 `Server #NNNN` 标识，而身份页写"所在王国"，那"确认切到了哪个角色"
   就需要把两个字段对齐 —— **这是实施前必须先量的一件事**。
3. **`Change Account` 与 `Characters` 是两个不同动作**：前者换账号（可能是登出），
   后者才是换角色。pror 的 box 显示 `Change Account` 在**最底部**（y≈94-97），
   与 `Settings` 在档案页的位置形态相似，**点错会登出**。风险等级：高。
4. **`Create new character`** 在 `Characters` 页顶部（y≈29-31），点错会**创建新角色**。
   风险等级：不可逆。
5. 切换角色后 **WorldState 必须整体作废重读**（体力/行军/队列/页面全都是新角色的），
   `learning/observation_state.json` 与 `_goal_meters` 都不能跨角色复用。

⇒ 因此本能力的**风险等级不是"普通交互"**：`Change Account` 与 `Create new character`
两个控件就在同一屏，其中一个不可逆。按 §七 的边界，它必须走"先识别代价与效果、再决定是否执行"，
**不能当作自主试错动作**。

## 四、为什么本轮没有实现（如实）

- 实施需要一次真机确认（页签文字、`Characters` 列表实际字段）。
- 真机本轮归 AUTO：本轮第一优先是解除"开发验证租约永久占用设备"，修完后 AUTO 才第一次跑起来。
  **为了角色探索再去抢设备，会立刻把刚恢复的 Gameplay 停掉**，与本轮目标相反。
- 也**不能**把外部项目那份 OCR 参考直接当实现接进生产（§六：外部必须实际落地且经真机校准；
  README/参考坐标不是证据）。

## 五、下一次真机窗口要做的（最小、有界）

1. 打开领主档案（页面与入口**已有 LIVE 帧**，`role_identity` 那次就是这么进去的）。
2. 点「设置」（右下角；坐标可由本帧测量，**不要**照抄 prior 的百分比）。
3. 截图 → 读页签文字 → 记录中文实际用词（**这是唯一必须新测的 UI 事实**）。
4. 进「角色」页 → 截图 → 记录每行字段（区服号 / 角色名 / 等级）。
5. **不点** `Create new character`，**不点** `Change Account`。
6. 上述三帧即可把本文件从 `PRIOR` 抬到 `OBSERVED`；真正的切换动作留到有第二个角色可切时再做。

## 六、状态

- 本文件：`PRIOR`（外部 OCR 参考 + 本项目身份帧交叉印证，**无任何真机切换证据**）
- `ROLE_SWITCH` capability：`MISSING`（无 skill、无模板、无 verifier、无 brain 路由）
- 不得据此声称"多角色已支持"。
