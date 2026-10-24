"""天气查询插件（open-meteo 免 key 版，替换原 qweather 实现）。"""

import httpx
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__

WMO_CODE_ZH = {
    0: "晴", 1: "大致晴朗", 2: "多云", 3: "阴", 45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "小阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}
WMO_CODE_EN = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain", 71: "slight snow",
    73: "moderate snow", 75: "heavy snow", 80: "rain showers", 95: "thunderstorm",
}

GET_WEATHER_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询某个城市的实时天气和今明两天预报。用户问天气时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "城市名，如'深圳'。不确定用户位置时传'深圳'",
                },
            },
            "required": ["location"],
        },
    },
}


def _desc(code: int, lang: str) -> str:
    zh = lang.startswith("zh")
    table = WMO_CODE_ZH if zh else WMO_CODE_EN
    return table.get(code, WMO_CODE_ZH.get(code, "未知") if zh else f"code {code}")


@register_function("get_weather", GET_WEATHER_FUNCTION_DESC, ToolType.SYSTEM_CTL)
async def get_weather(conn, location: str = "深圳", lang: str = "zh_CN"):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "zh" if lang.startswith("zh") else "en"},
            )
            results = geo.json().get("results") or []
            if not results:
                return ActionResponse(action=Action.RESPONSE, response=f"没找到「{location}」这个城市的天气呢")
            place = results[0]
            lat, lon = place["latitude"], place["longitude"]

            wx = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                    "forecast_days": 2, "timezone": "auto",
                },
            )
            data = wx.json()

        cur = data["current"]
        daily = data["daily"]
        zh = lang.startswith("zh")
        name = place.get("name", location)
        admin = place.get("admin1", "") or ""
        region = f"{admin}{name}" if zh and admin and admin not in name else name

        def day_line(i, prefix):
            code = daily["weather_code"][i]
            hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
            return f"{prefix}{_desc(code, lang)}，{lo:.0f}到{hi:.0f}度" if zh else \
                f"{prefix}{_desc(code, lang)}, {lo:.0f}-{hi:.0f}°C"

        if zh:
            text = (
                f"{region}现在{_desc(cur['weather_code'], lang)}，{cur['temperature_2m']:.0f}度，"
                f"湿度{cur['relative_humidity_2m']:.0f}%，风速{cur['wind_speed_10m']:.0f}公里每小时。"
                f"今天{day_line(0, '')}，明天{day_line(1, '')}。"
            )
        else:
            text = (
                f"{name}: now {_desc(cur['weather_code'], lang)}, {cur['temperature_2m']:.0f}°C, "
                f"humidity {cur['relative_humidity_2m']:.0f}%. Today {day_line(0, '')}. Tomorrow {day_line(1, '')}."
            )
        return ActionResponse(action=Action.REQLLM, result=text, response="")
    except Exception as e:
        return ActionResponse(action=Action.RESPONSE, response="天气查询出错了，稍后再试试")
