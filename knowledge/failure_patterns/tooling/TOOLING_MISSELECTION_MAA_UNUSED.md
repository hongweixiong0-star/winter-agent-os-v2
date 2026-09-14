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
