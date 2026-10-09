"""LaTeX 公式（掃描數學書，pdf.mode: vlm）的共用處理：EPUB 的 MathML、行內式切分。

公式在 book.json 裡有兩種：獨立公式是 {"type": "math", "text": LaTeX, "tag": "1.83"}；行內式以 $…$ 留在段落文字裡。
EPUB 用 temml（Node，epubtrans/output/js/）轉成 MathML，MathML 的 annotation 附上 TeX 原文；
PDF 端讀譯本 EPUB 時從 annotation 取回 LaTeX，交給 Typst 的 mitex 排。
"""
import html, json, os, re, shutil, subprocess

JS = os.path.join(os.path.dirname(__file__), "js")
INLINE = re.compile(r"\$(.+?)\$")
# temml 不支援粗體草寫（\boldsymbol{\mathscr{r}} 會排成細體 𝓇）：先換成 Unicode 粗體草寫字母
_BOLD_SCR = re.compile(r"\\(?:boldsymbol|mathbf|bm|pmb)\s*\{\s*\\mathscr\s*\{\s*([A-Za-z])\s*\}\s*\}")
_SCR_BOLD = {**{c: chr(0x1D4D0 + i) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
             **{c: chr(0x1D4EA + i) for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}}


def split_inline(text):
    """段落文字 → [(是否公式, 片段)]；公式片段不含 $。"""
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def has_math(book):
    return any(it["type"] == "math" or "$" in (it.get("text") or "")
               for c in book["chapters"] for it in c["items"])


def _prep(tex):
    return _BOLD_SCR.sub(lambda m: "\\text{" + _SCR_BOLD[m.group(1)] + "}", tex)


# 公式裡的英文說明（\text{for points inside the sphere,}、\text{(Gauss's law)}）：公式不進逐段譯稿，
# 譯名寫在 drafts/math_text.yaml，build 時代換。text: 是一般位置的說明文字；sub: 是上下標裡要譯的片語
# （∫ 下的 all space 之類）；whole: 是語序得整條改寫的公式（原文 TeX → 譯過的 TeX）。
# 沒列的照原文，所以 E_{\text{above}} 這種符號名稱的下標維持英文。
MATH_TEXT = "math_text.yaml"
_TEXT_CMD = re.compile(r"\\(text|textrm|textbf|textit|mbox)\s*\{([^{}]*)\}")


def load_text_table(cfg):
    path = os.path.join(cfg.drafts, MATH_TEXT)
    if not os.path.exists(path):
        return {}
    import yaml
    t = yaml.safe_load(open(path, encoding="utf-8")) or {}
    return {"text": t.get("text") or {}, "sub": t.get("sub") or {}, "whole": t.get("whole") or {}}


def localize(tex, table):
    """把公式裡 \\text{…} 的英文換成 math_text.yaml 的譯文；前後空白照留（決定和符號之間的間距）。"""
    if not table:
        return tex
    if tex.strip() in table["whole"]:
        return table["whole"][tex.strip()]

    def one(m):
        body = m.group(2)
        in_script = re.search(r"[_^]\s*\{?\s*$", tex[:m.start()]) is not None
        zh = table["sub" if in_script else "text"].get(body.strip())
        if zh is None:
            return m.group(0)
        lead, trail = body[:len(body) - len(body.lstrip())], body[len(body.rstrip()):]
        return f"\\{m.group(1)}{{{lead}{zh}{trail}}}"
    return _TEXT_CMD.sub(one, tex)


def to_mathml(pairs, text_table=None):
    """[(tex, display)] → {(tex, display): MathML 或 None}。一次呼叫 node 轉完整本書。
    text_table（load_text_table）：公式裡的英文說明換成譯文再轉；回傳的 key 仍是原文 TeX。"""
    pairs = sorted(set(pairs))
    if not pairs:
        return {}
    node = shutil.which("node")
    if not node or not os.path.isdir(os.path.join(JS, "node_modules", "temml")):
        raise SystemExit("書裡有 LaTeX 公式，EPUB 要用 temml 轉成 MathML：\n"
                         f"  brew install node && npm install --prefix {JS}")
    local = [localize(t, text_table) for t, d in pairs]
    r = subprocess.run([node, os.path.join(JS, "tex2mathml.mjs")], cwd=JS, capture_output=True, text=True,
                       input=json.dumps([{"tex": _prep(t), "display": d} for t, (_, d) in zip(local, pairs)]))
    if r.returncode:
        raise SystemExit(f"temml 轉換失敗：{r.stderr[-2000:]}")
    out = {}
    for (tex, d), lt, mml in zip(pairs, local, json.loads(r.stdout)):
        if mml is not None and "color:#b22222" in mml:
            mml = None            # temml 不認得的指令會排成紅字而不報錯：當成轉不了
        if mml is not None:       # annotation 放（譯過說明文字的）TeX，前處理只為了排版；PDF 從這裡取回公式
            mml = re.sub(r'(<annotation encoding="application/x-tex">).*?(</annotation>)',
                         lambda m: m.group(1) + html.escape(lt, quote=False) + m.group(2), mml, flags=re.S)
        out[(tex, d)] = mml
    return out


# EPUB 嵌入的數學字型：MathML 要有 OpenType MATH 表的字型，括號、根號、積分號才拉得高。
# STIX Two Math（SIL OFL，可嵌入）macOS 內建；temml 附的 Temml-STIX2.css 是對應的排版規則。
MATH_FONT = "/System/Library/Fonts/Supplemental/STIXTwoMath.otf"


def epub_font_and_css():
    """回傳 (字型檔 bytes 或 None, 要加進 CSS 的規則)。字型路徑相對於 style/main.css。"""
    css_path = os.path.join(JS, "node_modules", "temml", "dist", "Temml-STIX2.css")
    css = open(css_path, encoding="utf-8").read() if os.path.exists(css_path) else ""
    css = re.sub(r"@font-face\s*\{.*?\}", "@font-face{font-family:STIX2;src:url('../fonts/STIXTwoMath.otf');}",
                 css, count=1, flags=re.S)
    font = open(MATH_FONT, "rb").read() if os.path.exists(MATH_FONT) else None
    return font, css
