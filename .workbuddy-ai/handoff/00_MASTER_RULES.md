# 00 — MASTER RULES（指针）

**本文件已迁至 `.workbuddy-ai/rules/OPERATIONAL.md`，正文不再放这里。**
移动发生在 2026-10-06，与规则层收敛同批（依据 `docs/RULES_AUDIT_2026-10-05.md`）。

保留本指针路径，是因为代码里大量注释按 **`00_MASTER_RULES.md §N`** 的形式引用本文件
（例：`§5`、`§8`、`§18b`、`§24.2`、`§24.3`、`§25`、`§26.4`、`§27.4`、`§28.6`）。
**这些引用原样有效**——节号没有改动，只是文件换了位置。

| 你要找什么 | 去哪 |
|---|---|
| 本节全部规则正文（§0–§28 及子节） | `.workbuddy-ai/rules/OPERATIONAL.md` |
| 原则层规则（《FINAL》+《不许停》） | `.workbuddy-ai/rules/PRINCIPLES.md` |
| 优先级阶梯、`§N` 解析表、裁决记录 | `.workbuddy-ai/rules/README.md` |

## 为什么这两份文件必须被区别对待

`docs/MASTER_RULES.md`（原《FINAL》+《不许停》副本）与本节曾**被混为一谈**，
但两者的节号是**重叠的**（都有 §1–§28），所以代码里的裸 `§N` 引用长期不可解析。
实测同一批代码里同一个 `§N` 分别指向：本文件、`dev`《FINAL》、`FISHING POLICY V2`、
`TASK THROUGHPUT V1`——**裸 `§N` 不能当作证据**。详见 `.workbuddy-ai/rules/README.md §3`。

**新写引用一律用 `文件#节号`**，例如 `OPERATIONAL §24.2`、`PRINCIPLES §39`。
