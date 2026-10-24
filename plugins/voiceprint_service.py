"""声纹识别服务 — 对标 xiaozhi-esp32-server voiceprint 协议。

接口：
  GET  /voiceprint/health?key=xxx          → {"status":"healthy"}
  POST /voiceprint/enroll?key=xxx          → form: speaker_id, file(wav) 注册声纹
  POST /voiceprint/identify?key=xxx        → form: speaker_ids(a,b,c), file(wav)
                                            → {"speaker_id": best 或 "", "score": cos}
模型：3dspeaker campplus (sherpa-onnx, 192-dim, CPU)
"""

import os
import subprocess
import numpy as np
import shutil
import tempfile
from typing import List, Tuple
from fastapi import FastAPI, File, Form, Header, UploadFile, HTTPException
import sherpa_onnx

MODEL = os.environ.get("VP_MODEL", "/home/ubuntu/xiaozhi-voiceprint/campplus.onnx")
EMB_DIR = os.environ.get("VP_EMB_DIR", "/home/ubuntu/xiaozhi-voiceprint/embeddings")
API_KEY = os.environ.get("VP_KEY", "change-me-voiceprint-key")

app = FastAPI()
_ext = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=1, provider="cpu")
)
_mgr = sherpa_onnx.SpeakerEmbeddingManager(_ext.dim)
os.makedirs(EMB_DIR, exist_ok=True)


def _wav_to_samples(path: str) -> np.ndarray:
    """任意音频 → 16k mono float32 采样。"""
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ar", "16000", "-ac", "1", "-"],
        capture_output=True, timeout=30,
    )
    if p.returncode != 0 or not p.stdout:
        raise ValueError(f"ffmpeg 解码失败: {p.stderr[:200]}")
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _embed(samples: np.ndarray) -> np.ndarray:
    if len(samples) < 16000:  # <1s 拒绝
        raise ValueError("音频太短（<1秒），声纹无法提取")
    stream = _ext.create_stream()
    stream.accept_waveform(16000, samples)
    stream.input_finished()
    emb = np.asarray(_ext.compute(stream), dtype=np.float32)
    if emb.size != _ext.dim:
        raise ValueError("embedding 计算失败")
    return emb


def _load_all():
    """启动时从磁盘恢复所有注册声纹（同名多条取平均后注册）。"""
    by_speaker = {}
    for fn in sorted(os.listdir(EMB_DIR)):
        if fn.endswith(".npy"):
            sid = fn.rsplit("_", 1)[0]
            by_speaker.setdefault(sid, []).append(np.load(os.path.join(EMB_DIR, fn)))
    for sid, embs in by_speaker.items():
        _mgr.add(sid, np.mean(embs, axis=0))
    return {k: len(v) for k, v in by_speaker.items()}


def _require_key(key: str):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid key")


def _key_from(auth_header: str, fallback: str = "") -> str:
    """兼容 Authorization: Bearer xxx 与表单/query key 两种认证。"""
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return fallback


@app.get("/voiceprint/health")
def health(key: str = ""):
    _require_key(key)
    return {"status": "healthy", "speakers": _mgr.num_speakers}


@app.post("/voiceprint/enroll")
async def enroll(authorization: str = Header(""), key: str = Form(""), speaker_id: str = Form(...), file: UploadFile = File(...)):
    _require_key(_key_from(authorization, key))
    sid = speaker_id.strip()
    if not sid or not sid.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "speaker_id 仅限字母数字")
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        emb = _embed(_wav_to_samples(tmp))
    finally:
        os.unlink(tmp)
    idx = len([x for x in os.listdir(EMB_DIR) if x.startswith(f"{sid}_")]) + 1
    np.save(os.path.join(EMB_DIR, f"{sid}_{idx}.npy"), emb)
    # 重新平均注册
    embs = [np.load(os.path.join(EMB_DIR, x)) for x in sorted(os.listdir(EMB_DIR)) if x.startswith(f"{sid}_")]
    if sid in _mgr.all_speakers:
        _mgr.remove(sid)
    _mgr.add(sid, np.mean(embs, axis=0))
    return {"success": True, "speaker_id": sid, "samples": len(embs)}


@app.post("/voiceprint/identify")
async def identify(authorization: str = Header(""), key: str = Form(""), speaker_ids: str = Form(""), file: UploadFile = File(...)):
    _require_key(_key_from(authorization, key))
    candidates = [s.strip() for s in speaker_ids.split(",") if s.strip() and s.strip() in _mgr.all_speakers]
    if not candidates:
        return {"speaker_id": "", "score": 0.0}
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        emb = _embed(_wav_to_samples(tmp))
    except ValueError as e:
        return {"speaker_id": "", "score": 0.0, "error": str(e)}
    finally:
        os.unlink(tmp)
    best_id, best_score = "", 0.0
    for sid in candidates:
        score = float(_mgr.score(sid, emb))
        if score > best_score:
            best_id, best_score = sid, score
    return {"speaker_id": best_id if best_score > 0.0 else "", "score": round(best_score, 4)}


loaded = _load_all()
print(f"voiceprint service ready: model={MODEL} dim={_ext.dim} speakers={loaded}")
