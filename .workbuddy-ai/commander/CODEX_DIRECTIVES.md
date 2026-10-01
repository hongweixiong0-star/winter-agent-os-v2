# Codex Commander — 2026-10-02 正式开发交接

## 03:36后最新事实更新

- 核验时间：2026-10-02T03:38:11+08:00。HEAD：4598da3e3d3543e1a869902e1e230da902843344；origin/main：9592b438e91cf0d5ed2972cea3e03394ff2f2495；PIN：4598da3e3d3543e1a869902e1e230da902843344。
- fresh snapshot tick：2026-10-01T19:37:36.766550+00:00；state：IDLE；runtime_thread_alive：False；scheduler_loop_alive：False。这些证明运行快照恢复更新，不代替进程加载fingerprint或游戏Goal完成。
- Root已提交413bd4c/e9f68da日历持久化+due/detail接线、4598da3安全Bootstrap目标入口、bbe2b69同帧语义列表滑动；队列02/03先继承做真实回归，禁止重复建设。
- 上文03:28/03:25停机事实为历史采样。当前仍Codex sole Release Owneractive；待最终发布与接手前再刷新事实，WorkBuddy不得并发发布/输入。

正式接口：[WORK_QUEUE.json](WORK_QUEUE.json)。8 项 READY，最大主动工时合计 525 分钟（8.75 小时）；12–24 小时只可作为真实条件允许的普通 AUTO 观察窗口。用户启动 WorkBuddy 后直接读文件，不要求复制聊天任务。

## 当前所有权与交接触发

当前唯一 Release Owner 为 Codex Root，本轮额度已刷新约 98%，Codex 继续恢复生产并开发。队列已经准备，不代表现在立即交班。

触发条件：Codex 剩余额度 <=15%，或 Codex 明确暂停/离线。触发只能启动交接核验，不自动授予发布权。WorkBuddy先核对最新 Review/handoff、当前 Git、实际进程、PIN/loaded revision、文件归属及租约。Codex仍活跃时，不并发修改共享代码或控制 MuMu。

没有明确 Release Owner 移交记录，WorkBuddy不得 push main、repin production、reload AUTO。当前进程不存在、旧 snapshot alive、本队列 READY、额度阈值均不能单独证明移交。代码文件需确认独立所有权后才编辑/小提交。继承 Root 已完成的安全恢复，不重复启动 panel/worker。

## 生成时事实

HEAD = origin/main = 9592b438e91cf0d5ed2972cea3e03394ff2f2495；生产 manifest PIN = d7a86c47b4e8d6ff763b18b0ba73255824dabd9f。runtime last_tick 为 2026-10-02 01:13 CST，已陈旧；Root约03:25确认当前无panel/worker，正处理恢复。生成时尚不能断言 AUTO_ALIVE。发布后由 Root 刷新基线，WorkBuddy执行每单前重新读取当前事实。

main 已包含此前 Runtime/Bootstrap、safe discovery learning window、UNKNOWN observation ticket；不要重复开发。9592b43记录日历 Goal 每帧重生造成调度饥饿。现有 calendar_scan_due 导入不证明 store/due/cooldown真的生效；需沿真实执行链核查。Root正在修改 event_schedule/runtime/executor/runtime_snapshot 等文件，不得覆盖。

23:02:53 badge helper crash 已 c74f0bb 修复；旧 18 unexpected exits /24 watchdog 是陈旧累计，正常重载不算 crash。FIRST→Candidate→SECOND 无模型闭环尚未有完整证据；射手营799真实训练model0不能算Venus FIRST。旧五次真实调用/grounding0只是一段历史窗口，不是当前总数。

## 工作顺序

1. 事实与唯一所有权交接。
2. 日历饥饿最小修复或继承核验，确保扫描结果写回和其他 READY 工作不饿死。
3. Bootstrap真实 FIRST/SECOND 学习闭环。
4. UNKNOWN覆盖与竞技场安全入口/次数观察。
5. 科研返回恢复。
6. 巨兽搜索与 own-rally 实证。
7. BUILD_STARTED。
8. 被动稳定性与32K资源采样。

普通任务30–60分钟，复杂任务最多90分钟。timebox内无Live improvement或明确root cause/blocker则STOP，写WorkBuddy自有blocked/results后自动下一单。依赖单 BLOCKED 属终态，后续只在对应真实条件允许时继续，不绕过所有权门禁。新P0 worker/lease/role失真可即时优先处理并记录，普通功能不扩十条线。

## 开发与执行约束

复用唯一 Global Scheduler、WorldState、Generic Session Engine、MAA Executor和设备租约；唯一 UI-Venus-2-9B Q4_K_M、context32768。Known Skill/L1/semantic retry/L0实时/Fishing realtime不调用模型；UI-Venus只处理真正ONLINE_UNKNOWN，不引入新模型/MAI runtime/第二Agent。

Bootstrap仅安全 OPEN/OBSERVE/READ/TAB/SCROLL/BACK/CLOSE；窗口UNKNOWN只能观察，不授权攻击、出征、召回、集结或消费。普通已接生产任务仍可依用户授权与当前Policy使用测试小号普通资源，不给其他角色复制宽松探索授权。真实支付、特殊鱼饵、未经当前任务授权的不可逆操作仍禁止。

每次输入需当前角色、页面、目标条件与独占租约；retry重新定位当前帧，不重放历史bbox/永久绝对坐标。模型2次/screen、4安全steps、1bootstrap visit/run、局部时间/cooldown沿现有Runtime；结果未知先观察，不盲目重复消耗。预算耗尽defer当前Goal，不停止整个AUTO。

Candidate保存语义、页面/前置条件、模板/OCR锚/关系、Verifier及trace/frame；模型一次性bbox不进入长期知识。第二次相同身份优先复用；失败再fresh observe→bounded deterministic→Venus。

## 文件职责、版本纪律与证据

Codex owns WORK_QUEUE.json / CODEX_DIRECTIVES.md / LAST_CODEX_REVIEW.md。WorkBuddy不重写原单，使用现有 tools/cq.py 更新 EXECUTION_STATE、results、BLOCKED_QUEUE、REVIEW_REQUESTS；旧三文件已按字节及SHA256归档，WorkBuddy旧状态/结果保持原样。

只显式add已确认功能文件/代码块，小commit；不批量提交dirty、日志、截图、凭据/账号会话。禁止 reset --hard、clean -fd、checkout .、restore .、blind stash pop、git add .。mutable运行数据不得被checkout覆盖。

WorkBuddy runtime channel保持 enabled=false、auto_submit_jobs=false；本队列仅开发交接，不恢复游戏Runtime模型通道。

Code存在、Test通过、模型proposal、grounding、MAA发送、UI变化、Verifier PASS、Goal完成、Candidate复用、LIVE_VERIFIED、STABLE必须分开。成功须真实游戏状态；缺窗口/设备/UI/时间来源用AWAITING_LIVE/BLOCKED_ENVIRONMENT/NEEDS_EVIDENCE，不能虚构成功或时间。结果遵守cq.py字段和live证据要求。

## Root已确认恢复的真实生产证据

2026-10-02 03:33:39新AUTO run；03:37:24 ROLE_B / CLEAR_INTEL / DISMISS_INTEL_GENERIC_REWARD，Verifier PASS，worker和Scheduler实际存活。HEAD/PIN4598da3。这是普通任务进展，不算Venus FIRST/SECOND；日历413bd4c+e9f68da已有实现，后续只先验普通AUTO新trace与真实剩余阻塞。全部发布权仍归当前Codex线程。

## Root最终发布更新 2026-10-01T20:01:45.286355+00:00

HEAD/origin=fe78e9cd93198fc9c91c7d21e57ccadfbf109d27；代码PIN=5a0aeb2458113a83e395e5c9dbe5d291a5cf179f（后续main仅测试/交接，不重复重载以追版本号）。当前snapshot=2026-10-01T20:01:41.678820+00:00 GOAL_RUNNING；每单必须再确认真实进程。最新日历链9341eee已真机入口/首滚动；发现正文timer误识别tabs，5a0aeb2已最小修复并以当前frame ROI重放正确读出日历，四swipe/run后yield。125相关测试PASS，不等于grid/detail完成。

队列02只继承最新代码做真实tab/grid/detail/日历入库与不饿死验证；不要重复store、name/aliases或hub接线。FIRST/SECOND仍未完成；历史5真实模型调用不是学习成功。额度不足/离线时，Root允许WorkBuddy按任务01核对无Codex并发发布/输入并记录独占接手后执行开发队列与正常发布；这条明确条件授权不解除运行时Policy，不恢复retired通道。

## 2026-10-01T20:07:39.406701+00:00 当前生产结果更新

代码HEAD/PIN951abbd；普通AUTO040016已真实完成entry→strip→TAB三步Verifier PASS，识别7日期列、8活动条目。详情断点为observer OCR headings与executor colored bar选择不一致；951abbd沿真实before frame重放已纠正expected identity，须下次普通AUTO确认详情/全扫描。不要重复开发前述接线。模型窗口实际6次：3REPLAN/2拒绝/1OBSERVE，仍无grounded模型动作/候选/SECOND成功；不宣布学习闭环完成。
