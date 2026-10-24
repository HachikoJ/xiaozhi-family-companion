#!/bin/bash
OTA_URL='https://xiaozhi.example.com/xiaozhi-http/xiaozhi/ota/'
# 1) 等待并连接热点（最多90秒）
for i in $(seq 1 30); do
  networksetup -setairportnetwork en0 "xiaozhi-ap" >/dev/null 2>&1
  IP=$(ifconfig en0 | awk '/inet /{print $2}')
  if [[ "$IP" == 192.168.4.* ]]; then echo "connected: $IP $(date +%H:%M:%S)"; break; fi
  sleep 3
done
[[ "$IP" == 192.168.4.* ]] || { echo "NO AP"; exit 1; }
# 2) 探测页面可达
for i in $(seq 1 8); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 6 http://192.168.4.1/)
  [ "$CODE" = "200" ] && { echo "page OK"; break; }
  sleep 3
done
[ "$CODE" = "200" ] || { echo "PAGE FAIL"; exit 1; }
# 3) JSON POST 保存 OTA 地址
RESP=$(curl -s --noproxy '*' --connect-timeout 5 --max-time 15 -X POST http://192.168.4.1/advanced/submit \
  -H 'Content-Type: application/json' \
  -d "{\"ota_url\":\"$OTA_URL\",\"max_tx_power\":80,\"remember_bssid\":false,\"sleep_mode\":false}")
echo "RESP: $RESP"
echo "$RESP" | grep -qi "success\|true" && echo "OTA URL SAVED" || echo "CHECK RESP"
