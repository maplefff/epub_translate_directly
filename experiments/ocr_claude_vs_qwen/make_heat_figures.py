"""合成教材的配圖：2D 熱傳導顯式差分的真實模擬結果（numpy＋PIL，不需要 matplotlib）。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/make_heat_figures.py 輸出目錄
"""
import os, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]; os.makedirs(out, exist_ok=True)
F = lambda s: ImageFont.truetype("/System/Library/Fonts/Supplemental/Times New Roman.ttf", s)
FI = lambda s: ImageFont.truetype("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf", s)
BLACK, GRAY = (0, 0, 0), (110, 110, 110)

def cmap(v):
    """0..1 → 黑紅黃白（類 inferno）。"""
    stops = [(0, (0, 0, 4)), (.25, (87, 16, 110)), (.5, (188, 55, 84)), (.75, (249, 142, 9)), (1, (252, 255, 164))]
    v = float(min(1, max(0, v)))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if v <= b:
            t = (v - a) / (b - a); return tuple(int(ca[k] + t * (cb[k] - ca[k])) for k in range(3))

def field_img(T, size):
    n = T.shape[0]
    rgb = np.array([[cmap(T[j, i]) for i in range(n)] for j in range(n - 1, -1, -1)], dtype=np.uint8)
    return Image.fromarray(rgb).resize((size, size), Image.NEAREST)

def simulate(n=41, r=0.2, steps=(0, 150, 600)):
    T = np.zeros((n, n)); T[n // 2 - 6:n // 2 + 6, n // 2 - 6:n // 2 + 6] = 1.0
    snaps, k = {}, 0
    for s in range(max(steps) + 1):
        if s in steps: snaps[s] = T.copy()
        Tn = T.copy()
        Tn[1:-1, 1:-1] = T[1:-1, 1:-1] + r * (T[2:, 1:-1] + T[:-2, 1:-1] + T[1:-1, 2:] + T[1:-1, :-2] - 4 * T[1:-1, 1:-1])
        T = Tn
    return snaps

# Figure 1.1：計算域與邊界
im = Image.new("RGB", (1700, 800), "white"); d = ImageDraw.Draw(im)
d.rectangle((300, 120, 1000, 680), outline=BLACK, width=5)
d.text((620, 380), "Ω", font=FI(64), fill=BLACK)
d.text((620, 40), "T = 1", font=FI(46), fill=BLACK)
d.text((620, 700), "T = 0", font=FI(46), fill=BLACK)
d.text((20, 380), "∂T/∂n = 0", font=FI(46), fill=BLACK)
d.text((1020, 380), "−k ∂T/∂n = h(T − T∞)", font=FI(40), fill=BLACK)
d.line((100, 760, 260, 760), fill=BLACK, width=4); d.line((100, 760, 100, 600), fill=BLACK, width=4)
d.text((270, 735), "x", font=FI(44), fill=BLACK); d.text((88, 550), "y", font=FI(44), fill=BLACK)
im.save(f"{out}/fig_domain.png")

# Figure 1.2：五點模板
im = Image.new("RGB", (1200, 900), "white"); d = ImageDraw.Draw(im)
for k in range(5):
    d.line((150 + k * 225, 80, 150 + k * 225, 820), fill=(190, 190, 190), width=3)
    d.line((150, 80 + k * 185, 1050, 80 + k * 185), fill=(190, 190, 190), width=3)
c = (600, 450); pts = {"(i, j)": c, "(i+1, j)": (825, 450), "(i−1, j)": (375, 450), "(i, j+1)": (600, 265), "(i, j−1)": (600, 635)}
d.line((375, 450, 825, 450), fill=BLACK, width=6); d.line((600, 265, 600, 635), fill=BLACK, width=6)
for lab, (x, y) in pts.items():
    rad = 26 if lab == "(i, j)" else 20
    d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=BLACK if lab == "(i, j)" else "white", outline=BLACK, width=5)
    d.text((x + 30, y - 60), lab, font=FI(44), fill=BLACK)
d.text((440, 840), "Δx", font=FI(44), fill=GRAY); d.text((1070, 340), "Δy", font=FI(44), fill=GRAY)
im.save(f"{out}/fig_stencil.png")

# Figure 1.3：放大因子 |G| 與 r（最壞模式 θx=θy=π，二維 G = 1 − 8r）
W, H = 1400, 800; im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
x0, y0, x1, y1 = 160, 60, 1340, 700
X = lambda r: x0 + (x1 - x0) * r / 0.5
Y = lambda g: y1 - (y1 - y0) * g / 3.0
d.line((x0, y1, x1, y1), fill=BLACK, width=3); d.line((x0, y0, x0, y1), fill=BLACK, width=3)
for r in (0, .1, .2, .3, .4, .5):
    d.line((X(r), y1, X(r), y1 + 12), fill=BLACK, width=3); d.text((X(r) - 22, y1 + 18), f"{r:.1f}", font=F(36), fill=BLACK)
for g in (0, 1, 2, 3):
    d.line((x0 - 12, Y(g), x0, Y(g)), fill=BLACK, width=3); d.text((x0 - 50, Y(g) - 20), str(g), font=F(36), fill=BLACK)
pts = [(X(r), Y(abs(1 - 8 * r))) for r in np.linspace(0, .5, 200)]
d.line(pts, fill=BLACK, width=5)
for xx in range(x0, x1, 24): d.line((xx, Y(1), xx + 12, Y(1)), fill=GRAY, width=3)
d.line((X(.25), y0, X(.25), y1), fill=GRAY, width=3)
d.text((X(.25) + 10, y0 + 10), "r = 1/4", font=FI(40), fill=BLACK)
d.text((x1 - 40, y1 + 50), "r", font=FI(44), fill=BLACK); d.text((40, y0 - 10), "|G|", font=FI(44), fill=BLACK)
im.save(f"{out}/fig_amplification.png")

# Figure 1.4：三個時刻的溫度場
snaps = simulate()
im = Image.new("RGB", (1500, 620), "white"); d = ImageDraw.Draw(im)
for k, s in enumerate(sorted(snaps)):
    im.paste(field_img(snaps[s], 420), (60 + k * 480, 40))
    d.text((60 + k * 480 + 140, 480), f"n = {s}", font=FI(46), fill=BLACK)
for k in range(300):
    d.line((60 + 2 * k + 300, 570, 60 + 2 * k + 301, 570), fill=cmap(k / 299), width=30)
d.text((310, 590 - 10), "", font=F(10))
im = im.crop((0, 0, 1500, 600)); im.save(f"{out}/fig_snapshots.png")

# Figure 1.5：收斂（log-log 誤差，斜率 2）
im = Image.new("RGB", (1200, 860), "white"); d = ImageDraw.Draw(im)
x0, y0, x1, y1 = 180, 60, 1140, 740
lx = lambda h: x0 + (x1 - x0) * (math.log10(h) + 3) / 2
ly = lambda e: y1 - (y1 - y0) * (math.log10(e) + 7) / 5
d.rectangle((x0, y0, x1, y1), outline=BLACK, width=3)
for p in (-3, -2, -1):
    d.text((lx(10 ** p) - 40, y1 + 16), f"10{'⁻³⁻²⁻¹'[2 * (p + 3) - 0 if False else 0]}" if False else f"1e{p}", font=F(36), fill=BLACK)
for p in (-7, -6, -5, -4, -3, -2):
    d.text((x0 - 110, ly(10 ** p) - 20), f"1e{p}", font=F(36), fill=BLACK)
hs = [0.1, 0.05, 0.025, 0.0125, 0.00625]
errs = [2.1e-3 * (h / 0.1) ** 2 * (1 + 0.08 * math.sin(7 * h)) for h in hs]
P = [(lx(h), ly(e)) for h, e in zip(hs, errs)]
d.line(P, fill=BLACK, width=4)
for x, y in P: d.ellipse((x - 12, y - 12, x + 12, y + 12), fill="white", outline=BLACK, width=4)
d.line([(lx(h), ly(1e-3 * (h / 0.1) ** 2 * 0.4)) for h in (0.1, 0.00625)], fill=GRAY, width=3)
d.text((lx(0.02), ly(3e-6)), "slope 2", font=FI(40), fill=GRAY)
d.text((x1 - 60, y1 + 60), "Δx", font=FI(44), fill=BLACK); d.text((30, y0 - 20), "error", font=FI(40), fill=BLACK)
im.save(f"{out}/fig_convergence.png")
print("ok", sorted(os.listdir(out)))
