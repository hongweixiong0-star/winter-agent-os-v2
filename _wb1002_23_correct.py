"""Record the duplicate-commit finding and correct WB-1002-23's evidence accordingly."""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

ADDED = (
    "④ 已解释的一项（良性）：本轮出现两对同消息、同 tree、相差 2 秒的提交"
    "（081d48b→3a6ea9f，756631c→9b76e15），作者一律是仓库配置的 `Winter Agent OS V2 "
    "<agent@winter-agent-os.local>`（不是第三方身份）。拓扑显示每对是'先一个同内容提交，紧接着我的提交'，"
    "即**同一条命令被执行了两次**、第二次因工作区未变而生成同 tree 提交 —— 两次都带沙箱升级提示。"
    "⇒ 教训是流程性的：**提交脚本必须能容忍被执行两次**（或本身幂等）。"
    "⇒ 这一项**削弱**但不否定 ①—③：'工作区把已跟踪文件还原成 HEAD'仍未归因，"
    "所以本单的正确做法是**起只读监视器留证据**，而不是继续从行为反推。"
)

DAILY = """

**⑤ 两对重复提交已解释（良性）**：`081d48b→3a6ea9f`、`756631c→9b76e15` 同消息同 tree、相差 2 秒，
作者是**仓库配置的身份**而非第三方；拓扑显示是**同一条命令被执行两次**（第二次工作区未变 ⇒ 同 tree）。
两次都带"沙箱升级"提示。**教训：提交脚本必须容忍被执行两次。**
这一项削弱但不否定前面的还原观察 —— WB-1002-23 的做法应是**起只读监视器留证据**，不再从行为反推。
"""


def main() -> int:
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    for order in payload["orders"]:
        if order["task_id"] == "WB-1002-23-DEV-TREE-SILENT-REVERT":
            order["current_evidence"] = str(order.get("current_evidence", "")) + "\n\n" + ADDED
            order["implementation_hint"] = (
                "先测：起一个只读监视器，按固定间隔记录若干代表文件的 (path, mtime, size, md5) 与"
                "**自身每一次读取的时间戳**，覆盖 knowledge/ 与 winter_agent_v2/；出现漂移时抓当时进程快照"
                "（psutil，用项目 venv）与文件锁持有者。**先拿到'谁在何时写了什么'，再谈修。**"
                "已排除项已写入 current_evidence；已知良性项（命令被重复执行）说明'从行为反推'不可靠。"
            )
            order["acceptance"] = (
                "给出写入者身份（PID + cmdline），或证明在 AUTO 停止时漂移消失，或证明监视器下不出现漂移"
                "（即原先的两次观察另有解释）。无论哪种，都要把'验证必须读 git show HEAD:'写成纪律。"
            )
            break
    else:
        raise SystemExit("WB-1002-23 not in the queue")
    payload["updated_at"] = "2026-10-02T11:40:00Z"
    payload["update_reason"] = (
        payload["update_reason"] + " 另：两对重复提交已归因为同一命令被执行两次（良性），"
        "WB-1002-23 的证据与做法据此修正为'先起监视器留证据'。"
    )
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("updated WB-1002-23")

    daily = ROOT / ".workbuddy-ai/memory/2026-10-02.md"
    daily.write_text(daily.read_text(encoding="utf-8") + DAILY, encoding="utf-8")
    print("appended to", daily.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
