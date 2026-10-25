#!/usr/bin/env python3
"""用一本英文書的 book.json（預設 tests/fixtures/non_stop/：《不停 Non-Stop》約 20 頁的節錄，進版控）
產生兩份測試用 PDF 與標準答案：

  process/{原文書名} PDF/{原文書名}.pdf           有文字層、有書籤的英文平裝書（版面見 english_book.typ）
  process/{原文書名} Scan/{原文書名} (scan).pdf   同一本書逐頁點陣化成純圖片：模擬掃描書，沒有文字層、沒有書籤

測試書用原文書名（book.json 的 title，可用 --name 改）命名，不沿用書本目錄名：
書本目錄是《…》開頭，PDF 檔名若也以《開頭，會被當成產出而不算原檔。

加 --style b 改產生版面 B（english_book_b.typ：段落不縮排、靠左不對齊、章不換頁、沒有書籤、
有引文與清單），輸出到 process/{原文書名} PDF B/ 與 process/{原文書名} Scan B/，用來確認規則沒有只貼合一種版面。

兩個目錄各放一份 fixture.json（標準答案）與 system_prompts.yaml，tests/test_import_pdf.py 拿它們比對。
標準答案＝原 EPUB 抽出的 book.json，再加上這裡人為插入的註腳與插圖。
產物全部放在 process/（不進版控）；要重建就重跑這支。

用法：./.venv/bin/python tests/fixtures/make_test_pdfs.py [書本目錄] [--name 測試書名] [--dpi 250] [--style b]
      不給書本目錄＝用 tests/fixtures/non_stop/ 的節錄；給的話讀 process/{書本目錄}/work/（先跑過 extract）
"""
import argparse, json, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pymupdf
from epubtrans.core.config import PROCESS, SETTINGS, safe_filename

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = {"a": os.path.join(HERE, "english_book.typ"), "b": os.path.join(HERE, "english_book_b.typ")}
TYPST = shutil.which("typst") or "/opt/homebrew/bin/typst"

# 人為插入的註腳：(第幾個正文章, 第幾段) → 註腳文字。文字是測試自己寫的，不是原書內容。
# 位置都落在節錄（6 個正文章，每章 22 段）的範圍內
EXCERPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "non_stop")
FOOTNOTES = {
    (0, 10): "The ship's surviving logs give the length of a watch as roughly eight hours.",
    (1, 18): "Quarters is the name the tribe uses for its own territory, not for the whole deck.",
    (2, 12): "Contemporary reviewers compared this passage to the closing chapters of an earlier voyage novel, "
              "and the comparison is long enough to wrap onto a second line of the footnote area.",
    (4, 8): "Ponics: the hydroponic growth that has overrun most of the corridors.",
    (5, 15): "See the author's preface for the changes made to this edition.",
}
FIGURE_AT = (1, 15)          # 第 2 個正文章的第 15 段之後插一張圖（沿用封面圖）
# 版面 B 另外插入的引文與清單（第 2 個正文章），文字同樣是測試自己寫的
QUOTE_AT = (1, 5)
QUOTE = ("The ship was designed to be self-sufficient for many generations; its builders assumed that "
         "the knowledge needed to run it would be handed down intact, and that assumption proved to be "
         "the weakest part of the whole design.")
LIST_AT = (1, 8)
LIST = ["the corridors overgrown with ponics", "the barricades that mark the end of Quarters",
        "the rumoured Giants moving between decks"]


def sections_from_book(book, style="a"):
    """EPUB 的章節 → 排版用的區段：front / contents / part / chapter / back。"""
    chs = [c for c in book["chapters"] if not all(it["type"] == "image" for it in c["items"])]
    is_part = lambda c: c["level"] == 1 and len(c["items"]) == 1 and c["items"][0]["type"] == "heading"
    first_part = next(i for i, c in enumerate(chs) if is_part(c))
    last_body = max(i for i, c in enumerate(chs) if c["level"] == 2)
    out, n_chapter = [], 0
    for i, c in enumerate(chs):
        if i == first_part:
            out.append({"kind": "contents"})
        if is_part(c):
            out.append({"kind": "part", "title": c["title"], "subtitle": c["items"][0]["text"]})
        elif c["level"] == 2:
            items = []
            for k, it in enumerate([x for x in c["items"] if x["type"] != "image"]):
                it = {"type": it["type"], "text": it["text"]}
                para_no = sum(1 for x in items if x["type"] == "para")
                if it["type"] == "para" and (n_chapter, para_no) in FOOTNOTES:
                    it["footnote"] = FOOTNOTES[(n_chapter, para_no)]
                items.append(it)
                if (n_chapter, para_no) == FIGURE_AT and it["type"] == "para":
                    items.append({"type": "image", "file": book["cover"]})
                if style == "b" and it["type"] == "para" and (n_chapter, para_no) == QUOTE_AT:
                    items.append({"type": "quote", "text": QUOTE})
                if style == "b" and it["type"] == "para" and (n_chapter, para_no) == LIST_AT:
                    items.extend({"type": "li", "text": t} for t in LIST)
            out.append({"kind": "chapter", "title": c["title"], "items": items})
            n_chapter += 1
        else:
            kind = "front" if i < first_part else "back"
            assert i < first_part or i > last_body
            items = [{"type": "para" if it["type"] == "para" else "center", "text": it["text"]}
                     for it in c["items"] if it["type"] != "image"]
            out.append({"kind": kind, "items": items})
    return out


def expected(sections):
    """標準答案：依閱讀順序的區段，各帶應出現的文字（註腳另列，應收在該章結尾）。"""
    exp = []
    for s in sections:
        if s["kind"] == "contents":
            continue
        if s["kind"] == "part":
            exp.append({"kind": "part", "title": s["title"], "texts": [s["subtitle"]], "footnotes": []})
        else:
            exp.append({"kind": s["kind"], "title": s.get("title"),
                        "texts": [it["text"] for it in s["items"] if it["type"] != "image"],
                        "images": sum(it["type"] == "image" for it in s["items"]),
                        "quotes": sum(it["type"] == "quote" for it in s["items"]),
                        "lists": sum(it["type"] == "li" for it in s["items"]),
                        "footnotes": [it["footnote"] for it in s["items"] if "footnote" in it]})
    return exp


def write_config(bookdir, name, source, title, author):
    tpl = open(os.path.join(SETTINGS, "system_prompts.template.yaml"), encoding="utf-8").read()
    tpl = tpl.replace("{name}", name).replace("{src}", source)
    tpl = tpl.replace('  title: "' + name + '"', f'  title: "{title}"').replace('  author: ""', f'  author: "{author}"')
    with open(os.path.join(bookdir, "system_prompts.yaml"), "w", encoding="utf-8") as f:
        f.write(tpl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book", nargs="?", help="process/ 底下已 extract 的書本目錄；省略＝用 tests/fixtures/non_stop/ 的節錄")
    ap.add_argument("--name", help="測試書目錄與 PDF 的名稱；預設用原文書名")
    ap.add_argument("--dpi", type=int, default=250, help="掃描版的解析度")
    ap.add_argument("--style", choices=["a", "b"], default="a", help="a：小說版面（預設）；b：非小說版面")
    a = ap.parse_args()
    suffix = "" if a.style == "a" else " B"
    src = os.path.join(PROCESS, a.book, "work") if a.book else EXCERPT
    book = json.load(open(os.path.join(src, "book.json"), encoding="utf-8"))
    sections = sections_from_book(book, a.style)
    name = a.name or safe_filename(book["title"])

    text_dir = os.path.join(PROCESS, f"{name} PDF{suffix}")
    scan_dir = os.path.join(PROCESS, f"{name} Scan{suffix}")
    build = os.path.join(text_dir, "work", "fixture_build")
    # 整個 work/ 清掉：OCR 快取（work/ocr/pNNNN.json）只依頁碼存，換了來源書或節錄範圍會沿用到別頁的結果
    for d in (text_dir, scan_dir):
        shutil.rmtree(os.path.join(d, "work"), ignore_errors=True)
    os.makedirs(os.path.join(build, "images"))
    os.makedirs(scan_dir, exist_ok=True)
    shutil.copy(os.path.join(src, "images", book["cover"]), os.path.join(build, "images", book["cover"]))
    content = {"title": book["title"], "author": book["author"], "cover": book["cover"], "sections": sections}
    json.dump(content, open(os.path.join(build, "content.json"), "w", encoding="utf-8"), ensure_ascii=False)
    shutil.copy(TEMPLATES[a.style], os.path.join(build, "book.typ"))

    pdf = os.path.join(text_dir, f"{name}.pdf")
    r = subprocess.run([TYPST, "compile", "--root", build, os.path.join(build, "book.typ"), pdf],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    doc = pymupdf.open(pdf)
    print(f"文字層版：{pdf}（{len(doc)} 頁，書籤 {len(doc.get_toc())} 筆）")

    scan_pdf = os.path.join(scan_dir, f"{name} (scan).pdf")
    out = pymupdf.open()
    for page in doc:
        pix = page.get_pixmap(dpi=a.dpi, colorspace=pymupdf.csGRAY)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=pix.tobytes("jpg", jpg_quality=75))
    out.save(scan_pdf, garbage=3, deflate=True)
    print(f"掃描版：{scan_pdf}（{len(out)} 頁，{a.dpi} dpi，{os.path.getsize(scan_pdf) / 1e6:.0f} MB）")

    exp = {"source_book": a.book or os.path.relpath(EXCERPT, ROOT), "pages": len(doc), "sections": expected(sections)}
    for d, source in ((text_dir, os.path.basename(pdf)), (scan_dir, os.path.basename(scan_pdf))):
        json.dump(exp, open(os.path.join(d, "fixture.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        write_config(d, os.path.basename(d), source, book["title"], book["author"])
        os.makedirs(os.path.join(d, "drafts"), exist_ok=True)
    n = sum(len(s["texts"]) for s in exp["sections"])
    print(f"標準答案：{len(exp['sections'])} 個區段、{n} 段文字、"
          f"{sum(len(s['footnotes']) for s in exp['sections'])} 個註腳、"
          f"{sum(s.get('images', 0) for s in exp['sections'])} 張插圖")


if __name__ == "__main__":
    main()
