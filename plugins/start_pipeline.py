"""流水线触发插件：用户对小智说「一键发文」时，向 Mac 下发发文任务。"""

import json
import os
import datetime
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
TASK_DIR = "/home/ubuntu/xiaozhi-pipeline"
TASK_FILE = os.path.join(TASK_DIR, "task.json")
STATUS_FILE = os.path.join(TASK_DIR, "status.json")

start_pipeline_function_desc = {
    "type": "function",
    "function": {
        "name": "start_pipeline",
        "description": "当用户说'一键发文''自动发文''发一篇''今天发文'等要求启动公众号发文流水线时调用。任务会下发给爸爸的电脑自动执行，通常需要十几到几十分钟，结束后我会播报结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "用户指定的主题，没有指定传空字符串",
                },
            },
            "required": ["topic"],
        },
    },
}


def _status_desc():
    try:
        st = json.load(open(STATUS_FILE))
        d = st.get("date", "")
        today = datetime.date.today().isoformat()
        if d == today:
            s = st.get("status", "")
            if s == "running":
                return "今天已经有一篇文章正在发布流程中了"
            if s == "draft_pushed":
                return f"今天的文章《{st.get('title','')}》已经发布过了"
        return ""
    except Exception:
        return ""


@register_function("start_pipeline", start_pipeline_function_desc, ToolType.WAIT)
def start_pipeline(topic=""):
    dup = _status_desc()
    if dup:
        return ActionResponse(Action.REQLLM, f"不能重复启动：{dup}。可以问用户要不要换一篇", None)
    try:
        os.makedirs(TASK_DIR, exist_ok=True)
        task = {
            "action": "publish",
            "topic": (topic or "").strip(),
            "requested_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "requested_by": "xiaozhi_voice",
        }
        json.dump(task, open(TASK_FILE, "w"), ensure_ascii=False)
        # 同时把状态置为 running，让查询立即反映
        json.dump(
            {
                "date": datetime.date.today().isoformat(),
                "title": "（正在创作中）",
                "published_at": task["requested_at"],
                "status": "running",
                "workspace": "",
                "reason": "",
                "source": "wechat-article-pipeline",
            },
            open(STATUS_FILE, "w"),
            ensure_ascii=False,
        )
        return ActionResponse(
            Action.REQLLM,
            "任务已下发给爸爸的电脑，发文流水线马上启动。全程大约十几到几十分钟，"
            "跑完我会主动汇报结果是成功还是失败。这期间爸爸该干嘛干嘛～",
            None,
        )
    except Exception as e:
        return ActionResponse(Action.REQLLM, f"任务下发失败：{e}", None)
