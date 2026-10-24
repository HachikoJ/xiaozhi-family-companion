# 🤖 XiaoZhi Family Companion — 小智家庭伴侣服务器

> 把一台 ESP32 小智音箱，改造成懂全家的育儿语音伴侣：会讲故事、放儿歌、认家人声纹、记得住事、能定提醒，还能跟你 Mac 上的自动化流水线联动。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Linux%20server%20%2B%20ESP32-orange)
![Cost](https://img.shields.io/badge/monthly%20cost-¥0-success)

## ✨ 它能做什么

| 能力 | 说明 |
|------|------|
| 🎵 在线音乐·双模式 | 精准点播走「严格原版过滤」（盗版/伴奏/蹭名合唱一律出局）；模糊需求（"来点欢快的儿歌"）走氛围理解，**自动连播同类歌曲，最多 10 首，打断即停** |
| 📖 讲故事 | 宝宝巴士等正版儿童故事音频，支持"讲个小白兔的故事"和"讲个晚安的故事"两类说法 |
| 🗣️ 声纹识人 | 本地 campplus 声纹模型（15ms/次），认出爸爸/妈妈/奶奶/宝宝自动切换对话人设 |
| 🧠 家庭记忆 | 本地长期记忆（身份图谱/高光语录/潜在关怀），越用越懂你家，数据不出服务器 |
| ⏰ 语音提醒 | "一分钟后提醒我关火"→ 设备闹钟（离线也响）+ 服务器准点语音 + 记忆兜底三层保障 |
| 🌤️ 晨间简报 | 每天第一次唤醒自动播报：日期农历 + 天气 + 你的自动化任务状态 + 育儿小贴士 |
| 📰 自动化联动 | 语音触发「一键发文」，Mac 无人值守跑完整内容流水线，结束后音箱播报结果 |
| 🛠️ Web 管理台 | 在线改人设提示词 / 切音色 / 开关技能 / 看记忆，保存即生效 |
| ✋ 全双工打断 | 说话即打断（0.01s 响应），音乐故事随时切 |

**全程零月费**：ASR（本地 sherpa-onnx）+ VAD（silero）+ TTS（EdgeTTS）+ LLM（智谱 glm-4-flash 免费档）。

## 🏗️ 架构

```
ESP32 小智音箱（原厂固件即可，无需刷机）
   │  wss (Nginx 443 反代)
   ▼
┌─────────────────── 你的云服务器 ───────────────────┐
│  xiaozhi-server（对话核心，本项目适配层）           │
│   ├── 插件: play_online_music / play_story /       │
│   │         set_reminder / morning_brief / ...     │
│   ├── 声纹服务 (campplus, FastAPI)                 │
│   ├── 管理台 (FastAPI + BasicAuth)                 │
│   └── 记忆 (data/.memory.yaml)                     │
│  轮询器：SSH 拉取「一键发文」任务 → Mac 执行 → 回传  │
└────────────────────────────────────────────────────┘
```

## 🚀 快速开始

> 前提：一台 2GB+ 内存的 Linux 服务器（Ubuntu 22.04+ 测试通过）、一台 ESP32 小智音箱（原厂固件支持 MCP 即可）、[xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) 主程序。

### 1. 部署主程序

按 [xiaozhi-esp32-server 官方文档](https://github.com/xinnan-tech/xiaozhi-esp32-server) 部署主服务（本项目的插件体系基于它）。小内存服务器可参考本仓库的裁剪经验：跳过 torch/funasr 全家桶，ASR 用 sherpa-onnx 本地模型，VAD 用 onnxruntime 路线，可省 2GB+ 磁盘。

### 2. 安装本项目的插件

```bash
git clone https://github.com/<you>/xiaozhi-family-companion.git
cp xiaozhi-family-companion/plugins/*.py  ~/xiaozhi-esp32-server/main/xiaozhi-server/plugins_func/functions/
```

在 `data/.config.yaml` 的 `Intent.intent_llm.functions` 注册：

```yaml
Intent:
  intent_llm:
    type: intent_llm
    llm: ChatGLMLLM          # 智谱免费档
    functions:
      - play_online_music    # 音乐（双模式+连播）
      - play_story           # 故事
      - get_weather          # 天气（open-meteo 免 key）
      - morning_brief        # 晨间简报
      - set_reminder         # 语音提醒
      - get_publish_status   # 自动化任务状态查询（可选）
      - start_pipeline       # 语音触发外部流水线（可选）
```

### 3. 声纹服务（可选，强烈推荐）

```bash
# 下载 campplus 模型（27MB）
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
# 启动（工具目录含 voiceprint_service.py）
VP_KEY=your-secret uvicorn voiceprint_service:app --host 127.0.0.1 --port 8102
```

注册家人声纹：每人对着手机录 2-3 条 5-10 秒语音，用 `tools/enroll_voice.sh` 上传。

### 4. 管理台（可选）

```bash
uvicorn admin_service:app --host 127.0.0.1 --port 8103
# Nginx 加 Basic Auth 反代即可
```

### 5. 设备切换

音箱进配网模式，OTA 地址填你的服务器（Nginx 反代 8003），设备会自动用 WebSocket 连上来。原厂固件全程无需刷机，随时可切回官方云。

## 📁 目录结构

```
├── plugins/                 # xiaozhi-server 插件
│   ├── play_online_music.py # 音乐：双模式选歌 + 严格原版过滤 + 自动连播
│   ├── play_story.py        # 故事：正版儿童故事检索
│   ├── set_reminder.py      # 提醒：设备闹钟+服务器语音+记忆三层保障
│   ├── morning_brief.py     # 晨报：农历/天气/任务状态/育儿贴士
│   ├── get_weather.py       # 天气（open-meteo 免 key）
│   ├── start_pipeline.py    # 语音触发外部自动化（任务文件协议）
│   ├── get_publish_status.py# 自动化状态查询
│   ├── voiceprint_service.py# 声纹识别服务（FastAPI，对标 xiaozhi 协议）
│   └── admin_service.py     # Web 管理台
├── tools/
│   ├── simulate_device.py   # 模拟设备全链路测试（无需真机）
│   ├── enroll_voice.sh      # 声纹注册
│   ├── report_publish.sh    # 自动化结果回报（成功/失败双状态+记忆注入）
│   ├── capture_serial.py    # 设备串口抓取
│   └── auto_config2.sh      # 配网模式自动写入 OTA 地址
├── docs/
│   └── prompt_child.txt     # 育儿伴侣人设提示词（四种家人模式）
└── README.md
```

## ⚠️ 重要修复补丁（上游 bug）

对话核心的 `sendAudioHandle.py` 有一个长音频截断 bug：`tts stop` 消息绕过发送队列直发，导致音乐/故事放几秒就断。需在 `sendAudioMessage` 的 `LAST` 分支补一行等待：

```python
if not conn.calling and sentenceType == SentenceType.LAST:
    from core.handle.sendAudioHandle import _wait_for_audio_completion  # 同模块直接调用
    await _wait_for_audio_completion(conn)   # ← 补这行：等音频队列真正发完
    await send_tts_message(conn, "stop", None)
```

## 🙏 致谢

- [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) — 对话核心
- [ABUGG-007/xiaozhi-mcp-music](https://github.com/ABUGG-007/xiaozhi-mcp-music) — 音源解析模块
- [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — ASR 与声纹模型
- [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — 小智固件生态

## ⚖️ 免责声明

- 音乐/故事解析仅供个人学习研究，请尊重版权，商用后果自负
- 声纹数据与家庭记忆均存于你自己的服务器，本项目不上传任何数据
- 提示词模板中的人设（家人称呼/风格）请按自己家庭情况修改 `docs/prompt_child.txt`

## License

MIT
