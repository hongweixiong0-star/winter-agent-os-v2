# TOOLING_MISSELECTION_MAA_UNUSED

- **分类**：`TOOLING_MISSELECTION`（根因大类：`ENVIRONMENT_BLOCK` 的子类——被自研掩盖的环境能力未使用）
- **记录日期**：2026-09-14
- **记录者**：winter-agent-v2-dev（寒野），依据 `docs/AVAILABLE_TOOLING.md`、
  `knowledge/execution/backend_routing.json` 与本机实测探针

## 事实

MaaFramework **一直安装在项目环境里并能驱动 MuMu**，但开发阶段没有先发现和利用它，
于是手工重新实现了截图、模板匹配与输入三件事。

| 项 | 事实 | 来源 |
|---|---|---|
| MAA 版本 | `MaaFw==5.12.3`（导入名 `maa`），`MaaAgentBinary==1.0.1` | `maa.library.Library.version()` 实测 `v5.12.3` |
| ADB 设备 | `127.0.0.1:7555` 在线 | `adbutils` 实测 |
| 截图 A/B | ADB `324.12 ms` vs MAA `8.92 ms`（**36.3×**，20 样本交替） | `tools/maa_live_case.py capture-ab --attempts 20` |
| 识别 A/B | legacy 固定 ROI `34.5 ms` vs MAA 全帧 `113.03 ms`（legacy **快 3.3×**，命中率同为 20/20） | 同上 |
| 实际代价 | UI 定位、Intel、Battle 调试浪费大量时间；其中一次战斗按钮手工标定耗去约两小时 | `docs/AVAILABLE_TOOLING.md`、backend_routing.json 备注 |

## 根因

1. **没有在开工时做 Tool Inventory**：默认进入"写代码模式"，直接自研底层能力。
2. **不知道已装什么**：MAA 已在 venv 里，但没有机器可读清单，新账号无从得知。
3. **API 认知偏差**：以为导入名是 `maafw`，实际是 `maa`——靠记忆猜 API 会直接判定"不可用"。
4. **静默降级未被察觉**：适配器最初没协商到 MuMu extras，悄悄退回 178 ms 通用路径，
   早期 5 样本探针的 `12.1 ms` 因此不可信。

## Lesson（写入永久行为）

1. **任何底层工程问题，先做 Tool Inventory**（`tool-discovery`），再决定写多少代码。
2. 接管流程在 CURRENT TRUTH 之后**必须**读 `docs/AVAILABLE_TOOLING.md`
   与 `knowledge/tooling/tool_registry.json`（见 `winter-os-takeover` §5b）。
3. **MAA 不是万能**：采集赢 36×，全帧识别反而慢 3.3×。逐 semantic 按证据迁移，
   禁止 wholesale 切换（`backend_routing.json` 的既定政策）。
4. **MAA 无 OCR 模型**：OCR 一律走 RapidOCR + 专用 ROI，不要试图用 MAA 做 OCR。
5. 协商结果必须落盘记录（`adapter.negotiated`），防止静默降级再次伪装成性能数据。

## 触发条件（再次出现即按本卡处理）

- 准备自己写截图 / 模板匹配 / 输入 / 等待循环 / Recovery 之前
- 新账号接管项目，尚未读工具清单之前
- 讨论"识别太慢 / 找不到按钮 / 定位不稳"时

## 相关

- `docs/AVAILABLE_TOOLING.md` — 人读版工具清单与环境陷阱
- `knowledge/tooling/tool_registry.json` — 机器可读注册表（含 benchmark 与 last_checked）
- `knowledge/execution/backend_routing.json` — 已做出的后端选型决策与证据
- `skills/tool-discovery` — 30 分钟 Tool Waste Watchdog、Tool Selection Gate

## 2026-09-18 现状实测：技术债清单（不启动全量迁移）

用户指令：**禁止开启「全量 MAA 迁移工程」**，但把当前未迁移的技能记录为技术债。
下表的每个数字都来自 `learning/executor_backend.jsonl` 的真实行（00:30Z 之后 23 行），
不是配置声明。

| skill | executor | ledger capture | recognition | 备注 |
|---|---|---|---|---|
| `SCAN_MAP_FOR_BEAST` | ADB | ADB_EXEC_OUT | **NONE** | 11 步。盲扫（无识别），验证器只判地图页对；最大技术债 |
| `OPEN_MAP` | ADB | ADB_EXEC_OUT | V2 | 1 步 |
| `SUBMIT_RESOURCE_SEARCH` | ADB | ADB_EXEC_OUT | V2 | 2 步 |
| `DISPATCH_MARCH` | ADB | ADB_EXEC_OUT | V2 | 2 步 |
| `OPEN_HOME` | **MAA** | MAA_MUMU_EXTRAS | MAA | 1 步 |
| `SEARCH_RESOURCE` | **MAA** | MAA_MUMU_EXTRAS | V2（混合） | 2 步 |
| `SELECT_RESOURCE` | **MAA** | MAA_MUMU_EXTRAS | V2（混合） | 2 步 |
| `START_GATHER` | **MAA** | MAA_MUMU_EXTRAS | MAA | 2 步 |

**两个必须分清、不要混为一谈的字段**（混了会得出错误结论）：

- **episode 的 `capture_backend`** 回答「这两帧是谁采的」——当前生产是
  `MAA_MUMU_EXTRAS`（观测设备是 MAA 适配器）。
- **ledger 的 `capture_backend`** 回答「这次动作走的是哪条执行通道」——未迁移的技能是
  `ADB_EXEC_OUT`。

所以用户指令里写的「`SCAN_MAP_FOR_BEAST` capture_backend = ADB_EXEC_OUT」在新日志里
**已经只对一半**：该技能的 *executor* 仍是 ADB（技术债成立），但*观测*已是 MAA。
**ADB（技能尚未迁移）** 与 **ADB 降级（请求 MAA 却失败）** 是两件事，GUI 必须继续分开显示
（前者是待迁移，后者是缺陷）。

**债务处理方式（本卡规则）**：以后开发/修复任何能力时，截图 / 页面识别 / 模板 · ROI ·
颜色 · 特征 / 点击 / 滑动 / 返回 / 等待 / Retry / UI Recovery **优先用 MAA**；
文字数字走 RapidOCR + 专用 ROI。**不做事后批量重写**。

**已知风险（`SCAN_MAP_FOR_BEAST`）**：`recognition = NONE` 意味着这条扫描链**没有任何
识别环节**，它无法判断视野里有没有目标——与 2026-09-18 的
`SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST` 升级（job `2934e9cd`）
指向的根因一致。
