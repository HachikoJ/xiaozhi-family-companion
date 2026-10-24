#!/bin/bash
# 公众号发文状态上报 → 小智播报
# 用法: ./report_publish.sh [pipeline工作空间目录] [--status success|failed|running] [--reason "原因"]
# 效果: ①小智可被询问播报 ②下次唤醒时主动汇报（记忆注入）
set -u
PEM="$HOME/.ssh/xiaozhi_server_key"
SRV="ubuntu@xiaozhi.example.com"
STATUS_REMOTE="/home/ubuntu/xiaozhi-pipeline/status.json"

# 解析参数
WS=""
STATUS="draft_pushed"
REASON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --status) STATUS="$2"; shift 2 ;;
    --reason) REASON="$2"; shift 2 ;;
    *) WS="$1"; shift ;;
  esac
done

# 定位工作空间（默认今天）
if [ -z "$WS" ]; then
  WS="$HOME/Downloads/wechat-article-history/wechat-pipeline-$(date +%Y-%m-%d)"
fi
[ -d "$WS" ] || WS="none"

# 提取标题
TITLE="今天的公众号文章"
ART="$WS/article/article.md"
if [ -f "$ART" ]; then
  T=$(grep -m1 '^title:' "$ART" | sed 's/^title:[[:space:]]*//; s/^"//; s/"$//')
  [ -z "$T" ] && T=$(grep -m1 '^# ' "$ART" | sed 's/^# //')
  [ -n "$T" ] && TITLE="$T"
fi

# 组状态 JSON 并上传
NOW=$(date '+%Y-%m-%d %H:%M:%S')
DAY=$(date '+%Y-%m-%d')
WSNAME=$([ "$WS" = "none" ] && echo "" || basename "$WS")
STATUS_DESC="draft_pushed"
case "$STATUS" in
  success) STATUS_DESC="draft_pushed" ;;
  failed)  STATUS_DESC="failed" ;;
  running) STATUS_DESC="running" ;;
esac
python3 - "$TITLE" "$NOW" "$DAY" "$WSNAME" "$STATUS_DESC" "$REASON" << 'PYEOF' > /tmp/xz_publish_status.json
import json, sys
title, now, day, ws, status, reason = sys.argv[1:7]
print(json.dumps({
    "date": day, "title": title, "published_at": now,
    "status": status, "workspace": ws, "reason": reason,
    "source": "wechat-article-pipeline",
}, ensure_ascii=False))
PYEOF
scp -q -i "$PEM" /tmp/xz_publish_status.json "$SRV:$STATUS_REMOTE" || { echo "[report_publish] 上传失败"; exit 1; }

# 记忆注入（仅终态：success/failed）
if [ "$STATUS" = "success" ] || [ "$STATUS" = "failed" ]; then
  ssh -i "$PEM" -o BatchMode=yes "$SRV" "~/xiaozhi-esp32-server/.venv/bin/python - << 'PYEOF'
import json, yaml, os, datetime, sys

path = '/home/ubuntu/xiaozhi-esp32-server/main/xiaozhi-server/data/.memory.yaml'
mac = 'AA:BB:CC:DD:EE:FF'
status = json.load(open('/home/ubuntu/xiaozhi-pipeline/status.json'))
if status.get('status') == 'failed':
    note = f\"今天公众号发文失败了，原因是{status.get('reason','未知原因')}，爸爸可能需要安慰和帮助排查\"
else:
    note = f\"今天的公众号文章《{status['title']}》已发布成功，记得向爸爸汇报这个好消息\"

all_mem = {}
if os.path.exists(path):
    all_mem = yaml.safe_load(open(path)) or {}
raw = all_mem.get(mac)
try:
    mem = json.loads(raw) if isinstance(raw, str) else (raw or {})
except Exception:
    mem = {}
pending = mem.get('待响应', {}).get('潜在关怀', [])
note_full = f\"[{datetime.date.today().isoformat()}] {note}\"
if note_full not in pending:
    pending.insert(0, note_full)
    mem.setdefault('待响应', {})['潜在关怀'] = [p for p in pending if p != note][:5]
    all_mem[mac] = json.dumps(mem, ensure_ascii=False)
    yaml.dump(all_mem, open(path, 'w'), allow_unicode=True)
print('memory injected:', status.get('status'))
PYEOF"
fi
echo "[report_publish] 上报完成: status=$STATUS title=$TITLE @ $NOW"
