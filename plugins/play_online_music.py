"""在线音乐点播插件：免费音源搜索 → 下载 → 通过 TTS 队列推流到设备喇叭。

选歌策略：严格优先原唱版本，过滤 KTV/伴奏/Live/翻唱/铃声等杂版本。
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

# 标题/歌手里出现这些词的版本视为"乱七八糟版本"
BAD_KEYWORDS = [
    "KTV", "伴奏", "Live", "live", "現場", "现场", "演唱会", "音质", "翻唱", "翻唱版",
    "铃声", "抖腿", "DJ版", "dj版", "加快版", "降调", "变速", "demo", "Demo", "DEMO",
    "清唱", "自制", "试听", "片段", "cut", "Cover", "cover", "cover版", "吉他版",
    "钢琴版", "八音盒", "铃声版", "提取", "伴奏版", "backing",
    "会员", "VIP", "vip", "付费", "完整版需", "开通",
    "合唱", "对唱", "嘉宾", "串烧", "remix", "Remix", "REMIX", "翻自", "致敬", "模仿秀",
]
# 儿歌场景常见的正规发行方（加分）
GOOD_ARTIST_HINTS = ["宝宝巴士", "贝瓦", "小伴龙", "儿歌", "童谣", "亲宝", "智慧树", "变形警车", "小猪佩奇"]


def _bad(text: str) -> bool:
    return any(k in text for k in BAD_KEYWORDS)


def _real_duration(path: str) -> float:
    """ffprobe 实测音频时长（秒），失败返回 0。用于识破会员提示音/试听片段。"""
    import subprocess

    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, timeout=15,
        )
        return float(p.stdout.decode().strip()) if p.returncode == 0 else 0.0
    except Exception:
        return 0.0


def _strip_title(t: str) -> str:
    """剥掉标题里的括号副标题（含中英文括号），保留主标题。"""
    import re
    return re.sub(r'[（(【\[][^）)】\]]*[）)】\]]', '', t or '').strip()


def _score(song, song_name: str, artist_hint: str) -> int:
    """原版原唱严格打分，负分直接淘汰。盗版/蹭名/合唱/翻唱一律出局。"""
    title = f"{song.title} {song.artist}"
    if _bad(title):
        return -100
    dur = getattr(song, "duration", 0) or 0
    if 0 < dur < 90:  # 铃声/试听片段/会员提示音（多数 30-60 秒）
        return -100

    artist = (song.artist or '').strip()
    bare_title = _strip_title(song.title or '')

    # 歌手必须是本尊：蹭名合唱（"李鑫一&周杰伦"）直接出局
    if artist_hint:
        if artist == artist_hint or artist.startswith(artist_hint):
            artist_is_origin = True
        elif artist_hint in artist and ('&' in artist or 'feat' in artist.lower() or '、' in artist or '+' in artist):
            return -100  # 含本尊但与他人合唱 = 蹭名版
        elif artist_hint in artist:
            artist_is_origin = True
        else:
            artist_is_origin = False
    else:
        artist_is_origin = True  # 未指定歌手则不强卡

    # 标题剥壳后必须就是这首歌（剥掉"(Live版)"等副标题后的真身）
    title_is_song = bool(song_name) and bare_title == song_name

    score = 0
    if artist_is_origin and artist_hint:
        score += 60
    if title_is_song:
        score += 40
    elif song_name and song_name in (song.title or ""):
        score += 10  # 只有关键词包含（可能是串烧/同名蹭）弱加分
    if not artist_is_origin:
        score -= 80  # 不是本尊 → 几乎不可能当选
    if any(h in artist for h in GOOD_ARTIST_HINTS):
        score += 10  # 正规儿歌发行方
    if dur >= 180:
        score += 10
    return score


def _parse_query(song_name: str):
    """把 '周杰伦 晴天' 拆成 (artist_hint, 纯歌名)。"""
    parts = (song_name or "").strip().split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", (parts[0] if parts else "")


VAGUE_HINTS = {
    "舒缓": "轻音乐 放松", "安静": "安静 轻音乐", "轻音乐": "轻音乐 纯音乐",
    "欢快": "欢快 儿歌", "快乐": "欢快 儿歌", "睡前": "摇篮曲", "摇篮": "摇篮曲",
    "助眠": "白噪音 助眠", "白噪音": "白噪音 雨声", "儿歌": "儿歌 童谣",
    "钢琴": "钢琴曲 轻音乐", "流行": "流行 热门", "经典": "经典 老歌", "英文": "英文 儿歌",
    "随便": "热门 轻音乐", "任意": "热门 轻音乐", "轻松": "轻音乐 放松", "开心": "欢快 儿歌",
}
_FALLBACK_QUERY = "热门 轻音乐"


def _vague_score(song, want_words):
    """模糊场景打分：贴合想要的氛围即可，不卡原版。"""
    text = f"{song.title} {song.artist}"
    if _bad(text):
        return -100
    dur = getattr(song, "duration", 0) or 0
    if 0 < dur < 90:
        return -100
    score = 5
    for w in want_words:
        if w in text:
            score += 20
    if any(h in (song.artist or "") for h in GOOD_ARTIST_HINTS):
        score += 25  # 儿歌/轻音乐正规发行方
    if 120 <= dur <= 480:
        score += 10
    return score


play_online_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_online_music",
        "description": (
            "当用户要求播放音乐、歌曲、儿歌时调用。支持两种需求："
            "①精准点播（用户说了具体歌名）→ 传 song_name（最好带歌手，如'周杰伦 晴天'）；"
            "②模糊氛围需求（用户没说歌名，只说风格/情绪/品类/歌手，如'来点舒缓的轻音乐''欢快的儿歌'"
            "'放首周杰伦的歌''随便来点音乐'）→ 传 mood/genre/artist 参数，不要编造歌名"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "具体歌名（用户明确说了歌名才传，如'晴天'或'周杰伦 晴天'）",
                },
                "mood": {
                    "type": "string",
                    "description": "氛围情绪：舒缓/安静/欢快/睡前/助眠 等（模糊需求时传）",
                },
                "genre": {
                    "type": "string",
                    "description": "品类：轻音乐/儿歌/摇篮曲/白噪音/钢琴曲/流行 等（模糊需求时传）",
                },
                "artist": {
                    "type": "string",
                    "description": "歌手泛需求（'来首周杰伦的歌'→artist=周杰伦，没指定歌名）",
                },
            },
            "required": [],
        },
    },
}


async def _download_to_tmp(url: str) -> str:
    import httpx

    os.makedirs("tmp", exist_ok=True)
    path = os.path.join("tmp", f"online_music_{uuid.uuid4().hex[:8]}.mp3")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
        async with client.stream("GET", url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    f.write(chunk)
    return path


def _pick_prompt(title: str) -> str:
    import random

    return random.choice(
        [
            f"好嘞！音乐小精灵，快为我们唱一首《{title}》吧！",
            f"来啦来啦，一起听《{title}》！",
            f"马上放，《{title}》，小耳朵准备好咯～",
        ]
    )


async def _push_audio_file(conn, path: str, speak_text: str, emoji: str = "🙂", emotion: str = "happy"):
    try:
        import json as _json
        await conn.websocket.send(_json.dumps({
            "type": "llm", "text": emoji, "emotion": emotion, "session_id": conn.session_id,
        }))
    except Exception as e:
        conn.logger.bind(tag=TAG).warning(f"发送音乐表情失败: {e}")
    conn.tts.store_tts_text(conn.sentence_id, speak_text)
    if conn.intent_type == "intent_llm":
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION)
        )
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=speak_text)
    )
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.FILE, content_file=os.path.abspath(path))
    )
    if conn.intent_type == "intent_llm":
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION)
        )


_CHAIN_TASKS = set()
CHAIN_MAX = 10  # 功耗保护：最多连播 10 首


def _chain_stopped(conn, sid0: str) -> bool:
    stopped = getattr(conn, "stop_event", None)
    return (stopped is not None and stopped.is_set()) or conn.sentence_id != sid0


async def _chain_play(conn, query: str, want_words, played: set, sid0: str, count: int, wait_s: float):
    """连播链：当前歌播完自动接同类下一首（不重复）；打断/断连/满10首自动停。"""
    import random
    import time as _time

    async def _wait(seconds):
        deadline = _time.monotonic() + seconds
        while _time.monotonic() < deadline:
            if _chain_stopped(conn, sid0):
                return False
            await asyncio.sleep(2)
        return not _chain_stopped(conn, sid0)

    try:
        while count < CHAIN_MAX:
            if not await _wait(wait_s):
                conn.logger.bind(tag=TAG).info(f"连播停止于第{count}首后（打断/断连）")
                return
            from music_mcp.sources import manager
            songs = await manager.search(query, limit=12)
            scored = sorted(
                [t for t in ((_vague_score(s, want_words), s) for s in songs)
                 if t[0] > 0 and t[1].title not in played],
                key=lambda x: -x[0])
            if not scored:
                conn.logger.bind(tag=TAG).info("连播无新候选，结束")
                return
            _, song = random.choice(scored[:4])
            try:
                play = await manager.resolve(song)
                if not play.url:
                    played.add(song.title)
                    continue
                path = await _download_to_tmp(play.url)
                real_dur = await asyncio.to_thread(_real_duration, path)
                if real_dur < 80:
                    os.unlink(path)
                    played.add(song.title)
                    continue
                played.add(song.title)
                count += 1
                conn.logger.bind(tag=TAG).info(f"连播第{count}首: {song.artist} - {song.title} ({real_dur:.0f}s)")
                await _push_audio_file(conn, path, f"继续听《{song.title}》", emoji="😌", emotion="relaxed")
                wait_s = real_dur + 2
            except Exception as exc:
                conn.logger.bind(tag=TAG).warning(f"连播该首失败: {getattr(song, 'title', '?')}: {exc}")
                played.add(getattr(song, 'title', ''))
                continue
    except asyncio.CancelledError:
        pass


@register_function("play_online_music", play_online_music_function_desc, ToolType.SYSTEM_CTL)
async def play_online_music(conn, song_name: str = "", mood: str = "", genre: str = "", artist: str = ""):
    try:
        from music_mcp.sources import manager

        song_name = (song_name or "").strip()
        mood = (mood or "").strip()
        genre = (genre or "").strip()
        artist = (artist or "").strip()
        vague = not song_name and (mood or genre or artist)

        if not song_name and not vague:
            return ActionResponse(action=Action.RESPONSE, result="no song", response="想听什么歌呀？说歌名，或者说想要的感觉，比如来点轻音乐～")

        # ===== 模糊模式：氛围/品类/歌手泛需求 =====
        if vague:
            want_words = [mood, genre] if (mood or genre) else []
            if mood and mood in VAGUE_HINTS:
                want_words = VAGUE_HINTS[mood].split()
            elif genre:
                hint = VAGUE_HINTS.get(genre, genre)
                want_words = hint.split() + ([mood] if mood else [])
            query = " ".join(filter(None, [
                (VAGUE_HINTS.get(mood, mood) if mood else ""),
                (VAGUE_HINTS.get(genre, genre) if genre else ""),
                artist,
            ])) or "热门 轻音乐"
            songs = await manager.search(query, limit=10)
            scored = sorted([(_vague_score(s, want_words or query.split()), s) for s in songs], key=lambda x: -x[0])
            scored = [t for t in scored if t[0] > 0]
            conn.logger.bind(tag=TAG).info(f"模糊选歌[{query}]: " + "; ".join(f"[{sc}]{s.artist}-{s.title}" for sc, s in scored[:4]))
            if not scored:
                return ActionResponse(action=Action.RESPONSE, result="vague empty", response="这个没找到合适的呢，换个说法试试？")
            import random as _r
            for _, song in _r.sample(scored[:3], k=min(3, len(scored))):  # 头部乱序逐个尝试
                try:
                    play = await manager.resolve(song)
                    if not play.url:
                        continue
                    path = await _download_to_tmp(play.url)
                    real_dur = await asyncio.to_thread(_real_duration, path)
                    if real_dur < 80:
                        os.unlink(path)
                        continue
                    text = _pick_prompt(song.title)
                    await _push_audio_file(conn, path, text, emoji="😌", emotion="relaxed")
                    # 连播链：同类歌曲自动接龙（打断即停，上限10首）
                    task = asyncio.get_event_loop().create_task(
                        _chain_play(conn, query, want_words or query.split(),
                                    {song.title}, conn.sentence_id, 1, real_dur + 2))
                    _CHAIN_TASKS.add(task)
                    task.add_done_callback(_CHAIN_TASKS.discard)
                    return ActionResponse(action=Action.RECORD, result="playing", response=text)
                except Exception as exc:
                    conn.logger.bind(tag=TAG).warning(f"模糊模式该首失败: {getattr(song, 'title', '?')}: {exc}")
                    continue
            return ActionResponse(action=Action.RESPONSE, result="vague failed", response="这首没放出来，再说一次我换一首～")

        # ===== 精准模式（原版严格过滤） =====

        artist_hint, pure_name = _parse_query(song_name)
        songs = await manager.search(song_name, limit=10)
        if not songs:
            return ActionResponse(action=Action.RESPONSE, result="not found",
                                  response=f"没有找到「{song_name}」，换个歌名试试？")

        # 原唱优先：过滤+打分排序
        scored = []
        for s in songs:
            sc = _score(s, pure_name, artist_hint)
            if sc > -100:
                scored.append((sc, s))
        scored.sort(key=lambda x: -x[0])
        conn.logger.bind(tag=TAG).info(
            "选歌: " + "; ".join(f"[{sc}]{s.artist}-{s.title}" for sc, s in scored[:5]) or "全部被过滤"
        )

        if not scored or scored[0][0] < 40:
            return ActionResponse(
                action=Action.RESPONSE, result="no original version",
                response="这首歌的原版暂时拿不到（多半需要音乐会员），翻唱伴奏版我就不放啦。换一首试试？",
            )

        last_err = None
        for sc, song in scored[:5]:
            if pure_name and pure_name not in _strip_title(song.title or ''):
                continue  # 候选必须是同一首歌，不放搜索推荐里的别的歌
            try:
                play = await manager.resolve(song)
                if not play.url:
                    continue
                path = await _download_to_tmp(play.url)
                # 双重校验：文件大小 + ffprobe 实测时长（识破会员提示音/试听片段）
                real_dur = await asyncio.to_thread(_real_duration, path) if os.path.getsize(path) >= 100_000 else 0.0
                if os.path.getsize(path) < 100_000 or real_dur < 80:
                    conn.logger.bind(tag=TAG).info(
                        f"淘汰疑似会员提示/试听片段: {song.title} ({real_dur:.0f}s, {os.path.getsize(path)//1024}KB)"
                    )
                    os.unlink(path)
                    continue
                text = _pick_prompt(song.title)
                conn.logger.bind(tag=TAG).info(f"在线音乐(原唱优先): {song.artist} - {song.title} | {real_dur:.0f}s | {song.source_name} | {path}")
                await _push_audio_file(conn, path, text, emoji="😌", emotion="relaxed")
                return ActionResponse(action=Action.RECORD, result="playing", response=text)
            except Exception as exc:
                last_err = exc
                conn.logger.bind(tag=TAG).warning(f"解析/下载失败 {getattr(song, 'title', '?')}: {exc}")

        return ActionResponse(action=Action.RESPONSE, result=f"failed: {last_err}",
                              response="这首歌暂时放不了，换一首试试吧～")
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"在线音乐插件错误: {e}")
        return ActionResponse(action=Action.RESPONSE, result=str(e), response="播放音乐时出错了")
