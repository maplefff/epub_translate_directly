"""譯本 EPUB → 可列印 PDF。

  read_translated_epub → prepare → layout（依紙張自動算版型）→ typst compile → 逐頁驗證

輸入是 `python -m epubtrans build` 產出的譯本 EPUB，輸出放在同一個目錄：
《中文書名 原文書名》（B5）.pdf；加 --tone 是夜讀的黃底版，（B5 Light night）.pdf；
預設是書本式（內側留寬、對頁鏡像）；加 --document 是左右等寬的文件式，（B5 Document）.pdf。每種紙張一份，不做縮放版或拼版 ——
要印在哪種紙上，就用那種紙排一次，列印時選「實際大小／100%」。

中間產物在 work/print/{紙張[-色調][-document]}/：content.json（書稿結構）、config.json（版型數字）、
book.typ。排版跑壞時先看那兩個 JSON —— 多半是結構抽錯，不是版面規則寫錯。
"""
import json, os, shutil, subprocess, sys
from . import layout, mathcheck, pagecheck
from .content import prepare, read_translated_epub

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "typst", "book.typ")
TYPST = shutil.which("typst") or "/opt/homebrew/bin/typst"


def paths(cfg, paper, tone=None, style=None):
    label, work = layout.PAPERS[paper][2], paper
    t = layout.tone(tone)
    if t:
        label += " " + t["label"]
        work += "-" + tone
    if style == "document":
        label += " Document"
        work += "-document"
    pdf = os.path.join(cfg.dir, f"{cfg.output_basename()}（{label}）.pdf")
    return pdf, cfg.wpath("print", work)


def run(cfg, paper, cli=None, tone=None):
    paper = layout.paper(paper)
    epub = cfg.output_epub()
    if not os.path.exists(epub):
        raise SystemExit(f"找不到譯本 EPUB：{epub}\n先跑 `python -m epubtrans build \"{cfg.name}\"`")
    if not os.path.exists(TYPST):
        raise SystemExit("找不到 typst，先 `brew install typst`")
    pcfg = layout.load(paper, cfg.raw.get("print"), cli, tone)
    # 書名頁底部的聲明（預設在 print_profile.yaml）代入翻譯模型；
    # 原書已是中文、沒有 book.translator 時，含 {translator} 的預設聲明不印
    if "{translator}" in (pcfg.get("imprint") or "") and not cfg.translator:
        pcfg["imprint"] = ""
    pcfg["imprint"] = cfg.fill_translator(pcfg.get("imprint") or "")
    pdf, work = paths(cfg, paper, tone, pcfg.get("style"))
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)

    print(layout.summary(pcfg))
    book = read_translated_epub.run(epub, work, pcfg.get("inline_images"))
    book = prepare.run(book, pcfg)
    mathcheck.run(book, work, TYPST)
    json.dump(book, open(os.path.join(work, "content.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(layout.to_typst(pcfg, book["meta"], book.get("cover")),
              open(os.path.join(work, "config.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    shutil.copy(TEMPLATE, os.path.join(work, "book.typ"))
    shutil.copy(mathcheck.MATH_TYP, os.path.join(work, "math.typ"))

    r = subprocess.run([TYPST, "compile", "--root", work, os.path.join(work, "book.typ"), pdf],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        raise SystemExit("Typst 編譯失敗（上面是它的錯誤訊息）")
    if r.stderr.strip():
        print(r.stderr.strip())

    from pypdf import PdfReader
    n = len(PdfReader(pdf).pages)
    print(f"寫入 {pdf}　（{n} 頁，{os.path.getsize(pdf) / 1024:.0f} KB）")
    if pagecheck.run(work, pdf):
        raise SystemExit(1)


def check(cfg, paper, tone=None, style=None):
    paper = layout.paper(paper)
    pdf, work = paths(cfg, paper, tone, style)
    if not os.path.exists(pdf):
        raise SystemExit(f"找不到 {pdf}\n先跑 `python -m epubtrans pdf \"{cfg.name}\" --paper {paper}`")
    if pagecheck.run(work, pdf):
        raise SystemExit(1)
