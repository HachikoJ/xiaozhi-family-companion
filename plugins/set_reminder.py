"""定时提醒插件：设备原生闹钟（离线也响）+ 服务器在线语音播报 + 记忆兜底。"""

import os
import json
import asyncio
import datetime
import uuid
from typing import TYPE_CHECKING

from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
# create_task 必须持引用，否则会被 GC 静默回收（ asyncio 经典坑）
_REMINDER_TASKS = set()
MEMORY_PATH = "/home/ubuntu/xiaozhi-esp32-server/main/xiaozhi-server/data/.memory.yaml"
DEVICE_MAC = "AA:BB:CC:DD:EE:FF"

set_reminder_function_desc = {
    "type": "function",
    "function": {
        "name": "set_reminder",
        "description": (
            "设置定时提醒。当用户说'X分钟后提醒我……''提醒我几点做……''到时间叫我……'时调用。"
            "时间换算规则：根据上下文中的当前时间计算差值换算成分钟（如现在12:00用户说明天早上8点，则minutes=1200）。"
            "设备闹钟会准时响铃，如果小智在线还会语音播报该做的事。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "at_time": {
                    "type": "string",
                    "description": "到点时刻，24小时制HH:MM（优先用这个）。根据上下文当前时间加上用户说的时长算出，如当前12:44用户说一分钟后→at_time=12:45；说三小时后→15:44。跨天(明天早上)则传明天的时刻即可",
                },
                "minutes": {
                    "type": "number",
                    "description": "多少分钟后提醒（备用，仅在用户直接说了分钟数时用：一分钟后=1，十分钟后=10，一小时后=60）。注意：一分钟后是1不是60！",
                },
                "event": {
                    "type": "string",
                    "description": "要提醒的事情，如'关火'、'带宝宝去打疫苗'、'开会'",
                },
            },
            "required": ["minutes", "event"],
        },
    },
}


def _write_memory_note(note: str):
    """连接已断时，把提醒写进记忆的潜在关怀，下次唤醒主动说。"""
    try:
        import yaml
        all_mem = {}
        if os.path.exists(MEMORY_PATH):
            all_mem = yaml.safe_load(open(MEMORY_PATH)) or {}
        raw = all_mem.get(DEVICE_MAC)
        try:
            mem = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            mem = {}
        pending = mem.get("待响应", {}).get("潜在关怀", [])
        tagged = f"[提醒到期] {note}"
        if tagged not in pending:
            pending.insert(0, tagged)
            mem.setdefault("待响应", {})["潜在关怀"] = pending[:6]
            all_mem[DEVICE_MAC] = json.dumps(mem, ensure_ascii=False)
            yaml.dump(all_mem, open(MEMORY_PATH, "w"), allow_unicode=True)
    except Exception:
        pass


async def _remind_later(conn, seconds: float, event: str):
    await asyncio.sleep(seconds)
    due = datetime.datetime.now().strftime("%H:%M")
    text = f"时间到啦！现在{due}，该{event}了哦！"
    try:
        stopped = getattr(conn, "stop_event", None)
        ws = getattr(conn, "websocket", None)
        if stopped is not None and stopped.is_set():
            raise RuntimeError("连接已关闭")
        if ws is None:
            raise RuntimeError("无连接")
        conn.client_abort = False
        sid = conn.sentence_id or uuid.uuid4().hex
        conn.tts.store_tts_text(sid, text)
        is_llm_intent = (conn.intent_type == "intent_llm")
        if is_llm_intent:
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(sentence_id=sid, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION)
            )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(sentence_id=sid, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=text)
        )
        if is_llm_intent:
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(sentence_id=sid, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION)
            )
    except Exception:
        _write_memory_note(f"{event}（{due} 到期，当时小智不在线没说上话）")


@register_function("set_reminder", set_reminder_function_desc, ToolType.SYSTEM_CTL)
async def set_reminder(conn: "ConnectionHandler", event: str, minutes: float = 0, at_time: str = ""):
    try:
        event = (event or "做的事").strip()
        delay_minutes = None
        at_time = str(at_time or "").strip()
        if ":" in at_time:
            # LLM 传到点时刻（加法不易错），服务器自己算时差
            try:
                hh, mm = at_time.split(":")[:2]
                due_dt = datetime.datetime.now().replace(hour=int(hh) % 24, minute=int(mm) % 60, second=0, microsecond=0)
                if due_dt <= datetime.datetime.now():
                    due_dt += datetime.timedelta(days=1)  # 已过则视为明天
                delay_minutes = (due_dt - datetime.datetime.now()).total_seconds() / 60
            except Exception:
                delay_minutes = None
        if delay_minutes is None:
            try:
                m = float(minutes)
                if m > 0:
                    delay_minutes = m
            except (TypeError, ValueError):
                delay_minutes = None
        if delay_minutes is None or delay_minutes <= 0:
            return ActionResponse(Action.RESPONSE, None, "提醒时间我没算明白，再说一次好吗？比如'十分钟后提醒我关火'")
        if delay_minutes < 0.2 or delay_minutes > 60 * 48:
            return ActionResponse(Action.RESPONSE, None, "提醒时间要在半分钟到两天之间哦")
        seconds = int(delay_minutes * 60)
        due = (datetime.datetime.now() + datetime.timedelta(seconds=seconds)).strftime("%H:%M")

        # 第一层：设备原生闹钟（断连也会响铃，屏幕显示事件名）
        alarm_ok = False
        try:
            mgr = conn.func_handler.tool_manager
            res = await mgr.execute_tool("self_alarm_set_alarm", {
                "seconds_from_now": seconds, "alarm_name": event[:20],
            })
            alarm_ok = bool(res and res.action not in (Action.NOTFOUND, Action.ERROR))
        except Exception:
            alarm_ok = False

        # 第二层：服务器定时（到点在线则语音播报具体事件；离线写记忆下次唤醒补提）
        task = asyncio.get_event_loop().create_task(_remind_later(conn, seconds, event))
        _REMINDER_TASKS.add(task)
        task.add_done_callback(_REMINDER_TASKS.discard)

        conn.logger.bind(tag=TAG).info(f"提醒已设: {delay_minutes:.1f}分钟后({due}) {event} at_time={at_time or '-'} 设备闹钟={alarm_ok}")
        say = f"好嘞，{due}我会提醒你{event}！"
        if not alarm_ok:
            say = f"好嘞，{due}提醒你{event}，到时候我会大声喊你的～"
        return ActionResponse(Action.RECORD, "reminder set", say)
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"set_reminder 错误: {e}")
        return ActionResponse(Action.RESPONSE, None, "设置提醒出了点问题，再试一次？")
