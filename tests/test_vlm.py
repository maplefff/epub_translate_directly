#!/usr/bin/env python3
"""掃描數學書（pdf.mode: vlm）：VLM 的整頁 Markdown → book.json → EPUB 的 MathML。

不載入任何模型：用合成的快取（Markdown＋版面框），內容取自 Griffiths 第三版的實際 OCR 輸出：
  - 獨立公式的 \\tag 抽成編號；編號寫在 $$ 外面一行也收得到；\\( \\)、\\[ \\] 也認
  - 書眉（「1.2. DIFFERENTIAL CALCULUS 15」）拿掉；粗斜體標記拿掉、公式內不動
  - 正文註腳標號（^{5}、$^5$、<sup>5</sup>）轉上標數字；[^5]: 註腳收到該節結尾的 Notes
  - 圖依「Figure X」圖說對位（圖說數不合時用 ![](figure) 佔位）；表格裁圖取代 VLM 的 Markdown 表
  - 多格圖：(a)(b)(c) 小標（Vision 讀不準，也看框寬）併進圖裡裁成一張，VLM 輸出的小標行拿掉；同一列依 x 排
  - Griffiths 實例：第 11 頁的表格圖、第 33 頁的 Figure 1.18（含跨頁接段）、第 19 頁各有圖說的並排圖（圖列）
  - 跨頁段落接回（上一頁沒有句尾標點、這頁小寫開頭）
  - 切章：「Chapter N」＋下一行標題開第一層，# 節標題開第二層
  - temml 轉 MathML：粗體草寫 𝓇 換成 𝓻、annotation 保留原 TeX、temml 不認得的指令當成轉不了
只用暫存目錄。MathML 的部分需要 node 與 epubtrans/output/js 的 temml（沒有就略過）。
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf
from epubtrans.source.import_pdf import vlm

CHECKS = []


def check(label, cond, detail=""):
    CHECKS.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not cond else ""))


def unit_parse():
    print("一頁 Markdown → 區塊")
    md = ("1.2. DIFFERENTIAL CALCULUS 15\n\n"
          "Consider the vector function\n"
          "$$ \\mathbf{v} = \\frac{1}{r^2} \\hat{\\mathbf{r}}. \\tag{1.83} $$\n"
          "and then\n\\[ x = y \\]\n(1.84)\n"
          "Thus $\\mathbf{B}$ is *also* proportional to $\\mathbf{H}$: $^5$ and **linear media**^{6}.\n"
          "*   **Problem 1.13** Let $\\boldsymbol{\\mathscr{r}}$ be the separation vector.\n"
          "| Material | Susceptibility |\n| --- | --- |\n"
          "[^5]: Physically, therefore, Eq. 6.28 would say exactly the same.\n")
    bs = vlm.strip_header(vlm.parse_markdown(md))
    kinds = [b["kind"] for b in bs]
    check("書眉拿掉、區塊順序對", kinds == ["para", "math", "para", "math", "para", "para", "table", "note"], kinds)
    check("\\tag 抽成編號、公式內容不帶 \\tag", bs[1]["tag"] == "1.83" and "\\tag" not in bs[1]["text"])
    check("編號寫在 $$ 外面一行、\\[ \\] 也認", bs[3]["text"] == "x = y" and bs[3]["tag"] == "1.84")
    check("粗斜體拿掉、註腳標號轉上標、公式不動",
          bs[4]["text"] == "Thus $\\mathbf{B}$ is also proportional to $\\mathbf{H}$:⁵ and linear media⁶.", bs[4]["text"])
    check("清單符號轉成 •、草寫 r 的 LaTeX 原樣保留",
          bs[5]["text"].startswith("• Problem 1.13 Let $\\boldsymbol{\\mathscr{r}}$"), bs[5]["text"])
    check("註腳", bs[7]["mark"] == "⁵" and bs[7]["text"].startswith("Physically"))


def fake_page(doc, layout, md, dpi=72):
    return {"md": md, "layout": layout, "dpi": dpi, "w": 612, "h": 792}


def unit_book(tmp):
    print("全書：圖說對位、跨頁、切章、註腳、空白頁")
    doc = pymupdf.open()
    for _ in range(6):
        doc.new_page(width=612, height=792)
    img = {"label": "image", "score": 0.9, "order": 1, "bbox": [100, 100, 300, 500]}
    img2 = {"label": "image", "score": 0.9, "order": 2, "bbox": [100, 520, 300, 900]}
    tab = {"label": "table", "score": 0.9, "order": 3, "bbox": [400, 100, 600, 900]}
    pages = [
        (0, fake_page(doc, [], "# Chapter 1\n\n# Vector Analysis\n\n## 1.1 Vector Algebra\n\n### 1.1.1 Vector Operations\n"
                              "If you walk 4 miles due north and then 3 miles due east, you will have gone a total of")),
        (1, fake_page(doc, [img, img2], "7 miles, but you're not 7 miles from where you set out.\n"
                                        "Figure 1.1\n\nFigure 1.2\n\nVectors have magnitude.^{1}\n"
                                        "[^1]: This is a footnote.")),
        (2, fake_page(doc, [img, tab], "![](figure)\nSome text after the figure.\n"
                                       "| a | b |\n|---|---|\nTable 6.1 Magnetic Susceptibilities.")),
        (3, fake_page(doc, [], "# 1.2 Differential Calculus\n### Example 1.3\nText of section two, and the sentence continues over\nFigure 1.5")),
        (5, fake_page(doc, [], "Figure 1.6\nthe page break after a figure.")),
        (4, fake_page(doc, [], "This page is blank.")),
    ]
    chapters, rep = vlm.build_book(type("C", (), {"get": lambda self, *a, default=None: default})(), doc, pages, tmp)
    titles = [(c["level"], c["title"]) for c in chapters]
    ex = [it for it in chapters[2]["items"] if it["type"] == "heading"]
    check("沒有編號的標題（Example 1.3）留在節內當小標、空白頁略過",
          [(h["text"], h["level"]) for h in ex] == [("Example 1.3", 3)]
          and not any("blank" in (it.get("text") or "") for c in chapters for it in c["items"]), ex)
    tail = [it["text"] for it in chapters[2]["items"] if it["type"] == "para"]
    check("跨頁接段略過頁尾、頁首的圖說", tail[0] == "Text of section two, and the sentence continues over "
          "the page break after a figure." and tail[1:] == ["Figure 1.5", "Figure 1.6"], tail)
    sub = [it for it in chapters[1]["items"] if it["type"] == "heading"]
    check("三段編號（1.1.1）是第 3 層小標", sub[0]["text"] == "1.1.1 Vector Operations" and sub[0]["level"] == 3, sub)
    check("「Chapter N」＋標題開第一層，節標題（看編號，不看 # 數量）開第二層",
          titles == [(1, "Chapter 1 Vector Analysis"), (2, "1.1 Vector Algebra"), (2, "1.2 Differential Calculus")], titles)
    sec = chapters[1]["items"]
    paras = [it for it in sec if it["type"] == "para"]
    check("跨頁段落接回", paras[0]["text"].endswith("a total of 7 miles, but you're not 7 miles from where you set out.")
          and paras[0].get("page_end") == 2, paras[0]["text"])
    types = [it["type"] for it in sec]
    i1 = types.index("figrow")
    check("同一列的兩張圖合成圖列，圖說依序接在後面", [c["cap"] for c in sec[i1]["cells"]] == [True, True]
          and sec[i1 + 1]["text"] == "Figure 1.1" and sec[i1 + 2]["text"] == "Figure 1.2", types)
    check("圖說數不合時用 ![](figure) 佔位；表格裁圖取代 Markdown 表、放在表的圖說前",
          [it["type"] for it in sec[i1 + 4:i1 + 8]] == ["image", "para", "image", "para"]
          and sec[i1 + 7]["text"].startswith("Table 6.1") and not any("| a |" in (it.get("text") or "") for it in sec),
          [(it["type"], it.get("text") or it.get("file")) for it in sec[i1 + 3:]])
    check("註腳收到該節結尾的 Notes", sec[-2]["text"] == "Notes" and sec[-1]["text"] == "¹This is a footnote.",
          sec[-2:])
    check("裁圖存檔", all(os.path.exists(os.path.join(tmp, it["file"])) for it in sec if it["type"] == "image"))
    check("報告：圖數（圖列逐格算）與佔位都對、沒有對位失敗", rep["figure_mismatch"] == [] and rep["images"] == 4, rep)


def unit_groups():
    print("圖框分組（Griffiths 的實際版面）")
    box = lambda label, b, sc=0.9: {"label": label, "score": sc, "order": 0, "bbox": b}
    # 第 47 頁：(a)(b)(c) 三格並排，只有中間下方一個圖說 Figure 1.28
    g = vlm.group_figures([box("image", [402, 145, 497, 264]), box("image", [393, 290, 496, 418]),
                           box("image", [392, 448, 496, 578]), box("figure_title", [505, 310, 520, 400])])
    check("多格圖併成一張、裁圖取聯集", len(g) == 1 and g[0]["bbox"] == [392, 145, 497, 578], g)
    # 第 19 頁：兩張圖並排，各有自己的圖說（Figure 1.7、1.8）
    g = vlm.group_figures([box("image", [82, 151, 209, 327]), box("figure_title", [224, 202, 240, 275]),
                           box("image", [116, 410, 207, 560]), box("figure_title", [224, 449, 239, 522])])
    check("並排但各有圖說的兩張圖分開", len(g) == 2 and all(x["title"] for x in g), g)
    # 第 35 頁：大框把兩個小框整個包住
    g = vlm.group_figures([box("image", [410, 106, 514, 281], 0.5), box("image", [387, 106, 524, 616], 0.59),
                           box("image", [387, 344, 525, 615], 0.54)])
    check("被包住的框拿掉", len(g) == 1 and g[0]["bbox"] == [387, 106, 524, 616], g)
    md = "```markdown\nSome text.\n```"
    check("整頁包在 ```markdown 裡也拆得開", [b["text"] for b in vlm.parse_markdown(md)] == ["Some text."])
    md = "so\n\\begin{align*}\nW &= a^2 \\\\\n&= b^2, \\tag{7.33}\n\\end{align*}\nwhere\n$$\\begin{align*}x\\end{align*}$$"
    bs = vlm.parse_markdown(md)
    check("沒包 $$ 的 align* 成為一條獨立公式（aligned、取出編號、^2 不轉上標）；已在 $$ 裡的不動",
          [b["kind"] for b in bs] == ["para", "math", "para", "math"]
          and bs[1]["text"] == "\\begin{aligned}W &= a^2 \\\\\n&= b^2, \\end{aligned}" and bs[1]["tag"] == "7.33"
          and bs[3]["text"] == "\\begin{align*}x\\end{align*}", bs)


# Vision 讀 (a)(c) 這種小框不可靠：實際讀到的是空白與「(э)」
P33 = [("paragraph_title", [81.9, 65.6, 101.4, 256.8], None),
       ("image", [364.9, 136.9, 516.9, 321.0], None), ("figure_title", [525.1, 219.8, 538.4, 238.7], None),
       ("image", [363.5, 357.0, 504.2, 577.3], None), ("figure_title", [526.4, 453.8, 541.4, 474.1], "(b)"),
       ("image", [566.0, 300.1, 701.9, 455.4], None), ("figure_title", [717.1, 367.6, 730.7, 386.6], "(э)"),
       ("figure_title", [744.5, 309.7, 760.6, 389.4], "Figure 1.18")]


# 第 19 頁：兩張圖並排，各有圖說；VLM 整頁包在 ```markdown 裡，連圖帶圖說都沒寫
P19 = [("image", [82.5, 151.1, 209.3, 326.9], None), ("figure_title", [223.9, 201.8, 240.0, 275.3], "Figure 1.7"),
       ("image", [115.9, 409.7, 207.3, 560.0], None), ("figure_title", [223.8, 449.4, 239.4, 522.2], "Figure 1.8"),
       ("paragraph_title", [418.6, 60.9, 433.4, 151.7], None)]


def layout_of(spec):
    return [{"label": l, "score": 0.9, "order": k, "bbox": b, **({"text": t} if t else {})}
            for k, (l, b, t) in enumerate(spec)]


def unit_cases(tmp):
    print("Griffiths 的實際案例（第 11、17、19、33、82、168、193、295、320、393 頁的版面框與 VLM 輸出）")
    g = vlm.group_figures(layout_of(P33))
    check("第 33 頁：(a)(b)(c) 小標不自成圖組，三格和小標裁成一張 Figure 1.18",
          len(g) == 1 and g[0]["cap"] == "Figure 1.18" and g[0]["bbox"] == [363.5, 136.9, 730.7, 577.3], g)
    rows = vlm.reading_rows([{"n": "b", "b": [363.5, 357, 504, 577]}, {"n": "a", "b": [364.9, 136, 516, 321]},
                             {"n": "c", "b": [566, 300, 701, 455]}], lambda x: x["b"])
    check("同一列依 x 排（(b) 頂端比 (a) 高 1 也排在後面）", [[x["n"] for x in r] for r in rows] == [["a", "b"], ["c"]], rows)

    # 第 193 頁：Figure 4.18 與三格的 Figure 4.19 並排；(a) 格和兩張圖都同列、又不在 4.19 圖說的正上方
    g = vlm.group_figures(layout_of([
        ("image", [595.9, 109.7, 688.4, 228.3], None), ("figure_title", [705.9, 128.0, 722.0, 208.5], "Figure 4.18"),
        ("image", [607.6, 281.8, 671.2, 362.5], None), ("figure_title", [676.7, 290.4, 691.2, 355.8], "(a) Sphere"),
        ("image", [530.9, 398.7, 671.7, 420.7], None), ("figure_title", [676.8, 375.3, 691.2, 441.9], "(b) Needle"),
        ("image", [532.1, 446.3, 673.6, 587.9], None), ("figure_title", [677.8, 466.4, 691.5, 526.6], "(c) Wafer"),
        ("figure_title", [707.7, 392.8, 723.0, 473.4], "Figure 4.19")]))
    check("第 193 頁：(a) 格併進同樣是多格圖的 Figure 4.19，兩張圖同一列",
          [(x["cap"], x["row"]) for x in g] == [("Figure 4.18", 0), ("Figure 4.19", 0)] and g[1]["bbox"][1] == 281.8, g)
    # 第 17 頁：Vision 把 Figure 1.1 讀成「Figure I.1」，這張圖改從佔位對位，緊接的圖說也要認領
    crops = [{"file": "a.png", "label": "image", "y": 0.65, "cap": "Figure I.1", "row": 0},
             {"file": "b.png", "label": "image", "y": 0.65, "cap": "Figure 1.2", "row": 0}]
    out, ok = vlm.place_figures(vlm.parse_markdown("Text.\n\n![](figure)\nFigure 1.1\n\n![](figure)\nFigure 1.2"), crops)
    check("第 17 頁：圖說讀錯的那張從佔位對位、認領緊接的圖說，圖列的圖說順序對",
          ok and [b["kind"] for b in out] == ["para", "figrow", "para", "para"]
          and [b["text"] for b in out[2:]] == ["Figure 1.1", "Figure 1.2"]
          and [c["cap"] for c in out[1]["cells"]] == [True, True], out)

    # 第 320 頁：Figure 7.22 上下兩格，(a)(b) 小標在圖框裡，上格貼著下格
    g = vlm.group_figures(layout_of([("image", [80.3, 213.2, 186.0, 507.7], None), ("image", [184.8, 257.9, 316.7, 507.5], None),
                                     ("figure_title", [332.3, 321.5, 348.2, 402.3], "Figure 7.22")]))
    check("第 320 頁：貼在正上方的框併進同一張圖", len(g) == 1 and g[0]["bbox"] == [80.3, 213.2, 316.7, 507.7], g)
    # 第 168 頁：上排兩張 VLM 沒寫；下排兩格的 Figure 3.34 圖說置中，和哪一格都不重疊
    g = vlm.group_figures(layout_of([
        ("image", [105.0, 123.2, 230.3, 318.3], None), ("figure_title", [245.4, 180.6, 262.0, 261.2], "Figure 3.32"),
        ("image", [84.3, 375.1, 229.7, 583.0], None), ("figure_title", [245.1, 440.9, 261.3, 521.4], "Figure 3.33"),
        ("image", [546.8, 237.5, 578.6, 307.1], None), ("figure_title", [582.6, 270.7, 595.5, 288.8], None),
        ("image", [521.2, 410.5, 578.2, 469.7], None), ("figure_title", [581.9, 433.0, 595.2, 452.6], None),
        ("figure_title", [610.4, 313.7, 626.3, 393.5], "Figure 3.34")]))
    check("第 168 頁：置中的圖說配給整組多格圖", [x["cap"] for x in g] == ["Figure 3.32", "Figure 3.33", "Figure 3.34"], g)
    crops = [{"file": f"{k}.png", "label": "image", "y": y, "cap": c, "row": r}
             for k, (y, c, r) in enumerate([(0.17, "Figure 3.32", 0), (0.16, "Figure 3.33", 0), (0.56, "Figure 3.34", 1)])]
    out, ok = vlm.place_figures(vlm.parse_markdown("Text.\n\nMore.\n\n![](figure)\nFigure 3.34\n\nProblem 3.30"), crops)
    check("第 168 頁：VLM 沒寫的 Figure 3.32 不搶 Figure 3.34 的佔位", not ok
          and [(b["kind"], b.get("text") or b.get("file")) for b in out][-3:]
          == [("image", "2.png"), ("para", "Figure 3.34"), ("para", "Problem 3.30")], out)

    # 第 82 頁：圖內小標題被框成圖說框、VLM 也寫成一行，夾在佔位與 Figure 2.13 之間
    g = vlm.group_figures(layout_of([
        ("image", [82.8, 158.4, 239.6, 537.0], None), ("figure_title", [247.4, 255.5, 262.2, 418.1], "Equal but opposite charges"),
        ("figure_title", [276.1, 306.5, 291.2, 386.1], "Figure 2.13")]))
    check("第 82 頁：圖內小標題裁進圖裡，圖說是 Figure 2.13", len(g) == 1 and g[0]["cap"] == "Figure 2.13"
          and g[0]["bbox"][2] == 262.2, g)
    bs = vlm.drop_figure_text(vlm.parse_markdown("Text.\n\n![](figure)\nEqual but opposite charges\nFigure 2.13\n\nMore text."))
    check("第 82 頁：VLM 寫在佔位與圖說之間的圖內文字拿掉",
          [(b["kind"], b.get("text")) for b in bs] == [("para", "Text."), ("fig", None), ("para", "Figure 2.13"),
                                                      ("para", "More text.")], bs)
    bs = vlm.drop_figure_text(vlm.parse_markdown(
        "![](figure)\nFerromagnetic domains. (Photo courtesy of R. W. DeBlois)\nFigure 6.26\n\nare competing neighbors"))
    check("第 295 頁：寫在圖號上方、像句子的圖說本文併進圖說",
          [b.get("text") for b in bs] == [None, "Figure 6.26 Ferromagnetic domains. (Photo courtesy of R. W. DeBlois)",
                                          "are competing neighbors"], bs)

    # 第 393 頁：VLM 把 Table 9.1 寫成 LaTeX tabular（表名包在 \\begin{center} 裡）
    md = ("Text before.\n\n\\begin{center}\n\\textbf{The Electromagnetic Spectrum}\n\\end{center}\n\n"
          "\\begin{tabular}{lll}\n\\hline\nFrequency (Hz) & Type & Wavelength (m) \\\\\n\\hline\n"
          "$10^{22}$ & & $10^{-13}$ \\\\\n\\end{tabular}\n\nTable 9.1\n\nwhere the amplitudes")
    out, ok = vlm.place_figures(vlm.parse_markdown(md), [{"file": "t.png", "label": "table", "y": 0.3, "cap": "Table 9.1", "row": 0}])
    check("第 393 頁：LaTeX tabular 也當表格，裁圖取代它、原始碼不留在正文",
          ok and [(b["kind"], b.get("text") or b.get("file")) for b in out]
          == [("para", "Text before."), ("image", "t.png"), ("para", "Table 9.1"), ("para", "where the amplitudes")], out)

    texts = {tuple(b): t for _, b, t in P33 + P19 if t}
    real = vlm._ocr_caption
    vlm._ocr_caption = lambda page, bbox, dpi: texts.get(tuple(bbox))
    try:
        doc = pymupdf.open()
        for _ in range(4):
            doc.new_page(width=612, height=792)
        p11 = ("# Advertisement\n\n## What is electrodynamics, and how does it fit into the general scheme of physics?\n\n"
               "### Four Realms of Mechanics\n\nIn the diagram below I have sketched out the four great realms of mechanics:\n\n"
               "| Classical Mechanics (Newton) | Quantum Mechanics (Bohr, Heisenberg, Schrödinger, *et al.*) |\n| :--- | :--- |\n"
               "| **Special Relativity** (Einstein) | **Quantum Field Theory** (Dirac, Pauli, Feynman, Schwinger, *et al.*) |\n\n"
               "Newtonian mechanics was found to be inadequate in the early years of this century.\n\nxi")
        p33 = ("### 1.2.4 The Divergence\n\nFor example, the vector function in Fig. 1.18a has a large (positive) divergence. "
               "(Please understand that $\\mathbf{v}$ here is a *function*. In the diagrams,\n\n"
               "![](figure)\n(a)\n\n![](figure)\n(b)\n\n![](figure)\n(c)\n\nFigure 1.18")
        p34 = "of course, I can only draw the arrows at a few representative points.)"
        p19 = ("```markdown\nIf $\\mathbf{A}$ and $\\mathbf{B}$ are perpendicular, then $\\mathbf{A} \\cdot \\mathbf{B} = 0$.\n\n"
               "### Example 1.1\nLet $\\mathbf{C} = \\mathbf{A} - \\mathbf{B}$ (Fig. 1.7), and calculate the dot product.\n"
               "This is the law of cosines.\n```")
        pages = [(0, fake_page(doc, layout_of([("doc_title", [268.8, 65.1, 313.3, 593.1], None),
                                               ("table", [429.2, 137.7, 525.4, 479.7], None)]), p11)),
                 (1, fake_page(doc, layout_of(P33), p33)), (2, fake_page(doc, [], p34)),
                 (3, fake_page(doc, layout_of(P19), p19))]
        chapters, rep = vlm.build_book(type("C", (), {"get": lambda self, *a, default=None: default})(), doc, pages, tmp)
    finally:
        vlm._ocr_caption = real
    adv = [(it["type"], (it.get("text") or it.get("file"))[:24]) for it in chapters[0]["items"] if it["page"] == 1]
    check("第 11 頁：表格裁圖取代 VLM 的 Markdown 表格，排在「In the diagram below…」之後",
          [t for t, _ in adv] == ["heading", "heading", "para", "image", "para"]
          and adv[2][1].startswith("In the diagram below") and adv[4][1].startswith("Newtonian"), adv)
    items = [it for c in chapters for it in c["items"]]
    div = [(it["type"], it.get("text") or it.get("file")) for it in items if it.get("page") in (2, 3)]
    check("第 33 頁：一張圖、圖說跟在後面，正文沒有孤立的 (a)(b)(c)",
          [t for t, _ in div][-3:] == ["para", "image", "para"] and div[-1][1] == "Figure 1.18"
          and not any(t == "para" and x.strip("()") in "abc" for t, x in div), div)
    check("第 33～34 頁：「In the diagrams, … of course, I can only draw…」接成同一段",
          div[-3][1].endswith("In the diagrams, of course, I can only draw the arrows at a few representative points.)"),
          div[-3][1])
    p19 = [(it["type"], it.get("text") or it.get("cells")) for it in items if it.get("page") == 4]
    row = next((x for t, x in p19 if t == "figrow"), None)
    k = [t for t, _ in p19].index("figrow") if row else -1
    check("第 19 頁：VLM 沒寫的兩張並排圖合成圖列，Vision 讀的圖說 Figure 1.7、1.8 依序補在後面",
          row and [c["cap"] for c in row] == [True, True] and [x for _, x in p19[k + 1:k + 3]] == ["Figure 1.7", "Figure 1.8"],
          p19)
    check("報告：VLM 沒寫圖的第 19 頁列入 figure_mismatch；圖數逐格算", rep["figure_mismatch"] == [4]
          and rep["images"] == 4, rep)


def unit_mathml():
    print("temml：LaTeX → MathML")
    from epubtrans.output import math as tm
    if not os.path.isdir(os.path.join(tm.JS, "node_modules", "temml")):
        print("  （略過：沒有 epubtrans/output/js/node_modules/temml）")
        return
    r = tm.to_mathml([("\\boldsymbol{\\mathscr{r}} = \\mathbf{r}-\\mathbf{r}'", False),
                      ("\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}", True), ("\\badcmd{x}", False)])
    bold = r[("\\boldsymbol{\\mathscr{r}} = \\mathbf{r}-\\mathbf{r}'", False)]
    check("粗體草寫 r 排成 𝓻，annotation 保留原 TeX",
          "𝓻" in bold and "\\boldsymbol{\\mathscr{r}}" in bold, bold[:200])
    check("獨立公式（aligned）轉得出來", r[("\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}", True)] is not None)
    check("temml 不認得的指令當成轉不了", r[("\\badcmd{x}", False)] is None)
    table = {"text": {"when": "當", "(Gauss's law)": "（高斯定律）", "above": "上方"}, "sub": {"all space": "全空間"},
             "whole": {"w \\equiv \\text{position of } q": "w \\equiv q \\text{ 的位置}"}}
    loc = tm.localize("V = 0 \\text{ when } y = 0 \\quad \\text{(Gauss's law)} \\quad E_{\\text{above}} "
                      "\\int_{\\text{all space}} \\text{and}", table)
    check("公式裡的英文說明依 math_text.yaml 代換：前後空白照留、下標只換 sub:、沒列的不動",
          loc == "V = 0 \\text{ 當 } y = 0 \\quad \\text{（高斯定律）} \\quad E_{\\text{above}} "
                 "\\int_{\\text{全空間}} \\text{and}", loc)
    check("語序不同的整條改寫（whole:）", tm.localize("w \\equiv \\text{position of } q", table) == "w \\equiv q \\text{ 的位置}")
    r = tm.to_mathml([("V \\text{ when } x", True)], table)
    check("to_mathml：key 仍是原文、MathML 與 annotation 用譯過的 TeX",
          "當" in r[("V \\text{ when } x", True)] and "when" not in r[("V \\text{ when } x", True)])


def unit_pdf(tmp):
    print("PDF：EPUB 的 MathML 取回 TeX、逐條試排")
    import shutil
    from bs4 import BeautifulSoup
    from epubtrans.output.export_pdf.content import read_translated_epub as rte
    from epubtrans.output.export_pdf import mathcheck
    ann = lambda t, d="": (f'<math xmlns="http://www.w3.org/1998/Math/MathML"{d}><semantics><mi>x</mi>'
                           f'<annotation encoding="application/x-tex">{t}</annotation></semantics></math>')
    html = (f'<html><body><p>where {ann("y")} is north, {ann("x")}.</p>'
            f'<div class="eq">{ann("\\mathbf{v} = 1", " display=\"block\"")}<span class="eqno">(1.83)</span></div></body></html>')
    soup = BeautifulSoup(html, "lxml")
    rte._math_to_text(soup, soup.body)
    p = soup.find("p")
    check("行內式換成私用區字元包住的 TeX，前後不多空格",
          rte._clean(p.get_text(" ", strip=True)) == f"where {rte.MATH_L}y{rte.MATH_R} is north, {rte.MATH_L}x{rte.MATH_R}.",
          p.get_text(" ", strip=True))
    eq = soup.find("p", class_="__eq")
    check("獨立公式取回 TeX 與編號", eq is not None and eq["data-tex"] == "\\mathbf{v} = 1" and eq["data-tag"] == "1.83")
    typst = shutil.which("typst")
    if not typst:
        print("  （略過試排：沒有 typst）")
        return
    work = os.path.join(tmp, "print", "b5")
    os.makedirs(work)
    book = {"chapters": [{"blocks": [
        {"k": "p", "t": f"good {rte.MATH_L}\\mathscr{{r}}^2{rte.MATH_R} bad {rte.MATH_L}\\frac{{1}}{rte.MATH_R}"},
        {"k": "eq", "tex": "\\nabla \\cdot \\mathbf{v} = 0", "tag": "1.84"},
        {"k": "eq", "tex": "\\frac{1}", "tag": None}]}]}
    bad = mathcheck.run(book, work, typst)
    bl = book["chapters"][0]["blocks"]
    check("\\mathscr 換成 mitex 認得的 \\mathcal、排得出來的照常", f"{rte.MATH_L}\\mathcal{{r}}^2{rte.MATH_R}" in bl[0]["t"]
          and bl[1]["ok"], bl[0]["t"])
    check("排不出來的行內式改成原樣印出、獨立公式標 ok=False",
          f"{mathcheck.RAW_L}\\frac{{1}}{mathcheck.RAW_R}" in bl[0]["t"] and bl[2]["ok"] is False and bad == ["\\frac{1}"], bad)
    check("試排結果有快取", os.path.exists(os.path.join(tmp, "print", "mathcheck.json")))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        unit_parse()
        unit_book(tmp)
        unit_groups()
        unit_cases(tmp)
        unit_mathml()
        unit_pdf(tmp)
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} 通過")
    sys.exit(0 if all(CHECKS) else 1)
