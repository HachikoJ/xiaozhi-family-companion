"""模拟小智设备全链路对话：发语音"播放周杰伦的晴天"，验证 ASR→LLM→音乐插件→opus 推流。"""
import asyncio, json, sys, time
import websockets
from opuslib_next import Encoder as OpusEncoder
from opuslib_next.constants import APPLICATION_VOIP

URI = "wss://xiaozhi.example.com/xiaozhi/v1/"
PCM_PATH = "/tmp/test_voice.pcm"

encoder = OpusEncoder(16000, 1, APPLICATION_VOIP)
encoder.bitrate = 32000


def load_opus_frames():
    pcm = open(PCM_PATH, "rb").read()
    frames = []
    step = 960 * 2  # 60ms @16k mono s16le
    for i in range(0, len(pcm) - step + 1, step):
        frames.append(encoder.encode(pcm[i:i + step], 960))
    return frames


async def main():
    frames = load_opus_frames()
    print(f"opus frames: {len(frames)} ({len(frames)*0.06:.1f}s)")
    async with websockets.connect(URI, max_size=2**22, proxy=None,
                                  additional_headers={"device-id": "12:34:56:78:9A:BC"}) as ws:
        await ws.send(json.dumps({
            "type": "hello", "version": 1, "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
        }))
        hello = json.loads(await ws.recv())
        print("<< hello, session:", hello.get("session_id", "")[:8])

        await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "auto"}))
        for i, f in enumerate(frames):
            await ws.send(f)
            await asyncio.sleep(0.06)
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))
        print(">> voice sent, waiting server response...")

        audio_bytes = 0
        deadline = time.time() + 90
        saw_stt = saw_tts_start = False
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), 10)
            except asyncio.TimeoutError:
                print("(idle 10s, ending)")
                break
            if isinstance(raw, bytes):
                audio_bytes += len(raw)
                continue
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "stt":
                saw_stt = True
                print(f"<< STT: {msg.get('text')}")
            elif t == "llm":
                print(f"<< LLM emotion={msg.get('emotion')} text={str(msg.get('text'))[:60]}")
            elif t == "tts":
                state = msg.get("state")
                if state == "start":
                    saw_tts_start = True
                    print("<< TTS start")
                elif state == "stop":
                    print(f"<< TTS stop  (audio received: {audio_bytes//1024} KB)")
                    break
            elif t == "goodbye":
                print("<< goodbye:", msg.get("reason"))
                break
            else:
                print("<<", t, str(msg)[:120])

        print(f"\nRESULT: stt={saw_stt} tts={saw_tts_start} audio={audio_bytes} bytes")

asyncio.run(main())
