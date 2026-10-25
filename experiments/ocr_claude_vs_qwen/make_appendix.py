"""報告附錄：逐頁的掃描原頁、原稿（標準答案）、四種做法的原始輸出與逐詞差異。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/make_appendix.py
產出 process/_ocr_bench/report_assets/：appendix.json（report.typ 讀）、縮小的原頁 JPEG。
差異：以 token（LaTeX 指令、英文字、數字、單一符號）比對、不計空白；只差大括號、間距指令、
\\left/\\right、\\le/\\leq、\\text/\\mathrm 這類等價寫法的片段當作相同，不標色。
"""
import os, re, json, difflib, sys
from PIL import Image
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score as S

B = S.B
OUT = os.path.join(B, "report_assets"); os.makedirs(OUT, exist_ok=True)
METHODS = [("haiku", "Haiku 5.5"), ("sonnet", "Sonnet 5.5"), ("opus", "Opus 5.5"), ("qwen", "Qwen3.5-27B")]
SETS = [("heat", "熱傳導"), ("em", "電磁學")]
TOK = re.compile(r"\\[A-Za-z]+|\\.|[A-Za-z]+|\d+|[^\sA-Za-z\d]")
IGNORE = {"{", "}", "\\,", "\\;", "\\:", "\\!", "\\ ", "\\quad", "\\qquad", "\\left", "\\right", "\\big", "\\Big",
          "\\bigg", "\\Bigg", "\\displaystyle"}
SYN = {"\\le": "\\leq", "\\ge": "\\geq", "\\tfrac": "\\frac", "\\dfrac": "\\frac", "\\text": "\\mathrm",
       "\\textrm": "\\mathrm", "\\ldots": "\\dots", "\\cdots": "\\dots", "’": "'", "–": "-", "—": "-"}

def toks(s):
    return [(m.group(0), m.start(), m.end()) for m in TOK.finditer(s)]

def key(ts):
    out = []
    for t, *_ in ts:
        t = SYN.get(t, t)
        if t not in IGNORE: out.append(t)
    return out

def piece(s, ts, i, j, nxt):
    """原字串裡 token i..j-1 的片段，含到下一個 token 前的空白。"""
    if i >= j: return ""
    end = ts[j][1] if j < len(ts) else len(s)
    return s[ts[i][1]:end] if nxt else s[ts[i][1]:ts[j - 1][2]]

def diff(gt, out):
    a, b = toks(gt), toks(out)
    ka = [SYN.get(t, t) for t, *_ in a]; kb = [SYN.get(t, t) for t, *_ in b]
    segs = []
    def add(kind, text):
        if not text: return
        if segs and segs[-1][0] == kind: segs[-1][1] += text
        else: segs.append([kind, text])
    if b and b[0][1] > 0: add("=", out[:b[0][1]].lstrip("\n"))
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        if op == "equal" or key(a[i1:i2]) == key(b[j1:j2]):
            add("=", piece(out, b, j1, j2, True))
            continue
        if i2 > i1 and key(a[i1:i2]):
            add("-", piece(gt, a, i1, i2, False)); add("=", " " if j2 == j1 else "")
        if j2 > j1:
            if key(b[j1:j2]): add("+", piece(out, b, j1, j2, False)); add("=", piece(out, b, j2 - 1, j2, True)[len(b[j2 - 1][0]):] if j2 - 1 >= j1 else "")
            else: add("=", piece(out, b, j1, j2, True))
    return segs

data = []
for bset, bname in SETS:
    names = sorted(f[:-3] for f in os.listdir(os.path.join(B, bset, "gt")) if f.endswith(".md"))
    for k, n in enumerate(names):
        gt = open(os.path.join(B, bset, "gt", n + ".md"), encoding="utf-8").read().strip()
        im = Image.open(os.path.join(B, bset, "pages", n + ".png")).convert("L")
        im = im.resize((1700, int(im.height * 1700 / im.width)), Image.LANCZOS)
        img = f"{bset}_{n}.jpg"; im.save(os.path.join(OUT, img), quality=82)
        page = {"set": bname, "skey": bset, "name": n, "page": k + 1, "image": img, "gt": gt, "models": []}
        for m, label in METHODS:
            raw = S.load_out(m, bset, n).strip()
            r = S.score(raw, gt)
            page["models"].append({"label": label, "key": m, "segs": diff(gt, raw),
                                   "stat": f"正文 {r['text']:.3f}（原始 {r['text_raw']:.3f}）· 公式（去字體）{r['math_nf']:.3f} · "
                                           f"獨立公式 {r['disp_ok'][0]}/{r['disp_ok'][1]} · 標題 {r['head'][0]}/{r['head'][1]}"})
        data.append(page)
json.dump(data, open(os.path.join(OUT, "appendix.json"), "w", encoding="utf-8"), ensure_ascii=False)
n_diff = sum(1 for p in data for m in p["models"] for s in m["segs"] if s[0] != "=")
print("ok", len(data), "頁；標色片段", n_diff)
for p in data[:1]:
    for m in p["models"]:
        print(m["label"], [s for s in m["segs"] if s[0] != "="][:12])
