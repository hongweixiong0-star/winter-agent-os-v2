# 那四个"数据目录"不是两份拷贝，是**同一个目录**（NTFS junction）（2026-10-14）

> 一直在本会话里被当成"两棵树各自漂移"的 `knowledge/` / `learning/` / `dataset/` / `config/`，
> 实测**不是两个副本** —— 生产 pin 树里它们是指向数据根的 **junction（硬链接式目录）**。
> 这解释了 `repin_production` 为什么要排除这四个目录，也限定了我前几轮几条结论的适用范围。

---

## 一、事实（PowerShell 实测 `Get-Item .LinkType`）

对 `E:\无尽冬日智能体_worktrees\winter-prod-pinned\无尽冬日智能体\`：

| 目录 | 类型 |
|---|---|
| `knowledge` | **Junction → `E:\无尽冬日智能体\knowledge`** |
| `learning` | **Junction → `E:\无尽冬日智能体\learning`** |
| `dataset` | **Junction → `E:\无尽冬日智能体\dataset`** |
| `config` | **Junction → `E:\无尽冬日智能体\config`** |
| `winter_agent_v2` · `tests` · `tools` · `docs` · `results` · `evidence` · `backups` · `.workbuddy` · `.workbuddy-ai` | **真实目录**（各自独立副本） |

⇒ **四个"数据目录"只有一份物理内容，两个路径。** "数据根的那份"和"pin 树的那份"是同一个 inode。

## 二、它解释了什么（此前一直没落地的东西）

1. **`repin_production` 为什么正好排除这四个** —— 不是随手列的表：
   这四个在 pin 树里是 junction，`git checkout <sha> -- .` **本来也无法独立重置它们**
   （会直接改到数据根的那份运行态）。排除表与 junction 集合**逐项相同**。
2. **`verify_pin()` / `WORKTREE_CLEAN` 为什么只看代码** —— 它们白名单的正是这四个
   （"允许脏"），因为脏的不是"未提交的代码"，而是**共享的运行态**。
3. **"数据根在漂移"这个说法对这四个目录不成立** —— 不存在"两份"，只有一份在变。

## 三、这限定/更正了我前几轮的哪些结论

- ❌ **不再成立**：把 `knowledge/` / `learning/` / `dataset/` / `config/` 的 diff 当成
  "数据根相对 pin 树的漂移"。它们**没有第二份**。（我上一轮把 `knowledge/` 的 12k ins 当作
  "待分辨的漂移"来分析 —— 其中"是否有本地新增知识"这个问题**问错了**：
  它**只存在于一个地方**，不存在"另一棵树没有它"。）
- ✅ **仍然成立**：`tests/` 与 `winter_agent_v2/` 是**真实目录** ⇒ 它们**确实**是两份，
  上一轮"数据根 `tests/` 停在 10-08 之前、少 192 条"的结论**有效**（`tests/` 独立）。
- ✅ **仍然成立**：`.workbuddy-ai/memory/` 与 `.workbuddy/memory/` 是**真实目录** ⇒
  我前几轮把它们的未提交内容 `cp` 到 pin 树再提交**是有效的、必要的**（确实两份）。

## 四、实操含义

- **在任一树里写这四个目录，另一边立刻可见**（同一份文件）。所以"在数据根写、pin 树看不到"
  的焦虑对它们**不适用**；对 `.workbuddy*/`、`tests/`、`tools/` 等**真实目录才适用**。
- **提交这四个目录的内容 = 提交那份共享内容**（本次提交的
  `knowledge/failure_patterns/integration/WORKBUDDY_CHANNEL_RETIRED.md` 即如此；
  `cp` 当场报 "are the same file" 就是证据）。
- ⚠️ 反过来：**别对这四个目录做"恢复/重置"类操作**（`git checkout --`、`git restore`），
  它会直接改到共享的运行态，而**两个树都受影响**。

## 五、未做

没改任何 junction；没动 `repin_production` / `verify_pin` / `check_mainline`（它们的行为**本来就是对的**，
本文件只是把"为什么对"写下来）；没对那四个目录做任何重置。
