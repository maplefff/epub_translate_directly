// 掃描數學書 OCR 比較報告（先跑 make_appendix.py）：typst compile --root . experiments/ocr_claude_vs_qwen/report.typ experiments/ocr_claude_vs_qwen/REPORT.pdf
#set page(paper: "a4", margin: (x: 22mm, y: 22mm), numbering: "1")
#set text(font: ("Charter", "Songti TC"), size: 10pt, lang: "zh", region: "tw")
#set par(justify: true, leading: 0.75em, spacing: 1.1em)
#set heading(numbering: "1.1")
#show heading.where(level: 1): set text(size: 13pt)
#show heading.where(level: 2): set text(size: 11pt)
#show heading: set block(above: 1.4em, below: 0.8em)
#show table.cell.where(y: 0): set text(weight: "bold")
#set table(stroke: none, inset: (x: 5pt, y: 3.5pt))
#let ink2 = rgb("#52514e")
#let bar = rgb("#2a78d6")
#let note(body) = text(size: 8.5pt, fill: ink2, body)

#align(center)[
  #text(size: 16pt, weight: "bold")[掃描數學書 OCR：本機 Qwen3.5-27B 與 Claude 直接轉寫的比較]
  #v(0.3em)
  #text(fill: ink2)[2026-10-12 · M5 Max 128GB · epub_translate_directly]
]

= 結論

+ *精度：四種做法都很高，Claude 三個模型沒有實質錯誤。* 在 20 頁合成教材上，Haiku 5.5、Sonnet 5.5、Opus 5.5 的獨立公式全部正確（54/54），公式編號、圖、註腳、草寫 𝓇（22/22）、粗體向量（108/108）也全對；彼此的差異只剩等價寫法（`\text` 與 `\mathrm`、單位放公式內外）。Qwen 的公式結構同樣全對，但有 4 處字體錯（曲面 $cal(S)$ 寫成 $S$ 三次、零向量 *0* 少了粗體），標題層級系統性地深一層（對 8/23），也會違反格式規則（輸出書眉、表格寫成 LaTeX `tabular`、整頁包在程式碼區塊裡）；後三者正式流程的後處理已經會修。
+ *速度：Claude 約快 9 倍。* Claude 子代理每頁 6.5–8.7 秒；Qwen 單一程序每頁 68–69 秒。正式流程可以開 3 個 Qwen 程序並行（本次沒測並行吞吐量）。
+ *Token：Claude 每頁邊際約 5.6k 上下文＋0.9k 輸出，但子代理有約 5.9 萬的固定開銷，且每輪重讀整段上下文，10 頁累計快取讀取約 97 萬（Haiku 約 180–205 萬）。* Qwen 每頁輸入約 8.4k、輸出約 0.5k，在本機推論，不吃額度。
+ *決定性的限制是版權，不是精度。* 原本以真實 Griffith 頁面測試時，Haiku 在第 9 頁被 API 的輸出內容過濾擋下。逐字轉寫受版權保護的書，Claude 無法穩定跑完整本；這也是本次改用自製教材的原因。
+ *建議：維持 Qwen 本機流程為主力。* 若要更準，優先在 Qwen 的後處理補上「依節號重設標題層級」；Claude 不適合當整本書的 OCR 引擎。

= 方法

== 測試素材

原計畫抽 Griffith《Introduction to Electrodynamics》10 頁，但 Claude 轉寫時觸發內容過濾（見結論 4），而且由我逐字寫出整頁標準答案等於重製受版權保護的內容，所以改用兩份自製教材，各 10 頁。原稿就是標準答案（Markdown＋LaTeX），用專案的 Typst＋mitex 公式模組排版，再轉成 300 dpi 灰階的純影像 PDF（沒有文字層），兩邊讀到的像素完全相同。

- *熱傳導教材（乾淨掃描）*：2D 熱方程、有限差分、von Neumann 穩定性、Crank–Nicolson、ADI；29 條獨立公式（`cases`、`aligned`、塊三對角 `pmatrix`）、5 張圖（真實模擬的溫度場、模板、放大因子、收斂圖）、1 個表、2 則註腳、5 道習題。只加輕微模糊與雜訊。
- *電磁學教材（仿真掃描）*：仿 Griffith 第 2 章的版面慣例（內容自寫），刻意放進它的難點：草寫分離向量 𝓇（含粗體與單位向量版）、粗體向量、`\bar{\mathbf{E}}`、四極張量矩陣、多行 `aligned`、`cases`、註腳、圖只標號碼。紙張質感全部是程式產生的，不是真的掃描：歪斜 0.25–0.6°、先降到約 200 dpi 再放大（模擬掃描器解析度）、墨色變淡與灰底、光照不均、裝訂邊陰影、雜訊、JPEG 品質 38。字形本身仍是乾淨的向量字型，沒有真實舊書的墨點、斷筆、透印。

#note[排版時發現 mitex 不認 `\\[2mm]` 這種加間距的換行，會把「[2mm]」直接印在頁面上；這是 Haiku 第一次跑電磁學組時回報的。修正原稿後重建教材並重跑，有問題的那一輪不計入結果。]

== 四種做法

- *Qwen（現行流程）*：`vlm_worker.py` 原封不動（PP-DocLayout-V3 版面模型＋Qwen3.5-27B 8bit，貪婪解碼、迴圈偵測），用包裝腳本換提示詞，單一程序循序跑。電磁學組用專案的 Griffith 提示詞（含草寫 𝓇 規則），熱傳導組用拿掉 Griffith 專屬規則的通用版。
- *Claude Haiku／Sonnet／Opus 5.5*：每個模型每組各開一個子代理，逐頁「讀圖 → 立即寫檔」，提示詞與 Qwen 逐字相同；禁止讀任何其他檔案，不准回頭修改。

== 評分

逐頁和標準答案比對，平均或加總：
- *正文*：去掉公式後的英文字詞串，字元級編輯距離相似度（1 − CER）。分成「原始輸出」與「經後處理」兩欄。後處理比照正式流程（`vlm.py`）的做法：拆掉外框、`tabular` 轉 Markdown、刪書眉，四種做法一律套用。
- *公式*：所有公式依序串接後的相似度；「去字體」再去掉粗體、草寫、`\mathsf`、`\text` 等字體指令。*獨立公式全對*：標準答案的每條獨立公式，在輸出裡找不找得到正規化後完全相同的一條。正規化會吸收空白、大括號、`\left.`、`\\[2ex]`、上下標順序、`\le`／`\leq` 這類等價寫法。
- *結構*：`\tag` 編號、圖片佔位行、頁底註腳、標題（層級＋文字）。電磁學組另計草寫 𝓇 與粗體指令的數量。

== 時間與 token 的口徑

- *Qwen*：每頁時間取自快取的 `sec`（含版面模型與生成；模型已在系統快取裡，載入只要 3 秒，不計入）。輸出 token 取自 `gen_tokens`。輸入 token 依模型的前處理設定計算：2550×3300 的頁面不縮圖，每 32×32 像素一個視覺 token，約 8,240 個，加上提示詞約 8,440。
- *Claude*：從子代理的對話紀錄（JSONL）依 message id 去重，加總每輪的 usage。時間取「啟動到最後一頁寫完」除以 10，含工具往返。這是*子代理口徑*：每輪都把整段對話（含之前所有頁面圖）當作輸入重送，所以會出現大量快取讀取。

= 結果

== 精度（經後處理）

#figure(
  table(
    columns: (auto, auto, 1fr, 1fr, 1fr, 1fr, 1fr, 1fr),
    align: (left, left, right, right, right, right, right, right),
    table.hline(),
    [組別], [做法], [正文], [公式], [公式（去字體）], [獨立公式全對], [編號], [標題],
    table.hline(stroke: 0.5pt),
    [熱傳導], [Haiku], [0.998], [0.974], [0.994], [29/29], [25/25], [8/11],
    [], [Sonnet], [0.998], [0.973], [0.995], [29/29], [25/25], [11/11],
    [], [Opus], [0.996], [0.974], [0.992], [29/29], [25/25], [11/11],
    [], [Qwen], [0.996], [0.965], [0.993], [29/29], [25/25], [4/11],
    table.hline(stroke: 0.3pt + ink2),
    [電磁學], [Haiku], [0.999], [0.996], [0.998], [25/25], [24/24], [12/12],
    [], [Sonnet], [0.999], [0.982], [0.998], [25/25], [24/24], [12/12],
    [], [Opus], [0.999], [0.995], [0.998], [25/25], [24/24], [12/12],
    [], [Qwen], [0.999], [0.984], [0.994], [24/25], [24/24], [4/12],
    table.hline(),
  ),
  caption: [精度。圖片佔位行（熱傳導 5、電磁學 4）與註腳（各 2）四種做法全對；電磁學組的草寫 𝓇 四種都是 22/22，粗體 Claude 108/108、Qwen 107/108。],
)

「公式」一欄（含字體）的落差幾乎都是等價寫法：Sonnet 慣用 `\mathrm{above}` 而標準答案是 `\text{above}`，所以電磁學組比較低；四種做法也都沒有保留 `\mathsf{A}` 的無襯線字體（mitex 把它排成斜體無襯線，從圖上很難看出原稿用了 `\mathsf`）。Qwen 在電磁學組唯一沒對上的獨立公式，是把 $frac(sqrt(3) q a, 2) frac(cos theta, r^2)$ 合併成單一分數，數學上等價。

== 格式遵循（原始輸出）

#figure(
  table(
    columns: (auto, 1fr, 1fr, 1fr, 1fr),
    align: (left, right, right, right, right),
    table.hline(),
    [組別], [Haiku], [Sonnet], [Opus], [Qwen],
    table.hline(stroke: 0.5pt),
    [熱傳導：正文（不做後處理）], [0.998], [0.998], [0.996], [0.964],
    [電磁學：正文（不做後處理）], [0.999], [0.999], [0.999], [0.999],
    [標題層級正確（兩組合計）], [20/23], [23/23], [23/23], [8/23],
    table.hline(),
  ),
  caption: [原始輸出是否守提示詞的格式規則。],
)

Qwen 的熱傳導組在原始輸出下掉到 0.964，原因是：有幾頁照抄了書眉、表格寫成 `\begin{tabular}`、整頁包在 ```` ```markdown ```` 裡。這三種正式流程都已經處理，所以經後處理後回到 0.996。標題則是*系統性地深一層*（「1.1」用 `##`、「1.1.1」用 `###`），文字本身全對（不計層級時 23/23）；Haiku 也有 3 個小節標題層級不對。

== 速度

#let speed = (("Haiku 5.5", 7.6), ("Sonnet 5.5", 7.5), ("Opus 5.5", 8.1), ("Qwen3.5-27B（單程序）", 68.6))
#figure(
  block(width: 100%, {
    let maxv = 70.0
    grid(
      columns: (34mm, 1fr), row-gutter: 6pt, column-gutter: 8pt, align: (right + horizon, left + horizon),
      ..speed.map(((name, v)) => (
        text(size: 9pt)[#name],
        box(width: 100%, {
          box(width: 100% * (v / maxv) * 0.78, height: 11pt, fill: bar, radius: (right: 3pt))
          h(5pt)
          text(size: 9pt)[#v 秒／頁]
        }),
      )).flatten()
    )
  }),
  caption: [每頁平均秒數（兩組 20 頁平均）。Claude 為子代理從讀圖到寫檔的總時間除以頁數，含工具往返；Qwen 為單一程序循序推論。],
)

各組明細：Haiku 熱傳導 6.5、電磁學 8.7 秒；Sonnet 7.0／7.9；Opus 8.3／8.0；Qwen 69.0／68.2（單頁最快 53、最慢 80 秒）。電磁學組的粗糙掃描對 Qwen 的速度沒有影響，Haiku 則因為思考變長而慢了一點。

== Token 用量

#figure(
  table(
    columns: (auto, auto, 1fr, 1fr, 1fr, 1fr, 1fr),
    align: (left, left, right, right, right, right, right),
    table.hline(),
    [做法], [組別], [首輪上下文], [每頁增加], [輸出合計], [快取寫入], [快取讀取],
    table.hline(stroke: 0.5pt),
    [Haiku], [熱傳導], [59,398], [5,716], [10,579], [116,551], [1,792,843],
    [], [電磁學], [59,513], [6,655], [19,574], [66,553], [2,055,219],
    [Sonnet], [熱傳導], [59,416], [5,640], [9,707], [115,813], [973,492],
    [], [電磁學], [59,518], [5,630], [9,614], [115,812], [973,721],
    [*Opus*], [熱傳導], [59,406], [5,655], [8,841], [115,957], [974,372],
    [], [電磁學], [59,508], [5,582], [9,160], [115,328], [970,757],
    table.hline(stroke: 0.3pt + ink2),
    [Qwen], [每頁], [—], [≈ 8,440 輸入], [486–544／頁], [—], [—],
    table.hline(),
  ),
  caption: [Token 用量（每組 10 頁）。「首輪上下文」是子代理的固定開銷（系統提示與工具定義）；「每頁增加」是上下文每多一頁增加的量（頁面圖＋轉寫結果）。],
)

*Opus 子代理的消耗*：熱傳導組輸入合計 1,090,353（未快取 24＋快取寫入 115,957＋快取讀取 974,372），輸出 8,841，82.7 秒；電磁學組輸入合計 1,086,109（24＋115,328＋970,757），輸出 9,160，80.2 秒。兩組合計約 218 萬輸入（其中 194 萬是快取讀取）、1.8 萬輸出。

Haiku 的快取讀取約是 Sonnet、Opus 的兩倍。Haiku 每輪只呼叫一個工具，跑了 21–22 輪；Sonnet 和 Opus 會把「寫上一頁」和「讀下一頁」放在同一輪，只跑 12 輪，而每多一輪就要多重讀一次整段上下文。Haiku 在電磁學組的輸出也多了一倍（含思考）。

若改成直接呼叫 API、一頁一個請求，每頁大約是「頁面圖＋提示詞」的輸入加上約 0.9k 輸出，不會有子代理的固定開銷和累積重讀。#note[這是依上表推估，本次沒有實測，因為專案規約預設不直接呼叫模型端點。]

= 錯誤分析

#figure(
  table(
    columns: (auto, auto, 1fr),
    align: (left, left, left),
    table.hline(),
    [做法], [位置], [錯誤],
    table.hline(stroke: 0.5pt),
    [Qwen], [電磁學 p.3], [曲面 $cal(S)$ 寫成 $S$（三處：$integral.cont_(cal(S))$ 的下標與正文）],
    [Qwen], [電磁學 p.5], [$nabla times bold(E) = bold(0)$ 的零向量少了粗體],
    [Qwen], [兩組全部], [標題層級深一層（15 處）],
    [Qwen], [熱傳導多頁], [輸出書眉、表格用 `tabular`、整頁包程式碼區塊（正式流程會修）],
    [Haiku], [熱傳導], [3 個小節標題層級不對],
    table.hline(),
  ),
  caption: [實質錯誤（等價寫法不列入）。Claude 三個模型沒有任何讀錯符號或漏字的情況。],
)

兩份教材都沒有出現先前在 Griffith 上看到的典型錯誤（𝓇 讀成 z、粗體遺失、`\bar` 寫成 `\tilde`）。在仿真掃描組，四種做法的 𝓇 都是 22/22。

= 限制

- *素材是合成的。* 即使加了掃描效果，字形仍是乾淨的向量字型渲染，比真實的 1990 年代掃描（墨點、斷筆、透印）容易；兩組的分數都偏高，差距被壓縮了。在真實掃描書上，先前的 Griffith 測試裡 Qwen 的公式相似度約 0.99，與本次一致，但 Claude 在真實書上的表現因版權過濾無法完整測。
- *樣本小*：20 頁、54 條獨立公式。Claude 三者之間的差異都在雜訊範圍內，不能據此排序。
- *Claude 看到的解析度不明。* 頁面圖是 2550×3300，Read 工具或 API 會先縮圖再送進模型，實際送入的大小我無法確認；Qwen 則是全解析度。
- *計時口徑不同。* Claude 的時間包含子代理的工具往返與雲端排隊，Qwen 是本機純推論；Qwen 正式流程可開 3 個程序並行，本次只測單程序。
- *未計入的消耗*：兩次作廢的執行沒有計入結果。一次是 Haiku 的 Griffith 8 頁，在第 9 頁被內容過濾擋下，輸入合計 171 萬、輸出 2.7 萬；另一次是 Haiku 電磁學組的第一輪，原因是排版出了問題。主控監督（Opus）本身的消耗也沒有計入。

= 附錄：重現

腳本在 `experiments/ocr_claude_vs_qwen/`，素材與輸出在 `process/_ocr_bench/`（不進版控，可整個刪掉）：

#table(
  columns: (auto, 1fr),
  align: (left, left),
  table.hline(), [檔案], [用途], table.hline(stroke: 0.5pt),
  [`make_heat_figures.py`、`make_em_figures.py`], [兩份教材的配圖（numpy＋PIL）],
  [`build_synth.py`], [原稿 → Typst（mitex）→ 300 dpi 掃描 PDF、逐頁標準答案；設定在各組的 `meta.json`],
  [`run_qwen.py`], [包裝 `vlm_worker.py`，可換提示詞；不改專案程式],
  [`prompt_griffith.txt`、`prompt_general.txt`], [兩組用的提示詞（四種做法逐字相同）],
  [`claude_usage.py`], [從子代理紀錄抽出 token 與時間，不印內容],
  [`score.py`], [評分（含與正式流程相同的後處理）；`--json` 存下逐頁明細],
  [`render_outputs.py`], [把各做法的輸出排版成圖（公式逐條試排，排不出的照原樣印）],
  [`make_appendix.py`], [逐頁對照附錄的資料：原頁縮圖、原稿、差異標色],
  table.hline(),
)

// ── 附錄 B：逐頁對照（資料由 make_appendix.py 產生）──────────────────
#pagebreak()
= 附錄：逐頁對照

每頁分三部分：

+ *掃描原頁與原稿*：左邊是送進 OCR 的掃描頁，右邊是原稿的 Markdown＋LaTeX，也就是標準答案。
+ *排版結果*：四種做法的輸出，經過和正式流程相同的後處理（拆外框、`tabular` 轉表格、刪書眉）之後，用原書的字型與版心寬度排出來，可以直接跟原頁對看。圖只畫佔位框，因為 OCR 只標出圖的位置。公式先逐條試排，排不出的會照原樣印成#text(fill: rgb("#c0392b"))[紅色等寬字]；本次 379 條全部排得出來。
+ *原始輸出*：未經後處理的 LaTeX，和原稿逐詞比對：
  - #text(fill: rgb("#c0392b"))[#strike[紅色刪除線]]：原稿有、輸出漏掉或讀錯。
  - #highlight(fill: rgb("#cdeccf"))[綠底]：輸出多出來或寫法不同。
  - 只差空白、大括號、間距指令、`\left`／`\right`、`\le`／`\leq`、`\text`／`\mathrm` 的片段視為相同，不標色。
  - 上下標順序互換、單位寫進公式裡這類寫法仍會標色，但不算讀錯。

電磁學組的紙張底色、歪斜、裝訂邊陰影與 JPEG 雜訊都是程式產生的仿真效果，見 2.1 節。

#let mono = ("Menlo", "STIX Two Text", "Songti TC")
#let lines(s) = {
  let parts = s.split("\n")
  for (i, p) in parts.enumerate() {
    if i > 0 { linebreak() }
    p
  }
}
#let render(segs) = for (kind, s) in segs {
  if kind == "=" { lines(s) }
  else if kind == "-" { text(fill: rgb("#c0392b"), strike(lines(s))) }
  else { highlight(fill: rgb("#cdeccf"), lines(s)) }
}
#let pane(title, sub, body) = block(width: 100%, breakable: true, stroke: 0.4pt + rgb("#b9b8b2"), inset: 5pt, radius: 2pt)[
  #text(size: 8.5pt, weight: "bold")[#title] #h(4pt) #text(size: 7pt, fill: ink2)[#sub]
  #v(-2pt)
  #set par(justify: false, leading: 0.45em, spacing: 0.5em)
  #text(font: mono, size: 6.2pt, body)
]
#let shot(title, sub, file) = block(width: 100%, breakable: false, stroke: 0.4pt + rgb("#b9b8b2"), inset: 5pt, radius: 2pt)[
  #text(size: 8.5pt, weight: "bold")[#title] #h(4pt) #text(size: 7pt, fill: ink2)[#sub]
  #v(-4pt)
  #image(file, width: 100%)
]
#let A = "/process/_ocr_bench/report_assets/"

#let data = json(A + "appendix.json")
#for p in data {
  pagebreak(weak: true)
  heading(level: 2, numbering: none)[#p.set 第 #p.page 頁（#p.name）]
  grid(columns: (50%, 1fr), column-gutter: 8pt,
    image(A + p.image, width: 100%),
    pane([原稿（標準答案）], [], lines(p.gt)),
  )
  pagebreak(weak: true)
  text(size: 10pt, weight: "bold")[#p.set 第 #p.page 頁：排版結果]
  v(2pt)
  grid(columns: (1fr, 1fr), column-gutter: 8pt, row-gutter: 8pt,
    ..p.models.map(m => shot(m.label, [後處理後排版], A + "render/" + p.skey + "_" + p.name + "_" + m.key + ".png"))
  )
  pagebreak(weak: true)
  text(size: 10pt, weight: "bold")[#p.set 第 #p.page 頁：原始輸出與差異]
  v(2pt)
  grid(columns: (1fr, 1fr), column-gutter: 8pt, row-gutter: 8pt,
    ..p.models.map(m => pane(m.label, m.stat, render(m.segs)))
  )
}
