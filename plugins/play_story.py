"""讲故事插件：音源搜索儿童故事 → 下载 → TTS 队列推流到设备喇叭。

故事来源：酷我/网易云上丰富的儿童故事音频（宝宝巴士、睡前故事、童话等）。
"""

import os
import sys
import uuid
import asyncio

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (
    os.path.join(_HERE, "..", "..", "extras"),
    "/home/ubuntu/xiaozhi-esp32-server/main/xiaozhi-server/extras",
):
    _p = os.path.abspath(_p)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType

TAG = __name__

STORY_HINTS = ["故事", "睡前", "童话", "宝宝巴士", "凯叔", "儿童", "绘本", "哄睡", "童谣", "亲子"]
GOOD_STORY_BRANDS = ["宝宝巴士", "凯叔", "睡前故事", "儿童故事", "童话故事", "小伴龙", "亲宝", "贝瓦"]
BAD_KEYWORDS = ["KTV", "伴奏", "铃声", "翻唱", "DJ", "demo", "Demo", "提取", "加速", "变速",
                "试听", "会员", "VIP", "vip", "付费", "开通"]


def _real_duration(path: str) -> float:
    """ffprobe 实测音频时长（秒），失败返回 0。识破会员提示音/试听片段。"""
    import subprocess

    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, timeout=15,
        )
        return float(p.stdout.decode().strip()) if p.returncode == 0 else 0.0
    except Exception:
        return 0.0


def _score(song, theme: str) -> int:
    text = f"{song.title} {song.artist}"
    if any(k in text for k in BAD_KEYWORDS):
        return -100
    dur = getattr(song, "duration", 0) or 0
    score = 0
    if any(h in text for h in STORY_HINTS):
        score += 30
    if any(b in text for b in GOOD_STORY_BRANDS):
        score += 25
    if theme and theme in (song.title or ""):
        score += 20
    if dur >= 180:  # 故事通常 3 分钟以上
        score += 15
    elif 0 < dur < 75:  # 铃声/试听片段/会员提示音
        return -100
    return score


def _pick_prompt(title: str) -> str:
    import random

    return random.choice(
        [
            f"没问题！故事大王来啦～马上讲《{title}》，小耳朵竖起来咯！",
            f"好嘞，找一个舒服的姿势，《{title}》开始喽～",
            f"来啦来啦！今天的睡前故事是《{title}》，一起来听吧～",
        ]
    )


play_story_function_desc = {
    "type": "function",
    "function": {
        "name": "play_story",
        "description": (
            "当用户要求讲故事、听故事、睡前故事时调用（尤其对小朋友）。支持精准（'讲小红帽'→story_name=小红帽）"
            "和模糊（'讲个晚安的故事'→mood=晚安；'来个公主故事'→story_name=公主故事）两种需求，不要编造不存在的具体故事名"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "story_name": {
                    "type": "string",
                    "description": "故事主题或名字：具体故事（小红帽）或主题类别（公主/恐龙/小兔子），没指定传'睡前故事'",
                },
                "mood": {
                    "type": "string",
                    "description": "氛围：晚安/睡前/冒险/搞笑 等（用户说了想要的感觉时传）",
                },
            },
            "required": [],
        },
    },
}


@register_function("play_story", play_story_function_desc, ToolType.SYSTEM_CTL)
async def play_story(conn, story_name: str = "", mood: str = ""):
    try:
        from music_mcp.sources import manager
        import httpx

        theme = " ".join(filter(None, [(story_name or "").strip(), (mood or "").strip()])).strip() or "睡前故事"
        if theme == "random":
            theme = "睡前故事"

        # 多组搜索词，儿童故事资源命中率更高
        queries = [f"{theme} 故事", f"{theme} 睡前故事", f"儿童故事 {theme}"]
        candidates = []
        for q in queries[:2]:
            try:
                found = await manager.search(q, limit=8)
            except Exception:
                found = []
            for s in found:
                if s.song_id not in {c.song_id for c in candidates}:
                    candidates.append(s)
            if candidates:
                break

        scored = []
        for s in candidates:
            sc = _score(s, theme)
            if sc > -100:
                scored.append((sc, s))
        scored.sort(key=lambda x: -x[0])
        conn.logger.bind(tag=TAG).info(
            "选故事: " + "; ".join(f"[{sc}]{s.artist}-{s.title}" for sc, s in scored[:5]) or "无候选"
        )

        if not scored:
            return ActionResponse(
                action=Action.RESPONSE, result="not found",
                response=f"没找到「{theme}」的故事呢，换个故事名试试？比如小兔子、小红帽～",
            )

        last_err = None
        for sc, song in scored[:5]:
            try:
                play = await manager.resolve(song)
                if not play.url:
                    continue
                os.makedirs("tmp", exist_ok=True)
                path = os.path.join("tmp", f"story_{uuid.uuid4().hex[:8]}.mp3")
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
                    async with client.stream("GET", play.url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                        resp.raise_for_status()
                        with open(path, "wb") as f:
                            async for chunk in resp.aiter_bytes(65536):
                                f.write(chunk)
                if os.path.getsize(path) < 150_000:  # 故事应比 150KB 长
                    os.unlink(path)
                    continue
                # ffprobe 实测时长兜底：识破会员提示音/试听片段
                real_dur = await asyncio.to_thread(_real_duration, path)
                if real_dur < 60:
                    conn.logger.bind(tag=TAG).info(
                        f"淘汰疑似会员提示/试听片段: {song.title} ({real_dur:.0f}s)"
                    )
                    os.unlink(path)
                    continue
                text = _pick_prompt(song.title)
                conn.logger.bind(tag=TAG).info(f"播放故事: {song.artist} - {song.title} | {real_dur:.0f}s | {song.source_name} | {path}")
                try:
                    import json as _json
                    await conn.websocket.send(_json.dumps({
                        "type": "llm", "text": "😍", "emotion": "loving", "session_id": conn.session_id,
                    }))
                except Exception as e:
                    conn.logger.bind(tag=TAG).warning(f"发送故事表情失败: {e}")
                conn.tts.store_tts_text(conn.sentence_id, text)
                if conn.intent_type == "intent_llm":
                    conn.tts.tts_text_queue.put(
                        TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION)
                    )
                conn.tts.tts_text_queue.put(
                    TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=text)
                )
                conn.tts.tts_text_queue.put(
                    TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.FILE, content_file=os.path.abspath(path))
                )
                if conn.intent_type == "intent_llm":
                    conn.tts.tts_text_queue.put(
                        TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION)
                    )
                return ActionResponse(action=Action.RECORD, result="playing", response=text)
            except Exception as exc:
                last_err = exc
                conn.logger.bind(tag=TAG).warning(f"故事解析/下载失败 {getattr(song, 'title', '?')}: {exc}")

        return ActionResponse(action=Action.RESPONSE, result=f"failed: {last_err}",
                              response="故事加载有点问题，再说一次试试～")
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"故事插件错误: {e}")
        return ActionResponse(action=Action.RESPONSE, result=str(e), response="讲故事时出错了")
