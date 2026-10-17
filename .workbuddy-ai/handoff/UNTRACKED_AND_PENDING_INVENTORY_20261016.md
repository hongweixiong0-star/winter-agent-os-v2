# 待批清单：untracked / modified / deleted（测量于 2026-10-16 21:30）

**测量方式**：`git status --short` 全量导出＋分类脚本（本轮 r276 附带产出）。
**总览**：untracked **1094** · modified **119** · deleted **57**。
**原则**：本文只列清单与建议，不执行任何删除/提交之外的处置；逐组待批。

---

## A. modified（已跟踪文件的未提交修改）——**最优先审阅**

| 项 | 规模 | 内容 | 建议 |
|---|---|---|---|
| ~~`config/v2.json`~~ | ±10 行 | 10-08 operator 指令落地：运行时本地模型切至 Qwen3.6-35B-A3B（Q3_K_M）＋ llama.cpp 127.0.0.1:18080，UI-Venus 同指令删除 | **✅ 已提交 2026-10-16（`bf0dc45e`）**——理由：指令已执行 8 天、生产在用（junction 同盘）、handoff 有专档；不提交则非本盘 checkout 指向已删除模型的旧配置 |
| `START_HERE.md` | −47 行 | handoff 导航精简 | 审阅后提交 |
| `.workbuddy-ai/commander/` 3 件 | 重构 −75 行 | codex 命令行档 | 审阅后提交 |
| `.workbuddy/memory/2026-10-15.md` | 日志 | 昨日工作日志 | 与 10-16 日志同批提交 |
| `dataset/**` labels 等 ~100 件 | 数据 | 标签/数据微调（含 `candidate/intel_live_*`、`raw/*_labels_*.json`、`.gitkeep` 系列） | 按目录分组审阅、逐组提交 |
| `_capture_panel_window.py` | 根脚本 | 面板窗口捕获 | 审阅（纳入或归档） |

完整 119 项：`git status --short | grep '^ M'`。

## B. deleted（未提交的删除）57 件

- `backups/dataset_cleanup_20261006/*`（数据集清理留下的备份删除，已被磁盘状态确认）
- `learning/_ab_screen_key_plugin.py` 等
**建议**：确认后与对应的清理批次合并提交（删除已经实际发生）。

## C. untracked 1094 件——分类与建议

| 类 | 数量 | 例子 | 建议 |
|---|---|---|---|
| 根目录散件（json/log/sh 等） | 477 | `_stability_watch.jsonl`、`_bench_hash_*.json` | 观测产物：有价值留档、其余删（待批） |
| 根目录 `_*.txt` | 317 | `_fam*.txt`、`_out_*.txt` | 调试输出：建议删或 `archive/` |
| 根目录 `_*.py` | 162 | `_ab_*.py`、`_autocrop_*.py` | 一次性脚本：建议 `tools/archive/` 或删 |
| `out/` | 46 | `V2_READONLY_TAKEOVER_AUDIT_20261009.md`＋png | 审计 md 归档 handoff；图片随裁定 |
| `tools/` 其它脚本 | 42 | `gather_all.py`、`ocr_readall.py`、`build_current_failures.py` | **逐个审阅后纳入**（抽样均为正经工具、带完整 docstring） |
| `tools/` 行动探针 | 31 | `bear_new_account_baseline_pass2/3/8b/10.py` | 迭代版本：建议留最新＋归档其余 |
| `tools/_ab24/`、`tools/_ab_verify/` | 2 目录 | | 审阅 |
| 根报告 md | 8 | `AUTO_STALL_ROOT_CAUSE_20260930.md`、`V2_FULL_REPOSITORY_AUDIT.md`、`docs/GAME_KNOWLEDGE.md` | 归档到 handoff/ 或 docs/ |
| `.workbuddy-ai/` | 5 | commander 档案、audit/ | 提交流程决定 |
| `.workbuddy/` | 3 | `memory/automations/`×2、`suite_after.txt` | automations 保留；`suite_after.txt` 归档 |
| `dataset/exploration/` | 1 目录 | | 审阅 |

## C2. 跨树同步（pin 树）——**新发现（2026-10-16），不宜盲操作**

- **pin 树**（`C:\Users\xhw\.codex\worktrees\prod\repo`）：
  - 代码侧落后数据根（HEAD `9ffaf237`，其近期提交全是 codex 的 `memory:` 工作）。
  - **`memory/` 为双向差异**（已实测 `diff -rq`：9-13 起多文件两侧不同）——数据根写、
    **pin 树由 codex 活跃维护**——**盲目 `cp` 覆盖会冲掉另一条维护线**。
  - 10-14 记录的"cp 收尾"流程在当时成立，但两线已各自演化 → **需要一次专门的合并**
    （逐文件比对取新，或先裁定哪侧为准），**列入待专门处理**。
  - 结构提醒（10-14 事实）：pin 树的 `knowledge/learning/dataset/config` 是指向数据根的
    **NTFS junction**（同一份内容）；`winter_agent_v2/tests/tools` 等才是独立副本 ——
    **pin 树的代码推进（repin/镜像 merge/check_mainline）属"生产发布"动作**，待专门流程与时机，
    **勿做 `git checkout --` 类回滚**（junction 会连带数据根）。

## D. 本轮已完成的裁定（参照先例）

- **被引用即纳入**：4 个被生产注释引用的工具已提交（`d77fb067`：shop 三件套＋`diagnose_page_match`）。
- **全绿活规格纳入**：6 个数据根草稿测试已提交（`bd73a5a4`）；tests/ 下 untracked＝0。
- **规格先行闭环**：`test_template_lifecycle_precedence` 实现＋纳入同批完成（`17fbb9f9`）。

## E. 建议的处置顺序

1. **A 组**（modified）：按表逐组审阅提交，`config/v2.json` 优先。
2. **B 组**（deleted）：确认后随清理批次提交。
3. **C 组**：三筛——①被引用的纳入（剩余已为 0）；②正经工具逐个审议纳入（42 个候选）；
   ③其余（散件/txt/迭代探针）归档或删——**删除前按批次列清单**（每批 ≤10 个，先列后删）。
