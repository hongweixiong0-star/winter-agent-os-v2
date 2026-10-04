# 主仓与生产分支调和：唯一主线 = `codex/production-pin-recovery`（2026-10-04）

> 操作者指令："自主处理主仓与生产分支的关系，全程不需要问用户。"
> 本文记录：先查到的真实状态、方向判定、备份、执行、以及"没有丢任何提交"的证明。

---

## 一句话

主仓 `main`（`ff19040c`）与生产分支（`23360c0a`）**不是同一条线，但只差历史、不差内容**：
`main` 那唯一 1 个独有提交与生产线上的 `b314adb1` 是**同一个改动**（stable patch-id 相同），
生产里早就有。所以正确的方向是**把生产确立为唯一主线、让 `main` 快进追上**，
而不是把生产线合回一条落后 41 个提交的 `main`。调和用一个空合并完成，
**两边一个提交都没丢，生产代码一个字都没变**。

---

## 一、第一步：先查（不先合）

| 项 | 主仓 | 生产 worktree |
|---|---|---|
| 路径 | `E:\无尽冬日智能体` | `E:\无尽冬日智能体_worktrees\winter-prod-pinned\无尽冬日智能体` |
| 分支 | `main` | `codex/production-pin-recovery` |
| HEAD | `ff19040c` | `23360c0a` |
| 最近 5 个提交 | `ff19040c`, `05042268`, `0ca3a161`, `4090f326`, `113c1a52` | `23360c0a`, `de371b32`, `522166d9`, `50410444`, `b314adb1` |

- **是否同一个 commit**：不是。
- **merge-base**：`05042268`
- **领先/落后**：`main` 1 领先 / 41 落后
- **`main` 有没有未合并的本地改动**：有，而且是关键事实（见第五节）。

`ff19040c` 改动的文件只有一个：

```
tools/control_panel.py | 336 +++++++++++++++++++++++++++++++++++++++++++------
1 file changed, 301 insertions(+), 35 deletions(-)
```

### 判定的关键一步：那 1 个独有提交是不是"新东西"

```
ff19040c  stable patch-id : 7a3fb91a2184ceb82e1974311cf9cf8e7718ad8d
b314adb1  stable patch-id : 7a3fb91a2184ceb82e1974311cf9cf8e7718ad8d
```

**patch-id 相同 ⇒ 同一个改动。** 再看它在不在生产里：在。
所以 `main` 相对生产**没有任何独有的内容**。

---

## 二、方向判定

操作者给的分支：

- 生产领先 → 把生产合回主仓；
- **两边内容相同、只差历史** → 需要的是"让两条线的历史收拢到一点"，而不是搬运代码。

所以选定的做法是：

1. **在生产分支上做一次空合并**：`git merge --no-commit --no-ff ff19040c`
   —— 让合并提交同时拥有 `23360c0a` 和 `ff19040c` 两个父提交；
2. 得到合并提交 `ca336ddb`，**它的树与 `23360c0a` 逐字节相同**；
3. 让 `main` **快进**到 `ca336ddb`。

这样：生产没有被回滚（它仍是主线），`main` 不再落后，也没有任何提交被丢掉。

**为什么不反过来**（把生产合进 `main` 再让生产落后）：生产是活的，
回退生产是被明令禁止的；而且那样会在生产历史里插入一个 41 提交宽度的分叉，
让"生产 pin 从哪条线拉"重新变成需要考古的问题。

---

## 三、备份（合并前）

目录：`E:\无尽冬日智能体_backups\20261004_mainline\`

| 文件 | 内容 |
|---|---|
| `BEFORE_STATE.txt` | 两边 HEAD、分支、merge-base、ahead/behind、两个 patch-id、完整 `git branch -vv` |
| `all_refs_20261004.bundle` | `git bundle create --all`（248 MB），已校验为有效且同步 |
| `devtree_worktree_code.patch` | 主仓工作区改动补丁 |
| `devtree_index_code.patch` | 主仓索引改动补丁 |
| `devtree_code_allowlist.tar.gz` | `tools/ winter_agent_v2/ tests/ docs/ .workbuddy-ai/ .workbuddy/ START_HERE.md skills-lock.json` 的完整快照（27 MB） |
| `devtree_wt_before.patch` / `devtree_index_before.patch` / `devtree_status_before.txt` | 执行脚本前又冻结了一次（操作前状态） |
| `devtree_local_drafts/` | 下面第五节里被判定为"旧草稿"的 3 个文件的**原文** |
| `reconcile_devtree_to_mainline.sh` | 主仓调和脚本（可复跑） |
| `merge_msg.txt` / `section_27.md` | 合并提交信息 / §27 原文 |

---

## 四、执行

### 4.1 生产分支：空合并提交

```
git -C <生产 worktree> merge --no-commit --no-ff ff19040c
  → 0 冲突
  → 23360c0a tree : 6d922d190130f7166f3ad253970ab401684ed856
  → 合并树         : 6d922d190130f7166f3ad253970ab401684ed856
git commit -F merge_msg.txt
  → ca336ddb   父提交 = 23360c0a + ff19040c
```

### 4.2 主仓：把 `main` 快进到合并提交

`git reset --mixed ca336ddb`（**不动任何工作区文件**）+ 26 条**路径限定**的
`git checkout ca336ddb -- <代码路径>`。脚本：`reconcile_devtree_to_mainline.sh`。

### 4.3 部署：repin 到合并提交

```
python tools/repin_production.py --to ca336ddb
  [manifest] expected_commit 23360c0a... -> ca336ddb...
  RESULT: CLEAN_OUTSIDE_DATA
```

---

## 五、主仓工作区的真实状态（这是"没有丢东西"的证明）

主仓工作区**不是**生产代码的副本，也不是 `main` 的内容，而是一个三方混合体。
把"`ff19040c` 与 `ca336ddb` 之间有差异的 47 条路径"逐条比对工作区内容：

| 类别 | 条数 | 处理 |
|---|---|---|
| 工作区内容**已等于主线**（其中 17 条此前是"未跟踪"） | 19 | 无需动作；`reset --mixed` 后自动成为正常跟踪文件 |
| 工作区等于**旧 `main`**（属于主线代码的旧版） | 9 | 从主线补齐 |
| **磁盘上不存在**（主线有新文件） | 14 | 从主线补齐 |
| 工作区内容**两个提交里都没有** | 5 | 见下 |

合计 47 = 19 + 9 + 14 + 5。

### 那 5 条"只在本地存在"的处理

| 路径 | 判定依据 | 处理 |
|---|---|---|
| `tools/control_panel.py` | 任何 ref 都不可达；与主线差 375 行，主线**多** 328 行，且**没有** `ClosureCardProbe`/`CLOSURE_INTERVAL`，却有被取代的 `_CLOSURE_CACHE`/`CLOSURE_TTL_SECONDS` | 判定为**旧草稿**，原文留档后升级到主线版本 |
| `winter_agent_v2/event_schedule.py` | 与主线差 54 行，主线多 53 行；本地内容可达于 `workbuddy/page-residency-20261003` | 同上 |
| `winter_agent_v2/goal_library.py` | 与主线差 30 行，本地的"多出部分"是**重复且残缺**的 `available_skills=(),` | 同上 |
| `knowledge/execution/backend_routing.json` | 任何 ref 都不可达（**活数据**） | **原样不动** |
| `results/daily-training-collect-observation.json` | 未跟踪的结果产物 | **原样不动** |

**判据**：一个文件只有当它的本地内容在主线版本里**没有对应物**时才算"本地独有工作"。
上述三个代码文件的多出部分，全部是主线里已经有了的、更新形式的同一件事
（老式 `_CLOSURE_CACHE` vs 新 `ClosureCardProbe`），因此升级不损失任何东西；
原文仍然留档在 `devtree_local_drafts/`。

### 顺带修好的两处索引错误

- **8 个"索引里已删除"的文件**（`.workbuddy-ai/handoff/STRIP_ALREADY_OPEN_20261003.md`、
  `.workbuddy-ai/memory/2026-10-03.md`、6 个 `tests/`/`tools/` 文件）：
  **磁盘上都在、两边提交里也都有** —— 那是一份失效的索引，不是真删除。`reset --mixed` 后消失。
- `knowledge/events/event_registry.json` 的"已修改"状态：
  磁盘内容本来就等于主线版本，只是索引旧；重建索引后变干净。**文件内容未变。**

### 量化结果

```
porcelain 行数      : 1550  →  1512
  其中未跟踪 ??     : 1461  →  1435     （26 条被正确纳入跟踪）
  其中索引级错误     : 8 条 D（假删除）+ 2 条 MM  →  0
文件丢失            : 0   （消失的 26 条"未跟踪"行，其文件全部仍在磁盘上）
活数据目录被 checkout 的路径 : 0
跨操作新增的删除     : 0
```

---

## 六、验证

```
两条线              : main = codex/production-pin-recovery = ca336ddb（同一个 commit）
check_mainline.py   : RESULT: MAINLINE_OK（三条判据全过）
repin               : RESULT: CLEAN_OUTSIDE_DATA
check_wiring.py     : problems: 2（与本次改动前的基线逐字节相同，新增红 0）
pytest check_mainline: 10 passed
```

生产启动、`CODE_COMMIT`、AUTO 恢复与"提交没丢"的对比，见下节收尾记录
（重启在生产 pin worktree 上完成，本文件随后同步）。

---

## 七、硬规则落点

- `.workbuddy-ai/handoff/00_MASTER_RULES.md` **§26**（存储与路径硬规则；此前只存在于主仓工作区、
  从未提交，本次一并落地）+ **§27**（分支与主线硬规则）。
- `tools/check_mainline.py`：把 §27 变成三条可失败的事实，退出码 0/1。
- `tests/test_check_mainline.py`：每条判据先对着**假事实**测一遍。

---

## 八、遗留（不是本次范围，但必须写着）

1. **8 条支线仍未并回主线**：`workbuddy/page-residency-20261003`（领先 merge-base 29 个提交）、
   `codex/main-safe-alignment`、`codex/rally-engine-target-scope`、
   `codex/rally-target-parameterization`、`codex/calendar-detail-liveness`、
   `codex/global-multirole-*`、`codex/hero-gather-safe`、`codex/main-integration`。
   按 §27.2-4，它们要么"在主线重做"，要么"明确放弃"。**不要一条一条去合**。
2. **工作区还有一个 stash**：`stash@{0}: On main: wip-before-rebase-fishing`。
   内容未评估。
3. `check_wiring.py` 的 2 项红是**移植前既存**（已 A/B 证实）：
   `training: the page is consulted through OCR when the templates have nothing`、
   `proof: a no-progress signature needs a measured move, not a green step`。
   后者与循环检测器"输入不是那个事实"是同一个教训在 `escalation_queue` 里的写法 ——
   **规则已写好，等于修复说明书已写好**。
4. 主仓 `learning/` 下有 50 条"已跟踪但磁盘上没有"的文件（`learning/_*.txt` 散装探针），
   属历史清理留下的噪声，本次未处理。
5. 拓扑文件 `REPO_TOPOLOGY_8_WORKTREES_20261003.md` 里的"不要在 main 上提交"建议，
   已被 §27 以更准确的规则取代：**main 是只读镜像，只允许快进**。
