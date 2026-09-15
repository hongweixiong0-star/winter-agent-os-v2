
### 补充：真机 pin 循环跑完后的两条诚实结论（同轮，10:03Z）

`tools/run_intel_pins.py 3` → exit 0，`pins_processed=1`，
`evidence/intel_pins_20260915_100034.json`。

1. **`0az` 的恢复没有触发**：我的测量探针已经先把客户端从卡上挪到 MAP，
   所以 nav 周期是从 MAP 起手的（正常跑，`steps=4`，`stamina_after=110`）。
   ⇒ 「站在 BLOCKED 卡上 → 第 1 步 BACK → MAP」这条整链**尚未真机跑过**，
   目前是「落点已测量 + 单测覆盖」。**不要在 handoff 里读成已真机验证。**

2. **发现 `SEMANTIC_TARGET_NOT_VERIFIED` 的第 3 个独立子成因（`0ba`）**：
   2 条 `SELECT_INTEL_PIN` 失败，`page=INTEL→None`。读代码即定 ——
   `runtime.resolve()` 的 `INTEL_PIN` 分支在「每个检测到的 pin 都已在 40px 内点过」时
   **刻意返回 `None`**（注释明说不在已消费的 pin 上循环），但执行器统一记成「控件不存在」。
   与 `0ax` **同一类错误**：刻意拒绝被记成视觉缺陷。
   同一次运行还可见 `SELECT_INTEL_PIN → BACK → SELECT_INTEL_PIN(FAIL)` 的白烧往返。

**本轮最重要的认知**：`SEMANTIC_TARGET_NOT_VERIFIED` 这个 116 次的数字底下
**至少 3 个互不相干的子成因**（红花费 / `小队设置` 页 / pin 耗尽），
其中两个本轮已修或已解释。**在这个数字被拆干净之前，
不要再用它的总量去论证「视觉层在退化」。**
