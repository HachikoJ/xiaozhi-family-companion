"""小智轻量管理台 — 改提示词/音色/工具开关/看记忆/查状态。"""

import os
import subprocess
import json
import secrets
from functools import lru_cache
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from ruamel.yaml import YAML

CONFIG = "/home/ubuntu/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml"
MEMORY = "/home/ubuntu/xiaozhi-esp32-server/main/xiaozhi-server/data/.memory.yaml"
STATUS = "/home/ubuntu/xiaozhi-pipeline/status.json"
DEVICE_MAC = "AA:BB:CC:DD:EE:FF"

yaml = YAML()
yaml.preserve_quotes = True
app = FastAPI()


def _load():
    return yaml.load(open(CONFIG))


def _save(cfg):
    with open(CONFIG, "w") as f:
        yaml.dump(cfg, f)


def _restart_service():
    subprocess.run(["sudo", "-n", "systemctl", "restart", "xiaozhi-server"], timeout=60)


VOICES = {
    "zh-CN-XiaoyiNeural": "晓伊 · 活泼少女（当前人设推荐）",
    "zh-CN-XiaoxiaoNeural": "晓晓 · 标准女声",
    "zh-CN-XiaomoNeural": "晓墨 · 御姐",
    "zh-CN-XiaoxuanNeural": "晓萱 · 知性",
    "zh-CN-XiaohanNeural": "晓涵 · 温柔",
    "zh-CN-YunxiNeural": "云希 · 男声·阳光",
    "zh-CN-YunjianNeural": "云健 · 男声·沉稳",
    "zh-TW-HsiaoChenNeural": "曉臻 · 台湾腔（贴合人设）",
}

TOOLS = {
    "play_online_music": "在线音乐（原唱优先）",
    "play_story": "讲故事",
    "get_weather": "天气",
    "get_publish_status": "公众号发文查询",
    "start_pipeline": "语音触发一键发文",
}


class PromptIn(BaseModel):
    prompt: str


class VoiceIn(BaseModel):
    voice: str


class FunctionsIn(BaseModel):
    functions: List[str]


@app.get("/api/overview")
def overview():
    svc = subprocess.run(["systemctl", "is-active", "xiaozhi-server"], capture_output=True, text=True).stdout.strip()
    mem = subprocess.run(
        ["systemctl", "show", "xiaozhi-server", "-p", "MemoryCurrent"], capture_output=True, text=True
    ).stdout.strip().split("=")[-1]
    publish = {}
    if os.path.exists(STATUS):
        try:
            publish = json.load(open(STATUS))
        except Exception:
            pass
    cfg = _load()
    return {
        "service": svc,
        "memory_mb": round(int(mem or 0) / 1048576),
        "voice": cfg.get("TTS", {}).get("EdgeTTS", {}).get("voice", ""),
        "functions": cfg.get("Intent", {}).get("intent_llm", {}).get("functions", []),
        "publish": publish,
        "uptime": subprocess.run(["uptime", "-p"], capture_output=True, text=True).stdout.strip(),
    }


@app.get("/api/prompt")
def get_prompt():
    return {"prompt": _load().get("prompt", "")}


@app.post("/api/prompt")
def set_prompt(body: PromptIn):
    if len(body.prompt.strip()) < 50:
        raise HTTPException(400, "提示词太短（至少50字）")
    cfg = _load()
    cfg["prompt"] = body.prompt.strip()
    _save(cfg)
    _restart_service()
    return {"ok": True, "len": len(cfg["prompt"])}


@app.post("/api/voice")
def set_voice(body: VoiceIn):
    if body.voice not in VOICES:
        raise HTTPException(400, "未知音色")
    cfg = _load()
    cfg.setdefault("TTS", {}).setdefault("EdgeTTS", {})["voice"] = body.voice
    _save(cfg)
    _restart_service()
    return {"ok": True, "voice": body.voice}


@app.post("/api/functions")
def set_functions(body: FunctionsIn):
    unknown = [f for f in body.functions if f not in TOOLS]
    if unknown:
        raise HTTPException(400, f"未知工具: {unknown}")
    cfg = _load()
    cfg["Intent"]["intent_llm"]["functions"] = body.functions
    _save(cfg)
    _restart_service()
    return {"ok": True, "functions": body.functions}



@app.get("/api/morning-context")
def morning_context():
    """context_provider 每轮拉取：上午窗口内当日首次返回播报指令，之后返回空。"""
    import datetime
    now = datetime.datetime.now()
    flag = f"/tmp/morning_flag_{now.date()}"
    hour = now.hour
    data = {"当前时间": now.strftime("%Y-%m-%d %H:%M 星期") + "一二三四五六日"[now.weekday()]}
    if 5 <= hour < 13 and not os.path.exists(flag):
        open(flag, "w").write(now.isoformat())
        data["晨间任务"] = ("现在是早晨，如果本次对话你还没有说过早安，请先热情地向爸爸一家问早安，"
                          "并调用 morning_brief 工具获取今日晨报播报给全家人。已经说过就不要重复播报。")
    return {"code": 0, "data": data}


@app.get("/api/memory")
def get_memory():
    if not os.path.exists(MEMORY):
        return {"memory": None}
    data = yaml.safe_load(open(MEMORY)) or {}
    raw = data.get(DEVICE_MAC)
    if not raw:
        return {"memory": None}
    try:
        return {"memory": json.loads(raw) if isinstance(raw, str) else raw}
    except Exception:
        return {"memory": {"raw": str(raw)[:3000]}}


@app.post("/api/memory/clear")
def clear_memory():
    if os.path.exists(MEMORY):
        data = yaml.safe_load(open(MEMORY)) or {}
        data.pop(DEVICE_MAC, None)
        yaml.dump(data, open(MEMORY, "w"), allow_unicode=True)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>小智管理台</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'PingFang SC',sans-serif;background:#0e1a33;color:#e8ecf4;padding:24px;max-width:860px;margin:0 auto}
h1{font-size:20px;margin-bottom:4px} .sub{color:#7c8aa5;font-size:12px;margin-bottom:20px}
.card{background:#152242;border-radius:12px;padding:16px;margin-bottom:16px}
.card h2{font-size:14px;color:#38d6ac;margin-bottom:12px}
textarea{width:100%;height:320px;background:#0b1428;color:#dfe6f2;border:1px solid #2a3a5f;border-radius:8px;padding:12px;font-size:13px;line-height:1.7;font-family:inherit}
select,button{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:8px 16px;font-size:13px;cursor:pointer;margin-top:10px}
button.warn{background:#e84c3d} button.ghost{background:#2a3a5f}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.badge{display:inline-block;background:#1c2b52;border-radius:6px;padding:4px 10px;font-size:12px;margin:2px}
.badge.on{background:#123c2e;color:#38d6ac;border:1px solid #1e8e5a}
.badge.off{opacity:.45;cursor:pointer}
.badge.on{cursor:pointer}
pre{background:#0b1428;border-radius:8px;padding:12px;font-size:12px;line-height:1.6;overflow:auto;max-height:340px;color:#a8c0e0}
.msg{color:#38d6ac;font-size:12px;margin-left:10px}
.kv{font-size:13px;line-height:2}.kv b{color:#d4a017}
</style></head><body>
<h1>🤖 小智管理台</h1><div class="sub" id="ov"></div>

<div class="card"><h2>▎人设提示词</h2>
<textarea id="prompt"></textarea>
<div class="row"><button onclick="savePrompt()">保存并重启生效</button><span class="msg" id="msgP"></span></div></div>

<div class="card"><h2>▎音色</h2><div class="row">
<select id="voice"></select><button onclick="saveVoice()">切换</button><span class="msg" id="msgV"></span></div></div>

<div class="card"><h2>▎语音技能开关</h2><div id="fns"></div>
<div class="row"><button onclick="saveFns()">保存</button><span class="msg" id="msgF"></span></div></div>

<div class="card"><h2>▎小智的记忆</h2><pre id="mem"></pre>
<div class="row"><button class="warn" onclick="clearMem()">清空记忆</button><span class="msg" id="msgM"></span></div></div>

<script>
async function init(){
 const o=await (await fetch('/api/overview')).json();
 document.getElementById('ov').innerHTML=`服务 <b style="color:${o.service==='active'?'#38d6ac':'#e84c3d'}">${o.service}</b> · 内存 ${o.memory_mb}MB · ${o.uptime}<br>发文状态：${o.publish.title?`《${o.publish.title}》 ${o.publish.status} @ ${o.publish.published_at}`:'暂无'}`;
 const p=await (await fetch('/api/prompt')).json();
 document.getElementById('prompt').value=p.prompt;
 const sel=document.getElementById('voice');
 (await (await fetch('/__voices').catch(()=>({}))));
}
const VOICES={"zh-CN-XiaoyiNeural":"晓伊·活泼少女（推荐）","zh-CN-XiaoxiaoNeural":"晓晓·标准女声","zh-CN-XiaoxuanNeural":"晓萱·知性","zh-CN-XiaoxiaoNeural":"晓晓","zh-CN-XiaomoNeural":"晓墨·御姐","zh-CN-YunxiNeural":"云希·男声阳光","zh-CN-YunjianNeural":"云健·男声沉稳","zh-TW-HsiaoChenNeural":"曉臻·台湾腔"};
const TOOLS={"play_online_music":"在线音乐","play_story":"讲故事","get_weather":"天气","get_publish_status":"发文查询","start_pipeline":"语音触发发文"};
async function loadAll(){
 const o=await (await fetch('/api/overview')).json();
 document.getElementById('ov').innerHTML=`服务 <b style="color:${o.service==='active'?'#38d6ac':'#e84c3d'}">${o.service}</b> · 内存 ${o.memory_mb}MB<br>发文：${o.publish.title?('《'+o.publish.title+'》 '+o.publish.status+' @ '+o.publish.published_at):'暂无'} · ${o.uptime}`;
 const p=await (await fetch('/api/prompt')).json();document.getElementById('prompt').value=p.prompt;
 const sel=document.getElementById('voice');sel.innerHTML=Object.entries(VOICES).map(([k,v])=>`<option value="${k}" ${k===o.voice?'selected':''}>${v}</option>`).join('');
 const fn=document.getElementById('fns');fn.innerHTML=Object.entries(TOOLS).map(([k,v])=>`<span class="badge ${o.functions.includes(k)?'on':'off'}" onclick="this.classList.toggle('on');this.classList.toggle('off')" data-k="${k}">${v}</span>`).join('');
 const m=await (await fetch('/api/memory')).json();
 document.getElementById('mem').textContent=m.memory?JSON.stringify(m.memory,null,2):'（暂无记忆）';
}
async function savePrompt(){const r=await fetch('/api/prompt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:document.getElementById('prompt').value})});const j=await r.json();document.getElementById('msgP').textContent=r.ok?'✅ 已保存并重启':'❌ '+(j.detail||'失败');setTimeout(loadAll,9000)}
async function saveVoice(){const r=await fetch('/api/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:document.getElementById('voice').value})});document.getElementById('msgV').textContent=r.ok?'✅ 已切换':'❌ 失败';setTimeout(loadAll,9000)}
async function saveFns(){const fns=[...document.querySelectorAll('.badge.on')].map(x=>x.dataset.k);const r=await fetch('/api/functions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({functions:fns})});document.getElementById('msgF').textContent=r.ok?'✅ 已保存':'❌ 失败';setTimeout(loadAll,9000)}
async function clearMem(){if(!confirm('确定清空小智的全部记忆？'))return;await fetch('/api/memory/clear',{method:'POST'});document.getElementById('msgM').textContent='✅ 已清空';loadAll()}
loadAll();
</script></body></html>"""
