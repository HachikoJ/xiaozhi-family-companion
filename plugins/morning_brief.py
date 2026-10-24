"""晨间简报插件：日期农历 + 天气 + 发文状态 + 育儿小贴士。"""

import json
import os
import random
import datetime
import httpx
import cnlunar
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
STATUS_FILE = "/home/ubuntu/xiaozhi-pipeline/status.json"
CITY = "深圳"
LAT, LON = 22.5455, 114.0683

TIPS = [
    "蒙氏小贴士：给孩子有限的选择而不是命令，比如问她想先刷牙还是先换睡衣",
    "蒙氏小贴士：两岁是秩序敏感期，固定的生活流程会让她更有安全感",
    "蒙氏小贴士：孩子专注玩的时候不打扰，就是在保护她的专注力",
    "蒙氏小贴士：让孩子参与家务，哪怕只是把袜子配对，都是成长",
    "蒙氏小贴士：多说「我看到你自己把玩具收好了」，少说「你真棒」",
    "蒙氏小贴士：户外活动每天至少一小时，大自然是最好的感官教室",
]

WMO = {0: "晴", 1: "大致晴朗", 2: "多云", 3: "阴", 45: "有雾", 48: "有雾",
       51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
       71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 81: "阵雨", 82: "强阵雨", 95: "雷阵雨"}

morning_brief_function_desc = {
    "type": "function",
    "function": {
        "name": "morning_brief",
        "description": "晨间简报。当用户说'早上好''早安''早安呀''来个晨报''今天有什么新鲜事'时调用，返回日期农历、天气、发文状态等信息供你播报。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _weather_text() -> str:
    try:
        r = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": LAT, "longitude": LON,
                    "current": "temperature_2m,weather_code", "daily": "temperature_2m_max,temperature_2m_min",
                    "forecast_days": 1, "timezone": "auto"},
            timeout=5,
        ).json()
        cur, daily = r["current"], r["daily"]
        desc = WMO.get(cur["weather_code"], "天气正常")
        return f"{CITY}现在{desc}，{cur['temperature_2m']:.0f}度，今天{daily['temperature_2m_min'][0]:.0f}到{daily['temperature_2m_max'][0]:.0f}度"
    except Exception:
        return "天气暂时没查到"


def _publish_text() -> str:
    try:
        st = json.load(open(STATUS_FILE))
        if st.get("date") == datetime.date.today().isoformat():
            if st.get("status") == "failed":
                return f"昨天的公众号发文失败了，原因是{st.get('reason', '未知')}"
            if st.get("status") == "draft_pushed":
                return f"公众号文章《{st.get('title', '')}》已经推到草稿箱，记得去后台发布哦"
        else:
            return "今天还没有发文的记录"
    except Exception:
        pass
    return ""


@register_function("morning_brief", morning_brief_function_desc, ToolType.WAIT)
def morning_brief():
    # 返回成品口播文本（RESPONSE 直接送 TTS，不依赖 LLM 组织，避免偷懒）
    now = datetime.datetime.now()
    lunar = cnlunar.Lunar(now, godType="8char")
    weekday = "一二三四五六日"[now.weekday()]
    parts = [
        f"今天是{now.year}年{now.month}月{now.day}日 星期{weekday}",
        f"农历{lunar.lunarMonthCn[:-1]}{lunar.lunarDayCn}",
        _weather_text(),
    ]
    pub = _publish_text()
    if pub:
        parts.append(pub)
    tip = random.choice(TIPS)
    text = ("早上好呀！" + parts[0] + "，" + parts[1] + "。" + parts[2] + "。")
    if len(parts) > 3:
        text += parts[3] + "。"
    text += " " + tip + "。祝全家今天开开心心！"
    return ActionResponse(Action.RESPONSE, None, text)
