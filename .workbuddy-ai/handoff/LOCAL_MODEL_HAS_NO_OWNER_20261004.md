# 本机规划模型：24 小时没人管，因为没人拥有它

日期：2026-10-04
提交：`23360c0a`（`codex/production-pin-recovery`）
状态：**已上线**，生产 pin 已指向该提交

---

## 一、事故

`E:/winter_models/llama.cpp/server.log` 最后一次写入：**2026-10-03 10:21**。
端口 18080 无人监听，`curl -o /dev/null -w '%{http_code}'` = `000`。
计划任务只有一个（`WinterAgentV2Panel`）。**没有任何东西在监督这个模型。**

它死了大约 24 小时。这 24 小时里：

- 面板的 `_poll_local_model` 每 15 秒问一次 `/health`，一次不落，答案一直是"连不上"；
- 它把这个答案诚实地写进 `self._local_model`，并在窗口上把那一格判成 **等待**；
- **没有任何一层被允许对它做任何事。**

`[planner] UI-Venus-2-9B at http://127.0.0.1:18080 -> LOCAL_GUI_MODEL_UNAVAILABLE
127.0.0.1:18080 (TimeoutError)` —— 每一轮 AUTO 都打印这一行，然后那一轮照常往下走。

**探针整整一天都是对的，而故障是不可见的。** 报告一个窗口结束不了的故障，只是半个探针。

---

## 二、四个决定（每一个都有一个更便宜的错误答案）

### 1. 认领，绝不重载

`/health` 答话 → `ACT_REUSE`，永不重启。
一块 8 GB 的卡上跑两个 5.9 GB 的服务端，比这次故障更糟。
`port_owner()` 报出 pid，写进记录 —— 记录因此能说清"**这是谁的**模型"。

### 2. 启动由阶梯节流，不由轮询决定

`launch_gui_model_server` 会阻塞最多 180 秒等 `/health`（人手动跑的时候想要那个结论）。
**面板线程绝不能等** —— 网关探针和设备探针会排队三分半，窗口停止刷新，
正是这次会话花掉一整天才清掉的那一类缺陷。

所以：生成是 fire-and-forget，且 `launch_in_flight_until`（持久化、自描述）让**下一次**
轮询报 `STARTING` 而不是再起一个服务端。`START_BACKOFF = 60/120/300/600` 只增不减，
每一档都不短于 120 秒的宽限期 —— 一个不断崩溃的模型不能被塞进一张仍握着显存的卡。

> 写这个模块时踩到的坑，值得记：
> 起初分类写成 `starting = bool(record.get("spawned")) and waiting > 0 and failures == 0`。
> 这是个**永远不成立**的条件 —— 刚生成完的那一次 `failures` 已经加过 1 了。
> 于是 `STARTING` 和 `BACKOFF` 分不开，宽限期形同虚设。
> 修法是引入一个显式持久化字段 `launch_in_flight_until`，
> `state = STARTING if now < launch_in_flight_until else BACKOFF`。
> 教训：**用一个读者和写者都能看懂的字段，不要用两个字段的组合去暗示一个状态。**

### 3. "没探到"不是"挂了"

探针没答话时，交给 `ensure()` 的是 `None`（没有问题可问），不是捏造的故障。
网关自己的历史就是这条区分的证据：把可达性从配置里推出来，曾经把**一个健康的网关
连续重启了 51 次**。

### 4. 这里没有任何东西会抛进探针线程

探针炸了、生成炸了，都只是记录 —— 因为那个线程同时还在驱动网关和设备探针。

---

## 三、交付物

新增：

- `winter_agent_v2/gui_model_service.py`（375 行）
  `GuiModelService.ensure()` 一趟里做完测量 / 决策 / 动作 / 记录，
  所有副作用可注入（`spawn` / `probe` / `port_owner` / `clock` / `launcher` / `python`），
  所以测试不需要端口、不需要 GPU。
  状态机 `HEALTHY / STARTING / BACKOFF / DISABLED / UNKNOWN`，
  动作 `REUSE / START / WAIT / PASSIVE`。
  默认落盘 `learning/control_panel/gui_model_service.json`，
  启动日志 `learning/control_panel/gui_model_launcher.log`。

- `tests/test_gui_model_service.py`（22 项，全绿）
  认领不写 spawn；连续五次健康轮询从不声称生成过；挂掉的模型恰好被启一次；
  宽限期内那一次不会再起第二个；阶梯只升不降；模型回来后阶梯归零；
  planner 停用时永不被启动；配置读不出来 → 停用；无端口的 endpoint 不可执行；
  端口从 endpoint 取（18080）；调用方给的答话被复用（`probes == 0`）；
  调用方给的故障仍然会触发启动；记录里有 endpoint/model/port/launcher/`checked_at`；
  记录缺失或损坏都返回 `{}`；探针或生成抛异常永不外泄；
  只经 `winproc.spawn_detached` 触达进程层且模块里没有 `subprocess.Popen(`。

改动：

- `tools/control_panel.py`（+63/-1，四处纯追加）
  `PanelProbes` 接管模型**进程**生命周期，理由与它接管网关进程的理由相同；
  `_poll_local_model` 末尾先测量、再交给拥有者；
  新增 `_ensure_gui_model()`（**fire-and-forget，这是要求不是偷懒**）；
  新增只读 `local_model_lifecycle()`。

- `winter_agent_v2/control_plane_reload.py`（+7）
  把 `winter_agent_v2/gui_model_service.py` 加进 `CONTROL_PLANE_PATHS`。
  **这是按那个常量自己的判据加的，不是按症状加的**：
  "一个模块属于这里，当**这个窗口**在它自己的进程里跑它" ——
  `PanelProbes._ensure_gui_model` 就运行在窗口自己的探针线程上。
  它的过期会是**静默**的：窗口会继续认领一个它已经看不见的服务端，
  或者在一块 8 GB 的卡上起第二个 5.9 GB 的。已有三个名字是这条规则的前例。

- `tests/test_control_plane_reload.py`（+5）
  上面那条规则补一个参数化用例。

---

## 四、验证

- 移植方式：确定性脚本按四个**唯一**锚点做追加，**绝不整文件拷贝** ——
  开发树在过期的 `main` 上（领先 1 / 落后 40），它的 `control_panel.py`
  比生产版少 328 行。锚点唯一性先验（各 1 处），移植后 diff 62 行插入 / 1 行替换。
- `py_compile` 干净；pin 树内 `22 passed` / 五文件族 `157 passed` / 控制面重载族 `50 passed`。
- `tools/check_wiring.py`：`problems: 2` —— **与移植前逐字相同**（见下节），
  本次改动新增问题数 **0**。
- 真机认领检查（对着正在跑的模型）：
  `probe_health: (True, '')`、`state='HEALTHY'`、`action='REUSE'`、
  `port_pid=21252`、`spawned=False`、detail
  `本地规划模型在线（UI-Venus-2-9B @ http://127.0.0.1:18080），保持常驻`。
- 重启前的模型：`llama-server pid=21252`，
  `profile={"gpu_layers":30,"context":32768,"kv_type":"f16","port":18080}`，
  `multimodal_projector_loaded: true`，`/health = {"status":"ok"}`，
  GPU **7805 MiB 占用 / 153 MiB 空闲**（与 `-ngl 30` 的既有实测一致）。

---

## 五、遗留

1. **`tools/check_wiring.py` 在 pin 树 HEAD 上是红的（2 项），且本次改动之前就是红的**
   （已做 A/B：把移植回退后重跑，逐字相同的 2 项）。它们不是这次改动造成的，
   也还没有被修：
   - `training: the page is consulted through OCR when the templates have nothing`
   - `proof: a no-progress signature needs a measured move, not a green step`

   第二项**正好**是循环检测器那条教训在 `escalation_queue` 里的同一形态
   （`PROOF_IS_GOAL_PROGRESS` 要求 escalation 的 `NO_GOAL_PROGRESS` 必须凭
   `row["goal_progress"] is not True` 才算成立；检查要求三个使用点）。
   它是一份**已经写好的规则**，也就是一份已经写好的修复说明书。
   详见同日的 `LOOP_DETECTOR_INPUT_IS_NOT_THE_FACT_20261004.md`。

2. **模型仍然只由面板拥有。** 如果面板不跑（比如人工关掉窗口），模型无人监督。
   目前认为这是对的 —— 生命周期拥有者应该是窗口，第二处能启动它的地方就是第二个模型。
   但要意识到：面板停 = 模型无人管。

3. 之前把"模型死掉"当成 `SEMANTIC_TARGET_NOT_VERIFIED` 上升的原因，**已被实测推翻**：
   逐小时统计全部 10443 行，`SEMANTIC_TARGET_NOT_VERIFIED` 在 10-01~10-03
   （模型活着）一直占 5~12%，模型在 10-03 10:21 死掉时**没有台阶**。
   模型重新常驻之后，这个问题要**重新量**，不能假设。
