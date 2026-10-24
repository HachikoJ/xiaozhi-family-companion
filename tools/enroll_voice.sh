#!/bin/bash
# 声纹注册：./enroll_voice.sh <speaker_id> <音频文件>
# speaker_id: papa / mama / nainai / baobao
# 音频: wav/m4a/mp3 均可（服务器自动转码），建议每人录 2-3 条 5-10 秒自然说话
set -e
[ $# -eq 2 ] || { echo "用法: ./enroll_voice.sh <papa|mama|nainai|baobao> <音频文件>"; exit 1; }
SID=$1; FILE=$2
[ -f "$FILE" ] || { echo "文件不存在: $FILE"; exit 1; }
scp -q -i "$HOME/.ssh/xiaozhi_server_key" "$FILE" ubuntu@xiaozhi.example.com:/tmp/enroll_in.$$
ssh -i "$HOME/.ssh/xiaozhi_server_key" ubuntu@xiaozhi.example.com "
  ffmpeg -y -v error -i /tmp/enroll_in.\$\$ -ar 16000 -ac 1 /tmp/enroll_$SID.wav &&
  curl -s -X POST http://127.0.0.1:8102/voiceprint/enroll \
    -F 'Authorization: ' -H 'Authorization: Bearer change-me-voiceprint-key' \
    -F 'speaker_id=$SID' -F 'file=@/tmp/enroll_$SID.wav' &&
  rm -f /tmp/enroll_in.\$\$ /tmp/enroll_$SID.wav; echo
"
