"""PIL 绘制封面图（OfoxAI 欠费 fallback）：AI安全主题，900x383 微信封面比例。"""
from PIL import Image, ImageDraw, ImageFont
import math

W, H = 1800, 766  # 2.35:1，最后缩到 900x383

img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)

# 深夜蓝渐变背景
top, bottom = (10, 16, 38), (26, 18, 52)
for y in range(H):
    t = y / H
    r = int(top[0] + (bottom[0] - top[0]) * t)
    g = int(top[1] + (bottom[1] - top[1]) * t)
    b = int(top[2] + (bottom[2] - top[2]) * t)
    d.line([(0, y), (W, y)], fill=(r, g, b))

# 背景网格（电路感）
for x in range(0, W, 90):
    d.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
for y in range(0, H, 90):
    d.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)
# 半透明网格重绘（PIL 无 alpha 直线，改用暗色）
for x in range(0, W, 90):
    d.line([(x, 0), (x, H)], fill=(16, 22, 48), width=1)
for y in range(0, H, 90):
    d.line([(0, y), (W, y)], fill=(16, 22, 48), width=1)

ACCENT = (56, 214, 172)     # 青绿
RED = (232, 76, 61)         # 漏洞红
GOLD = (212, 160, 23)       # 万亿金

# 中央：笼子里的 AI 圆环
cx, cy, R = 1210, 383, 200
for i in range(36):
    ang = i * math.pi / 18
    x1 = cx + R * math.cos(ang)
    y1 = cy + R * math.sin(ang)
    x2 = cx + (R - 26) * math.cos(ang)
    y2 = cy + (R - 26) * math.sin(ang)
    d.line([(x1, y1), (x2, y2)], fill=ACCENT, width=3)
d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=ACCENT, width=4)
d.ellipse([cx - R + 26, cy - R + 26, cx + R - 26, cy + R - 26], outline=(40, 120, 100), width=2)
# 笼中核心（AI 芯片方块）
d.rounded_rectangle([cx - 62, cy - 62, cx + 62, cy + 62], radius=14,
                    fill=(16, 32, 60), outline=ACCENT, width=4)
# 芯片引脚
for i in range(4):
    off = -45 + i * 30
    d.line([(cx - 62 - 18, cy + off), (cx - 62, cy + off)], fill=ACCENT, width=3)
    d.line([(cx + 62, cy + off), (cx + 62 + 18, cy + off)], fill=ACCENT, width=3)
    d.line([(cx + off, cy - 62 - 18), (cx + off, cy - 62)], fill=ACCENT, width=3)
    d.line([(cx + off, cy + 62), (cx + off, cy + 62 + 18)], fill=ACCENT, width=3)

# 左侧：裂纹盾牌（漏洞）
sx, sy = 300, 300
d.polygon([(sx, sy - 90), (sx + 80, sy - 55), (sx + 80, sy + 25), (sx, sy + 100), (sx - 80, sy + 25), (sx - 80, sy - 55)],
          fill=(30, 40, 70), outline=(180, 190, 210), width=4)
# 裂纹（红色闪电）
crack = [(sx - 8, sy - 80), (sx + 18, sy - 30), (sx - 6, sy - 12), (sx + 22, sy + 30), (sx - 2, sy + 55)]
d.line(crack, fill=RED, width=6)
d.line([(sx - 8, sy - 80), (sx + 18, sy - 30)], fill=RED, width=6)
d.ellipse([sx + 96, sy - 120, sx + 136, sy - 80], fill=RED)   # 警示点

def font(sz, bold=True):
    for p in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", sz)

# 标题区（左侧留白处）
d.text((170, 120), "AI 挖出世纪漏洞", font=font(92), fill=(255, 255, 255))
d.text((170, 240), "OpenAI 却把模型", font=font(92), fill=(255, 255, 255))
d.text((170, 360), "关进了笼子", font=font(92), fill=ACCENT)
# 三个数据点
stats = [("69.4%", "全球网站用 PHP", RED), ("$1.25T", "OpenAI 新估值", GOLD), ("OFFLINE", "前沿训练环境", ACCENT)]
x0 = 170
for val, label, c in stats:
    d.text((x0, 540), val, font=font(56), fill=c)
    d.text((x0, 616), label, font=font(30), fill=(200, 205, 220))
    x0 += int(W * 0.212)

# 底部装饰线
d.line([(0, H - 8), (W, H - 8)], fill=ACCENT, width=6)

img = img.resize((900, 383), Image.LANCZOS)
img.save("/Users/wilson/Downloads/wechat-article-history/wechat-pipeline-2026-10-24/images/01_cover_final.jpg",
         "JPEG", quality=90)
print("cover drawn 900x383")
