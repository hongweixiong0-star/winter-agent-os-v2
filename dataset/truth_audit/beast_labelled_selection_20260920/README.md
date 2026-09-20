# 通用打野：点客户端标出来的那只野兽（2026-09-20）

## 一、为什么这件事是 P0

操作者指令：**情报已清完，剩下的体力去打普通野兽**。而 `AVOID_STAMINA_WASTE` 当时
**根本没被调度**——它被 capability_gate 判成 `DEVELOPMENT_PENDING`，理由是
「一个开发作业占着 `SPEND_STAMINA_ON_BEAST`」（job `17f1c743`）。

即使作业不存在，路线也到不了目标：它只有两种手段，**都是逐物种的**——
`TARGET_BEAST_MUSK_OX_9` 与 `TARGET_BEAST_MAMMOTH_5` 两个精灵模板，
以及一个没有收敛条件的视野平移（`SCAN_MAP_FOR_BEAST`，全史 420 次、`goal_progress` 恒为 false）。

## 二、患者帧（本目录 `key/`）

`01_map_frame_labelled_beast_20260919T144336.png`（720x1280，客户端 09-19 22:43:37）：

| 事实 | 读数 |
|---|---|
| 客户端在地图上画了什么 | 一只大兽，**旁边印着名字 `霜鳞避役`**，另有等级徽标 `20` |
| 用生产链读它 | `named_beast_label` → `霜鳞避役`（conf **0.89**）；`level_beside_label` → **20**（conf 1.00） |
| 查表 | `lookup_by_name` → `FROST_SCALED_RUNNER_20` 命中 |
| **然后** | `is_dispatchable` → **False**（该行 `dispatchable: false` / `UNVERIFIED`）⇒ `beast_from_its_label` 返回 `{}` ⇒ 路线记录为空 ⇒ 回到盲扫 |

⇒ **识别从头到尾没有问题，卡的是一道手写的逐物种预批准开关。**
这正是操作者说的「不要只针对某个物种」。

## 三、落点是怎么测出来的（不是猜的）

`02_label_geometry_grid_x3_20260919T144336.png` 是同一帧放大 3 倍并打了原图像素网格
（网格 x 60–420、y 760–1000，每 60 px 一条）。

| 元素 | 原图像素 |
|---|---|
| 兽体 | x 90–330，y 760–900 |
| 名字标签 `霜鳞避役`（深色圆角框） | x 157–204，y 831–846 ⇒ 中心 **(193, 838)** |
| 等级徽标 `20` | 中心约 (92, 895) |

**名字标签就画在兽体上**（客户端把 nameplate 叠在动物身上），所以点它的中心即选中该兽。
归一化落点 = `(193/720, 838/1280)` = **(0.2687, 0.6551)**，与生产链在真机帧上算出的
`tap_norm [0.2687, 0.6551]` 一致。

ROI 读出的 token 框是**相对于裁剪区**的，所以要映射回整帧必须知道帧尺寸——这就是
`beast_from_its_label(image_path, ocr, frame_size=...)` 那个参数存在的原因；
没有帧尺寸时**不给坐标**（`tap_norm` 缺席），而不是编一个。

## 四、改了什么

判定从「逐物种预批准」换成「**客户端自己的判定**」，于是同一个模块回答两个不同的问题：

| 问题 | 函数 | 规则 |
|---|---|---|
| 能不能**点**它（开卡，不花体力） | `may_evaluate` | 身份读出来了就行；**已被实测拒绝**的除外 |
| 能不能**花体力**打它 | `is_dispatchable` | 帧上有客户端印的 `本次出征胜券在握`；或该行本就预批准 |

`beast_catalog` 里各行的表现：

| 情形 | 可点 | 可花体力 | 说明 |
|---|---|---|---|
| 麝牛/9、猛犸象/5（地图，无判定） | ✅ | ✅ | **与改前完全一致**（预批准行仍由自己说了算） |
| 雪豹/29（实测红判定 + BLOCKED） | ❌ | ❌ | **比改前更严**：连点都不点；即使某帧带绿字也不翻案 |
| 霜鳞避役/20（注册但未测量） | ✅ | 需绿字 | **本次新增的能力** |
| 大角鹿/22（VERIFIED 但没记过判定） | ✅ | 需绿字 | 同上 |
| 麝牛/3（等级不符）、空片段 | ❌ | ❌ | 与改前一致 |

链路（新增只有第一跳，后面全是既有的、且已经是物种无关的）：

```
地图：客户端标签点名某兽        -> SELECT_BEAST_TARGET_LABELLED   （新增，落点实测）
卡面：卡自己的 攻击 控件        -> ATTACK_BEAST_CARD              （既有）
阵型页：客户端 胜券在握 条      -> DISPATCH_BEAST                 （既有，体力只在这里花）
低胜算                          -> SAFE_STOP beast_low_win_probability
```

## 五、凭什么说这是安全的

**没有任何一次花体力是由身份单独授权的。** 花体力只发生在阵型页读到客户端自己印的
`本次出征胜券在握` 之后——这也是操作者当初否掉 29 级雪豹时用的同一条证据。
所以 20 级的霜鳞避役即使被打不动，代价也只是开了一张卡（0 体力）然后被读成低胜算而拒发。

## 六、尚未验证（不许当已完成）

- **本帧不是一次成功的打野**。它证明的是「识别 + 落点 + 路由决策」这一段通了，
  上面那张表全部是离线在真机帧上跑出来的，**没有一次真机出征**。
- 真机链路（点标签 → 开卡 → 攻击 → 阵型页 → 出征 → verifier）**要等 AUTO 下一轮走到地图页**，
  且要等 `SPEND_STAMINA_ON_BEAST` 的门禁被释放（僵尸作业超时回收）之后才可能发生。
- 卡面是否真能由 nameplate 点开，**只有真机会说话**；本目录不含那样的帧。

复现：

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
from winter_agent_v2.ocr import OCRService, RapidOCRBackend, HybridVision
from winter_agent_v2.vision import SemanticWorldVision
F=Path('dataset/truth_audit/beast_labelled_selection_20260920/key/01_map_frame_labelled_beast_20260919T144336.png')
hv=HybridVision(SemanticWorldVision(Path('dataset/candidate/template_manifest.json')), OCRService(RapidOCRBackend()))
print(hv.observe(F).beast)
"
```
