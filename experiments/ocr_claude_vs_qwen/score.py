"""評分：各方法的輸出 vs 標準答案（process/_ocr_bench/{heat,em}/gt/*.md）。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/score.py [--json 輸出.json]
指標：
  text      去掉公式後的英文字詞串，字元級編輯距離相似度（1−CER）
  math      所有公式（行內＋獨立）正規化後依序串接的相似度；math_nf：再去掉字體（粗體、草寫、mathsf…）
  disp_ok   標準答案裡的獨立公式，有多少條在輸出裡找得到「去字體後完全相同」的一條
  tags      \\tag 編號：輸出與答案的集合交集／答案數
  fig/fn    圖片佔位行、頁底註腳的數量（得/應）
  raw       text 但不做後處理（原始輸出：書眉、tabular、外框都照算）
  head      標題（層級＋文字都對）的數量（得/應）；h_any：不計層級
  scr/bold  草寫 𝓇、粗體指令的數量（得/應）
"""
import re, sys, os, glob, json
import numpy as np

def lev(a, b):
    """編輯距離（逐列 numpy；插入用累積最小值一次處理）。"""
    if len(a) < len(b): a, b = b, a
    if not b: return len(a)
    bb = np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
    ar = np.arange(len(b) + 1)
    prev = ar.copy()
    for i, ch in enumerate(a.encode("utf-32-le")[k:k + 4] for k in range(0, 4 * len(a), 4)):
        c = (bb != np.frombuffer(ch, dtype=np.uint32)[0]).astype(np.int64)
        tmp = np.empty_like(prev); tmp[0] = i + 1
        tmp[1:] = np.minimum(prev[1:] + 1, prev[:-1] + c)
        prev = np.minimum.accumulate(tmp - ar) + ar
    return int(prev[-1])

B = os.path.join(os.path.dirname(__file__), "..", "..", "process", "_ocr_bench")

def strip_fence(s):
    s = re.sub(r"^\s*```[a-z]*\s*\n", "", s)
    return re.sub(r"\n\s*```\s*$", "", s).strip()

# 正式流程（epubtrans/source/import_pdf/vlm.py）會做的後處理，四種方法一律套用：
# 拆掉 ```markdown 外框（上面）、LaTeX tabular → Markdown 表格、刪掉頁首書眉與註解行
TABULAR = re.compile(r"(?:\\begin\{center\}(.*?)\\end\{center\}\s*)?\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}", re.S)
def _tabular_rows(m):
    rows = ["| " + re.sub(r"\\textbf\{(.*?)\}", r"\1", m.group(1)).strip() + " |"] if m.group(1) else []
    for r in re.split(r"\\\\", m.group(2)):
        r = r.replace("\\hline", "").strip()
        if r: rows.append("| " + " | ".join(c.strip() for c in r.split("&")) + " |")
    return "\n" + "\n".join(rows) + "\n"
RUNHEAD = re.compile(r"^\s*(\d+\s+)?[0-9.]*\s*(CHAPTER\s+\d+\.?)?[A-Z0-9 .,'-]{6,}?(\s+\d+)?\s*$")
def postprocess(s):
    s = strip_fence(s)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = TABULAR.sub(_tabular_rows, s)
    lines = s.split("\n")
    while lines and (not lines[0].strip() or RUNHEAD.match(lines[0]) and not lines[0].lstrip().startswith("#")):
        lines = lines[1:]
    return "\n".join(lines)

def split(s):
    s = s.replace("\\(", "$").replace("\\)", "$")
    s = re.sub(r"\\\[(.*?)\\\]", lambda m: "$$" + m.group(1) + "$$", s, flags=re.S)
    disp, maths = [], []
    def g2(m): disp.append(m.group(1)); maths.append(m.group(1)); return " "
    def g1(m): maths.append(m.group(1)); return " "
    s = re.sub(r"\$\$(.+?)\$\$", g2, s, flags=re.S)
    text = re.sub(r"\$(.+?)\$", g1, s, flags=re.S)
    return text, maths, disp

def norm_text(t):
    t = re.sub(r"!\[\]\(figure\)|\[\^\d+\]:|\^\{\d+\}", " ", t)
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("—", "-").replace("–", "-")
    return " ".join(re.findall(r"[A-Za-z0-9]+", t)).lower()

def _group(m, i):
    """從 i 讀一個上下標參數（平衡大括號、\\指令或單一字元），回傳結束位置。"""
    if i >= len(m): return i
    if m[i] == "{":
        depth = 0
        for j in range(i, len(m)):
            depth += {"{": 1, "}": -1}.get(m[j], 0)
            if depth == 0: return j + 1
        return len(m)
    if m[i] == "\\":
        j = i + 1
        while j < len(m) and m[j].isalpha(): j += 1
        return max(j, i + 2)
    return i + 1

def swap_scripts(m):
    out, i = [], 0
    while i < len(m):
        if m[i] == "^":
            a = _group(m, i + 1)
            if a < len(m) and m[a] == "_":
                b = _group(m, a + 1)
                out.append("_" + m[a + 1:b] + "^" + m[i + 1:a]); i = b; continue
        out.append(m[i]); i += 1
    return "".join(out)

def norm_math(m, keep_font=True):
    m = re.sub(r"\\tag\{[^}]*\}", "", m)
    m = re.sub(r"\\\\\[[^\]]*\]", r"\\\\", m)                 # \\[2ex] 換行間距
    m = re.sub(r"\\(left|right)\.", "", m)                       # 看不見的定界符
    m = swap_scripts(m)                                           # 上下標順序：x^a_b ≡ x_b^a
    m = re.sub(r"\\begin\{[a-z*]+\}|\\end\{[a-z*]+\}|\\left|\\right|\\[bB]igg?[lr]?|\\[,;:! ]|\\q?quad|\\displaystyle|&|\\\\|\s", "", m)
    m = m.replace("\\tfrac", "\\frac").replace("\\dfrac", "\\frac").replace("\\bm{", "\\boldsymbol{").replace("\\pmb{", "\\boldsymbol{")
    m = m.replace("\\dots", "...").replace("\\ldots", "...").replace("\\cdots", "...").replace("\\le", "\\leq").replace("\\leqq", "\\leq")
    m = m.replace("\\ge", "\\geq").replace("\\geqq", "\\geq").replace("\\leqslant", "\\leq")
    if not keep_font:
        m = re.sub(r"\\(mathbf|boldsymbol|mathrm|mathit|textbf|mathscr|mathcal|mathsf|textrm|text|operatorname)\{", "{", m)
    m = m.replace("{", "").replace("}", "")
    return m.rstrip(".,")

sim = lambda a, b: 1 - lev(a, b) / max(len(a), len(b)) if (a or b) else 1.0

def score(out, gt):
    raw = strip_fence(out)
    out = postprocess(out)
    to, mo, do = split(out); tg, mg, dg = split(gt)
    r = {"text_raw": sim(norm_text(split(raw)[0]), norm_text(tg)),
         "text": sim(norm_text(to), norm_text(tg)),
         "math": sim("".join(norm_math(x) for x in mo), "".join(norm_math(x) for x in mg)),
         "math_nf": sim("".join(norm_math(x, False) for x in mo), "".join(norm_math(x, False) for x in mg))}
    on = {norm_math(x, False) for x in do}
    r["disp_ok"] = (sum(norm_math(x, False) in on for x in dg), len(dg))
    tg_ = set(re.findall(r"\\tag\{([^}]*)\}", gt)); to_ = set(re.findall(r"\\tag\{([^}]*)\}", out))
    r["tags"] = (len(tg_ & to_), len(tg_), len(to_ - tg_))
    r["fig"] = (out.count("![]("), gt.count("![]("))
    r["fn"] = (len(re.findall(r"^\[\^\d+\]:", out, re.M)), len(re.findall(r"^\[\^\d+\]:", gt, re.M)))
    r["scr"] = (out.count("\\mathscr"), gt.count("\\mathscr"))
    r["bold"] = (len(re.findall(r"\\mathbf|\\boldsymbol|\\bm\b", out)), len(re.findall(r"\\mathbf|\\boldsymbol", gt)))
    hd = lambda x: [(len(h), norm_text(t)) for h, t in re.findall(r"^(#{1,6})\s+(.+)$", x, re.M)]
    ho, hg = hd(out), hd(gt)
    r["head"] = (sum(h in ho for h in hg), len(hg))
    r["head_any"] = (sum(t in [x for _, x in ho] for _, t in hg), len(hg))
    r["chars"] = len(out)
    return r

def load_out(method, bset, name):
    d = os.path.join(B, "out", method, bset)
    if method == "qwen":
        idx = int(name[1:3])
        f = os.path.join(d, f"p{idx:04d}.json")
        return json.load(open(f))["md"] if os.path.exists(f) else None
    f = os.path.join(d, name + ".md")
    return open(f, encoding="utf-8").read() if os.path.exists(f) else None

def main():
    res = {}
    methods = sorted(os.listdir(os.path.join(B, "out")))
    methods = [m for m in methods if os.path.isdir(os.path.join(B, "out", m))]
    for bset in ("heat", "em"):
        names = sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(B, bset, "gt", "*.md")))
        if not names: continue
        print(f"\n== {bset}（{len(names)} 頁標準答案）")
        print(f"{'method':8} {'n':>2} {'raw':>6} {'text':>6} {'math':>6} {'math_nf':>7} {'disp_ok':>8} {'tags':>8} {'fig':>6} {'fn':>5} {'head':>6} {'h_any':>6} {'scr':>7} {'bold':>8}")
        for m in methods:
            rows = []
            for n in names:
                o = load_out(m, bset, n)
                if o is not None:
                    rows.append((n, score(o, open(os.path.join(B, bset, "gt", n + ".md"), encoding="utf-8").read())))
            if not rows: continue
            res.setdefault(bset, {})[m] = {n: r for n, r in rows}
            avg = lambda k: sum(r[k] for _, r in rows) / len(rows)
            tot = lambda k, i: sum(r[k][i] for _, r in rows)
            print(f"{m:8} {len(rows):2} {avg('text_raw'):6.3f} {avg('text'):6.3f} {avg('math'):6.3f} {avg('math_nf'):7.3f} "
                  f"{tot('disp_ok',0):>3}/{tot('disp_ok',1):<4} {tot('tags',0):>3}/{tot('tags',1):<4} "
                  f"{tot('fig',0):>2}/{tot('fig',1):<3} {tot('fn',0):>2}/{tot('fn',1):<2} {tot('head',0):>2}/{tot('head',1):<3} {tot('head_any',0):>2}/{tot('head_any',1):<3} {tot('scr',0):>3}/{tot('scr',1):<3} {tot('bold',0):>3}/{tot('bold',1):<4}")
    if "--json" in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index("--json") + 1], "w"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
