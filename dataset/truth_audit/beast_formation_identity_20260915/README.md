# 出征页身份编造 —— 证据归档（2026-09-15）

## 一句话

`Page.MARCH`（出征编队页）上 vision 报出的野兽身份**不是量测出来的**，而是由"哪一份重复模板恰好命中"决定的；
该页真正显示目标的唯一位置是**标题栏**，vision 从未读过它。

## 症状（真机帧，可肉眼复核）

| 帧 | 标题栏实际内容 | 修复前 vision 报出 |
|---|---|---|
| `01_wilderness_arctic_wolf_beast6_march.png` | `目标：北极狼` | **`麝牛 / level 9`** ← 完全错误 |
| `02_wilderness_musk_ox_beast9_round3_march.png` | `目标：麝牛` | `麝牛 / level 9`（蒙对） |
| `03_wilderness_snow_leopard_low_win_march.png` | `目标：雪豹` | `雪豹 / level 29`（名字蒙对，等级编造） |
| `04_intel_formation_plain_title.png` | `出征` | **`麝牛 / level 9`** ← 编造 |
| `05_intel_formation_archived_episode.png` | `出征` | 无 name/level（走了另一分支） |

`04` 与 `05` 是**同一个页面**（都是情报出征页），却报出两种不同身份——差异只在于模板命中。

## 根因：四张模板是同一个控件的两份裁图

| 语义 | 父帧 | roi (y_norm, h_norm) |
|---|---|---|
| `BTN_BEAST_DISPATCH_MUSK_OX_9` | `beast9_round3_march` | (0.912, 0.070) |
| `BTN_BEAST_DISPATCH` | `live_beast_march_selection` | (0.914, 0.070) |
| `STATUS_VICTORY_ASSURED_MUSK_OX_9` | `beast9_round3_march` | (0.450, 0.045) |
| `STATUS_VICTORY_ASSURED` | `live_beast_march_selection` | (0.455, 0.045) |

`tools/probe_beast_formation_identity.py` 实测：四张模板在**两张父帧上都命中**，
距离 `0,0,4,0`（情报帧）/ `0,0,0,0`（野生帧）——0.002 的 ROI 差在感知哈希分辨率之下。
分支顺序把 `..._MUSK_OX_9` 排在前面，于是**情报帧也被报成麝牛/9**。

## 危害：verifier 在编造身份上通过

`verify_beast_dispatch` 当时要求 `before.beast.name == "麝牛" and level == 9` ——
正是编造出来的值。所以 `beast6_march.png`（北极狼）这条真实行军会被**记为成功**，
而且记录里的身份是假的。这与项目第一原则（不虚报）直接冲突。

## 该页其实显示了目标

标题栏 ROI（`x 0.08–0.50, y 0.004–0.066`）全语料 OCR 结果：

```
corpus=dataset/raw frames=2907 formation-page frames=104
  98 张  title OCR: '出征@1.00'
   4 张  title OCR: '目标：麝牛'
   1 张  title OCR: '目标：雪豹'
   1 张  title OCR: '目标：北极狼'
```

**104/104 全部读出，零张不可读**；6 张野生页（含 `live_beast_runtime_native_retry` 的 2 张）
全部带 `目标：`，98 张情报页全部是裸 `出征`。两个种群完全可分。
完整输出见 `corpus_gate_formation_titles.txt`。

## 修复

1. `vision.py`：三个 `Page.MARCH` 分支只断言模板真正证到的事实（`victory_assured`），
   不再写死 name/level。（`DIALOG_BEAST_MUSK_OX_9` → `Page.BEAST` 分支保留 name/level，
   因为该弹窗确实印着 `等级9 麝牛`，见 `07_...png`。）
2. `ocr.py`：`HybridVision` 在 `Page.MARCH` 且 `beast` 非空时读标题栏，填
   `beast["name"]` 与 `beast["target_kind"]`（`WILDERNESS` / `INTEL`）；读不出则两者都不填。
3. `verifier.py`：`verify_beast_march_open` / `verify_beast_dispatch` 的 MARCH 一侧
   去掉 `level`（该页不显示等级），改为绑定**量测到的** `name`。
   `verify_beast_hunt` 的 `march_ok` 同样去掉编造等级，`target_ok` 改用 `mission_id`。
4. `brain.py`：MARCH 路由从 `level == 22`（编造）改为 `target_kind == "WILDERNESS"`（量测）。
   **野生分支要求正向证据**；其余（情报标题 / 读不出 / goal=INTEL）一律走情报路由——
   因为两个出征按钮是同一个控件（点哪个都落），但两个 verifier 不等价：
   把身份未量测的编队送给 `verify_beast_dispatch` 会把**正确动作记成 FAILURE**。

## 测试

- `tests/test_beast_formation_identity.py`（新增）：模板层不编造、四张模板确为重复、标题可读、路由、verifier 正反例。
- `tests/test_beast_formation_page.py`：原 `test_the_reviewed_formation_frame_keeps_its_original_identity`
  **断言了 `level == 9`（把 bug 写成了测试）**，已改为断言不编造。这是本项目第 4 次同类事故。
- `tests/test_stamina_beast_runtime.py`：编队帧改用生产栈观测（名字只在标题栏，模板层拿不到）。

## 复现

```
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_beast_formation_identity.py
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_formation_title.py
```
