# WorkBuddy 与 Codex Skills 盘点

盘点时间：2026-09-26（本机 Asia/Shanghai）。WorkBuddy 版本：5.6.2.0（安装文件 ProductVersion）。
WorkBuddy 有效 Skill 列表缓存版本 5，共 55 条；所有记录的 `SKILL.md` 路径都存在。用户目录下有 3 个本地 Skill，其余为插件或内置 Skill。完整缓存条目见下表。

## 与 Winter Agent V2 开发直接相关

| Skill | WorkBuddy | Codex | V2 AUTO | 安装位置与用途 | 可执行内容 / 依赖 | 本轮处理 |
|---|---|---|---|---|---|---|
| `maa-pipeline-generate` | 启用 | 是（项目 `.agents/skills` 已加载） | 已调用 Skill CLI 主流程，V2 接管设备与注册 | `C:\Users\xhw\.workbuddy\skills\maa-pipeline-generate\SKILL.md`；基于当前画面 OCR box 生成单个 MaaFramework OCR 节点和 ROI sweep。 | Python；其完整 CLI 默认依赖 `maa_mcp` 的设备、OCR 和 Pipeline MCP 接口。此环境未向 Codex 提供 MaaMCP，也无单独系统命令。直接生成 OCR 单节点；不支持模板、ColorMatch 或多节点状态机。 | 读取 Skill 与脚本；V2 runtime 现调用实际 `generate_node.py` 主流程，截获节点输出，再使用现有路由表注册；当前尚无本轮由生产 AUTO 触发的完整闭环 Episode。 |
| `mumu-control` | 启用 | 否（当前 Codex Skills catalog 未加载此 Skill） | 否 | `C:\Users\xhw\.workbuddy\skills\mumu-control\SKILL.md`；管理 MuMu Player 12，含 ADB、截图、OCR、点击/滑动脚本。 | Python 与 MuMu/ADB；有 7 个脚本。独立输入入口绕过 V2 MAA 租约，不用于 V2 AUTO。 | 核验文件；MuMu 操作继续由已持租约的 MAA 链执行。 |
| `skills-security-check` | 启用 | 否（WorkBuddy 专属；可以直接读取文件） | 否 | `C:\Users\xhw\.workbuddy\skills\skills-security-check\SKILL.md`；第三方 Skill 安全审计。 | WorkBuddy Prompt Skill；当前目录没有 Python 脚本。执行说明与允许工具见其 SKILL.md。 | 确认已安装并可由 WorkBuddy 加载；本轮未对其他 Skill 自动复制或启用。 |

## WorkBuddy 当前有效 Skill 清单

| 名称 | 来源 | 实际 SKILL.md 路径 | 文件存在 | Python 脚本数 | 分类 |
|---|---|---|---:|---:|---|
| maa-pipeline-generate | userSettings | C:\Users\xhw\.workbuddy\skills\maa-pipeline-generate\SKILL.md | True | 3 | V2 开发相关 |
| mumu-control | userSettings | C:\Users\xhw\.workbuddy\skills\mumu-control\SKILL.md | True | 7 | V2 开发相关 |
| Skill安全审计（云鼎实验室） | userSettings | C:\Users\xhw\.workbuddy\skills\skills-security-check\SKILL.md | True | 0 | V2 开发相关 |
| ardot-design-core | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\ardot-design-core\SKILL.md | True | 0 | builtin 插件 Skill |
| ardot-design-to-code | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\ardot-design-to-code\SKILL.md | True | 0 | builtin 插件 Skill |
| ardot-poster | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\ardot-poster\SKILL.md | True | 0 | builtin 插件 Skill |
| ardot-slides | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\ardot-slides\SKILL.md | True | 0 | builtin 插件 Skill |
| ardot-ui-design | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\ardot-ui-design\SKILL.md | True | 0 | builtin 插件 Skill |
| buddy-image-processing | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\buddy-image-processing\SKILL.md | True | 1 | builtin 插件 Skill |
| buddy-multimodal-generation | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\buddy-multimodal-generation\SKILL.md | True | 1 | builtin 插件 Skill |
| cloud-service | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\cloud-service\SKILL.md | True | 0 | builtin 插件 Skill |
| design-router | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\design-router\SKILL.md | True | 0 | builtin 插件 Skill |
| expert-manager | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\expert-manager\SKILL.md | True | 7 | builtin 插件 Skill |
| geo-map-compliance-guard | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\geo-map-compliance-guard\SKILL.md | True | 0 | builtin 插件 Skill |
| library | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\library\SKILL.md | True | 49 | builtin 插件 Skill |
| livestream-poster | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\livestream-poster\SKILL.md | True | 0 | builtin 插件 Skill |
| marketplace-skill-installer | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\marketplace-skill-installer\SKILL.md | True | 0 | builtin 插件 Skill |
| miora-brand-design | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\miora-brand-design\SKILL.md | True | 0 | builtin 插件 Skill |
| miora-creative-core | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\miora-creative-core\SKILL.md | True | 0 | builtin 插件 Skill |
| miora-image-generation | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\miora-image-generation\SKILL.md | True | 0 | builtin 插件 Skill |
| miora-video-generation | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\miora-video-generation\SKILL.md | True | 0 | builtin 插件 Skill |
| recommend-connectors | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\recommend-connectors\SKILL.md | True | 0 | builtin 插件 Skill |
| recommend-experts | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\recommend-experts\SKILL.md | True | 0 | builtin 插件 Skill |
| 发布为应用 | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\sites\SKILL.md | True | 0 | builtin 插件 Skill |
| skill-creator | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\skill-creator\SKILL.md | True | 3 | builtin 插件 Skill |
| tencent-docs-routing | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\tencent-docs-routing\SKILL.md | True | 0 | 文档、表格或 PDF |
| tencent-local-office-edit | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\tencent-local-office-edit\SKILL.md | True | 1 | 文档、表格或 PDF |
| wb-finance-skill | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\wb-finance-skill\SKILL.md | True | 16 | 财经 |
| wecom-forwarded-chat-resources | builtin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\wecom-forwarded-chat-resources\SKILL.md | True | 0 | builtin 插件 Skill |
| agent-browser | plugin | C:\Users\xhw\.workbuddy\plugins\marketplaces\codebuddy-plugins-official\plugins\agent-browser\SKILL.md | True | 0 | 浏览器或 Skill 管理 |
| find-skills | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\codebuddy-plugins-official\plugins\find-skills\skills\find-skills\SKILL.md | True | 0 | 浏览器或 Skill 管理 |
| weixinpay-feedback | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\weixinpay\skills\weixinpay-feedback\SKILL.md | True | 0 | 支付 |
| weixinpay-pay | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\weixinpay\skills\weixinpay-pay\SKILL.md | True | 0 | 支付 |
| weixinpay-register | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\weixinpay\skills\weixinpay-register\SKILL.md | True | 0 | 支付 |
| tencent-docs | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docs-plugin\skills\tencent-docs\SKILL.md | True | 2 | 文档、表格或 PDF |
| tencent-saas-docs | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docs-plugin\skills\tencent-saas-docs\SKILL.md | True | 4 | 文档、表格或 PDF |
| tencent-docs-sheet-generation | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\sheetagent\skills\excel-generation\SKILL.md | True | 3 | 文档、表格或 PDF |
| tencent-docs-sheetagent | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\sheetagent\skills\excel-handler\SKILL.md | True | 0 | 文档、表格或 PDF |
| tencent-pptx | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-pptx\skills\tencent-pptx\SKILL.md | True | 2 | 文档、表格或 PDF |
| brief-compose | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\brief-compose\SKILL.md | True | 0 | 文档、表格或 PDF |
| design-token | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\design-token\SKILL.md | True | 1 | userSettings 插件 Skill |
| doc-typeset | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\doc-typeset\SKILL.md | True | 0 | 文档、表格或 PDF |
| format-extract | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\format-extract\SKILL.md | True | 1 | 文档、表格或 PDF |
| generate-fillable-contract-html | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\generate-fillable-contract-html\SKILL.md | True | 0 | 文档、表格或 PDF |
| html-review | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\html-review\SKILL.md | True | 1 | 文档、表格或 PDF |
| html-to-docx | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\html-to-docx\SKILL.md | True | 29 | 文档、表格或 PDF |
| tdoc-orchestrator | userSettings | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\skills\tdoc-orchestrator\SKILL.md | True | 0 | 文档、表格或 PDF |
| tencent-docx | plugin | E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\builtin-plugins\tencent-docx\SKILL.md | True | 33 | 文档、表格或 PDF |
| pdf | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\document-skills\skills\pdf\SKILL.md | True | 8 | 文档、表格或 PDF |
| pdfkit-py | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\document-skills\skills\pdfkit-py\SKILL.md | True | 57 | 文档、表格或 PDF |
| neodata-financial-search | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\finance-data\skills\neodata-financial-search\SKILL.md | True | 1 | 财经 |
| westock-data | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\finance-data\skills\westock-data\SKILL.md | True | 0 | 财经 |
| westock-tool | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\finance-data\skills\westock-tool\SKILL.md | True | 0 | 财经 |
| playwright-cli | userSettings | C:\Users\xhw\.workbuddy\plugins\marketplaces\codebuddy-plugins-official\plugins\playwright-cli\skills\playwright-cli\SKILL.md | True | 0 | 浏览器或 Skill 管理 |
| github | connector | C:\Users\xhw\.workbuddy\plugins\marketplaces\workbuddy-connector-plugins-official\connectors\github\skills\github\SKILL.md | True | 0 | connector 插件 Skill |

## 能力边界与本轮接线

- WorkBuddy 有效 cache 中 55 个条目全部存在；用户级本地 Skills 为 `maa-pipeline-generate`、`mumu-control`、`skills-security-check`。缓存列出的插件 Skill 与 V2 可执行工具不是同一层能力。
- Codex 已加载项目共享 `maa-pipeline-generate`。另两个 WorkBuddy Skill 未出现在本轮 Codex Skills catalog 中；可读文件不等于 Codex 已加载 Skill。
- `maa-pipeline-generate` 不是系统命令。它附带两个主脚本 `generate_node.py`、`generate_sweep.py` 和路径辅助脚本；生成器依赖 MaaMCP 做真实 OCR 与 Pipeline I/O。Codex 当前工具表未暴露 MaaMCP 服务。
- V2 已有 `PipelineAutoGen` 及 `LiveRuntime._maybe_autogen_node`：当前语义解析失败时可抓取当前帧、用 V2 OCR 生成识别节点，并注册到现有路由和 Skill Registry；异常只记录，不终止 AUTO。
- 本轮把运行时生成器改为实际加载并调用安装 Skill 的 `generate_node.py` CLI 主流程。V2 注入自己持租约得到的 OCR box，截获 Skill 的 merge 回调，随后由 V2 现有路由表注册。没有启动另一个 MaaMCP ADB 控制器。Skill CLI 主流程调用已通过针对性测试；仍缺生产 AUTO 触发的一次自主生成→MAA→Verifier 完整 Episode。
- `tools/pipeline_coverage.py` 当前只读统计：137 个 Skill 定义中 9 个有 MAA recognition node；16 个 Goal 中 A=0、B=0、C=11、D=5。训练 Skill 已定义，但这个工具按 routing node 口径仍把训练 Goal 列为 C，说明当前 MAA node coverage 不能代表三兵营真机 `TRAIN_TROOPS` 闭环；活动日历、联盟、建筑、科研等仍有多项缺失节点。
- 节点生成、AUTO 注册、MAA 输入、Verifier PASS、Goal 完成是分开的证据状态。
- 工作区存在大量先前修改；盘点过程未覆盖或重置这些文件。
