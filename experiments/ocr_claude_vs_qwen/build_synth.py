"""合成教材：source.md（Markdown＋LaTeX，也是標準答案）→ Typst（mitex 排公式）→ PDF → 300dpi 灰階「掃描」PDF。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/build_synth.py process/_ocr_bench/heat
設定在該目錄的 meta.json：prefix（頁檔名字首）、figs（[檔名, 寬度]，依出現順序）、header_even／header_odd、
first_page（第一頁的頁碼）、font、scan（clean：輕微模糊＋雜訊；rough：歪斜、降解析度、光照不均、裝訂邊陰影、JPEG）。
產出：book.typ／book_vector.pdf／book.pdf（純影像，給 OCR）／pages/{prefix}01.png…／gt/{prefix}01.md…
"""
import os, re, subprocess, sys, io
import pymupdf
from PIL import Image, ImageFilter
import numpy as np, json

D = sys.argv[1]
META = json.load(open(os.path.join(D, "meta.json"), encoding="utf-8"))
FIGS, PFX = META["figs"], META["prefix"]

def tex(m):
    """mitex 不認 \\mathscr：換成 \\mathcal（Typst 的 cal 是草寫字形）；只影響排版，標準答案不動。"""
    return m.replace("\\mathscr{", "\\mathcal{")
src = open(os.path.join(D, "source.md"), encoding="utf-8").read()
pages = [p.strip() for p in src.split("<!-- page -->")]

ESC = re.compile(r"([\\#$*_`<>@\[\]~=/+-])")
def esc(t):
    t = ESC.sub(lambda m: "\\" + m.group(1) if m.group(1) not in "=/+-" else m.group(1), t)
    return t.replace("--", "-\u200b-")

def inline(t, notes):
    out, pos = [], 0
    pat = re.compile(r"\$(.+?)\$|\*\*(.+?)\*\*|\*(.+?)\*|\^\{(\d+)\}")
    for m in pat.finditer(t):
        out.append(esc(t[pos:m.start()]))
        if m.group(1) is not None:
            out.append("#mi(`" + tex(m.group(1)) + "`)")
        elif m.group(2) is not None:
            out.append("#strong[" + inline(m.group(2), notes) + "]")
        elif m.group(3) is not None:
            out.append("#emph[" + inline(m.group(3), notes) + "]")
        else:
            out.append("#footnote[" + inline(notes[m.group(4)], notes) + "]")
        pos = m.end()
    out.append(esc(t[pos:]))
    return "".join(out)

head = r'''#import "@preview/mitex:0.2.7": mi, mitex
#set page(paper: "us-letter", margin: (x: 1in, top: 1in, bottom: 0.9in),
  header: context {
    let n = counter(page).get().first() + FIRST - 1
    set text(size: 9pt)
    if calc.even(n) [#n #h(1fr) HEVEN]
    else [HODD #h(1fr) #n]
  })
#set text(font: "FONT", size: 10.5pt)'''.replace("FIRST", str(META["first_page"])).replace("HEVEN", META["header_even"]) \
    .replace("HODD", META["header_odd"]).replace("FONT", META["font"]) + r'''
#set par(justify: true, leading: 0.62em, spacing: 0.9em)
#show math.equation: set text(font: "New Computer Modern Math")
#set footnote.entry(separator: line(length: 30%, stroke: 0.5pt))
#let deq(n, body) = block(width: 100%, grid(columns: (1fr, auto), align: (center + horizon, right + horizon), body, [(#n)]))
#let cap(body) = align(center, block(width: 85%, text(size: 9.5pt, body)))
'''
body, fig_i, gts = [head], 0, []
for pno, pg in enumerate(pages):
    notes = dict(re.findall(r"^\[\^(\d+)\]: (.+)$", pg, flags=re.M))
    gts.append(pg)
    blocks = re.split(r"\n\s*\n", re.sub(r"^\[\^\d+\]: .+$", "", pg, flags=re.M).strip())
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        if b.startswith("$$"):
            m = b.strip("$").strip(); tag = re.search(r"\\tag\{([^}]*)\}", m); m = re.sub(r"\s*\\tag\{[^}]*\}", "", m)
            eq = "mitex(`" + tex(m) + "`)"
            body.append(f"#deq([{tag.group(1)}], {eq})" if tag else f"#block(width: 100%, {eq})")
        elif b.startswith("!["):
            f, w = FIGS[fig_i]; fig_i += 1
            body.append(f'#align(center, image("figures/{f}", width: {w}))')
        elif re.match(r"^(Figure|Table) \d+\.\d+(:|$)", b):
            lab, _, rest = b.partition(": ")
            body.append(f"#cap[#strong[{esc(lab)}{':' if rest else ''}] {inline(rest, notes)}]")
        elif b.startswith("|"):
            rows = [r.strip().strip("|").split("|") for r in b.splitlines() if not re.match(r"^\|[-|\s]+\|$", r)]
            cells = []
            for k, r in enumerate(rows):
                for c in r:
                    c = inline(c.strip(), notes)
                    cells.append(f"[#strong[{c}]]" if k == 0 else f"[{c}]")
            body.append(f"#align(center, text(size: 9.5pt, table(columns: {len(rows[0])}, stroke: none, "
                        f"inset: (x: 6pt, y: 4pt), table.hline(), {', '.join(cells[:len(rows[0])])}, table.hline(stroke: 0.5pt), "
                        f"{', '.join(cells[len(rows[0]):])}, table.hline())))")
        elif b.startswith("#"):
            lv = len(b) - len(b.lstrip("#")); t = inline(b.lstrip("# "), notes)
            size = {1: "15pt", 2: "12.5pt", 3: "11pt"}[lv]
            body.append(f"#block(above: 1.4em, below: 0.9em, text(size: {size}, weight: \"bold\")[{t}])")
        else:
            body.append(inline(b.replace("\n", " "), notes))
        body.append("")
    if pno < len(pages) - 1:
        body.append("#pagebreak()\n")
typ = os.path.join(D, "book.typ")
open(typ, "w", encoding="utf-8").write("\n".join(body))
vec = os.path.join(D, "book_vector.pdf")
subprocess.run(["typst", "compile", "--root", D, typ, vec], check=True)
doc = pymupdf.open(vec)
assert doc.page_count == len(pages), f"排出 {doc.page_count} 頁，應為 {len(pages)} 頁（有頁面溢出）"

def rough(im, i):
    """仿真掃描：歪斜、先降到約 200dpi 再放大（掃描器解析度）、墨色變淡、光照不均、裝訂邊陰影、雜訊、JPEG。"""
    w, h = im.size
    im = im.rotate([0.45, -0.3, 0.6, -0.5, 0.25][i % 5], resample=Image.BICUBIC, fillcolor=255)
    im = im.resize((int(w * 0.68), int(h * 0.68)), Image.LANCZOS).resize((w, h), Image.BICUBIC)
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = 0.13 + 0.80 * a                                         # 墨色不是全黑、紙不是全白
    xs = np.linspace(0, 1, w)[None, :]; ys = np.linspace(0, 1, h)[:, None]
    light = 1.0 - 0.07 * ys - 0.05 * (xs if i % 2 else 1 - xs)  # 光照不均
    gutter = 1.0 - 0.35 * np.exp(-((xs if i % 2 == 0 else 1 - xs) * w / 90.0))  # 裝訂邊陰影
    a = a * light * gutter * 255 + rng.normal(0, 7, (h, w))
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=38); buf.seek(0)
    return Image.open(buf).convert("L"), buf.getvalue()

# 掃描化：300dpi 灰階，包成純影像 PDF（沒有文字層）
os.makedirs(os.path.join(D, "pages"), exist_ok=True); os.makedirs(os.path.join(D, "gt"), exist_ok=True)
scan = pymupdf.open(); rng = np.random.default_rng(0)
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if META["scan"] == "rough":
        im, data = rough(im, i)
    else:
        im = im.filter(ImageFilter.GaussianBlur(0.7))
        a = np.asarray(im, dtype=np.float32) + rng.normal(0, 6, (pix.height, pix.width))
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        buf = io.BytesIO(); im.save(buf, "PNG"); data = buf.getvalue()
    im.save(os.path.join(D, "pages", f"{PFX}{i + 1:02d}.png"))
    p = scan.new_page(width=page.rect.width, height=page.rect.height); p.insert_image(p.rect, stream=data)
    open(os.path.join(D, "gt", f"{PFX}{i + 1:02d}.md"), "w", encoding="utf-8").write(gts[i].strip() + "\n")
scan.save(os.path.join(D, "book.pdf"))
print("ok", doc.page_count, "頁")
