"""把參考答案與各模型的 OCR 輸出排成一份 PDF，供肉眼比對。

在 process/_latex_ocr_test/ 底下執行：python make_compare_pdf.py
讀 pages/、gt/、out/，寫 compare/（中間檔）與 OCR比對.pdf。
模型輸出一字不改：排版檢視只為了顯示而辨認公式分隔符號；每頁另附原始輸出。
排不出來的公式在排版檢視裡標紅，照原樣列出原始碼。
"""
import json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

PAGES = [("p030", "原書第 15 頁"), ("p060", "原書第 45 頁"), ("p515", "原書第 500 頁")]
MODELS = [  # (目錄, 名稱, 說明)
    ("qwen27", "Qwen3.5-27B（v1 提示）", "mlx-community/Qwen3.5-27B-8bit，整頁轉寫，提示詞 v1"),
    ("q27v2", "Qwen3.5-27B（v2 提示）", "mlx-community/Qwen3.5-27B-8bit，整頁轉寫，提示詞 v2"),
    ("q122", "Qwen3.5-122B-A10B（v1 提示）", "mlx-community/Qwen3.5-122B-A10B-4bit，整頁轉寫，提示詞 v1"),
    ("q122v2", "Qwen3.5-122B-A10B（v2 提示）", "mlx-community/Qwen3.5-122B-A10B-4bit，整頁轉寫，提示詞 v2"),
    ("q38", "Qwen3.8-27B", "lmstudio-community/Qwen3.8-27B-MLX-8bit，整頁轉寫，提示詞 v1"),
    ("q36", "Qwen3.6-35B-A3B", "mlx-community/Qwen3.6-35B-A3B-8bit，整頁轉寫，提示詞 v1"),
    ("fnext", "Qwen3.8-Flash-Next（REAP-288 剪枝版）", "sh0wie/Qwen3.8-Flash-Next-REAP-288-MLX-4bit，整頁轉寫，提示詞 v1"),
    ("gemma4", "Gemma-4-26B-A4B", "mlx-community/gemma-4-26b-a4b-it-8bit，整頁轉寫，提示詞 v1"),
    ("glm2", "GLM-OCR（兩段式）", "PP-DocLayout-V3 切區塊，mlx-community/GLM-OCR-bf16 逐塊辨識（Text Recognition: ／ Formula Recognition:）。"
     "注意，切塊與組裝是 Claude 寫的測試程式：版面信心門檻 0.5，第 15 頁有 3 行小題沒被偵測到而漏掉；"
     "公式編號區塊沒有送去辨識，所以沒有編號；標題前的「## 」是程式加的。"),
    ("unlim", "Unlimited-OCR", "mlx-community/Unlimited-OCR-bf16，整頁，提示詞「document parsing.」（輸出含版面框標記）"),
    ("dots", "dots.ocr", "mlx-community/dots.ocr-bf16，整頁，提示詞「Extract the text content from this image.」"),
]

DISPLAY = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
INLINE = re.compile(r"\$(.+?)\$|\\\((.+?)\\\)")
DET = re.compile(r"<\|det\|>(.*?)<\|/det\|>")
SUP = re.compile(r"<sup>(.*?)</sup>")


def prep_math(tex):
    """只為排版：抽出 \\tag、把 mitex 不認的 \\mathscr 換成 \\mathcal。原始碼另外照原樣顯示。"""
    tags = re.findall(r"\\tag\s*\{([^}]*)\}", tex)
    tex = re.sub(r"\\tag\s*\{[^}]*\}", "", tex).replace("\\mathscr", "\\mathcal").strip()
    return tex, (tags[-1] if tags else None)


def inline_segs(line, formulas):
    """一行文字 → 片段：文字（帶粗斜體狀態）、行內公式、上標、版面框標記。"""
    segs, bold, ital = [], False, False
    pos = 0
    tokens = []
    for m in re.finditer(INLINE.pattern + r"|" + DET.pattern + r"|" + SUP.pattern, line):
        tokens.append(("t", line[pos:m.start()]))
        if m.group(1) is not None or m.group(2) is not None:
            tokens.append(("m", m.group(1) if m.group(1) is not None else m.group(2)))
        elif m.group(3) is not None:
            tokens.append(("det", m.group(3)))
        else:
            tokens.append(("sup", m.group(4)))
        pos = m.end()
    tokens.append(("t", line[pos:]))
    for kind, v in tokens:
        if kind == "m":
            tex, _ = prep_math(v)
            formulas.add(tex)
            segs.append({"k": "m", "v": tex, "src": v})
        elif kind in ("det", "sup"):
            segs.append({"k": kind, "v": v})
        else:
            for part in re.split(r"(\*\*|(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*]))", v):
                if part == "**":
                    bold = not bold
                elif part == "*":
                    ital = not ital
                elif part:
                    segs.append({"k": "t", "v": part, "b": bold, "i": ital})
    return segs


def parse(src, formulas):
    blocks, pos = [], 0
    def text_blocks(chunk):
        for line in chunk.splitlines():
            s = line.strip()
            if not s:
                continue
            if re.fullmatch(r"-{3,}", s):
                blocks.append({"k": "hr"}); continue
            if re.match(r"!\[[^\]]*\]\([^)]*\)", s):
                blocks.append({"k": "fig", "v": s}); continue
            h = re.match(r"(#{1,6})\s+(.*)", s)
            if h:
                blocks.append({"k": "h", "lv": len(h.group(1)), "segs": inline_segs(h.group(2), formulas)}); continue
            s = re.sub(r"^\*\s{2,}", "• ", s)
            blocks.append({"k": "p", "segs": inline_segs(s, formulas)})
    for m in DISPLAY.finditer(src):
        text_blocks(src[pos:m.start()])
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        tex, tag = prep_math(raw)
        formulas.add(tex)
        blocks.append({"k": "eq", "v": tex, "tag": tag})
        pos = m.end()
    text_blocks(src[pos:])
    return blocks


def check_formulas(formulas, d):
    """每條公式單獨用 Typst＋mitex 編一次，編不過的在排版檢視裡改列原始碼。"""
    os.makedirs(d, exist_ok=True)
    fl = sorted(formulas)
    def one(i):
        json.dump({"f": fl[i]}, open(f"{d}/f{i}.json", "w"), ensure_ascii=False)
        open(f"{d}/f{i}.typ", "w").write(
            f'#import "@preview/mitex:0.2.7": mitex\n#let d = json("f{i}.json")\n#mitex(d.f)\n')
        r = subprocess.run(["typst", "compile", f"{d}/f{i}.typ", f"{d}/f{i}.pdf"], capture_output=True)
        return fl[i], r.returncode == 0
    with ThreadPoolExecutor(12) as ex:
        ok = dict(ex.map(one, range(len(fl))))
    return ok


def mark(blocks, ok):
    for b in blocks:
        if b["k"] == "eq":
            b["ok"] = ok[b["v"]]
        for s in b.get("segs", []):
            if s["k"] == "m":
                s["ok"] = ok[s["v"]]


def main():
    formulas = set()
    sections = [{"title": "參考答案", "desc": "由 Claude 看原書掃描頁人工轉寫（Markdown＋LaTeX），可能有誤，請和前面的原書掃描頁對照。",
                 "pages": [{"label": lab, "blocks": parse(open(f"gt/{p}.md").read(), formulas),
                            "raw": open(f"gt/{p}.md").read()} for p, lab in PAGES]}]
    for tag, name, desc in MODELS:
        stats = {}
        if os.path.exists(f"out/{tag}/_stats.json"):
            stats = json.load(open(f"out/{tag}/_stats.json"))
        pages = []
        for p, lab in PAGES:
            raw = open(f"out/{tag}/{p}.md").read()
            sec = stats.get(p, {}).get("sec")
            pages.append({"label": lab + (f"（{sec} 秒）" if sec else ""), "blocks": parse(raw, formulas), "raw": raw})
        sections.append({"title": name, "desc": desc, "pages": pages})
    ok = check_formulas(formulas, "compare/formulas")
    for s in sections:
        for pg in s["pages"]:
            mark(pg["blocks"], ok)
    bad = sum(1 for v in ok.values() if not v)
    print(f"公式 {len(ok)} 條，排不出來 {bad} 條")
    data = {"scans": [{"label": lab, "img": f"../pages/{p}.png"} for p, lab in PAGES], "sections": sections,
            "prompts": {"v1": open("prompt_general.txt").read(), "v2": open("prompt_v2.txt").read()}}
    json.dump(data, open("compare/data.json", "w"), ensure_ascii=False, indent=1)
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = os.path.join(here, "compare.typ")
    open("compare/compare.typ", "w").write(open(tpl).read())
    r = subprocess.run(["typst", "compile", "--root", ".", "compare/compare.typ", "OCR比對.pdf"], capture_output=True, text=True)
    print(r.stderr[-3000:] if r.returncode else "→ OCR比對.pdf")
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
