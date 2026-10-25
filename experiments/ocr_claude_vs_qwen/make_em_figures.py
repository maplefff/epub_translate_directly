"""電磁學合成教材的配圖（線稿，仿教科書插圖）。numpy＋PIL。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/make_em_figures.py 輸出目錄
"""
import os, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]; os.makedirs(out, exist_ok=True)
FI = lambda s: ImageFont.truetype("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf", s)
FB = lambda s: ImageFont.truetype("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf", s)
K = (0, 0, 0)

def arrow(d, a, b, w=4, head=22):
    d.line((a, b), fill=K, width=w)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    p1 = (b[0] - head * math.cos(ang - .35), b[1] - head * math.sin(ang - .35))
    p2 = (b[0] - head * math.cos(ang + .35), b[1] - head * math.sin(ang + .35))
    d.polygon([b, p1, p2], fill=K)

# Figure 2.1：源點 r'、場點 r、分離向量
im = Image.new("RGB", (1300, 900), "white"); d = ImageDraw.Draw(im)
O, S, P = (200, 760), (520, 330), (1080, 230)
arrow(d, O, S); arrow(d, O, P); arrow(d, S, P, w=5)
for q in (S, P): d.ellipse((q[0] - 12, q[1] - 12, q[0] + 12, q[1] + 12), fill=K)
d.text((330, 450), "r′", font=FB(54), fill=K); d.text((700, 520), "r", font=FB(54), fill=K)
d.text((780, 175), "𝓻", font=ImageFont.truetype("/System/Library/Fonts/Supplemental/STIXTwoMath.otf", 64), fill=K)
d.text((470, 270), "dq′", font=FI(48), fill=K); d.text((1100, 180), "P", font=FI(48), fill=K)
d.text((150, 780), "O", font=FI(48), fill=K)
for k in range(14):
    a = 2 * math.pi * k / 14
    d.ellipse((S[0] + 70 * math.cos(a) - 4, S[1] + 50 * math.sin(a) - 4, S[0] + 70 * math.cos(a) + 4, S[1] + 50 * math.sin(a) + 4), fill=(90, 90, 90))
im.save(f"{out}/fig_separation.png")

# Figure 2.2：均勻帶電球與高斯面
im = Image.new("RGB", (1100, 900), "white"); d = ImageDraw.Draw(im)
c = (550, 450)
d.ellipse((c[0] - 200, c[1] - 200, c[0] + 200, c[1] + 200), fill=(215, 215, 215), outline=K, width=4)
for k in range(0, 360, 6):
    a = math.radians(k); r = 330
    d.arc((c[0] - r, c[1] - r, c[0] + r, c[1] + r), k, k + 3, fill=K, width=4)
arrow(d, c, (c[0] + 200 * math.cos(-.6), c[1] + 200 * math.sin(-.6)))
arrow(d, c, (c[0] + 330 * math.cos(.7), c[1] + 330 * math.sin(.7)))
d.text((640, 330), "R", font=FI(52), fill=K); d.text((700, 560), "r", font=FI(52), fill=K)
d.text((700, 50), "Gaussian surface", font=FI(40), fill=K)
d.text((470, 420), "ρ", font=FI(56), fill=K)
im.save(f"{out}/fig_gauss.png")

# Figure 2.3：面電荷上的筆盒
im = Image.new("RGB", (1200, 700), "white"); d = ImageDraw.Draw(im)
d.polygon([(100, 420), (800, 420), (1100, 280), (400, 280)], outline=K, fill=(225, 225, 225), width=3)
cx, cy = 600, 350
for yoff in (-110, 110):
    d.ellipse((cx - 160, cy + yoff - 40, cx + 160, cy + yoff + 40), outline=K, width=4)
d.line((cx - 160, cy - 110, cx - 160, cy + 110), fill=K, width=4); d.line((cx + 160, cy - 110, cx + 160, cy + 110), fill=K, width=4)
arrow(d, (cx, cy - 110), (cx, cy - 250)); arrow(d, (cx, cy + 110), (cx, cy + 250))
d.text((cx + 20, cy - 270), "E_above", font=FI(44), fill=K); d.text((cx + 20, cy + 210), "E_below", font=FI(44), fill=K)
d.text((150, 300), "σ", font=FI(60), fill=K); d.text((cx + 180, cy - 30), "A", font=FI(50), fill=K)
im.save(f"{out}/fig_pillbox.png")

# Figure 2.4：偶極的電場線（數值積分）
W, H = 1200, 1000; im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
q = [((-0.35, 0.0), 1.0), ((0.35, 0.0), -1.0)]
def E(x, y):
    ex = ey = 0.0
    for (qx, qy), s in q:
        dx, dy = x - qx, y - qy; r3 = (dx * dx + dy * dy) ** 1.5 + 1e-9
        ex += s * dx / r3; ey += s * dy / r3
    return ex, ey
X = lambda x: W / 2 + x * 520; Y = lambda y: H / 2 - y * 520
for k in range(16):
    a = 2 * math.pi * (k + .5) / 16
    x, y = -0.35 + 0.04 * math.cos(a), 0.04 * math.sin(a); pts = [(X(x), Y(y))]
    for _ in range(4000):
        ex, ey = E(x, y); n = math.hypot(ex, ey)
        x += 0.004 * ex / n; y += 0.004 * ey / n; pts.append((X(x), Y(y)))
        if abs(x) > 1.2 or abs(y) > 1.0 or math.hypot(x - 0.35, y) < 0.04: break
    d.line(pts, fill=K, width=3)
    m = len(pts) // 3
    if m > 2: arrow(d, pts[m - 1], pts[m], w=3, head=18)
for (qx, qy), s in q:
    d.ellipse((X(qx) - 26, Y(qy) - 26, X(qx) + 26, Y(qy) + 26), fill="white", outline=K, width=4)
    d.text((X(qx) - 13, Y(qy) - 30), "+" if s > 0 else "−", font=FB(52), fill=K)
im.save(f"{out}/fig_dipole.png")
print("ok", sorted(os.listdir(out)))
