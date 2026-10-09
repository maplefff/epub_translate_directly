# 掃描數學書（pdf.mode: vlm）圖片處理的改善計畫

2026-10-07 整理。分支 `latex_OCR_test`。對象書：`process/Introduction to Electrodynamics 3rd Edition/`（Griffiths 第三版掃描檔，596 頁）。

## 實作結果（2026-10-07）

四項都做了，第 3 項採 (b) 圖列，第 4 項採「排在原位」（`print.image_float: false`，預設仍浮動）。
commit：`d9fd7bc`（第 1、2 項）、`a4c9412`（第 3 項＋全書抽查的對位修正）、`9541a36`（LaTeX tabular 表格）、`72b7dc0`（第 4 項）。
驗收各條都通過；B5 第 4、16、32 頁分別是 Four Realms 圖表、Figure 1.7／1.8 並排、Figure 1.18。
仍未處理：版面模型沒框到圖的頁（第 136 頁 Figure 3.7、154 頁 Table 3.1、390 頁 Figure 9.7）只剩圖說、沒有圖；
VLM 沒寫的圖（`figure_mismatch`，32 頁）位置仍依高度推定。

## 開工前要知道的

- **背景有 OCR 在跑**（`vlm_worker.py`，單一程序，寫進 `work/vlm/pNNNN.json`）。不要停它、不要刪 `work/vlm/`，也不要另開 OCR 程序：
  3 個程序會互相搶 GPU，整體反而更慢（實測每頁約 100 秒，單程序約 65 秒）。進度看 `work/vlm/run.log`。
- 下面的修正**只動抽取與排版，不需要重跑 OCR**。快取不齊時 `extract` 會略過缺的頁並警告，可以照常測試：
  ```bash
  N="Introduction to Electrodynamics 3rd Edition"
  ./.venv/bin/python -m epubtrans extract "$N"
  ./.venv/bin/python -m epubtrans build "$N" --allow-partial
  ./.venv/bin/python -m epubtrans pdf "$N" --paper b5
  ```
  `extract` 會用 macOS Vision 讀圖說框，跟背景 OCR 搶不到多少資源；`pdf` 的公式試排會吃滿 CPU，跑完就好。
- 相關程式：
  - `epubtrans/source/import_pdf/vlm.py`：`group_figures`、`crop_figures`、`place_figures`、`build_book`
  - `epubtrans/output/export_epub.py`：`render()` 的 image 分支、`is_caption`
  - `epubtrans/output/export_pdf/content/read_translated_epub.py`：讀 `<figure>`
  - `epubtrans/output/export_pdf/typst/book.typ`：`fig()`、`fig-image()`
- 測試：`./.venv/bin/python tests/test_vlm.py`（目前 28/28），另外 `test_pipeline.py`、`test_index.py`、`test_naming.py` 不能壞。
  依專案慣例分節實作，每節測試通過就 commit，文件更新放同一個 commit。
- 查問題時用 `./.venv/bin/python -m epubtrans page "$N" 頁碼` 看原書頁面；版面框在 `work/vlm/pNNNN.json` 的 `layout`
  （`bbox` 是 `[y0, x0, y1, x1]`，0～1000，相對頁面），VLM 輸出在 `md`。

## 流程分環節

| 環節 | 內容 |
|---|---|
| A 版面模型 | PP-DocLayout-V3：圖框（image／table）、圖說框（figure_title）、書眉頁碼等，帶座標 |
| B OCR 模型 | Qwen3.5-27B：整頁轉成 Markdown＋LaTeX，圖寫成 `![](figure)` 佔位 |
| C 抽取對位 | `vlm.py`：把 A、B 的結果組成 book.json（圖的分組、裁圖、插入位置） |
| D EPUB | `export_epub.py`：每張圖一個 `<figure>` |
| E PDF | `book.typ`：每張圖一個滿寬置中的浮動區塊（`place(auto, float: true)`） |

**結論：三個問題 A、B 都正確，錯在 C；E 的浮動規則讓其中兩個更明顯。**

## 發現的問題與根因

頁碼指 B5 PDF 上印的頁碼。

### 1. 原書左右並排的圖，PDF 一律上下排

- A 有每個圖框的座標，看得出並排；B 用 Markdown 寫，本來就沒辦法表達並排，這不是錯。
- C：book.json 只有「一張圖一個 image 項目」，沒有「同一列」的概念。
- D、E：每張圖各自成一個 `<figure>`／一個滿寬浮動區塊，所以一定上下排。
- 分兩種情況：
  - **多格圖**：同一個「Figure N」底下的 (a)(b)(c)。只有格子小標沒被 A 偵測成獨立的圖說框時，C 才會把格子併成一張（例：Figure 1.28）。小標被偵測成圖說框時就併不起來（例：Figure 1.18，見第 3 點）。
  - **獨立的並排圖**：各有自己的圖說（例：原書 PDF 第 19 頁的 Figure 1.7、1.8）。目前設計一律上下排。

### 2. 第 4 頁：「Four Realms of Mechanics」圖表跑到章名「Advertisement」之上

原書 PDF 第 11 頁。
- B 正確：把 2×2 圖表寫成 Markdown 表格，位置在「In the diagram below I have sketched out…」之後。
- A 正確：標成 `table`，`bbox [429, 138, 525, 480]`。
- C 錯：表格有裁圖時，`place_figures` 把 VLM 的 Markdown 表格整個刪掉，等於丟掉了現成的正確錨點；又沒有「Table N」圖說可以對位，只好退回「依圖在頁面上的高度比例」推算位置。段落有長有短，結果插到「Four Realms of Mechanics」標題前面。
- E 錯：PDF 的圖會浮動，被推到頁面最上方，排在同一頁的章名之上。

### 3. 第 33～34 頁：句子被「(a)(b)(c)」切斷，Figure 1.18 拆成三張圖

原書 PDF 第 33 頁：(a)(b) 並排在上，(c) 在下，三格共用一個「Figure 1.18」。
- A 正確：3 個 image 框、3 個格子小標框（figure_title，內容是 (a)/(b)/(c)），外加 1 個「Figure 1.18」框 `[744, 310, 761, 389]`。
- B 正確：依序輸出 `![](figure) (a) ![](figure) (b) ![](figure) (c) Figure 1.18`。
- C 錯，共四處：
  1. `group_figures`：每個圖框都配到正下方最近的格子小標，而不是「Figure 1.18」。「Figure 1.18」的圖組因此是空的，被丟掉。
  2. 圖組依 `(y0, x0)` 排序：(b) 的 y0=364 比 (a) 的 365 小 1，順序變成 b、a、c，跟圖說與佔位的配對全部錯開。
  3. VLM 輸出的「(a)」「(b)」「(c)」三行沒被當成格子小標，留成正文段落，把「In the diagrams, … of course, I can only draw…」這句話切斷。
  4. 第 3 項的連帶影響：跨頁接段時，上一頁最後一段變成「(c)」（短、不像段落），下一頁的「of course, I can only draw…」就沒接回原段落。
- E：三張圖各自浮動，(a) 漂到第 33 頁底，(b)(c) 漂到第 34 頁頂。

## 修正方案

使用者尚未決定要做哪幾項，也還沒選定第 3 項的 (a)／(b)。動手前先確認。

1. **以 VLM 的位置為主要錨點**：`![](figure)` 佔位和 Markdown 表格的位置，直接當作圖的插入點（有表格裁圖時，用裁圖取代該表格，而不是刪掉表格再另找位置）。只有 VLM 完全沒提到這張圖時，才退回用高度比例推算，並列進報告的 `figure_mismatch`。
2. **多格圖整張裁**：「Figure N」圖說上方、同一區域內的所有格子與 (a)(b)(c) 小標，裁成同一張圖（取聯集），保留原書的並排排法。
   - 小標的判斷：圖說框的 Vision 文字符合 `SUBLABEL`（已有，`^\(?[a-z]\)?\.?$`）就不自成圖組，歸給下方或附近的「Figure N」圖說。
   - 同時刪掉 VLM 輸出裡對應的小標行（緊鄰 `![](figure)` 的單獨「(a)」「(b)」行），讓它們不再變成段落、也不再擋住跨頁接段。
   - 排序不要只看 `(y0, x0)`：同一列（垂直重疊超過一半）的框，依 x 排。
3. **獨立的並排圖**（各有自己的圖說）：
   - (a) 也整列裁成一張圖：最簡單、忠於原書，但圖說會變成圖片的一部分，無法翻譯。
   - (b) 新增「圖列」結構（**建議**）：book.json 加一種項目（例如 `{"type": "figrow", "items": [{"file": …}, …]}`，圖說仍是接在後面、可翻譯的段落），EPUB 用 flex 並排，PDF 用 Typst 的 `grid` 並排。這樣 D、E 都要改，`read_translated_epub` 也要能讀出來。
4. **PDF 浮動規則**：圖不能浮到同一頁的章名之上。最保險的做法是數學書的圖不浮動、排在原位（例如 `print:` 加一個設定，讓 `fig()` 改成非浮動），代價是頁尾偶爾會留白。另一種做法是只允許浮到頁底。

## 驗收

- B5 PDF 第 4 頁：「Four Realms」圖表排在「In the diagram below…」之後，在章名之下。
- 第 33～34 頁：Figure 1.18 是一張圖，(a)(b) 並排、(c) 在下；正文沒有孤立的 (a)(b)(c)；「In the diagrams, … of course, I can only draw…」是同一段。
- 原書 PDF 第 19 頁的 Figure 1.7、1.8 在 EPUB 和 PDF 裡都是左右並排（若採第 3 項 (b)）。
- 第 1 章其他圖沒有變差：這次預覽有 64 張圖，報告裡「VLM 漏寫的圖」原本是第 11、19、20、21、56、60、63、77 頁。
- `pdf` 的逐頁核對全部通過，所有測試通過；`tests/test_vlm.py` 把上面三個案例（第 11、19、33 頁的版面框與 VLM 輸出）做成合成測試。

## 其他已知但不在這次範圍的問題

- EPUB 獨立公式裡的分式在 Chromium 上偏小（像行內大小）；`\boldsymbol{\nabla}` 不會變粗（STIX Two Math 沒有粗體）。Apple Books 等閱讀器還沒實機確認。
- 粗體、斜體的強調在抽取時拿掉了（現有流程本來就不保留字體），原書加粗的定義名詞在參考版裡是一般字。
- 電源模式（`pmset -g` 的 powermode）會自己從 2（高效能）跳回 0（自動）。在自動模式下，長時間 GPU 滿載時效能會被壓到約三分之一（實測記憶體頻寬只有 205 GB/s），OCR 每頁從約 65 秒變成 240 秒以上。
