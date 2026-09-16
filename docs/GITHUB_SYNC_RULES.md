# GitHub 持续同步规则（本项目执行细则）

> 操作者 2026-09-16 指令的**可执行版本**。原文是意图，本文件是"在这台机器上怎么做"。
> 事实源仍然是：代码 / episodes / evidence / `git log`。本文件若与工具行为冲突，以工具输出为准并修本文件。

**仓库**：`https://github.com/hongweixiong0-star/winter-agent-os-v2`（**PUBLIC**）
**默认分支**：`main`
**目标**：让 GitHub 成为"接近当前真实开发状态的外部镜像"，而不是几天更新一次的备份，
也不是每改一行就推的日志系统。**commit / push 的边界 = 一个可验证工作单元。**

---

## 0. 两条命令（其余都是解释）

```bash
# 现在同步到哪一步了？（会 fetch，刷新 remote-tracking ref）
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/git_sync.py status

# 推送（先跑敏感信息闸门，被拦就不推）
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/git_sync.py push
```

`status` 打印：`local_head / remote_head / unpushed_commits / behind / git_dirty / last_push_at /
last_push_status`，并把脏文件按 **KEEP / TEMP / DISCARD? / UNKNOWN** 分类（只分类，**从不删除**）。
这三个字段同时也由 `tools/update_workbuddy_handoff.py` 写进
`01_CURRENT_TRUTH.md §A2`、`08_LIVE_METRICS.json.git_sync`、`10_LAST_HANDOFF.md`，
所以**新会话不需要先问人**就知道本地是否领先远端。

---

## 1. 什么时候**必须** commit + push

| # | 时机 | 为什么 |
|---|---|---|
| 1 | 一个 Work Order 完成 | 队列结果的落点 |
| 2 | 一个 Capability 达到 **LIVE_VERIFIED** | 这是本项目唯一真正的"完成" |
| 3 | 一个重要 Bug 修好**并验证** | 验证是界限，不是修好 |
| 4 | P0/P1 根因确认并修复 | 回滚安全网 |
| 5 | MAA Production 接线有实质变化 | 主链 |
| 6 | Verifier / Recovery 有重要修复 | 安全边界 |
| 7 | Work Queue / Handoff 有关键状态变化 | 跨账号接力 |
| 8 | 开始较大风险修改**之前**（安全 checkpoint） | 出事能回 |
| 9 | 准备标 BLOCKED、但本地已有值得保留的成果 | 丢掉最亏 |
| 10 | 会话即将结束 / 额度即将耗尽 | §六 |

## 2. 什么时候**不要**为了"存一下"就推 main

改注释、临时 debug print、临时脚本、做了一半的错误实验、明知测试不过、
未验证的猜测性改动 —— 这些**留本地**。要保存就先本地 checkpoint，
确认有效再正式 commit（`git stash` / 本地分支 / 未推送的 commit 都算）。

**明确禁止**：明显 broken 的状态推 `main`。

## 3. 每次正式提交前最低检查

```bash
git status                                     # 脏文件里有没有不该提交的
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -c "import ast;ast.parse(open('<file>',encoding='utf-8').read())"
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/check_wiring.py     # problems: 0
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -m pytest <targeted tests> -q
```

- 改动影响生产主链 ⇒ **至少 replay 或对应 verifier test**。
- 有真机条件 ⇒ **优先附 Live Verify Evidence**（截图 + episode）。
- 本机全量 pytest 的坑见 §8。

## 4. Commit message 规范

前缀：`feat:` `fix:` `refactor:` `test:` `docs:` `chore:` `evidence:` `runtime:`
有时更好的是**带能力名**：`feat(gather): live verify coal gather e2e`、`fix(march): stop hardcoding march_max=6`。

正文写"**为什么**"，并写清证据边界（验证了几次、哪个账号、哪些没验）——
本项目的 commit 历史是给下一个会话读的，不是给日历读的。

## 5. Push 边界

完成 1–3 个紧密相关的工作单元就必须 push，不要让本地长期领先。
以下四类**完成即推**，不等攒批：重大修复 / Live Verified / P0 Runtime 修复 / MAA Production 变化。

## 6. 会话结束前强制同步

```bash
git status && git log -1 --oneline && git rev-parse HEAD && git rev-parse origin/main
```

`HEAD != origin/main` 且改动是**已验证成果** ⇒ 必须 push。
未提交改动必须被**明确分类**（KEEP / TEMP / DISCARD），不许静默留下一堆脏树；
分类结果写进 `10_LAST_HANDOFF.md` 的手写块或本轮的 memory 日志。

## 7. 禁止同步敏感信息（PUBLIC 仓库）

**推之前必须先过闸门**（`git_sync.py push` 自动跑；也可单独跑）：

```bash
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/scan_public_repo.py --json out_secret_scan.json
```

它检查四类：**不该被跟踪的文件名**（`.env*` / `secrets*` / `credentials*` / `token*` /
`cookie*` / `session*` / `*.pem` / `*.key` / `id_rsa*`）、**凭据形状**（GitHub/Slack/Google/AWS
token、私钥块、JWT、`password=...` 长字面量）、**个人数据**（手机号、邮箱，带白名单）、
以及 **`.gitignore` 是否覆盖上述模式**。
`.gitignore` 里已有对应区块；`session*` 对四个**游戏域**文件（`session_disconnected` 弹窗模板等）
有显式例外，改它们不会被静默忽略。

⚠ 手机号规则会命中 sha256/dhash 里的数字串（实测 10 处全在
`dataset/candidate/dataset_audit.json` 的哈希里）⇒ 扫描器**已抑制落在 16 位以上十六进制串内的命中**。
看到命中先去人眼确认，再决定白名单还是删数据。

## 8. Evidence 同步原则

**可以**：测试摘要、结构化 episode、脱敏 runtime 证据、必要的小截图/报告。
**不要**：含账号信息的大量原始数据、无意义海量截图、临时缓存、大体积运行垃圾。
大证据**留本地**，GitHub 只同步**索引 + 摘要 + 关键样本 + 引用路径**
（`evidence/INDEX.json` 就是这个索引）。
`dataset/truth_audit/**` 默认被忽略，只按白名单放行**被测试引用**的那些帧（见 `.gitignore`）。

## 9. Handoff 也要同步

`START_HERE.md`、`.workbuddy-ai/handoff/`、`.workbuddy-ai/commander/`、
`.workbuddy-ai/memory/MEMORY.md` 有**实际开发意义**的变化时，与对应代码**同一个 commit/push**。
**不要**为每次 timestamp 变化制造提交 —— 那是噪音。

## 10. Advisor Issue（`#2 CHATGPT-ADVISOR`）

**只在**出现下列之一时更新：`BLOCKED > 60min`、`ARCHITECTURE_DECISION`、`TOOL_SELECTION`、
`CONFLICTING_EVIDENCE`、`UNKNOWN_GAME_MECHANIC`、`REPEATED_LIVE_FAILURE`、`P0_RUNTIME_FAILURE`。
**上报前先 push 当前有效代码**，评论里**必须带 commit hash** —— 否则外部审查者看到的
问题对不上代码版本，等于白问。

## 11. 同步失败时不停止开发

push 失败 ⇒ 记录 `GIT_SYNC_PENDING`（`learning/git_sync_state.json` 的
`last_push_status`），**继续本地开发**，后台低频重试；连续失败写进 handoff / open issue。
**禁止**因 GitHub 暂时异常阻塞一个 Capability。

## 12. 绝对禁止

- `git push --force`
- 擅自重写 `main` 历史
- 自动 `git reset --hard` 到远端
- 冲突时先看远端变化再决定 merge / rebase；**不要破坏已有提交历史**

（`tools/git_sync.py` 在"本地落后"时**直接拒绝推送**并打印它看到的状态：
冲突是决定，工具不允许替人做这个决定。）

## 13. 推荐节奏

```
完成一个真实能力 → 测试 → Live Verify → Evidence → commit → push → 下一个能力
```

而不是"开发半天 → 一次性推 30 个混合改动"。

## 14. 本机已知的同步相关坑

1. **全量 pytest 拿不到汇总行**：宿主批量删除守卫会在会话末尾拦下 pytest 自己清理
   `%TEMP%\pytest-of-xhw\garbage-*`，`SystemExit` 吞掉终端汇总。
   对策：`-o tmp_path_retention_policy=all`（别让它在末尾删），
   或 `PYTEST_PLUGINS=winter_failwatch PYTHONPATH=tools`（失败发生时就把 nodeid+longrepr
   写进 `out_failwatch.txt`）。`%TEMP%\pytest-of-xhw` 属宿主保护目录，**不要**擅自递归删。
2. **repo 可能有两个写入方**：另一个会话可能在你工作期间提交你的工作树。
   改完**立刻** `git log --oneline -3` 复核，不要默认"未提交的改动还在"。
3. **不要用 `git credential fill`**（GCM 会弹 GUI 把非交互调用挂死）；
   推送身份走已配置的 `gh` CLI（`gh auth setup-git` 已接进 git）。
