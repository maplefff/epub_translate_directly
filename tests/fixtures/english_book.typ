// 測試用的英文平裝書版面：tests/fixtures/make_test_pdfs.py 產生 content.json 後編譯。
// 刻意做出真實書籍 PDF 會有、而 PDF 抽取必須處理的東西：
// 書眉（左頁書名、右頁部名）、頁碼、左右頁不同邊界、英文斷字、左右對齊、首行縮排、
// 跨頁段落、註腳、插圖、部扉頁、印出來的目錄頁，以及 PDF 書籤（部與章）。
#let book = json("content.json")

#set document(title: book.title, author: book.author)
#set text(font: "Libertinus Serif", size: 10.5pt, lang: "en", hyphenate: true)
#set par(justify: true, first-line-indent: 1.3em, leading: 0.62em, spacing: 0.62em)
#show footnote.entry: set text(size: 8.5pt)

#let in-body = state("in-body", false)
#let running = state("running", "")

#set page(
  width: 5.5in, height: 8.5in,
  margin: (inside: 0.9in, outside: 0.65in, top: 0.85in, bottom: 0.85in),
  header: context {
    let n = here().page()
    let opens = query(<opening>).map(m => m.location().page())
    if not in-body.get() or n in opens { return }
    set text(size: 8.5pt)
    if calc.even(n) [#text(tracking: 0.12em, upper(book.title)) #h(1fr)]
    else [#h(1fr) #emph(running.get())]
  },
  footer: context {
    let n = here().page()
    if n > 1 { align(center, text(size: 9pt, counter(page).display())) }
  },
)

#show heading: set text(weight: "regular")
#show heading.where(level: 1): it => align(center, text(size: 13pt, tracking: 0.2em, it.body))
#show heading.where(level: 2): it => align(center, text(size: 20pt, it.body))
#show heading.where(level: 3): it => align(center, text(size: 11pt, weight: "bold", it.body))

#let item(it) = {
  if it.type == "para" {
    if "footnote" in it [#it.text#footnote(it.footnote)] else [#it.text]
    parbreak()
  } else if it.type == "center" {
    align(center, emph(it.text))
    parbreak()
  } else if it.type == "heading" {
    heading(level: 3, outlined: false, it.text)
  } else if it.type == "image" {
    align(center, image("images/" + it.file, width: 55%))
    parbreak()
  }
}

// 封面：整頁圖
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
    in-body.update(true)
    running.update(sec.subtitle)
    [#metadata(none) <opening>]
    v(28%)
    heading(level: 1, sec.title)
    v(1em)
    align(center, text(size: 22pt, sec.subtitle))
  } else if sec.kind == "chapter" {
    pagebreak(weak: true)
    [#metadata(none) <opening>]
    v(12%)
    heading(level: 2, sec.title)
    v(2.2em)
    for it in sec.items { item(it) }
  }
}
