// OCR 比對：原書掃描頁 → 參考答案 → 各模型輸出。資料由 make_compare_pdf.py 寫進 data.json。
#import "@preview/mitex:0.2.7": mitex-convert, mitex-scope
// mitex 的 array 把每格排成行內式、行距 0.5em，多行分式會上下重疊；這裡改成展示式、加大行距（只影響排版檢視）
#let arr(arg0: ("l",), ..args) = {
  if args.pos().len() == 0 { return }
  if type(arg0) != str {
    if arg0.has("children") {
      arg0 = arg0.children.filter(it => it != [ ] and it != [#math.zws]).map(it => it.text).filter(it => it in ("l", "c", "r"))
    } else { arg0 = (arg0.text,) }
  }
  let rows = args.pos().map(row => if type(row) == array { row } else { (row,) })
  let m = calc.max(..rows.map(r => r.len()))
  rows = rows.map(r => r + (m - r.len()) * (none,))
  let al = ("l": left, "c": center, "r": right).at(if arg0.len() > 0 { arg0.at(0) } else { "l" })
  set align(al)
  pad(y: 0.2em, grid(columns: m, column-gutter: 0.5em, row-gutter: 0.9em, ..rows.flatten().map(it => $display(it)$)))
}
#let scope2 = mitex-scope + (mitexarray: arr)
#let mx(s, block: true) = math.equation(block: block, eval("$" + mitex-convert(mode: "math", s) + "$", scope: scope2))
#let mi(s) = mx(s, block: false)
#let mitex(s) = mx(s)
#let d = json("data.json")

#set page(paper: "a4", margin: (x: 16mm, top: 20mm, bottom: 16mm), numbering: "1",
  header: context {
    let pg = here().page()
    let on = query(heading.where(level: 1)).filter(h => h.location().page() == pg)
    let hs = if on.len() > 0 { on } else { query(selector(heading.where(level: 1)).before(here())) }
    if hs.len() > 0 and pg > 1 {
      set text(8pt, fill: gray.darken(30%))
      if on.len() > 0 { on.first().body } else { hs.last().body }
      h(1fr)
      [OCR 比對]
      v(-2pt)
      line(length: 100%, stroke: 0.4pt + gray)
    }
  })
#set text(font: ("Charter", "Songti TC"), size: 10pt, lang: "zh", region: "tw")
#set par(justify: false, leading: 0.7em)
#show heading.where(level: 1): it => { pagebreak(weak: true); block(below: 8pt, text(17pt, it.body)) }
#show heading.where(level: 2): it => block(above: 14pt, below: 6pt, text(12pt, fill: rgb("#1f4e79"), it.body))

#let bad(src, display: false) = box(fill: rgb("#fde8e8"), stroke: 0.6pt + red, inset: 2pt, radius: 2pt)[
  #text(7pt, fill: red)[無法排版] #text(font: "Menlo", size: 7.5pt, src)]

#let seg(s) = {
  if s.k == "m" { if s.ok { mi(s.v) } else { bad(s.src) } }
  else if s.k == "sup" { super(s.v) }
  else if s.k == "det" { text(6.5pt, fill: rgb("#8a6d00"), font: "Menlo", "⟨" + s.v + "⟩") }
  else {
    let t = text(s.v)
    if s.b and s.i { strong(emph(t)) } else if s.b { strong(t) } else if s.i { emph(t) } else { t }
  }
}

#let render(blocks) = {
  for b in blocks {
    if b.k == "p" { par(for s in b.segs { seg(s) }) }
    else if b.k == "h" {
      block(above: 8pt, below: 4pt, text(size: (14pt, 12.5pt, 11pt, 10.5pt, 10pt, 10pt).at(b.lv - 1), weight: "bold",
        text(fill: gray, size: 8pt, "#" * b.lv + " ") + for s in b.segs { seg(s) }))
    }
    else if b.k == "eq" {
      let body = if b.ok { mitex(b.v) } else { bad(b.v) }
      block(width: 100%, grid(columns: (1fr, auto), align: (center + horizon, right + horizon),
        body, if b.tag != none { [(#b.tag)] } else { [] }))
    }
    else if b.k == "fig" { block(rect(width: 45%, height: 1.6cm, stroke: 0.5pt + gray, fill: luma(245))[
      #align(center + horizon, text(8pt, fill: gray, "圖片佔位：" + b.v))]) }
    else if b.k == "hr" { line(length: 100%, stroke: 0.4pt + gray) }
  }
}

#let page-entry(pg) = {
  heading(level: 2, pg.label)
  block(sticky: true, below: 4pt, text(8pt, fill: gray.darken(20%))[排版檢視（只辨認公式分隔符號以便排出公式，內容未改；\\mathscr 以 \\mathcal 字形顯示）])
  block(width: 100%, stroke: 0.6pt + luma(180), inset: 10pt, radius: 3pt, render(pg.blocks))
  v(4pt)
  block(sticky: true, below: 4pt, text(8pt, fill: gray.darken(20%))[原始輸出（一字未改）])
  block(width: 100%, fill: luma(246), inset: 8pt, radius: 3pt,
    text(font: ("Menlo", "Songti TC"), size: 7.2pt, raw(pg.raw, block: true)))
}

// 封面說明
#align(center, text(20pt, weight: "bold")[Griffiths 掃描頁公式 OCR 比對])
#v(4pt)
#align(center, text(10pt, fill: gray.darken(20%))[原書：Introduction to Electrodynamics 第三版（掃描 PDF）・測試日期 2026-10-07・本機 mlx-vlm 推論])
#v(10pt)
*閱讀方式*
- 第一部分是原書掃描頁（第 15、45、500 頁），第二部分是參考答案，之後每個模型一節，每節依序是這三頁。
- 每頁先列「排版檢視」：把輸出裡的公式排成數學式，方便看結構。下面接「原始輸出」：模型輸出原文，一字未改。
- 排版檢視只做了兩件事：辨認 `$…$`、`$$…$$`、`\(…\)`、`\[…\]` 公式分隔符號，以及把 `\tag{…}` 的編號排到右側。`\mathscr` 用 `\mathcal` 的字形顯示（排版套件不認 `\mathscr`）。其餘照原樣。
- 公式語法錯到排不出來的，排版檢視裡以紅框標示，並列出原始碼。
- Unlimited-OCR 的輸出帶有版面框標記（`<|det|>…<|/det|>`），排版檢視以褐色小字 ⟨…⟩ 顯示。
- 參考答案是 Claude 看掃描頁人工轉寫的，沒有經過獨立驗證；第 500 頁轉寫時看的裁切圖缺左邊幾個字，那幾處依上下文補上。
- 粗體 𝓇（分離向量）與一般 𝓇（長度）在排版檢視裡以粗細區分，細節以原始輸出為準：`\boldsymbol{\mathscr{r}}` 是粗體，`\mathscr{r}` 是一般。

*各節*
#for s in d.sections [ - *#s.title*：#s.desc
]

#heading(level: 1)[原書掃描頁]
#for (i, sc) in d.scans.enumerate() {
  if i > 0 { pagebreak() }
  heading(level: 2, sc.label)
  align(center, image(sc.img, height: 245mm))
}

#for s in d.sections {
  heading(level: 1, s.title)
  text(9pt, fill: gray.darken(20%), s.desc)
  for (i, pg) in s.pages.enumerate() {
    if i > 0 { pagebreak() }
    page-entry(pg)
  }
}

#heading(level: 1)[附錄：提示詞]
== 提示詞 v1（Qwen、Gemma 各模型）
#block(fill: luma(246), inset: 8pt, radius: 3pt, text(font: "Menlo", size: 8pt, raw(d.prompts.v1, block: true)))
== 提示詞 v2
#block(fill: luma(246), inset: 8pt, radius: 3pt, text(font: "Menlo", size: 8pt, raw(d.prompts.v2, block: true)))
