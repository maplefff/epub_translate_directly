// 測試用的英文版面 B（非小說風格）：刻意和 english_book.typ 處處不同，確認抽取規則沒有只貼合一種版面。
// 段落不縮排、段間空一行、靠左對齊（右邊參差）、不斷字；字型 New Computer Modern；
// 書眉：左邊部名、右邊頁碼（頁碼在頁首，不在頁尾）；部換頁、章不換頁（章標題出現在頁面中間）；
// 沒有 PDF 書籤；有引文段（左右內縮、小一號字）與項目清單。
#let book = json("content.json")

#set document(title: book.title, author: book.author)
#set text(font: "New Computer Modern", size: 10.5pt, lang: "en", hyphenate: false)
#set par(justify: false, first-line-indent: 0pt, leading: 0.65em, spacing: 1.25em)
#set heading(bookmarked: false)
#show footnote.entry: set text(size: 8.5pt)

#let running = state("running", "")

#set page(
  width: 6in, height: 9in,
  margin: (x: 0.85in, top: 0.95in, bottom: 0.8in),
  header: context {
    let n = here().page()
    if n == 1 { return }
    set text(size: 8.5pt)
    [#smallcaps(running.get()) #h(1fr) #counter(page).display()]
  },
  footer: none,
)

#show heading: set text(weight: "bold")
#show heading.where(level: 1): it => block(above: 1em, below: 0.6em, text(size: 22pt, it.body))
#show heading.where(level: 2): it => block(above: 2.4em, below: 1.2em, text(size: 15pt, it.body))
#show heading.where(level: 3): it => block(above: 1.6em, below: 0.9em, text(size: 12pt, style: "italic", it.body))

#let item(it) = {
  if it.type == "para" {
    if "footnote" in it [#it.text#footnote(it.footnote)] else [#it.text]
    parbreak()
  } else if it.type == "center" {
    align(center, it.text)
    parbreak()
  } else if it.type == "heading" {
    heading(level: 3, outlined: false, it.text)
  } else if it.type == "quote" {
    pad(left: 2.2em, right: 2.2em, text(size: 9.5pt, it.text))
    parbreak()
  } else if it.type == "li" {
    list(it.text)
  } else if it.type == "image" {
    align(center, image("images/" + it.file, width: 50%))
    parbreak()
  }
}

#page(margin: 0pt, header: none, footer: none, image("images/" + book.cover, width: 100%, height: 100%, fit: "cover"))

#for sec in book.sections {
  if sec.kind == "front" or sec.kind == "back" {
    pagebreak(weak: true)
    for it in sec.items { item(it) }
  } else if sec.kind == "contents" {
    pagebreak(weak: true)
    outline(title: [Contents], depth: 2, indent: 1.5em)
  } else if sec.kind == "part" {
    pagebreak(weak: true)
    running.update(sec.subtitle)
    heading(level: 1, sec.title)
    text(size: 17pt, weight: "bold", sec.subtitle)
    parbreak()
  } else if sec.kind == "chapter" {
    heading(level: 2, sec.title)
    for it in sec.items { item(it) }
  }
}
