#!/usr/bin/env python3
"""書末索引的重建：解析條目 → 頁碼對回段落 → EPUB 連結 → PDF 頁碼。

每一條都來自 House of Debt 的真實索引：
  - run-in 子條目（「; bank runs in, 123–26」）、條目本身沒有頁碼（「borrowers: …」）、
    參見（「. See also …」、純「See …」）；書名裡的冒號（「Manias, …: A History …」）不是子條目。
  - 頁碼寫在連結外的尾巴：130f（圖）、195nn7–8（注）、149 加上連結外的「–51」。
  - 對位要找「那一頁講到這個詞的段落」，不是那一頁的第一段；範圍取迄頁最後一段。
  - 注釋頁碼過時（平裝版插入後記，注釋整批往後移）：頁差從資料推出來，
    同號注有好幾條時以頁碼為準、關鍵字只在同頁的幾條之間挑。
  - 索引自己寫錯注號（第一章只有 22 條注卻寫 192n29）：改在那一頁的注裡找詞。
  - PDF 印的頁碼必須等於目標段落實際所在的頁。
只用暫存目錄，不碰 process/ 底下任何一本書。需要 typst。
"""
import json, os, re, shutil, sys, tempfile, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epubtrans.core import config
from epubtrans.source import book_index as bi
from test_pipeline import xhtml

CHECKS = []


def check(label, cond, detail=""):
    CHECKS.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not cond else ""))


def ref(t, page):
    return {"t": t, "page": page}


def unit_parse():
    print("解析條目")
    e = bi.parse(["bank crises, ", ref("7–9", 7), ", ", ref("192n20", 192), "; bank runs in, ",
                  ref("123–26", 123), ". See also the Depression; Great Recession"])
    check("條目本身的頁碼、子條目、參見",
          e["head"] == "bank crises" and e["segs"][0]["label"] is None
          and [r["q"] for r in e["segs"][0]["refs"]] == [9, 192]
          and e["segs"][0]["refs"][1]["notes"] == [20]
          and e["segs"][1]["label"] == "bank runs in" and e["segs"][1]["refs"][0]["q"] == 126
          and e["see"] == "See also the Depression; Great Recession", e)
    e = bi.parse(["borrowers: consumer spending of, ", ref("55", 55), ", ", ref("140–42", 140)])
    check("「head: 子條目」—— 條目本身沒有頁碼",
          e["head"] == "borrowers" and e["segs"][0]["label"] == "consumer spending of"
          and bi.slots(e) == ["borrowers", "consumer spending of"], e)
    e = bi.parse(["“Debt Deflation: Theory and Evidence” (King), ", ref("193", 193)])
    f = bi.parse(["Manias, Panics, and Crashes: A History of Financial Crises (Kindleberger), ", ref("110", 110)])
    check("書名、論文名裡的冒號不當成子條目",
          e["head"] == "“Debt Deflation: Theory and Evidence” (King)" and e["segs"][0]["label"] is None
          and f["head"].startswith("Manias") and f["segs"][0]["label"] is None, (e, f))
    e = bi.parse(["securitization market, ", ref("95–103", 95), "; borrower default rates in, 101–3; "
                  "credit-rating scores in, ", ref("103–4", 103)])
    check("原書漏了連結的頁碼（「; label, 101–3;」）照文字收",
          [s["label"] for s in e["segs"]] == [None, "borrower default rates in", "credit-rating scores in"]
          and e["segs"][1]["refs"][0]["p"] == 101 and e["segs"][1]["refs"][0]["q"] == 103, e)
    e = bi.parse(["crash. See collapse in housing prices; Great Recession"])
    check("純參見", e == {"head": "crash", "segs": [], "see": "See collapse in housing prices; Great Recession"}, e)
    e = bi.parse(["stress in, ", ref("129", 129), ", ", ref("130", 130), "f, ", ref("195", 195), "nn7–8, ",
                  ref("149", 149), "–51, ", ref("107–8", 107)])
    rs = e["segs"][0]["refs"]
    check("連結外的尾巴：130f、195nn7–8、149–51；107–8 補成 108",
          rs[1]["fig"] and rs[2]["notes"] == [7, 8] and rs[3]["q"] == 151 and rs[4]["q"] == 108
          and "warn" not in e, e)


def para(text, page, end=None):
    it = {"type": "para", "text": text, "page": page}
    if end:
        it["page_end"] = end
    return it


def unit_resolve():
    print("頁碼對回段落")
    fill = "Filler text about many other things."
    body = {"id": "c001", "level": 2, "title": "One", "items": [
        para(fill, 4, 5),                                   # 0 從第 4 頁跨到第 5 頁
        para(fill, 5), para(fill, 5),                       # 1 2
        para("Keynes argued that debt matters.", 5),        # 3 第 5 頁的第四段
        para("Leverage amplifies losses.", 5, 6),           # 4
        para("More on leverage and debt.", 6),              # 5
        para(fill, 6),                                      # 6
        para(fill, 7, 8), para(fill, 8),                    # 7 8
    ]}
    notes = {"id": "c002", "level": 1, "title": "Notes", "items": [
        {"type": "heading", "level": 2, "text": "Chapter One", "page": 20},
        para("1. John Maynard Keynes, General Theory.", 20),
        para("2. International Monetary Fund report.", 20),
        para("3. Mortgage data from CoreLogic.", 20),
        {"type": "heading", "level": 2, "text": "Chapter Two", "page": 20},
        para("1. Mortgage data from CoreLogic.", 20, 21),   # 11 跨到第 21 頁
        para("2. Another source on mortgage defaults.", 21),
        {"type": "heading", "level": 2, "text": "Chapter Three", "page": 21},
        para("1. Mortgage lenders and their losses.", 22),
    ]}
    idx = {"id": "c003", "level": 1, "title": "Index", "items": [
        {"type": "para", "text": "x", "parts": p} for p in (
            ["Keynes, John Maynard, ", ref("5", 5), ", ", ref("10n1", 10)],
            ["leverage, ", ref("5–6", 5)],
            ["quiet pages, ", ref("8", 8)],
            ["mortgages, ", ref("11n1", 11), ", ", ref("10nn1–2", 10)],
            ["mortgage lenders, ", ref("12n1", 12)],
            ["International things, ", ref("10n29", 10)],
        )]}
    bi.run([body, notes, idx])
    refs = [r for it in idx["items"] for s in it["entry"]["segs"] for r in s["refs"]]
    check("找「那一頁講到這個詞的段落」而非第一段", refs[0]["to"] == ["c001", 3] and refs[0]["how"] == "詞", refs[0])
    check("範圍：起頁第一段有詞、迄頁最後一段有詞",
          refs[2]["to"] == ["c001", 4] and refs[2]["end"] == ["c001", 5], refs[2])
    check("那一頁沒有詞：取從那一頁開始的第一段（不取跨頁進來的）",
          refs[3]["to"] == ["c001", 8] and refs[3]["how"] == "頁", refs[3])
    check("注釋頁差由資料推出（10n1 → 第 20 頁的第一章注 1）",
          refs[1]["to"] == ["c002", 1] and refs[1]["how"] == "注", refs[1])
    check("同號注以頁碼為準：11n1 → 跨到第 21 頁的第二章注 1（第一章注 3 的詞一樣也不選）",
          refs[4]["to"] == ["c002", 5], refs[4])
    check("同一頁有兩條注 1 時以關鍵字挑；nn1–2 的迄注在同一節",
          refs[5]["to"] == ["c002", 5] and refs[5]["end"] == ["c002", 6], refs[5])
    check("12n1 → 第 22 頁的第三章注 1", refs[6]["to"] == ["c002", 8], refs[6])
    check("注號寫錯（那一頁沒有注 29）：在那一頁的注裡找詞，標成「注?」",
          refs[7]["how"] == "注?" and refs[7]["to"] == ["c002", 2], refs[7])


# ── 端到端 ────────────────────────────────────────────────────────────
FILL = "Household balance sheets vary widely across regions and over several decades of data."
KEY = "Keynes argued that the level of household debt drives the decline in spending."
LEV1 = "Leverage magnifies losses for the most indebted borrowers."
LEV2 = "Leverage again shows up when the bubble finally bursts."
ZH = {FILL: "家庭資產負債表在各地區、數十年的資料裡差異很大，這裡只是填充的段落。",
      KEY: "凱因斯主張家庭債務的水準決定支出下滑的幅度。",
      LEV1: "槓桿放大了負債最重的借款人的損失。",
      LEV2: "泡沫終於破滅時，槓桿又再度出現。"}


def body_paras():
    """(原文, 內文 HTML)。第 1–5 頁，每頁的標記放在段首或段中。"""
    out = [(FILL, f'<p><a class="page" id="p1"/>{FILL}</p>')]
    out += [(FILL, f"<p>{FILL}</p>")] * 29
    out += [(FILL, f'<p>{FILL[:40]}<a class="page" id="p2"/>{FILL[40:]}</p>')]
    out += [(FILL, f"<p>{FILL}</p>")] * 3 + [(KEY, f"<p>{KEY}</p>")] + [(FILL, f"<p>{FILL}</p>")] * 20
    out += [(LEV1, f'<p><a class="page" id="p3"/>{LEV1}</p>')] + [(FILL, f"<p>{FILL}</p>")] * 30
    out += [(FILL, f'<p><a class="page" id="p4"/>{FILL}</p>'), (LEV2, f"<p>{LEV2}</p>")]
    out += [(FILL, f"<p>{FILL}</p>")] * 5
    out += [(FILL, f'<p><a class="page" id="p5"/>{FILL}</p>')] + [(FILL, f"<p>{FILL}</p>")] * 3
    return out


NOTES = ('<h1 class="ctbm">Notes</h1><h2 class="ah">Chapter One</h2>'
         '<p><a class="page" id="p20"/>1. John Maynard Keynes, General Theory of Employment.</p>'
         '<p>2. Unrelated source.</p><h2 class="ah">Chapter Two</h2>'
         '<p><a class="page" id="p21"/>1. Mortgage data from CoreLogic.</p>')
INDEX = ('<h1 class="ctbm">Index</h1><div class="index">'
         '<p class="inf">debtors. <i>See</i> borrowers</p>'
         '<p class="inf">household debt, <a class="xref" href="ch1.xhtml#p2">2</a>, '
         '<a class="xref" href="ch1.xhtml#p4">4</a></p>'
         '<p class="inf">Keynes, John Maynard, <a class="xref" href="ch1.xhtml#p2">2</a>, '
         '<a class="xref" href="ch1.xhtml#p4">4n1</a></p>'
         '<p class="in">leverage: borrowers and, <a class="xref" href="ch1.xhtml#p3">3–4</a>; '
         'spending and, <a class="xref" href="ch1.xhtml#p2">2</a>. <i>See also</i> debt</p>'
         '<p class="in">mortgages, <a class="xref" href="ch1.xhtml#p5">5</a>n1</p>'
         '<p class="inf">quiet pages, <a class="xref" href="ch1.xhtml#p5">5</a></p>'
         '<p class="inf">Anenberg, Elliot, <a class="xref" href="ch1.xhtml#p4">4n1</a></p></div>')
INDEX_ZH = [["debtors", "債務人｜見 borrowers（借款人）"], ["household", "家庭債務"], ["Keynes", "凱因斯"], ["leverage", "槓桿；借款人；支出｜另見 debt（債務）"],
            ["mortgages", "房貸"], ["quiet", "安靜的頁面"], ["Anenberg", "Anenberg, Elliot"]]


def make_source(path, files):
    ids = [f[:-6] for f in files]
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="u">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title>'
           '<dc:language>en</dc:language><dc:identifier id="u">x</dc:identifier></metadata><manifest>'
           + "".join(f'<item id="{i}" href="{i}.xhtml" media-type="application/xhtml+xml"/>' for i in ids)
           + '</manifest><spine>' + "".join(f'<itemref idref="{i}"/>' for i in ids) + '</spine></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        for name, body in files.items():
            z.writestr(f"OEBPS/{name}", xhtml(body))


def end_to_end():
    tmp = tempfile.mkdtemp(prefix="epubtrans-index-")
    config.PROCESS = tmp
    try:
        d = os.path.join(tmp, "T")
        os.makedirs(os.path.join(d, "drafts"))
        paras = body_paras()
        make_source(os.path.join(d, "src.epub"), {
            "ch1.xhtml": '<h1 class="ct">1: One</h1>' + "".join(h for _, h in paras),
            "notes.xhtml": NOTES, "index.xhtml": INDEX})
        open(os.path.join(d, "system_prompts.yaml"), "w", encoding="utf-8").write(
            'book: {title: "Book", title_zh: "書", source_file: "src.epub"}\n'
            'extract: {heading_levels: {ct: 2}}\nprint: {title: 書}\n')
        cfg = config.BookConfig("T")

        print("extract")
        from epubtrans import source as extract      # extract 指令入口（依原檔格式分派）
        extract.run(cfg)
        book = json.load(open(cfg.wpath("book.json"), encoding="utf-8"))
        ch1, notes, idx = book["chapters"]
        items = ch1["items"]
        k = next(i for i, it in enumerate(items) if it["text"] == KEY)
        l1 = next(i for i, it in enumerate(items) if it["text"] == LEV1)
        l2 = next(i for i, it in enumerate(items) if it["text"] == LEV2)
        check("段首的標記：那一段從新的一頁開始", items[0]["page"] == 1 and items[l1]["page"] == 3)
        check("段中的標記：記成跨頁（page 1、page_end 2）",
              items[30]["page"] == 1 and items[30]["page_end"] == 2, items[30])
        e = [it["entry"] for it in idx["items"]]
        check("索引的頁碼連結記成 entry，parts 不留在 book.json",
              len(e) == 7 and all("parts" not in it for it in idx["items"]))
        check("Keynes 的第 2 頁 → 凱因斯那一段；4n1 → 注釋第一章注 1（頁差 +16 由資料推出）",
              e[2]["segs"][0]["refs"][0]["to"] == [ch1["id"], k]
              and e[2]["segs"][0]["refs"][1]["to"] == [notes["id"], 1], e[2])
        check("leverage 的 3–4 → 起訖兩段", e[3]["segs"][0]["refs"][0]["to"] == [ch1["id"], l1]
              and e[3]["segs"][0]["refs"][0]["end"] == [ch1["id"], l2], e[3])
        check("mortgages 5n1 → 第 21 頁的第二章注 1", e[4]["segs"][0]["refs"][0]["to"] == [notes["id"], 4], e[4])

        print("merge / build")
        titles = [["1: One", "第一章　一"], ["Notes", "注釋"], ["Index", "索引"]]
        drafts = {ch1["id"]: [[src.split()[0], ZH[src]] for src, _ in paras],
                  notes["id"]: [["Chapter", "第一章"], ["1", None], ["2", None], ["Chapter", "第二章"], ["1", None]],
                  idx["id"]: INDEX_ZH}
        json.dump(titles, open(os.path.join(d, "drafts", "titles.json"), "w", encoding="utf-8"), ensure_ascii=False)
        for cid, rows in drafts.items():
            json.dump(rows, open(os.path.join(d, "drafts", f"{cid}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        from epubtrans.translate import drafts as dr
        dr.merge(cfg)
        from epubtrans.output import export_epub as build
        check("譯稿欄位數不符會被抓到", build.index_zh("槓桿；借款人｜另見 debt", e[3]) is None
              and build.index_zh("槓桿；借款人；支出", e[3]) is None
              and build.index_zh("槓桿；借款人；支出｜另見 debt", e[3]) is not None)
        build.run(cfg)
        z = zipfile.ZipFile(cfg.output_epub())
        body_x = z.read(f"EPUB/{ch1['id']}.xhtml").decode()
        idx_x = z.read(f"EPUB/{idx['id']}.xhtml").decode()
        check("目標段落有錨點", f'<p id="i{k}">' in body_x and f'<p id="i{l2}">' in body_x)
        check("索引連到段落、範圍帶 data-end、注釋帶注號",
              f'href="{ch1["id"]}.xhtml#i{k}"' in idx_x
              and f'data-end="{ch1["id"]}.xhtml#i{l2}"' in idx_x
              and 'data-note="1">第一章注1</a>' in idx_x)
        check("同章多處寫成「第一章①②」", "第一章<a" in idx_x and "①</a>" in idx_x and "②</a>" in idx_x)
        check("參見與純參見", "另見 debt（債務）" in idx_x and "見 borrowers（借款人）" in idx_x)
        check("譯名與原文相同時只寫一次（只見於注釋書目的人名）", idx_x.count("Anenberg, Elliot") == 1)

        print("pdf b5")
        from epubtrans.output.export_pdf import pipeline
        try:
            pipeline.run(cfg, "b5", {}, None)
            ok = True
        except SystemExit as ex:
            ok = False
            print("   ", ex)
        check("PDF 逐頁驗證全數通過", ok)
        from pypdf import PdfReader
        from epubtrans.output.export_pdf import pagecheck
        work = cfg.wpath("print", "b5")
        pc = json.load(open(os.path.join(work, "config.json"), encoding="utf-8"))
        zones = [pagecheck._zones(p, pc["margin_top"] * pagecheck.MM, pc["margin_bottom"] * pagecheck.MM)
                 for p in PdfReader(pipeline.paths(cfg, "b5")[0]).pages]

        def folio(zh):
            return next(f for _, f, b in zones if pagecheck._norm(zh) in b)
        text = "".join(b for _, _, b in zones)
        want_k, want_1, want_2 = folio(ZH[KEY]), folio(ZH[LEV1]), folio(ZH[LEV2])
        m = re.search(r"凱因斯(\d+),(\d+)注1", text)
        check("PDF 索引的頁碼＝目標段落實際所在頁",
              m and m.group(1) == want_k, (m and m.groups(), want_k))
        m = re.search(r"借款人(\d+)–(\d+)", text)
        check("範圍的起訖頁都算對", m and m.groups() == (want_1, want_2), (m and m.groups(), want_1, want_2))
    finally:
        if os.environ.get("KEEP"):
            print(f"保留暫存目錄：{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    unit_parse()
    unit_resolve()
    end_to_end()
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} 通過")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
