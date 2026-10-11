#!/usr/bin/env python3
"""端到端：合成一本小 EPUB，走完 extract → merge → build → pdf（含逐頁驗證）。

釘住的是「書的結構」這一層的行為，每一條都曾經是真實的書踩到的坑：
  - 原書封面頁引用的就是封面圖：抽取時不另存一份，build 讓它直接當譯本封面、
    排在目錄之前，不再多一張 ebooklib 產生的封面或一頁只有「封面」二字的空白頁。
  - 章標題同一個 class、層級卻不同（第一章在第一部之前，與各部同層）：
    extract.chapter_levels 按 id 覆寫；PDF 用 print.chapter_ids 讓它照正文章排版。
  - 注號：譯稿用上標數字（¹），EPUB 轉 <sup>，PDF 由 Typst super 排，行距不能被撐開。
  - 半書名頁的章名就是書名：PDF 的逐頁驗證不能把排版產生的書名頁當成它的起始頁。
  - 章內小標在多頁的章中間：不能讓那一頁沒有書眉、也不能變成後面各頁的書眉，
    小標後的正文要回到行距格線上；正文頁的上標注號不能被量成一行。
  - 內文插圖：PDF 端要找得到 EPUB 裡的圖（路徑相對於 XHTML，不是 OPF）。
  - 圖說跟著圖：EPUB 放進同一個 <figure>，PDF 排在同一頁；直式窄圖不能依寬度放大到
    超出版心（House of Debt 的圖 2.2 被放到 316mm 高，上下被切）。
  - 圖列（掃描數學書裡各有圖說的並排圖，book.json 的 figrow）：EPUB 是 div.figrow 裡的幾個 <figure>，
    圖說依序進各自的 <figure>；PDF 並排在同一頁、同一高度。
  - print.image_float: false（掃描數學書）：圖不浮動、排在原位，不能跑到前面的文字（章名）之上；行距格線不斷。
  - 翻譯模型名稱：colophon 的 {translator} 代入 book.translator，只印在版權頁、不上書名頁；
    沒填就停下來，不讓佔位字印進譯本。
只用暫存目錄，不碰 process/ 底下任何一本書。需要 typst。
"""
import json, os, re, shutil, struct, sys, tempfile, zipfile, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epubtrans.core import config

CHECKS = []


def check(label, cond, detail=""):
    CHECKS.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not cond else ""))


def png(w=60, h=90):
    """純 Python 產生一張灰色 PNG，當封面圖與內文插圖。"""
    raw = b"".join(b"\x00" + b"\x80" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def xhtml(body):
    return ('<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Book</title></head>'
            f'<body><div class="chapter">{body}</div></body></html>')


PARA = ("Debt concentrates losses on those least able to bear them, and spending falls "
        "when house prices collapse.")
FILES = {
    "p01.xhtml": '<div><img src="images/front-cover.png"/></div>',          # 原書封面頁
    "p02.xhtml": '<h1 class="bkht">Book</h1>',                              # 半書名頁
    "p03.xhtml": ('<h1 class="ct"><b>1</b>: One</h1>'
                  + f'<p>{PARA}<a class="enref" href="#">1</a></p>' * 3
                  + '<p style="visibility:hidden;"><a href="#">1</a></p>'),   # 轉檔殘留的隱藏段落
    "p04.xhtml": '<h1 class="pn">PART I</h1><h1 class="pt">Busted</h1>',   # 部扉頁
    "p05.xhtml": ('<h1 class="ct"><b>2</b>: Two</h1>'
                  + f'<p>{PARA}<a class="enref" href="#">2</a></p>' * 2
                  + '<h2 class="ah">Where Spending Declined<a class="enref" href="#">3</a></h2>'
                  + f'<p>{PARA}</p>' * 30),
    "p06.xhtml": ('<h1 class="ct"><b>3</b>: Three</h1>' + f'<p>{PARA}</p>' * 40
                  + '<h2 class="ah">Subhead</h2>'
                  + '<div class="figure"><img src="images/tall.png"/>'
                  + '<p class="caption">Figure 3.2: Tall</p></div>'
                  + f'<p>{PARA}<a class="enref" href="#">4</a></p>' * 30
                  + '<div class="figure"><img src="images/fig1.png"/>'
                  + '<p class="caption">Figure 3.1: Debt</p></div>'),
}


def make_source(path):
    ids = [f[:-6] for f in FILES]
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="u">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title>'
           '<dc:language>en</dc:language><dc:identifier id="u">x</dc:identifier>'
           '<meta name="cover" content="cov"/></metadata><manifest>'
           '<item id="cov" href="images/front-cover.png" media-type="image/png"/>'
           + "".join(f'<item id="{i}" href="{i}.xhtml" media-type="application/xhtml+xml"/>' for i in ids)
           + '</manifest><spine>' + "".join(f'<itemref idref="{i}"/>' for i in ids) + '</spine></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/images/front-cover.png", png())
        z.writestr("OEBPS/images/fig1.png", png(120, 60))
        z.writestr("OEBPS/images/tall.png", png(30, 200))
        for name, body in FILES.items():
            z.writestr(f"OEBPS/{name}", xhtml(body))


YAML = """\
book:
  title: "Book"
  title_zh: "書"
  source_file: "src.epub"
  translator: "測試模型 1.0"
  title_overrides:
    c000: "封面"
  colophon: |
    本書中文譯本由 {translator} 翻譯。
extract:
  heading_levels: {ct: 2}
  chapter_levels: {c002: 1}
print:
  title: 書
  part_ids: [c003]
  chapter_ids: [c002]
"""
ZH = "債務把損失集中在最無力承擔的人身上，房價崩跌時支出就隨之下滑。"


def sides(pdf):
    """頁碼置中於版心，所以頁碼中心偏離紙張中線多少，就是左右邊界差的一半（mm）：[(實體頁碼, 偏移)]。"""
    import pymupdf
    out = []
    for i, page in enumerate(pymupdf.open(pdf), 1):
        W, H = page.rect.width, page.rect.height
        folio = [l["bbox"] for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])
                 if l["bbox"][1] > H * 0.92 and "".join(sp["text"] for sp in l["spans"]).strip().isdigit()]
        if folio:
            out.append((i, round(((folio[0][0] + folio[0][2]) / 2 - W / 2) * 25.4 / 72, 2)))
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="epubtrans-test-")
    config.PROCESS = tmp                       # BookConfig 在建構時才讀這個模組變數
    try:
        d = os.path.join(tmp, "T")
        os.makedirs(os.path.join(d, "drafts"))
        make_source(os.path.join(d, "src.epub"))
        open(os.path.join(d, "system_prompts.yaml"), "w", encoding="utf-8").write(YAML)
        cfg = config.BookConfig("T")

        print("extract")
        from epubtrans import source as extract      # extract 指令入口（依原檔格式分派）
        extract.run(cfg)
        book = json.load(open(cfg.wpath("book.json"), encoding="utf-8"))
        levels = {c["id"]: c["level"] for c in book["chapters"]}
        check("chapter_levels 覆寫：第一章在第一層，二、三章在第二層",
              levels == {"c000": 1, "c001": 1, "c002": 1, "c003": 1, "c004": 2, "c005": 2}, levels)
        c002 = [it["text"] for it in book["chapters"][2]["items"]]
        check("隱藏段落（visibility:hidden）不抽", c002 == [PARA + " 1"] * 3, c002)
        c000 = book["chapters"][0]["items"]
        check("封面頁的圖記成 cover 檔名", c000 == [{"type": "image", "file": "cover.png"}], c000)
        imgs = sorted(os.listdir(cfg.wpath("images")))
        check("封面圖不以原檔名另存一份", imgs == ["cover.png", "fig1.png", "tall.png"], imgs)
        # 圖列只有掃描數學書（vlm）的抽取會產生：這裡直接加進 book.json
        for fn, (w, h) in (("row1.png", (80, 60)), ("row2.png", (70, 50))):
            open(cfg.wpath("images", fn), "wb").write(png(w, h))
        c005 = next(c for c in book["chapters"] if c["id"] == "c005")
        c005["items"] += [{"type": "figrow", "cells": [{"file": "row1.png", "cap": True}, {"file": "row2.png", "cap": True}]},
                          {"type": "para", "text": "Figure 3.3 Left"}, {"type": "para", "text": "Figure 3.4 Right"}]
        json.dump(book, open(cfg.wpath("book.json"), "w", encoding="utf-8"), ensure_ascii=False)

        print("merge / build")
        titles = [["Book", "書"], ["1 : One", "第一章　一"], ["PART I Busted", "第一部　崩盤"],
                  ["2 : Two", "第二章　二"], ["3 : Three", "第三章　三"]]
        rows = {"c002": [["Debt", ZH + "¹"]] * 3,
                "c004": [["Debt", ZH + "²"]] * 2 + [["Where", "支出在哪裡下滑³"]] + [["Debt", ZH]] * 30,
                "c005": [["Debt", ZH]] * 40 + [["Subhead", "小標"]] + [["Figure", "圖 3.2：直式窄圖"]]
                        + [["Debt", ZH + "⁴"]] * 30 + [["Figure", "圖 3.1：債務"]]
                        + [["Figure", "圖 3.3 左"], ["Figure", "圖 3.4 右"]]}
        json.dump(titles, open(os.path.join(d, "drafts", "titles.json"), "w", encoding="utf-8"), ensure_ascii=False)
        for cid, r in rows.items():
            json.dump(r, open(os.path.join(d, "drafts", f"{cid}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        from epubtrans.translate import drafts
        drafts.merge(cfg)
        from epubtrans.output import export_epub as build
        build.run(cfg)
        z = zipfile.ZipFile(cfg.output_epub())
        opf = z.read("EPUB/content.opf").decode()
        spine = re.findall(r'<itemref idref="([^"]+)"', opf)
        href = {i: h for h, i in re.findall(r'<item href="([^"]+)" id="([^"]+)"', opf)}
        order = [href.get(i, i) for i in spine[:3]]
        check("spine：封面章第一、目錄第二", order == ["c000.xhtml", "nav.xhtml", "c001.xhtml"], order)
        check("沒有 ebooklib 另生的封面頁", "cover.xhtml" not in z.namelist())
        check("封面章只有圖", '<img src="images/cover.png"' in z.read("EPUB/c000.xhtml").decode()
              and "<h1" not in z.read("EPUB/c000.xhtml").decode())
        c004 = z.read("EPUB/c004.xhtml").decode()
        check("注號轉成 <sup>（段落與小標）", c004.count("<sup>2</sup>") == 2 and "下滑<sup>3</sup>" in c004)
        c005 = z.read("EPUB/c005.xhtml").decode()
        check("圖說放進同一個 <figure>，不另成一段",
              "<figcaption>圖 3.1：債務</figcaption></figure>" in c005 and "<p>圖 3.1" not in c005)
        check("圖列：div.figrow 裡兩個 <figure>，圖說各進各的",
              '<div class="figrow"><figure><img src="images/row1.png" alt="原書插圖"/><figcaption>圖 3.3 左</figcaption>'
              '</figure><figure><img src="images/row2.png" alt="原書插圖"/><figcaption>圖 3.4 右</figcaption></figure></div>'
              in c005 and "<p>圖 3.4" not in c005, c005[-400:])
        from bs4 import BeautifulSoup
        nav = BeautifulSoup(z.read("EPUB/nav.xhtml").decode(), "lxml")
        li = {a["href"]: a.find_parent("li") for a in nav.find_all("a")}
        check("目錄層級：二、三章掛在第一部底下，第一章與部同層",
              li["c004.xhtml"].find_parent("li") is li["c003.xhtml"]
              and li["c005.xhtml"].find_parent("li") is li["c003.xhtml"]
              and li["c002.xhtml"].parent is li["c003.xhtml"].parent)
        colo = z.read("EPUB/colophon.xhtml").decode()
        check("colophon 的 {translator} 代入模型名稱", "本書中文譯本由 測試模型 1.0 翻譯。" in colo
              and "{translator}" not in colo, colo[-120:])
        print("pdf b5")
        from epubtrans.output.export_pdf import pipeline
        try:
            pipeline.run(cfg, "b5", {}, None)          # 逐頁驗證有 ✗ 會 SystemExit(1)
            ok = True
        except SystemExit as e:
            ok = False
            print("   ", e)
        check("PDF 逐頁驗證全數通過（書眉、頁碼、部扉頁、目錄頁碼、行距）", ok)
        content = json.load(open(cfg.wpath("print", "b5", "content.json"), encoding="utf-8"))
        chs = {c["id"]: c for c in content["chapters"]}
        check("封面章不印成正文頁", "c000" not in chs, list(chs))
        check("半書名頁不被當成部扉頁", not chs["c001"]["is_part"])
        check("第一章照正文章排版", chs["c002"]["as_chapter"] and chs["c002"]["level"] == 1)
        check("內文插圖與圖說進 PDF 書稿",
              {"k": "img", "file": "fig1.png", "cap": "圖3.1：債務"} in chs["c005"]["blocks"])  # 手動空格已剝
        row = [b for b in chs["c005"]["blocks"] if b["k"] == "figrow"]
        check("圖列進 PDF 書稿", row and [(x["file"], x.get("cap")) for x in row[0]["cells"]]
              == [("row1.png", "圖3.3左"), ("row2.png", "圖3.4右")], row)
        pdf = pipeline.paths(cfg, "b5")[0]
        import pymupdf
        at = {}
        for pno, page in enumerate(pymupdf.open(pdf), 1):
            for info in page.get_image_info():
                if (info["width"], info["height"]) in ((80, 60), (70, 50)):
                    at[info["width"]] = (pno, info["bbox"])
        check("圖列的兩張圖在同一頁並排（左右分開、底端對齊）", len(at) == 2 and at[80][0] == at[70][0]
              and at[80][1][2] < at[70][1][0] and abs(at[80][1][3] - at[70][1][3]) < 1, at)
        from pypdf import PdfReader
        pages = [p.extract_text() or "" for p in PdfReader(pdf).pages]
        if shutil.which("pdfimages"):
            import subprocess
            rows = [r.split() for r in subprocess.run(["pdfimages", "-list", pdf], capture_output=True,
                                                      text=True).stdout.splitlines()[2:]]
            pc = json.load(open(cfg.wpath("print", "b5", "config.json"), encoding="utf-8"))
            body_h = pc["paper_h"] - pc["margin_top"] - pc["margin_bottom"]
            tall = [int(r[4]) / int(r[12]) * 25.4 for r in rows if (int(r[3]), int(r[4])) == (30, 200)]
            check("直式窄圖的高度不超過版心的 image_max_height",
                  tall and tall[0] <= body_h * pc.get("image_max_height", 55) / 100 + 0.5, (tall, body_h))
            img_pages = {int(r[0]) for r in rows}
            cap_pages = {i for i, t in enumerate(pages, 1) if re.search(r"圖\s*3\.[12]：", t)}
            check("圖說和圖在同一頁", cap_pages and cap_pages <= img_pages, (cap_pages, img_pages))
        side = sides(pdf)
        check("預設書本式：奇數頁左寬、偶數頁右寬（內側在裝訂邊）",
              side and all((d > 1.5) if n % 2 else (d < -1.5) for n, d in side), side)
        try:
            pipeline.run(cfg, "b5", {"style": "document"}, None)
            ok = True
        except SystemExit:
            ok = False
        flat = pipeline.paths(cfg, "b5", style="document")[0]
        check("--document 另出一份（B5 Document）且逐頁驗證通過", ok and flat.endswith("（B5 Document）.pdf")
              and os.path.exists(pdf), flat)
        side = sides(flat)
        check("--document：左右邊界等寬", side and all(abs(d) < 0.3 for _, d in side), side)
        try:
            pipeline.run(cfg, "b5", {"image_float": False}, None)
            ok = True
        except SystemExit:
            ok = False
        check("image_float: false 逐頁驗證通過（含圖說後的行距）", ok)
        doc = pymupdf.open(pdf)

        def first_y(text):                     # (頁, y)：text 第一次出現的位置
            for pno, page in enumerate(doc, 1):
                r = page.search_for(text)
                if r:
                    return pno, r[0].y0
        def img_y(size):
            for pno, page in enumerate(doc, 1):
                for info in page.get_image_info():
                    if (info["width"], info["height"]) == size:
                        return pno, info["bbox"][1]
        order = [first_y("小標"), img_y((30, 200)), first_y("圖3.2"), first_y("圖3.1"), img_y((80, 60))]
        check("圖排在原位：小標 → 直式窄圖 → 它的圖說；圖 3.1 的圖說 → 圖列", None not in order
              and order[0] < order[1] < order[2] and order[3] < order[4], order)
        t = chs["c004"]["blocks"][0]["t"]
        check("<sup> 轉回上標字元、前面不多空格", t.endswith("下滑。²") or t.endswith("滑。²"), t[-8:])
        check("書名頁不印譯者模型（只放版權頁）", "測試模型" not in pages[0], pages[0][-60:])
        check("PDF 的版權頁印出譯者模型", any("測試模型" in p for p in pages[1:]))
        cfg.raw["book"]["translator"] = ""
        try:
            cfg.fill_translator("由 {translator} 翻譯")
            stopped = False
        except SystemExit:
            stopped = True
        check("translator 沒填、卻用了 {translator}：停下來", stopped)
        check("沒用 {translator} 的字串照原樣通過", cfg.fill_translator("非商業發行") == "非商業發行")
    finally:
        if os.environ.get("KEEP"):
            print(f"保留暫存目錄：{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} 通過")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
