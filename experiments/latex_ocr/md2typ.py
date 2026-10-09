"""測試用：VLM 的 markdown → Typst（mitex 排公式、\\tag 排到右側）。"""
import re, sys
def fix(m):
    m = m.replace("\\boldsymbol{\\mathscr{r}}", "\\mathbfscrr").replace("\\mathscr{r}", "\\mathcal{r}")
    return m
def inline(t):
    out, pos = [], 0
    for mm in re.finditer(r"\$(.+?)\$", t):
        out.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"_\1_", t[pos:mm.start()])).replace("#", "\\#"))
        out.append("#mi(`" + fix(mm.group(1)) + "`)"); pos = mm.end()
    out.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"_\1_", t[pos:])))
    return "".join(out)
src = open(sys.argv[1]).read()
body = ['#import "@preview/mitex:0.2.7": mi, mitex',
        '#set page(width: 182mm, height: 257mm, margin: 18mm)',
        '#set text(font: ("Charter", "Songti TC"), size: 10pt)', '#set par(justify: true)',
        '#let mathbfscrr = text(weight: "bold")[$cal(r)$]',
        '#let deq(n, body) = grid(columns: (1fr, auto), align: (center + horizon, right + horizon), body, [(#n)])']
src = re.sub(r"\$\$(.+?)\$\$", lambda m: "\n\x00" + m.group(1).replace("\n", " ") + "\x00\n", src, flags=re.S)
lines = [l.strip() for l in src.splitlines() if l.strip() and l.strip() != "---"]
for blk in lines:
    blk = blk.replace("\x00", "$$")
    if blk.startswith("$$"):
        m = blk.strip("$").strip(); tag = re.search(r"\\tag\{([^}]*)\}", m); m = re.sub(r"\\tag\{[^}]*\}", "", m)
        eq = "mitex(`" + fix(m) + "`)"
        body.append(f"#deq([{tag.group(1)}], {eq})" if tag else f"#{eq}")
    elif blk.startswith("!["): body.append('#rect(width: 40%, height: 2.5cm, stroke: 0.5pt + gray)[#align(center + horizon)[圖]]')
    elif blk.startswith("#"):
        lv = len(blk) - len(blk.lstrip("#")); body.append("=" * lv + " " + inline(blk.lstrip("# ")))
    else: body.append(inline(blk))
    body.append("")
open(sys.argv[2], "w").write("\n".join(body))
