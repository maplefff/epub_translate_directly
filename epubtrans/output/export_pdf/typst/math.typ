// 公式（掃描數學書）：LaTeX 交給 mitex 轉成 Typst 數學。book.typ 與 mathcheck（逐條試排）共用這一份。
//
// 文字裡的行內式由 read_translated_epub 包成「私用區字元＋TeX」：U+E000 TeX U+E001；
// mathcheck 試排失敗的改包成 U+E002 TeX U+E003，照原樣印成等寬字（mitex 一條出錯整本書就編不出來）。
#import "@preview/mitex:0.2.7": mitex-convert, mitex-scope

// mitex 把 aligned／array 包成 block 放進公式，基線落在區塊底部：
// \left. … \right\} 的括號以數學軸為中心上下對稱伸長，會往下多出一截（Griffiths 的方程組，例 9.197）。
// 改成區塊的垂直中心對準數學軸（約 0.25em）。
#let on-axis(body) = box(baseline: 50% - 0.25em, body)

// mitex 的 array 把每格排成行內式、行距 0.5em，多行分式會上下重疊（Griffiths 的張量、方程組）：
// 改成展示式、加大行距。
#let mitex-array(arg0: ("l",), ..args) = {
  if args.pos().len() == 0 { return }
  if type(arg0) != str {
    if arg0.has("children") {
      arg0 = arg0.children.filter(it => it != [ ] and it != [#math.zws]).map(it => it.text)
        .filter(it => it in ("l", "c", "r"))
    } else { arg0 = (arg0.text,) }
  }
  let rows = args.pos().map(row => if type(row) == array { row } else { (row,) })
  let m = calc.max(..rows.map(r => r.len()))
  rows = rows.map(r => r + (m - r.len()) * (none,))
  set align(("l": left, "c": center, "r": right).at(if arg0.len() > 0 { arg0.at(0) } else { "l" }))
  on-axis(pad(y: 0.2em, grid(columns: m, column-gutter: 0.5em, row-gutter: 0.9em,
    ..rows.flatten().map(it => $display(it)$))))
}

#let mitex-aligned(..args) = if args.pos().len() == 0 { math.zws } else {
  on-axis(pad(y: 0.2em, block(math.op(math.display(args.pos().at(0))))))
}
#let mitex-alignedat(arg0: none, it) = on-axis(pad(y: 0.2em, block(math.op(it))))
#let tex-scope = mitex-scope + (mitexarray: mitex-array, aligned: mitex-aligned, alignedat: mitex-alignedat)

#let mx(s, block: true) = math.equation(block: block,
  eval("$" + mitex-convert(mode: "math", s) + "$", scope: tex-scope))

#let tex-raw(s) = text(font: "Menlo", size: 0.85em, fill: rgb("#a00000"), s)

// 段落字串 → 內容：切出包在私用區字元裡的公式
#let rich(t) = {
  if type(t) != str or not (t.contains("\u{E000}") or t.contains("\u{E002}")) { return t }
  let out = []
  let pos = 0
  for m in t.matches(regex("\u{E000}([^\u{E001}]*)\u{E001}|\u{E002}([^\u{E003}]*)\u{E003}")) {
    out += t.slice(pos, m.start)
    let (ok, bad) = m.captures
    out += if ok != none { mx(ok, block: false) } else { tex-raw("$" + bad + "$") }
    pos = m.end
  }
  out + t.slice(pos)
}

// 獨立公式：置中，編號靠右。放不下時（Griffiths 式 10.55 這類長推導，B5 全書約 7 條）：
//   1. 加上編號只差一點（縮到 90% 以上就放得下）→ 微縮，編號留在同一行；
//   2. 否則編號移到下一行靠右（LaTeX 的做法），公式獨占整行，比版心寬才等比縮小。
#let eq-min-scale = 0.9
#let eq-block(b, above: 0.6em, below: 0.6em) = block(width: 100%, above: above, below: below, breakable: false,
  layout(size => {
    let eq = if b.at("ok", default: true) { mx(b.tex) } else { tex-raw("$$" + b.tex + "$$") }
    let has-tag = b.at("tag", default: none) != none
    let tag = if has-tag [(#b.tag)] else []
    let gutter = 1em.to-absolute()
    let w = measure(eq).width
    let tw = if has-tag { measure(tag).width + gutter } else { 0pt }
    let shrink(body, avail) = if w <= avail { body } else { scale(avail / w * 100%, reflow: true, body) }
    let row(body) = grid(columns: (1fr, auto), align: (center + horizon, right + horizon),
      column-gutter: gutter, body, tag)
    if w + tw <= size.width or (size.width - tw) / w >= eq-min-scale {
      row(shrink(eq, size.width - tw))
    } else {
      stack(dir: ttb, spacing: 0.4em, align(center, shrink(eq, size.width)), align(right, tag))
    }
  }))
