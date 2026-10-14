# 两套页面词汇表差 **15 个名字**；而闸门只用其中一套（2026-10-14 复核 D-G）

> 决策包里的 **D-G**（`pages.json` 与 `Page` 的"15 名分歧"）此前标为"**较早登记、本轮未复核**"。
> 本轮把它量到名字级别，并**顺着它查到一个闸门特性**：`pages.json` 是那个闸门的**唯一**词表，
> 而它比代码里的 `Page` 枚举**多 11 个名字**。

---

## 一、量出来的分歧（名字级）

同一提交 `155d4255` 上实读（`winter_agent_v2/models.py:9` 的 `Page` 枚举 vs `knowledge/ui/pages.json`）：

| | 数量 |
|---|---:|
| `Page` 枚举成员 | **22** |
| `pages.json` 的 `pages` | **29** |
| 交集 | 18 |
| **分歧合计** | **15** |

**只在 `Page` 枚举里（4，`pages.json` 没有）**：
`LOADING` · `MAINTENANCE` · `PET_TREASURE` · `UNKNOWN`

**只在 `pages.json` 里（11，枚举没有）**：
`ARENA` · `BEAR` · `DANGER_TRAVEL` · `ENDLESS_JOURNEY` · `GIANT_BEAST` · `PET` ·
`PROFILE` · `SETTINGS` · `SNOWFIELD_TRAVEL` · `UNDERGROUND_EXPLORATION` · `VIP`

⇒ 记了两周的"15 名分歧"就是这 **4 + 11**。**数已确认**。

## 二、关键：`pages.json` 是**那个闸门的唯一词表**

`winter_agent_v2/capability_bootstrap.py:1493-1527`（实读）：

```python
vocabulary = set(json.loads((base / "knowledge/ui/pages.json").read_text(...))["pages"])
...
declared_page = data.get("required_page")
if declared_page and str(declared_page) not in vocabulary:
    out.append(StaticKnowledgeDrift(..., field="required_page", missing=str(declared_page),
               kind="page", detail="not in knowledge/ui/pages.json, so no page reader can emit it"))
```

它扫 `knowledge/skills/**/*.json` 的 `required_page`，**凡不在 `pages.json` 里就报 drift**
（`tests/test_declared_pages_and_elements_are_registered.py` 直接 import 这段，运行期与测试共用一个实现）。

⇒ 于是：**这个闸门用"声明式清单"判定"某页能否被读出"，而清单比代码多 11 个名字。**

## 三、后果：闸门对那 11 个名字**过宽**（现在是**潜在**的）

- 一个 spec 若声明 `required_page: "ARENA"`（或 `BEAR` / `VIP` / `GIANT_BEAST` …），
  因为 **`ARENA` 在 `pages.json` 里**，闸门**放行**；
  但页面读取器返回的是 **`Page` 枚举**，而枚举里**没有 `ARENA`** ⇒ **没有任何 reader 能产出它**。
  ⇒ 闸门本该抓的正是这种"声明了、却没人能读出"的 spec，对那 11 个名字**抓不到**。
- **实测：今天没有一条 spec 受影响**（对 11 个名字逐一在 `knowledge/skills/` 搜
  `"required_page": "<name>"` ⇒ **0 命中**）⇒ 这是**潜在漏洞，不是现行故障**。
- 反方向那 4 个（`LOADING`/`MAINTENANCE`/`UNKNOWN` 属瞬态/状态，排掉是对的；
  但 `PET_TREASURE` 是个**真实页面名却没进清单**）—— 若某 spec 声明它，会被**误报**为 drift。

## 四、所以 D-G 该怎么读

不是"名字对不齐、看着难受"，而是：**两套词汇表里哪一套是权威**，决定了闸门对不对。

- 若**枚举**是权威（理由：页面读取器**只能**返回枚举成员）⇒ 闸门应当按**枚举**校验
  （或至少"枚举 ∩ 清单"），否则对 11 个名字过宽。
- 若 `pages.json` 是**已知但有意的超前清单**（VIP/ARENA/PET 等确实多为**未实现**的能力，
  见 `04_OPEN_ISSUES.md` 的 `CAP-AY05`/`CAP-B09`）⇒ 那它**不该被当作"能否读出"的判据**，
  应当改用别的字段表达"计划中"。

## 五、能说 / 不能说

- **能说**：① 15 个分歧名字**逐一列出**；② `pages.json` 是那个闸门的**唯一**词表（实读）；
  ③ 闸门对 11 个名字**过宽**，**今天 0 条 spec 受影响**（实测）；④ `PET_TREASURE` 会**误报**。
- **不能说**：哪一套**该**当权威（**设计决定**）；那 11 个是否是刻意预留（**未读到说明**）。

## 六、未做

**没改 `pages.json`、没改 `Page` 枚举、没改那个闸门**（改闸门 = 改唯一台账/闸门语义那一类，
按项目尺子应单独审）；没动 `knowledge/skills/**`；没动设备。
本文件只把 D-G **从"未复核"升级为"已量到名字级 + 后果已定性"**。
