"""把四種做法的 OCR 輸出（Markdown＋LaTeX）排版成圖，供報告附錄和原頁並排比對。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/render_outputs.py
- 先套用正式流程相同的後處理（score.postprocess：拆外框、tabular → 表格、刪書眉）。
- 公式逐條試排（同 epubtrans/output/export_pdf/mathcheck.py 的做法）：mitex 排不出的照原樣印成紅色等寬字。
- 字型、版心寬度沿用該組教材的 meta.json，圖只畫佔位框（OCR 只標位置）。
產出 process/_ocr_bench/report_assets/render/{組}_{頁}_{做法}.png
"""
import os, re, sys, json, hashlib, subprocess
from concurrent.futures import ThreadPoolExecutor
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score as S

B = S.B
OUT = os.path.join(B, "report_assets", "render"); os.makedirs(OUT, exist_ok=True)
TMP = os.path.join(B, "report_assets", "_tmp"); os.makedirs(TMP, exist_ok=True)
METHODS = ["haiku", "sonnet", "opus", "qwen"]
SETS = ["heat", "em"]
MITEX = '#import "@preview/mitex:0.2.7": mi, mitex\n'

def tex(m):
    return m.replace("\\mathscr{", "\\mathcal{").strip()

ESC = re.compile(r"([\\#$*_`<>@\[\]~])")
def esc(t):
    return ESC.sub(r"\\\1", t).replace("--", "-\u200b-")

def raw_red(t):
    return '#text(fill: rgb("#c0392b"), font: "Menlo", size: 0.85em, ' + json.dumps(t, ensure_ascii=False) + ")"

OK = {}
def math(t, display=False):
    t = tex(t)
    if not OK.get(t, False):
        return raw_red(("$$" if display else "$") + t + ("$$" if display else "$"))
    return ("mitex(" if display else "#mi(") + "`" + t + "`)"

def inline(t):
    out, pos = [], 0
    pat = re.compile(r"\$(.+?)\$|\*\*(.+?)\*\*|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|\^\{(\d+)\}")
    for m in pat.finditer(t):
        out.append(esc(t[pos:m.start()]))
        if m.group(1) is not None: out.append(math(m.group(1)))
        elif m.group(2) is not None: out.append("#strong[" + inline(m.group(2)) + "]")
        elif m.group(3) is not None: out.append("#emph[" + inline(m.group(3)) + "]")
        else: out.append("#super[" + m.group(4) + "]")
        pos = m.end()
    out.append(esc(t[pos:]))
    return "".join(out)

def normalize(md):
    md = S.postprocess(md)
    md = md.replace("\\(", "$").replace("\\)", "$")
    md = re.sub(r"\\\[(.*?)\\\]", lambda m: "$$" + m.group(1) + "$$", md, flags=re.S)
    return re.sub(r"\$\$(.+?)\$\$", lambda m: "\n\n$$" + m.group(1).replace("\n", " ") + "$$\n\n", md, flags=re.S)

def formulas(md):
    md = normalize(md)
    disp = re.findall(r"\$\$(.+?)\$\$", md, re.S)
    rest = re.sub(r"\$\$(.+?)\$\$", " ", md, flags=re.S)
    return [tex(re.sub(r"\\tag\{[^}]*\}", "", d)) for d in disp] + [tex(x) for x in re.findall(r"\$(.+?)\$", rest, re.S)]

def to_typ(md, font):
    md = normalize(md)
    notes = re.findall(r"^\[\^(\d+)\]:\s*(.+)$", md, flags=re.M)
    md = re.sub(r"^\[\^\d+\]:.*$", "", md, flags=re.M)
    body = [MITEX,
            '#set page(width: 6.5in, height: auto, margin: (x: 0.12in, y: 0.15in), fill: white)',
            f'#set text(font: ("{font}", "STIX Two Text", "Songti TC"), size: 10.5pt)',
            '#set par(justify: true, leading: 0.62em, spacing: 0.9em)',
            '#show math.equation: set text(font: "New Computer Modern Math")',
            '#let deq(n, body) = block(width: 100%, grid(columns: (1fr, auto), align: (center + horizon, right + horizon), body, [(#n)]))',
            '#let cap(body) = align(center, block(width: 85%, text(size: 9.5pt, body)))', '']
    for b in re.split(r"\n\s*\n", md.strip()):
        b = b.strip()
        if not b: continue
        if b.startswith("$$") and b.endswith("$$"):
            m = b[2:-2].strip(); tags = re.findall(r"\\tag\{([^}]*)\}", m); m = re.sub(r"\s*\\tag\{[^}]*\}", "", m)
            eq = math(m, display=True)
            if eq.startswith("#text"):
                body.append(f"#block(width: 100%)[{eq}]")
            else:
                body.append(f"#deq([{', '.join(tags)}], {eq})" if tags else f"#block(width: 100%, {eq})")
        elif re.match(r"^!\[[^\]]*\]\([^)]*\)$", b):
            body.append('#align(center, rect(width: 45%, height: 2.2cm, fill: luma(240), stroke: 0.5pt + luma(150))[#align(center + horizon, text(fill: luma(110), size: 9pt)[圖（OCR 只標位置）])])')
        elif re.match(r"^(Figure|Table) \d+\.\d+", b):
            body.append(f"#cap[{inline(b.replace(chr(10), ' '))}]")
        elif b.startswith("|"):
            rows = [r.strip().strip("|").split("|") for r in b.splitlines()
                    if r.strip().startswith("|") and not re.match(r"^\|[\s:|-]+\|?$", r.strip())]
            n = max(len(r) for r in rows) if rows else 1
            cells = []
            for k, r in enumerate(rows):
                r = (r + [""] * n)[:n]
                for c in r:
                    c = inline(c.strip()); cells.append(f"[#strong[{c}]]" if k == 0 else f"[{c}]")
            body.append(f"#align(center, text(size: 9.5pt, table(columns: {n}, stroke: none, inset: (x: 6pt, y: 4pt), "
                        f"table.hline(), {', '.join(cells[:n])}, table.hline(stroke: 0.5pt), {', '.join(cells[n:])}{',' if cells[n:] else ''} table.hline())))")
        elif b.startswith("#"):
            lines = b.split("\n"); h = lines[0]
            lv = min(3, len(h) - len(h.lstrip("#"))); size = {1: "15pt", 2: "12.5pt", 3: "11pt"}[lv]
            body.append(f'#block(above: 1.2em, below: 0.8em, text(size: {size}, weight: "bold")[{inline(h.lstrip("# "))}])')
            if lines[1:]: body.append(inline(" ".join(lines[1:])))
        else:
            body.append(inline(b.replace("\n", " ")))
        body.append("")
    if notes:
        body.append("#v(0.6em) #line(length: 30%, stroke: 0.5pt)")
        for n, t in notes:
            body.append(f"#text(size: 8.5pt)[#super[{n}]{inline(t)}]\n")
    return "\n".join(body)

# 1) 收集所有公式，逐條試排（依內容快取）
cache_f = os.path.join(B, "report_assets", "mathcheck.json")
cache = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
jobs, allf = [], set()
for bset in SETS:
    names = sorted(f[:-3] for f in os.listdir(os.path.join(B, bset, "gt")))
    for n in names:
        for m in METHODS:
            md = S.load_out(m, bset, n); jobs.append((bset, n, m, md)); allf.update(formulas(md))
key = lambda t: hashlib.sha1(t.encode()).hexdigest()
todo = [t for t in allf if key(t) not in cache]
def one(t):
    k = key(t); f = os.path.join(TMP, f"f{k}.typ")
    open(f, "w").write(MITEX + "#mitex(`" + t + "`)\n#mi(`" + t + "`)\n")
    r = subprocess.run(["typst", "compile", f, os.path.join(TMP, f"f{k}.pdf")], capture_output=True)
    return t, r.returncode == 0 and "`" not in t
print(f"公式試排 {len(todo)} 條（快取 {len(allf) - len(todo)} 條）")
with ThreadPoolExecutor(12) as ex:
    for t, ok in ex.map(one, todo): cache[key(t)] = ok
json.dump(cache, open(cache_f, "w"))
OK.update({t: cache[key(t)] for t in allf})
bad = [t for t in allf if not OK[t]]
print(f"排不出 {len(bad)} 條：", [b[:60] for b in bad[:10]])

# 2) 逐頁排版成 PNG
def render(job):
    bset, n, m, md = job
    font = json.load(open(os.path.join(B, bset, "meta.json")))["font"]
    f = os.path.join(TMP, f"{bset}_{n}_{m}.typ")
    open(f, "w", encoding="utf-8").write(to_typ(md, font))
    png = os.path.join(OUT, f"{bset}_{n}_{m}.png")
    r = subprocess.run(["typst", "compile", "--ppi", "170", f, png], capture_output=True, text=True)
    if r.returncode == 0:                           # 灰階＋最佳化，報告 PDF 才不會太大（紅色的排不出公式另存彩色）
        from PIL import Image
        im = Image.open(png).convert("RGB")
        if "c0392b" not in open(f, encoding="utf-8").read():
            im = im.convert("L")
        im.save(png, optimize=True)
    return job[:3], r.returncode, r.stderr[-300:]
fails = []
with ThreadPoolExecutor(8) as ex:
    for j, rc, err in ex.map(render, jobs):
        if rc: fails.append((j, err))
print(f"排版 {len(jobs)} 份，失敗 {len(fails)}")
for j, e in fails[:5]: print(j, e)
