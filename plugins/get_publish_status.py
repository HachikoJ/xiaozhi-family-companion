"""公众号发文状态查询插件：读流水线上报的状态文件播报（三态：running/success/failed）。"""

import json
import os
import datetime
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
STATUS_FILE = "/home/ubuntu/xiaozhi-pipeline/status.json"

get_publish_status_function_desc = {
    "type": "function",
    "function": {
        "name": "get_publish_status",
        "description": "查询爸爸公众号的最新发文状态。当用户问'今天发文了吗''发文成功了吗''公众号怎么样''文章到哪一步了'时调用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


@register_function("get_publish_status", get_publish_status_function_desc, ToolType.WAIT)
def get_publish_status():
    if not os.path.exists(STATUS_FILE):
        return ActionResponse(
            Action.REQLLM,
            "还没有任何发文记录。如果爸爸想发文，可以让我下发给电脑一键发文",
            None,
        )
    try:
        st = json.load(open(STATUS_FILE))
    except Exception:
        return ActionResponse(Action.REQLLM, "发文状态文件读取失败", None)

    date = st.get("date", "")
    today = datetime.date.today().isoformat()
    title = st.get("title", "公众号文章")
    if date != today:
        return ActionResponse(
            Action.REQLLM,
            f"最近一次发文是 {date} 的《{title}》，今天还没有发文的记录",
            None,
        )

    status = st.get("status", "")
    if status == "running":
        started = st.get("published_at", "")
        return ActionResponse(
            Action.REQLLM,
            f"今天的发文流水线 {started} 启动，正在创作发布中，请耐心等待，结束会主动汇报",
            None,
        )
    if status == "failed":
        reason = st.get("reason", "未知原因")
        return ActionResponse(
            Action.REQLLM,
            f"今天 {st.get('published_at','')} 的发文失败了，原因是：{reason}。爸爸可能需要帮忙排查",
            None,
        )
    return ActionResponse(
        Action.REQLLM,
        f"今天 {st.get('published_at','')} 的文章《{title}》已推送到公众号草稿箱，爸爸可以去后台预览并发布",
        None,
    )
