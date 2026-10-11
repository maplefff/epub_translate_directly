// 中文書籍的印刷版心 —— 版面規則就在這個檔案裡，要調版改這裡。
//
// 為什麼內容走 JSON 而不是產生 Typst 原始碼：小說正文裡到處是 # * _ [ ] < > @ ~ $
// 這些 Typst 的 markup 符號，把正文串成原始碼遲早會被解析器吃掉一個字。
// json() 讀進來的字串完全不經過 markup 解析，是純資料。

#import "math.typ": rich, eq-block
#let data = json("content.json")
#let cfg = json("config.json")

#let bs = cfg.body_size * 1pt
#let lead = cfg.leading * 1pt
#let fonts = (cfg.latin_font, cfg.cjk_font)
#let title = cfg.title
#let flat(x) = x * 1pt

// 夜讀色調：page_color／text_color 為 null 時就是白紙黑字。次要文字（書眉、頁碼、
// 副標、版權小字）在白底是固定灰階；黃底上改成「字色往底色混」，不往白色調淡 ——
// 往白色淡會在深黃底上糊掉（琥珀底的版權小字只剩 2:1）。混 60% 的灰階比例後，
// 最深的琥珀底上書眉 5.7:1、小字 4.9:1，和白底版的 6.4:1、4.4:1 相當。
#let ink = if cfg.text_color == none { black } else { rgb(cfg.text_color) }
#let dim(l) = if cfg.text_color == none { luma(l) } else {
  let p = l / 255 * 60%
  color.mix((ink, 100% - p), (rgb(cfg.page_color), p), space: rgb)
}

// 第一層標題有兩種身分：部扉頁與前後附件（獻詞、作者簡介、版權頁）。
// 兩者在目錄裡都該齊頭不縮排，所以同是 level 1；差別只在字級與整頁留白。
// Typst 的 heading 沒有自訂欄位可掛，用 state 在發出標題前先標記是哪一種
// —— 把字級寫進 heading 的 body 也能分，但那樣目錄會連字級一起繼承過去。
#let hkind = state("hkind", "matter")

// ── 頁面 ──────────────────────────────────────────────────────────
// binding: left ＋ inside/outside ＝ 對頁鏡像。預設的書本式（style: book）：
// 雙面印之後不論裝訂或釘書針，內側那條邊都會被吃掉，所以要留得比外緣寬。
// 文件式（--document）layout.py 把內外給成同一個值，鏡像就等於左右對稱。
#set page(
  // 紙張由 layout.py 給寬高（mm），不用 Typst 的紙張名稱：JIS B5 與 ISO B5
  // 同名不同大小，直接給尺寸就不會對應錯。
  width: cfg.paper_w * 1mm,
  height: cfg.paper_h * 1mm,
  margin: (
    inside: cfg.margin_inside * 1mm, outside: cfg.margin_outside * 1mm,
    top: cfg.margin_top * 1mm, bottom: cfg.margin_bottom * 1mm,
  ),
  binding: left,
  fill: if cfg.page_color == none { none } else { rgb(cfg.page_color) },
)

#set text(
  font: fonts,
  size: bs,
  fill: ink,
  lang: "zh",
  region: "TW",
  // 中西文之間自動插 1/4 em。原稿裡的手動半形空格已在 Python 端剝掉，
  // 留著會和這個疊加成過寬的空隙。
  cjk-latin-spacing: if cfg.cjk_latin_spacing { auto } else { none },
  // 行框的上下緣用固定數值，不用字型度量。
  // Typst 預設是依「該行實際用到的字型」算行框，一行裡只要混進別的字型，
  // 行框就被撐高。實測：含破折號「——」的行由 Charter 排，行距從 15.9pt
  // 跳到 19.0pt，一頁出現三五處忽寬忽窄。固定成 1em 之後每一行一樣高，
  // 版心成為均勻的格線 —— 中文書版面的基本要求。
  top-edge: 0.88em,
  bottom-edge: -0.12em,
)

// 注號：epubread 把 EPUB 的 <sup>1</sup> 轉成上標字元（¹）交過來，這裡排成 super。
// 不能直接印上標字元：宋體與 Charter 只有 ¹²³ 有上標字形，⁴–⁹ 由別的字型補字，
// 大小、基線都對不齊。typographic: false ＝ 一律用 Charter 的正常數字縮小上移，
// 十位數的注號（¹²）才不會半邊是上標字形、半邊是合成的。行框已固定 1em，
// 上移的小字不會把行距撐開（實測行距與無注號的段落相同）。
#let sups = "⁰¹²³⁴⁵⁶⁷⁸⁹".clusters()
#show regex("[⁰¹²³⁴⁵⁶⁷⁸⁹]+"): it => super(typographic: false,
  it.text.clusters().map(c => str(sups.position(x => x == c))).join())

// 行框固定 1em 之後，行距就精確等於 1em + leading。
// spacing 設成與 leading 相同 ＝ 段落之間不另外留空：中文書靠首行縮排分段，
// 再加段距會把整片版心打散成一塊一塊。
#set par(
  leading: lead,
  spacing: lead,
  first-line-indent: (amount: 2em, all: true),
  justify: true,
)

// ── 書眉與頁碼 ────────────────────────────────────────────────────
// 只看第一、二層（部、章、前後附件）。章內小標（第三層）不算：House of Debt 每章
// 有十來個小標，第一版一律算進來，結果有小標的那一頁整頁沒有書眉，之後各頁的
// 書眉又變成小標文字（「重新配置？」），114 頁錯了 110 處。
#let top-heading = heading.where(level: 1).or(heading.where(level: 2))

#let running-head = context {
  let p = here().page()
  // 章首頁與部扉頁不放書眉：那一頁的標題本身就是最大的字，再加書眉會打架
  if query(top-heading).any(h => h.location().page() == p) { return }
  let prev = query(top-heading.before(here())).filter(h => h.outlined)
  if prev.len() == 0 { return }
  let last = prev.last()
  // 右頁書眉要帶部名：這本書四個部各有一個「第一章」，只寫章名的話
  // 讀者從書眉看不出自己在哪一部。前後附件（第一層、非部）就只寫它自己。
  let cur = if last.level == 2 {
    let part = prev.rev().find(h => h.level == 1)
    if part != none [#part.body#h(1.4em)#last.body] else { last.body }
  } else { last.body }
  set text(size: flat(cfg.head_size), fill: dim(95))
  set par(first-line-indent: 0em, justify: false)
  // 偶數頁翻開後在左手邊，放書名；奇數頁在右手邊，放目前所在的部與章
  if calc.even(p) { align(left, title) } else { align(right, cur) }
}

#let folio = context {
  set text(size: flat(cfg.folio_size), fill: dim(70))
  set par(first-line-indent: 0em, justify: false)
  align(center, counter(page).display("1"))
}

// ── 標題樣式 ──────────────────────────────────────────────────────
// 第二層的章名樣式；第一層的正文章（print.chapter_ids）也用它 —— 那種章在目錄裡
// 與各部同層，版面卻要和其他章一致。
#let chapter-title(body) = {
  set par(first-line-indent: 0em, justify: false)
  block(width: 100%, above: 0pt, below: flat(cfg.chapter_gap))[
    #let a = if cfg.chapter_align == "center" { center } else { left }
    #align(a)[#text(size: flat(cfg.chapter_size), weight: "bold", tracking: 0.08em)[#body]]
  ]
}

#show heading.where(level: 1): it => context {
  let kind = hkind.at(here())
  if kind == "chapter" { chapter-title(it.body) } else {
    let big = kind == "part"
    set par(first-line-indent: 0em, justify: false)
    block(width: 100%, above: 0pt, below: if big { 0pt } else { flat(cfg.chapter_gap) })[
      #align(center)[
        #text(size: flat(if big { cfg.part_size } else { cfg.sub_size }),
              weight: "bold", tracking: if big { 0.12em } else { 0em })[#it.body]
      ]
    ]
  }
}

#show heading.where(level: 2): it => chapter-title(it.body)

// 章內小標佔三行格線：上一行基線到小標基線正好兩行、小標到下一行正好一行，
// 小標之後的正文才會回到格線上。第一版給 lead × 1.8／0.9，量出來是 28.6／19.1pt
// （常態 19.6），小標後面整頁的行都偏離格線 8.5pt。行框上下緣固定為 0.88／0.12 em
// （見 set text），所以間距可以精確算出來。
// 小標長到換行時（《與焦慮和解》自我檢測的題目），行與行之間也要剛好一格正文行距：
// 照預設的 leading，行距是小標字級＋lead（A4 量出 24.8pt，常態 21.2），
// 每多一行，後面整頁就偏離格線 3.6pt。
#let sub = flat(cfg.sub_size)
#show heading.where(level: 3): it => {
  set par(first-line-indent: 0em, justify: false, leading: bs + lead - sub)
  block(width: 100%, above: 2 * (bs + lead) - 0.12 * bs - 0.88 * sub,
        below: bs + lead - 0.12 * sub - 0.88 * bs)[
    #text(size: flat(cfg.sub_size), weight: "bold")[#it.body]
  ]
}

// ── 積木 ──────────────────────────────────────────────────────────
#let quote-block(t) = block(width: 100%, inset: (left: 2em, right: 1em),
                            above: lead * 1.2, below: lead * 1.2)[
  #set text(size: bs * 0.95)
  #par(rich(t))
]

// 獻詞、題辭、簽名、版權條文、故事裡的告示牌：轉檔工具常把它們塞進 <h4>/<h5>，
// 它們不是章節層級的標題而是置中的排印行，不進目錄、不當標題。
//
// 正文裡（章內）的排印行必須留在格線上：同字級、不加額外空隙，只靠置中
// 與它自己的換行跟上下文區隔。第一版一律縮成 0.95 倍字級再加半行空，
// 放在前後附件頁沒事，放進正文就把那一頁的行距弄成 18.2／24.0pt。
// 前後附件頁（airy）才一條一條隔開一整行。
#let display-line(lines, airy: false, fine: false) = {
  set par(first-line-indent: 0em, justify: false)
  if fine {
    // 版權條文：小字、齊頭、條與條之間只空半行
    set text(size: bs * 0.82)
    set par(justify: true)
    block(width: 100%, below: lead * 1.4, lines.join(linebreak()))
  } else if airy {
    // 前後附件的題辭、獻詞排得比版心窄。滿版寬度時，《不停》的題辭剛好多出
    // 一個字，第二行只剩孤零零的「全。」；收窄後自然斷成兩行長短相近的句子。
    align(center, block(width: 80%, align(center, lines.join(linebreak()))))
    v(bs + lead)
  } else {
    align(center)[#lines.join(linebreak())]
  }
}

#let item-line(t) = {
  set par(first-line-indent: 0em, hanging-indent: 1em)
  par[· #rich(t)]
}

// ── 書末索引 ──────────────────────────────────────────────────────
// 索引連到的段落帶著標籤（epubread 從 EPUB 的錨點轉來），頁碼在這裡用
// counter(page).at() 算 —— 譯本的頁碼只有排完版才知道，不能從原書抄。
// 條目與正文同字級、同行距，版心格線不斷；字母分組之間空一行。
#let tagged(body, b) = if b.at("id", default: none) == none { body } else [#body#label(b.id)]

#let ix-page(id) = {
  if id == none { return none }
  let q = query(label(id))
  if q.len() == 0 { none } else { counter(page).at(q.first().location()).first() }
}

// 一組頁碼 → 「12, 30–31, 205注7」：同一頁的去重，重疊的範圍合併
#let ix-refs(refs) = {
  let out = ()
  for r in refs {
    let a = ix-page(r.to)
    if a == none { continue }
    let e = ix-page(r.end)
    if e == none or e < a { e = a }
    let sfx = if r.note != none { "注" + r.note } else if r.fig { "（圖）" } else { "" }
    if out.len() > 0 and out.last().at(2) == "" and sfx == "" and a <= out.last().at(1) {
      let prev = out.pop()
      out.push((prev.at(0), calc.max(prev.at(1), e), ""))
    } else if out.len() == 0 or out.last() != (a, e, sfx) {
      out.push((a, e, sfx))
    }
  }
  // 「205注7」是一個頁碼，不讓中西文間距把它拆成「205 注 7」。中西文間距是段落層級的
  // 設定，直接包 text(cjk-latin-spacing: none) 沒有作用（Typst 0.15 實測）；包進 box 才會
  // 自成一段排。box 也讓「112–113」不會在行尾被拆開。
  out.map(x => box({
    set text(cjk-latin-spacing: none)
    (if x.at(1) > x.at(0) { str(x.at(0)) + "–" + str(x.at(1)) } else { str(x.at(0)) }) + x.at(2)
  })).join(", ")
}

#let ix-entry(b) = context {
  set par(first-line-indent: 0em, hanging-indent: 2em, justify: false)
  let body = if b.zh == "" [#b.en] else [#b.en#h(0.6em)#b.zh]
  let any-ref = false
  for (i, sg) in b.segs.enumerate() {
    let nums = ix-refs(sg.refs)
    if nums != none and nums != "" { any-ref = true }
    let sep = if i > 0 [；] else if sg.zh != none [：] else [#h(0.6em)]
    let name = if sg.zh != none [#sg.zh#h(0.6em)] else []
    body = [#body#sep#name#nums]
  }
  if b.see != none {
    body = if any-ref [#body。#b.see] else [#body#h(0.6em)#b.see]
  }
  // 弱間距會與段距（lead）取大者而不是相加：要空出正好一行（基線距兩行），
  // 給 bs + 2·lead。第一版給 bs + lead，量出來 31.1pt，字母組之後整頁偏離格線。
  // 用弱間距是為了落在頁首時自動消失。
  if b.first { v(bs + 2 * lead, weak: true) }
  par(body)
}

// ── 圖 ────────────────────────────────────────────────────────────
// 寬度占版心 image_width%，但高度不超過版心的 image_max_height%。只看寬度的話，
// 直式窄圖會被放大到超出頁面：House of Debt 的圖 2.2（212×598 像素、三張小圖直疊）
// 被放到 316mm 高，版心只有 215mm，上下都被切掉。
#let body-h = (cfg.paper_h - cfg.margin_top - cfg.margin_bottom) * 1mm
#let fig-image(file) = layout(size => {
  // 掃描書的裁圖（PNG 記有原書解析度）照原書實際尺寸印，不放大：放大只會糊，原書的小插圖也不該變成半頁大圖
  let nat = image("images/" + file)
  let natw = measure(nat).width
  let img = if cfg.at("image_natural", default: false) and natw < size.width * cfg.image_width / 100 { nat }
            else { image("images/" + file, width: size.width * cfg.image_width / 100) }
  let maxh = body-h * cfg.image_max_height / 100
  if measure(img).height > maxh { image("images/" + file, height: maxh) } else { img }
})

// 圖與圖說綁成一塊，浮動到頁頂或頁底（place float），正文照常排滿（image_float，預設）。
// 第一版把圖當成流水的一段：放不下就整張換頁，前一頁底部空出一大塊
// （圖 2.2 前空了 101mm），圖說還會和圖分在兩頁。
// 圖說與正文同字級，行距格線不斷；浮動塊與正文之間空出正好一行
// （圖說基線到正文基線 = 兩行），逐頁驗證的行距檢查才量得準。
#let fig-cell(b) = {
  align(center, fig-image(b.file))
  let cap = b.at("cap", default: none)
  if cap != none {
    v(0.6em)
    align(center, tagged(par(rich(cap)), b))
  }
}
// 圖列（掃描數學書裡各有圖說的並排圖）：等寬欄並排，底端對齊，圖說才會在同一行
#let fig-body(b) = block(width: 100%, {
  set par(first-line-indent: 0em, justify: false)
  if b.k == "figrow" {
    grid(columns: (1fr,) * b.cells.len(), column-gutter: 1.5em, align: center + bottom, ..b.cells.map(fig-cell))
  } else { fig-cell(b) }
})
// image_float: false（掃描數學書）：圖排在原位，放不下就整塊移到下一頁。浮動的話圖會跑到頁頂，
// 壓在同一頁的章名之上（Griffiths 的「Advertisement」），也會離開緊接著它的推導。
// 前後與正文各空一行：圖說基線到下一段基線正好兩行，行距格線不斷。
#let fig(b) = if cfg.image_float {
  place(auto, float: true, clearance: bs + 2 * lead, fig-body(b))
} else {
  block(width: 100%, breakable: false, above: bs + 2 * lead, below: bs + 2 * lead, fig-body(b))
}

// 翻到下一個奇數頁（右頁）。中間那張補位的空白頁必須拿掉書眉與頁碼，
// 否則讀者會看到「一張只有頁碼的空白頁」，那是排版瑕疵不是留白。
//
// 第一版是在 context 裡看 here().page() 的奇偶、偶數才插一張 page()。
// 那會不收斂：插一頁改變了後面所有頁碼，後面的判斷跟著翻轉，Typst 的五輪
// 版面迭代在 47/48/49 頁之間來回震盪，書眉因此抓錯章名。
// 原生 pagebreak(to:) 由版面引擎自己處理補頁，是靜態結構；作用域內的
// set page 只套用到這個 block 裡「開始」的頁面，也就是補位頁本身 ——
// 落點那一頁仍沿用外層的書眉設定。
#let to-recto() = {
  set page(header: none, footer: none)
  pagebreak(to: "odd", weak: true)
}

// ── 前置頁（不編頁碼、無書眉）───────────────────────────────────────
#set page(header: none, footer: none)

// 封面背面一律留白，讓書名頁落在右頁
#if cfg.cover_image != none and cfg.use_cover {
  page(margin: 0mm)[#align(center + horizon)[#image("images/" + cfg.cover_image, height: 100%)]]
  page[]
}

#page[
  #set par(first-line-indent: 0em, justify: false)
  #v(30%)
  #align(center)[
    #text(size: flat(cfg.title_size), weight: "bold", tracking: 0.15em)[#title]
    #if cfg.subtitle != "" [
      #v(1.4em)
      #text(size: bs * 1.15, fill: dim(80), tracking: 0.05em)[#cfg.subtitle]
    ]
    #v(2.6em)
    #text(size: bs * 1.1)[#cfg.author]
  ]
  #align(center + bottom)[#text(size: flat(cfg.folio_size), fill: dim(120))[#cfg.imprint]]
]

#if cfg.toc {
  page[
    #set par(first-line-indent: 0em, justify: false, leading: lead * 1.2)
    #v(7%)
    #align(center)[#text(size: flat(cfg.chapter_size), weight: "bold", tracking: 0.3em)[目錄]]
    #v(2.2em)
    #show outline.entry.where(level: 1): it => {
      v(lead * 1.1, weak: true)
      strong(it)
    }
    #outline(title: none, depth: 2, indent: 1.8em)
  ]
}

// ── 正文 ──────────────────────────────────────────────────────────
// 正文第一頁一定落在右頁（實體奇數頁）。目錄若排超過一頁，前置頁就變奇數張，
// 不補這一下的話實體頁與頁碼的奇偶會錯開 —— 書眉左右放反，部扉頁也翻不到右頁。
#to-recto()
#set page(header: running-head, footer: folio)
// update(1) 不是 update(0)：此刻已站在正文第一頁的頁首，更新的就是這一頁。
// 第一版寫 0，目錄第一筆因此印成「第 0 頁」、全書頁碼少一。
#counter(page).update(1)

#for ch in data.chapters {
  let blocks = ch.blocks
  if blocks.len() == 0 and ch.title == "" { continue }

  if ch.at("is_part", default: false) {
    to-recto()
    // 部扉頁自成一頁，不帶書眉頁碼；背面留白，正文從下一個右頁開始
    page(header: none, footer: none)[
      #hkind.update("part")
      #v(cfg.part_top_ratio * 100%)
      #heading(level: 1, ch.title)
    ]
    to-recto()
  } else {
    let as-chapter = ch.level == 2 or ch.at("as_chapter", default: false)
    if as-chapter and cfg.chapter_recto { to-recto() } else { pagebreak(weak: true) }
    if ch.title != "" {
      if as-chapter { v(cfg.chapter_top_ratio * 100%) } else { v(6%) }
      hkind.update(if ch.level == 1 and as-chapter { "chapter" } else { "matter" })
      heading(level: if ch.level == 2 { 2 } else { 1 }, ch.title)
    }
  }

  for b in blocks {
    if b.k == "p" { tagged(par(rich(b.t)), b) }
    else if b.k == "quote" { tagged(quote-block(b.t), b) }
    else if b.k == "li" { tagged(item-line(b.t), b) }
    else if b.k == "display" {
      display-line(b.lines, airy: ch.level == 1, fine: ch.at("fine_print", default: false))
    }
    else if b.k == "h" { tagged(heading(level: 3, rich(b.t)), b) }
    else if b.k == "eq" { tagged(eq-block(b, above: lead, below: lead), b) }
    else if b.k == "img" or b.k == "figrow" { fig(b) }
    else if b.k == "ix" { ix-entry(b) }
    else if b.k == "ixnote" {
      par(first-line-indent: 0em, text(fill: dim(90))[條目依原書英文字母順序排列，頁碼為本書頁碼。])
    }
  }
  // 這一章還沒放的浮動圖在章末放掉，不能漂到下一章。放在章首不行：flush 本身算內容，
  // 換章的弱分頁會因此生效，正文第一頁前多出一張只有頁碼的空白頁（第一版就是如此）。
  if blocks.any(b => b.k == "img" or b.k == "figrow") { place.flush() }
}
