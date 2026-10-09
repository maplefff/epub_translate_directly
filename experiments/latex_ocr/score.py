"""對 gt/ 的三頁評分：正文文字、公式（含粗體）、公式（去掉字體）、草寫 r、粗體向量。"""
import re, sys, os, glob
from rapidfuzz.distance import Levenshtein as L

HDR = re.compile(r"^\s*(\d+\s+)?(\d+(\.\d+)*\.?\s+)?(CHAPTER\s+\d+\.?.*|[0-9.]+\s+[A-Z][A-Z .,'-]{6,})(\s+\d+)?\s*$")

def unify(s):
    s = re.sub(r"<\|det\|>(header|page_number)[^<]*<\|/det\|>[^\n]*", "", s)
    s = re.sub(r"<\|det\|>[^<]*<\|/det\|>", "\n", s)
    s = s.replace("\\(", "$").replace("\\)", "$")
    s = re.sub(r"\\\[(.*?)\\\]", lambda m: "$$" + m.group(1) + "$$", s, flags=re.S)
    lines = [l for l in s.splitlines() if not HDR.match(l.strip()) and not re.fullmatch(r"\s*\d{1,3}\s*", l)]
    return "\n".join(lines)

def split(s):
    s = unify(s)
    maths = []
    def grab(m):
        maths.append(m.group(1) or m.group(2)); return " "
    text = re.sub(r"\$\$(.+?)\$\$|\$(.+?)\$", grab, s, flags=re.S)
    return text, maths

def norm_text(t):
    t = re.sub(r"[*#_`>|]|^-{3,}", " ", t, flags=re.M)
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("—", "-")
    return " ".join(re.findall(r"[A-Za-z0-9]+", t)).lower()

def norm_math(m, keep_font=True):
    m = re.sub(r"\\tag\{[^}]*\}|\\begin\{[a-z*]+\}|\\end\{[a-z*]+\}|\\left|\\right|\\[,;:! ]|\\quad|\\qquad|&|\\\\|\s", "", m)
    m = re.sub(r"\(\d+\.\d+\)$", "", m)
    m = m.replace("\\bm{", "\\boldsymbol{").replace("\\pmb{", "\\boldsymbol{").replace("\\bf{", "\\mathbf{")
    m = m.replace("\\boldsymbol{\\mathscr", "\\mathbf{\\mathscr")
    if not keep_font:
        m = re.sub(r"\\(mathbf|boldsymbol|mathrm|mathit|textbf|bm|mathscr|mathcal)\{", "{", m)
    m = m.replace("{", "").replace("}", "")
    m = m.replace("\\dots", "...").replace("\\ldots", "...").rstrip(".,")
    return m

def sim(a, b):
    return 1 - L.normalized_distance(a, b)

def score(out, gt):
    to, mo = split(out); tg, mg = split(gt)
    r = {}
    r["text"] = sim(norm_text(to), norm_text(tg))
    r["math"] = sim("".join(norm_math(x) for x in mo), "".join(norm_math(x) for x in mg))
    r["math_nofont"] = sim("".join(norm_math(x, False) for x in mo), "".join(norm_math(x, False) for x in mg))
    r["scr"] = (out.count("\\mathscr"), gt.count("\\mathscr"))
    r["bold"] = (len(re.findall(r"\\mathbf|\\boldsymbol|\\bm\b", out)), len(re.findall(r"\\mathbf|\\boldsymbol", gt)))
    r["nmath"] = (len(mo), len(mg))
    return r

tags = sys.argv[1:] or sorted(os.path.basename(d) for d in glob.glob("out/*"))
print(f"{'model':10} {'text':>6} {'math':>6} {'m-nofont':>8} {'𝓇 got/gt':>9} {'bold got/gt':>11}  per page math")
for tag in tags:
    rows = []
    for p in ["p030", "p060", "p515"]:
        f = f"out/{tag}/{p}.md"
        if os.path.exists(f):
            rows.append((p, score(open(f).read(), open(f"gt/{p}.md").read())))
    if not rows: continue
    avg = lambda k: sum(r[k] for _, r in rows) / len(rows)
    sc = (sum(r["scr"][0] for _, r in rows), sum(r["scr"][1] for _, r in rows))
    bd = (sum(r["bold"][0] for _, r in rows), sum(r["bold"][1] for _, r in rows))
    pp = " ".join(f"{p}:{r['math']:.2f}" for p, r in rows)
    print(f"{tag:10} {avg('text'):6.3f} {avg('math'):6.3f} {avg('math_nofont'):8.3f} {sc[0]:>4}/{sc[1]:<4} {bd[0]:>5}/{bd[1]:<5}  {pp}  (n={len(rows)})")
