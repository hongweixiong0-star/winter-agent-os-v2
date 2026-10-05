# MASTER RULES — 指针

**本文件不再承载正文。** 规则正文已迁入 `.workbuddy-ai/rules/`，因为原来这里的正文
（《FINAL》全文 + 《持续开发，不许停》全文）**既不在 git 里，也是《不许停》在全机的唯一副本**
（2026-10-05 审计发现；`docs/RULES_AUDIT_2026-10-05.md`）。一条 `git clean -fd` 就能把规则删掉。

| 你要找什么 | 去哪 |
|---|---|
| 真源、优先级阶梯、`§N` 引用怎么解析、本次裁决记录 | `.workbuddy-ai/rules/README.md` |
| 《FINAL》+《不许停》**可执行版**（73+8 条，节号原样） | `.workbuddy-ai/rules/PRINCIPLES.md` |
| 操作判据型规则（存储/分支/指令翻译/宪法 A·B/权限分级） | `.workbuddy-ai/rules/OPERATIONAL.md` |
| 《FINAL》**逐字原文**（存档） | `.workbuddy-ai/rules/FINAL_FULL.md` |
| 《持续开发，不许停》**逐字原文**（存档） | `.workbuddy-ai/rules/PERSISTENT_DEVELOPMENT.md` |
| 诊断报告（81 条 → A 61 / B 8 / C 12 + 冲突 + 从未使用清单） | `docs/RULES_AUDIT_2026-10-05.md` |

**`docs/WorkBuddy_Persistent_Development.md` 从来不存在** —— 那是《不许停》全文，
现在在 `.workbuddy-ai/rules/PERSISTENT_DEVELOPMENT.md`。

## 三条最容易被忽略、但会真的做错事的规定

1. **优先级阶梯里宪法 A/B 排第 3 级**（`README.md §2`）。原来它**根本不在阶梯上**，
   而 `OPERATIONAL.md §24` 自标"优先级最高、不设生产点击例外"。
2. **开发阶段可以主动花体力和 Gem**（`README.md` R2 / `OPERATIONAL.md §8b` T0–T4），
   但真钱与不可逆账号操作**永久禁止**。
3. **裸 `§N` 不可解析**（`README.md §3`）——两份规则文件节号重叠，
   代码里还有至少两份专题文档在被裸引用。新写引用一律用 `文件#节号`。
