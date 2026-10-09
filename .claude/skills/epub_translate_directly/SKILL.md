---
name: epub_translate_directly
description: 在 epub_translate_directly 專案裡，由 Claude 直接逐段翻譯一本書成繁體中文（台灣）並組裝成譯本 EPUB，再依紙張（A4／B5／B4）自動排版成可列印 PDF——不呼叫任何模型端點、不用 proxy。原書可以是 EPUB、有文字層的 PDF、掃描 PDF（macOS Vision OCR），或書店的 ACSM 領書憑證（本機領書並解密）。本機只做抽取、對位合併、漏譯檢查、台灣用語檢查、組裝與 Typst 排版。原書已是中文時也能跳過翻譯、直接排版列印。Use when the user wants to translate / re-translate a book in this project (EPUB, PDF, scanned PDF, or ACSM), continue an unfinished book, fix passages in an existing translation, rebuild the EPUB, or make a printable PDF — including printing an already-Chinese book without translating（「直接翻」「整本重翻」「繼續翻下一章」「翻這本 PDF」「掃描書」「OCR」「ACSM 領書」「改這段譯文」「重新 build」「出 PDF」「印成 B5」「中文書直接印」「不用翻，只要排版」）.
---

# 直譯流程（原書：EPUB／PDF／掃描 PDF／ACSM）

譯文由你在對話裡直接寫，寫進 `process/{書名}/drafts/`；程式只負責把原文拿出來、把譯稿對位併回去、檢查、組裝。
不管原書是什麼格式，`extract` 都抽成同一份 `work/book.json`，之後的流程完全相同。

## 不可違反

1. **不呼叫模型端點，也不開子代理**，除非使用者明確要求。整本書由你循序翻完。
2. **`drafts/` 是唯一的真相來源。** `work/translations.json` 由 `merge` 從 drafts 重建，EPUB 由 `build` 產出；不要直接改這兩個檔，下次 merge / build 會蓋掉。
3. **不碰舊專案**：`~/Program/epub_translate`（原本的端點管線）、`~/Program/epub2print`（排版的前身）、`~/Program/acsm`（領書工具，已在本專案重建成 `fetch`）。可以讀，不可以寫。
4. **一律用 `./.venv/bin/python -m epubtrans …`**，`"書名"` 就是 `process/` 底下的目錄名，命名成 `《中文書名 原文書名》`（跟產出檔名一致）。`process/` 底下 `_` 開頭的目錄不是書（例如 `_system_prompts_backup_2026-10-01/` 是合併分支時的設定備份）。
5. **zh-lint 只報告。** 命中逐一判斷，確認是陸／港用語才回 drafts 改那一句；誤報照舊。
6. **對話會被壓縮，一致性靠檔案。** 譯名寫進 `drafts/glossary.yaml`（程式據此檢查全書），語體、譯例、不可洩底的線索寫進 `drafts/translation_notes.md`。每章翻完就補。
7. **譯名改了，已翻的章節要跟著改。** 照〈改譯名〉做，`glossary` 的舊譯殘留歸零才算改完。
8. **抽取結構定案後才開始翻。** 翻譯開始後再改抽取設定，章節 id 或段落切點一變，drafts 就會整章對不上；原文校正（`source_fixes.yaml`）也只能改段中字詞，不能動段落開頭。PDF 與掃描書尤其要先驗過結構。
9. **`adept/` 是 Adobe 授權（ACSM 解密用的私鑰）：不可刪、不可外流、不讀出內容。** `acsm-register` 會在 Adobe 建帳號，只能請使用者自己跑。

## 流程

### 開新書
```bash
mkdir -p "process/書名" && cp 原檔.epub "process/書名/"   # 原檔也可以是 .pdf；ACSM 見下
./.venv/bin/python -m epubtrans init    "書名"   # 產生 system_prompts.yaml 與 drafts/（原檔未放入時 source_file 留空＝自動偵測）
./.venv/bin/python -m epubtrans extract "書名"   # → work/book.json
./.venv/bin/python -m epubtrans status  "書名"   # 每章段數、字數
```
- 剛建時譯名還沒定，目錄先用原文書名。`title_zh` 定了以後改名成 `《中文書名 原文書名》`；`init` 已把 `identifier` 寫死，改名不影響閱讀器認書（舊書若 `identifier` 是空的，先填上再改）：
  ```bash
  mv "process/The Alchemy of Finance" "process/《金融煉金術 The Alchemy of Finance》"
  ```

#### 原書是 ACSM
書店（Kobo、Readmoo、Google Play…）給的 `URLLink.acsm` 只是領書憑證。`init` 之後先領書再 `extract`：
```bash
./.venv/bin/python -m epubtrans fetch "書名" ~/Downloads/URLLink.acsm   # 複製進書本目錄 → 領書 → 解密 → process/書名/{原書名}.epub
```
- ACSM 只有幾個小時效期（`fetch` 會印出期限）。過期就請使用者回書店重新下載一張，不要重試。
- 一張 ACSM 只能被一組 Adobe ID 領取。授權在專案根目錄的 `adept/`：不可刪、不可外流。`adept/` 是空的就請使用者自己跑 `acsm-register`（會在 Adobe 建帳號，不能代跑）。
- 去 DRM 只限使用者自己買的書、自己閱讀。

#### 原書是 PDF
`extract` 逐頁判斷：有文字層的頁直接讀，掃描頁走 OCR。抽完先驗結構再動筆：
```bash
./.venv/bin/python -m epubtrans extract "書名"      # 印出切章依據、刪掉的書眉頁碼、略過的目錄頁、註腳數
./.venv/bin/python -m epubtrans page    "書名" 37   # 原書第 37 頁輸出成圖，和 dump 的段落對照
```
- 抽查幾頁（章首、跨頁處、有註腳的頁）：段落切點、跨頁段落有沒有接回、行尾斷字有沒有接對、書眉頁碼有沒有混進正文。完整報告在 `work/extract_report.json`。
- 切章依據優先序：`pdf.chapters`（手動）> PDF 書籤 > 版面。沒有書籤時，文字層依字級切章：報告會印「標題字級」表（哪個字級出現幾次、當第幾層、哪些是接在標題後的副標），不對就設 `pdf.heading_sizes`（例：`{22: 1, 15: 2}`，0＝不切）。
- 不對就調 `system_prompts.yaml` 的 `pdf:`（`init` 偵測到 PDF 會附上說明）：`skip_pages`、`chapters`、`heading_sizes`、`chapter_levels`、`columns`、`footnotes`、`mode`（掃描書另見下節的圖表與雜訊設定），再重跑 extract。手動切章（`pdf.chapters`）時章名一律用設定的，章首頁只是重複章名的幾行會拿掉。
- 已知限制：右邊參差、段落間空一行的版面，跨頁時若句尾剛好落在頁底，分不出段落有沒有結束，會切成兩段（翻譯照翻即可，只是譯本多一個段落分隔）。
- **結構定案後才開始翻。** 之後再改抽取設定，章節 id 或段落切點一變，drafts 就會整章對不上。
- 註腳收到各章結尾的「Notes」小節，正文裡的標號轉成上標數字（¹²³）；翻譯時標號照留。
- 每段帶 `page`（原書頁碼），`dump` 看不出上下文時用 `page` 對照原頁。

#### 掃描書（OCR）
掃描書（或文字層品質太差、設 `pdf.mode: ocr` 的書）走 macOS 內建的 Vision OCR，本機執行、不呼叫模型端點；結果快取在 `work/ocr/`，改其他設定重抽不必重跑。OCR 版要多看報告裡的三項：
- **推定章名**：OCR 讀不好單獨的章號（I 讀成 1、II 漏掉、PART II 讀成 PART I）。看得出是章首（正文從頁面中段開始、部名後第一段）但讀不到章號，或編號不連續時，依前後章推定（前一章 IV → V、部名後第一章 → I）。逐一用 `page` 確認，錯了就用 `pdf.chapters` 指定。
- **低信心段落**（`extract_report.json` 的 `low_confidence`）：用 `page` 看原頁，錯字寫進 `drafts/source_fixes.yaml`。
- **掃描頁插圖**：沒被文字框蓋住的大片墨水當插圖，連同貼著它的圖名、刻度、圖例裁成圖片放回原位；圖裡被讀到的字會丟掉。用 `page` 抽看，切不好時：
  - `pdf.plate_pages`：整頁是圖表的圖版頁，「Note(s):」以上整片當一張圖，注記留作文字。
  - `pdf.framed_figures: true`：有框線的表格整塊當圖（框起來的引文不算：框裡幾乎都是長行）。
  - `pdf.figure_boxes`：自動找不到的（淺灰色印的圖、OCR 讀不成文字的二維公式圖），手動指定範圍（PDF 點）。
- **重複掃描的頁**：檢查印在頁上的頁碼是否連續，重複的頁寫進 `skip_pages`。
- **漏讀與雜訊**：Vision 偶爾整行漏讀，`extract` 會對有墨水卻沒字框的橫帶換解析度補讀；同一行被讀兩次（一次是亂碼）會自動去重；剩下的透印、污漬亂碼行用 `pdf.drop_lines` 拿掉。
- **註腳誤判**：頁底的編號清單、圖片出處被當成註腳時，用 `pdf.footnote_marks`（例 `"*†"`）限定註腳標記。

`drafts/source_fixes.yaml` 是原文校正檔（OCR 誤字、原書錯字、讀壞的公式），每次 extract 都會套用；格式是 `- {page: 14, old: "another?", new: "another.’"}`，`page` 省略＝全書套用。`new` 是空字串的段落會被拿掉：OCR 把一段拆成兩段時，把後半併進前一段、後一段改成空的（只能在開始翻譯前做）。**翻譯前就校好**：改到段落開頭，已寫的譯稿會對位不上。
OCR 的固定毛病：彎引號變直引號、破折號變「 - 」（翻譯時照常換成中文標點，不必校）；句號加右引號（.’）常被讀成「?」，看語意判斷，影響理解才校。

#### 掃描數學書（公式多：教科書、論文集）
Vision OCR 讀不了公式（獨立公式整條消失、∇ 讀成 V）。改走整頁 VLM：PP-DocLayout-V3 切版面、Qwen3.5-27B 把整頁轉成 Markdown＋LaTeX。
```bash
./.venv/bin/python -m epubtrans vlm-ocr "書名" --pages 31,61   # 先抽幾頁看品質（每頁約 1 分鐘）
./.venv/bin/python -m epubtrans vlm-ocr "書名" --workers 3     # 全書：數小時，背景跑，中斷重跑會接著做
```
- `system_prompts.yaml` 設 `pdf.mode: vlm`、`cover_page`、`skip_pages`（目錄、書末索引）；`extract` 只讀 `work/vlm/` 的快取。快取還沒齊時 `extract` 會略過缺的頁並警告。
- 圖放在 VLM 寫的位置（同號圖說之前、`![](figure)` 佔位、Markdown 表格由裁圖取代）；多格圖連同 (a)(b) 小標裁成一張。
  各有圖說、左右並排的圖合成圖列（`figrow`）：EPUB 用 flex、PDF 用 grid 並排，圖說仍是各自的段落，照常翻譯。
- 抽取報告看三項：`figure_mismatch`（VLM 沒寫到的圖，位置依高度推定，用 `page` 確認）、`loop_stopped`（VLM 卡在目錄點線之類的重複，提前結束、內容可能不全）、`untagged_math`。
- 獨立公式是 `math` 項目（不進譯稿，`dump` 不列）；行內式 `$…$` 留在段落裡，**譯文照抄 `$…$`，一字不改**。公式讀錯用 `drafts/source_fixes.yaml` 改 LaTeX。
- VLM 偶爾把多行推導寫成沒包 `$$` 的 `\begin{align*}…\end{align*}`：`extract` 自動包成獨立公式（align→aligned、gather→gathered，`\tag` 取出當式號），不必手動校。
- **公式裡的英文說明**（`\text{when}`、`\text{(Gauss's law)}`）不在譯稿裡，寫進 `drafts/math_text.yaml`，build 時代換（EPUB 的 MathML 與 PDF 都套用）：
  ```yaml
  text:    # 一般位置的 \text／\textrm／\textbf／\textit／\mbox{…}
    "when": "當"
    "(Gauss's law),": "（高斯定律），"
  sub:     # 前面是 _ 或 ^ 的（上下標裡的片語）
    "all space": "全空間"
  whole:   # 語序和中文不同，整條公式改寫：原文 TeX → 譯好的 TeX
    '\mathbf{w}(t) \equiv \text{position of } q \text{ at time } t.': '\mathbf{w}(t) \equiv q \text{ 在時刻 } t \text{ 的位置。}'
  ```
  key 是大括號內去掉前後空白後的原文，必須完全相同；前後空白照原文保留（決定和符號的間距）。沒列的照原文——符號名稱的下標（`E_{\text{above}}`、`Q_{\text{enc}}`）、單位、Re、SI、編號 (ii) 都不要列。全書譯完後，把含 `\text` 的獨立公式逐條看上下文再訂。
- 環境：`.venv-vlm`（requirements-vlm.txt）、`npm install --prefix epubtrans/output/js`（temml）。EPUB 的公式是 MathML，嵌入 STIX Two Math。
- PDF：公式由 Typst 的 mitex 排（`@preview/mitex:0.2.7`，第一次會下載）；每條先單獨試排，排不出來的印成紅色原始碼並列出（改 `source_fixes.yaml`）。含公式的頁不量行距。
  比版心寬的獨立公式自動處理：縮到 90%（`math.typ` 的 `eq-min-scale`）以內放得下就微縮、式號留同一行；否則公式獨占一行、式號移到下一行靠右。方程組、`\left. … \right\}` 的括號對準數學軸，上下對稱。
  裁出來的圖記有原書解析度，`print.image_natural: true` 讓它照原書尺寸印、不放大；
  `print.image_float: false` 讓圖排在原位、不浮動（浮到頁頂會壓在章名之上、離開緊接的推導；代價是放不下時頁尾留白）。
- **公式要對照原頁抽查**：temml 全數轉換成功只代表語法對，不代表讀對。每 20 頁抽 1 頁，用 `page` 對照獨立公式與行內式；讀錯的依頁寫進 `source_fixes.yaml`。
- 這本書的經驗（Griffiths《Introduction to Electrodynamics》第三版）：
  - 專用 OCR 小模型都把草寫 𝓇 讀成 z、丟掉粗體向量，只有 Qwen3.5-27B 都對。比較見 `experiments/latex_ocr/REPORT.md`。
  - Qwen 的固定錯誤：草寫積分範圍 𝒱、𝒮 常讀成一般 V、S（同一條公式裡也會混用；42 條獨立公式），校成 `\mathcal{V}`、`\mathcal{S}`；雙箭頭張量 T⃡ 讀成 `\hat{T}`，校成 `\overleftrightarrow{\mathbf{T}}`。
  - 原書加框的重要式常漏掉 `\boxed`（1,132 條有式號的只留 18 個框），只影響強調，未處理。
  - 習題前的「!」「•」是原書頁邊記號，抽取後會貼在題號前面。

#### 接著（各種格式共通）
- 依抽取結果調 `system_prompts.yaml`，改完重跑 extract：
  - EPUB：`extract.heading_levels`（某 class 的標題當第幾層）、`extract.chapter_levels`（按章節 id 覆寫層級，同 class 卻不同層時用，例如第一章在第一部之前）、`skip_files`（會讓後面的章節 id 位移，要在寫譯稿前定案）、`join_next`（spine 檔名含這些字串、只有圖的頁併進下一章開頭，例如各部前的跨頁照片）、`title_items`（章名寫在正文開頭幾段 `<p>`、`<title>` 全書同名時，按章節 id 指定前幾段併成章名，例 `{c008: 2}`）。
  - PDF：`pdf:`（見上）。
  - 同名章節標題：`book.title_overrides`。
- 原書的封面頁（整章只有封面圖）不必跳過：build 會直接拿它當譯本封面、排在目錄前，PDF 端則略過不印。
- `book.translator` 填你自己的模型名稱（例：`Claude Opus 5.5`），不要寫「AI 輔助翻譯」這類泛稱。範本的 `colophon`（譯本版權頁，EPUB 與 PDF 都有）寫「由 {translator} 翻譯，僅供個人閱讀研究使用」，build 時代入；沒填就停下來，不會把佔位字印出去。譯者模型與聲明**只放版權頁**，PDF 書名頁不寫（不設 `print.imprint`）。
- 建 `process/書名/drafts/translation_notes.md`：寫這本書的語體、不可提前揭曉的東西、譯例。通用規範見 [references/general_rules.md](references/general_rules.md)，書本規範優先。
- 建 `process/書名/drafts/glossary.yaml`：固定譯名表。格式跑一次 `glossary "書名"` 就會印出範例；每條是 `en`（原文，可列變體）、`zh`（譯名）、`old`（舊譯或禁用譯法）、`note`（選填）。

### 通讀全書，定譯名（動筆前）
翻譯前先把**整本書**讀過一遍，不是只讀前幾章。晚出場的專名、要到後段才揭曉真義的詞（反轉、身分、世界觀），只有讀完才能選出「前段不洩底、揭曉後也說得通」的譯名。
1. `python -m epubtrans terms "書名"` 產生專名候選清單（句中大寫的詞與詞組，附出現次數、小寫次數、首見章節），作為不漏項的底稿。
2. 依章 `dump` 讀下去。**邊讀邊寫**：每讀幾章就把定下的譯名補進 `glossary.yaml`，把不可提前揭曉的線索、語體觀察補進 `translation_notes.md`，不要等全書讀完才一次寫——對話中途被壓縮，沒寫進檔案的就沒了。明令禁用的譯法（例如會洩底的譯名）直接寫進該條的 `old`，之後翻譯時誤用就會被抓出來。
3. 讀到某章後跑 `python -m epubtrans terms "書名" --upto c012 --missing`，列出到這章為止出現過、glossary 和 notes 都還沒收的候選，逐一決定：收進 glossary，或判定為一般用詞略過。前付的書目、作者作品列表可以不收。
4. 全書讀完，`terms "書名" --missing` 剩下的應該都是有意略過的。回頭依結局修訂前面定的譯名，再開始翻。
5. 通讀和翻譯**分開兩個 session**：通讀的原文會一直佔著上下文。通讀的產出是 glossary 與 notes，翻譯另開 session，從讀這兩份開始。

### 逐章翻譯（主迴圈）
1. 先讀 `translation_notes.md` 與 `glossary.yaml`。對話壓縮過之後一定要重讀。
2. 印出原文：`python -m epubtrans dump "書名" c008`。超過約 70 段的章節分兩次印（`dump "書名" c008 0 65`、`dump … 65 200`）。
3. 寫譯稿 `process/書名/drafts/c008.json`。格式見下。長章分檔寫：`c008.json`、`c008.2.json`……
4. 對位檢查：`python -m epubtrans merge "書名" c008 --dry-run`。拒收就照錯誤訊息修，重新檢查。
5. 新專名補進 `glossary.yaml`，新譯例補進 `translation_notes.md`。
6. `python -m epubtrans glossary "書名"`：這章若用錯譯名、殘留舊譯，現在就改。
7. 每幾章跑一次 `python -m epubtrans merge "書名"`，寫入快取。

### 改譯名（已翻的章節要跟著改）
翻到一半發現某個譯名要換（讀到後文才知道真義、和另一個譯名撞了、使用者要求），已翻的章節**必須一起改**，不能只改之後的：
1. 在 `glossary.yaml` 把該條的舊譯名移進 `old`，`zh` 換成新譯名。
2. `python -m epubtrans glossary "書名" --term 舊譯名`：
   - 「舊譯殘留」逐段列出原文含這個專名、譯文還是舊譯的位置——全部要改。
   - 「舊譯名也出現在原文沒有這個專名的段落」——多半是一般用詞，但譯者用專名代替代名詞時也會落在這裡，逐段看過。
3. 逐處用 `revise` 改（每段語境不同，不要一次全域取代），改動會記進 `review_log.jsonl`。
4. 重跑 `glossary --term`，舊譯殘留歸零；`merge` 後照常出書。
5. 若這個譯名牽涉譯例（例如對白裡的稱呼方式），同步改 `translation_notes.md`。

### 譯稿格式
```json
[
["Like a radar", "就像雷達回波從遠方物體彈回……"],
["Well go on", "「好啊，要走就走啊！……」"],
["Greybeard (1964)", null]
]
```
- 依序對應該章**每一個**文字項目（para／heading／quote／li；image 不算），筆數必須和 `dump` 列出的一樣多。
- 第一欄放原文開頭 2–5 個字，只用來校驗對位。比對時只看英數字元，引號、破折號、大小寫打錯都沒關係。
- 譯文寫 `null` 表示照抄原文，用在書目、ISBN、網址。
- 注號（原文抽取後是句尾的「 1」「 2」）寫成 Unicode 上標數字，放在原文同一位置、後面不留空格：「……計畫。¹接下來」。build 會轉成 `<sup>`，PDF 由 Typst 排成上標；不要直接留一般數字或自己加括號。
- 章節標題寫在 `drafts/titles.json`：`[["PART I", "第一部"], ["I", "一"], …]`，第一欄要放完整原文標題。
- 用 `cat > file <<'EOF'` 寫檔（引號 heredoc，才不會展開 `$`）。譯文裡**不要出現 ASCII 雙引號** `"`，中文引號用「」『』，JSON 才不會壞。
- 常漏：只有一段的部名扉頁（例如 `QUARTERS`、`DEADWAYS`）。`status` 會標出 `·`（沒有譯稿）和 `…`（筆數不符）。

### 翻譯 PDF 來源的書
- 註腳在各章結尾的「Notes」小節（標題譯作「註釋」），每則開頭是上標標號（¹²³）；正文裡的上標標號照留在對應的字詞或句子後面，數字不改。
- 掃描書的原文是 OCR 結果：直引號、「 - 」照常換成中文標點；明顯的誤字（`another?` 其實是 `another.’`、`stgateway` 其實是 `sfgateway`）照作者本意翻，不必每處都校。會影響專名比對（`glossary`、`terms`）的誤字才寫進 `drafts/source_fixes.yaml`；開始翻之後只改段中字詞，不要改段落開頭（對位用）。
- 分段有誤（兩段黏在一起、一段被切成兩段）時，譯稿仍照 `dump` 的段落一段對一段寫，不能在譯稿裡合併或拆開；要修就回頭調抽取設定，在開始翻之前。
- `dump` 看不出上下文、懷疑抽錯時，查 `work/book.json` 該段的 `page`，用 `page "書名" 頁碼` 看原頁。

### 書末索引
原書有頁碼標記（`<a class="page" id="p33"/>`、`epub:type="pagebreak"`）、索引的頁碼又是連到標記的連結時，
索引**不要跳過，也不要照抄頁碼**——譯本的頁碼和原書無關。`extract` 會把每個頁碼對到「原書那一頁講到這個詞的段落」
（注釋頁碼過時也會依資料推出頁差），輸出一行統計，逐條結果寫在 `work/index_report.tsv`；「頁」「注?」「注近」幾類要抽看。
- 索引放在全書譯完之後翻：條目譯名要和 `glossary.yaml`、正文一致。
- `dump` 對索引條目印出樣板：`12  IX bank crises；bank runs in；current-account deficits in｜See also the Depression; Great Recession`。
  譯稿照樣板寫譯名，**不寫頁碼**：`["bank crises", "銀行危機；銀行擠兌；經常帳赤字｜另見 the Depression（大蕭條）；Great Recession（大衰退）"]`。
  「；」的欄數與樣板一致，有參見才寫「｜」；參見的對象保留英文（讀者要按英文字母去找），譯名放括號。欄數不符 `build` 會拒絕。
- 產出：條目維持原書英文字母順序，英文在前、譯名在後。EPUB 的頁碼換成連到段落的章名（同章多處寫成「第八章①②」，注釋寫「第二章注7」）；
  PDF 由 Typst 算出譯本頁碼（「205注7」），重疊的範圍自動合併。

### 譯後審閱（build 前）
機械檢查抓不到語意錯誤（多一個「先」就讓句意反轉、慣用語直譯、代名詞性別、雙關），每章翻完都要**對照原文逐段重讀**一次：
```bash
./.venv/bin/python -m epubtrans review "書名" c008 0 60      # 原文與譯文逐段並排
./.venv/bin/python -m epubtrans revise "書名" c008 46 --old "你" --new "妳" --why "對女性說話"
./.venv/bin/python -m epubtrans review "書名" c008 --done    # 標記本章已審
./.venv/bin/python -m epubtrans review "書名"                # 各章審閱進度與修改數
```
- 審閱時重點看：語意偏移或反轉、慣用語直譯、雙關、第二人稱與動物的代名詞（妳／牠）、和世界觀矛盾的字眼、原文錯字。
- 改譯稿一律用 `revise`：舊字串在該段必須恰好出現一次才會替換，並把原句、新句、理由記進 `drafts/review_log.jsonl`。不要用 sed 改。
- 改到跨章的譯名，照〈改譯名〉做；改到譯例，同步更新 `translation_notes.md`。

### 驗收與出書
```bash
./.venv/bin/python -m epubtrans merge   "書名"
./.venv/bin/python -m epubtrans status  "書名"   # 未完成章節 0、章節標題未譯 0
./.venv/bin/python -m epubtrans verify  "書名"   # ① 必須是 0；②③ 逐條看是否屬於合理保留
./.venv/bin/python -m epubtrans zh-lint "書名"   # 逐條判斷
./.venv/bin/python -m epubtrans glossary "書名"  # 舊譯殘留逐條判斷；缺譯名多半是代名詞帶過
./.venv/bin/python -m epubtrans build   "書名"   # → process/書名/《中文書名 原文書名》.epub
```
`build` 之後再抽查一次：把 EPUB 解到 scratchpad，統計中文字數、拉丁字母數，以及主要專名的出現次數。拉丁字母應該只出現在規範允許保留原文的地方。有舊譯本的話，兩版一起比。

### 出 PDF
先 `build` 出譯本 EPUB，再依紙張排版：
```bash
./.venv/bin/python -m epubtrans pdf "書名" --paper b5          # 可一次多種：--paper a4 b5 b4
```
- 紙張：`a4`、`b5`（JIS 182×257）、`b4`（JIS 257×364）；ISO 規格用 `iso-b5`、`iso-b4`。
- 版型（邊界、字級）依紙張自動算出；每次產出會自動逐頁驗證，出現 ✗ 就當作失敗。
- 輸出：`process/書名/《中文書名 原文書名》（B5）.pdf`。
- 夜讀黃底版：加 `--tone`，可選 `light`、`cream`、`wheat`、`honey`、`amber`（由淺到深，可一次多個），輸出 `《…》（B5 Light night）.pdf` 這類檔名。色調定義在 `epubtrans/settings/print_profile.yaml` 的 `tones:`。
- 邊界預設左右等寬（印成散頁閱讀）。要裝訂成冊加 `--binding`：內側比外側寬、左右頁鏡像，另存成 `《…》（B5 裝訂）.pdf`，不蓋掉散頁版；版心寬與字級兩者相同。某本書固定要裝訂版，在 `print:` 設 `binding: true`。
- 書名頁的書名／副標／作者寫在 `system_prompts.yaml` 的 `print:`（`title`、`subtitle`、`author`）。譯者模型與「僅供個人閱讀研究使用」只放版權頁（`book.colophon`），書名頁不寫，不設 `print.imprint`。
- `print.part_ids`：明確指定哪些章是部扉頁（半書名頁這類「只有章名」的第一層章節會被自動判斷誤認）。`print.chapter_ids`：第一層、卻要照正文章排版的章（大字章名、章首留白），目錄裡仍與各部同層。
- 圖：緊跟在圖後、原文以「Figure 2.1:」開頭的段落就是圖說，build 會把兩者放進同一個 `<figure>`（譯稿照常逐段寫，圖說譯成「圖 2.1：……」）。
  PDF 把圖與圖說綁在一起浮動到頁頂或頁底，正文照常排滿（`print.image_float: false` 改成排在原位）；圖寬占版心 `image_width`%，高度不超過 `image_max_height`%（直式窄圖依高度縮）。
  出書後用 `pdfimages -list` 看每張圖的頁碼與 ppi，抽看圖說是否和圖同頁。
- 封面圖預設不印（`use_cover: false`）：EPUB 封面多是螢幕解析度，滿版印出來會糊。原圖夠大才在 `print:` 設 `use_cover: true`。
- 列印時選「實際大小／100%」，用和版面同尺寸的紙。

### 原書已是中文：只排版列印
台灣書店買的中文電子書（例如 `process/《與焦慮和解》/`）不必翻譯，直接拿原書 EPUB 排版：
```bash
mkdir -p "process/書名" && ./.venv/bin/python -m epubtrans init "書名"
./.venv/bin/python -m epubtrans fetch "書名" ~/Downloads/xxx.acsm       # ACSM 才需要；有現成中文 EPUB 就直接放進書本目錄
mv "process/書名/{領回來的長書名}.epub" "process/書名/《書名》.epub"     # 放到譯本 EPUB 的位置
./.venv/bin/python -m epubtrans pdf "書名" --paper b5
```
- `system_prompts.yaml`：`title`、`title_zh` 都填中文書名，`author` 照中文版寫；`source_file` 與 `output_file` 都寫 `《書名》.epub`；`translator` 留空，並刪掉 `colophon` 裡含 `{translator}` 的那行。`pdf` 讀的是 `output_file`，所以會直接排原書。
- 不跑 extract、翻譯、merge。**不要跑 `build`**：`output_file` 就是原書，build 會用重組過的內容覆寫它（原書是買來解密的，ACSM 過期就領不回來）。
- 版面問題照〈出 PDF〉調 `print:`；不要為了排版去改原書 EPUB 檔。

### 修改既有譯文
用 `revise` 改那一句（見〈譯後審閱〉）→ `merge "書名" {cid}` → `verify` → `build`。要改的是同一個術語的系統性譯法時，照〈改譯名〉做，**逐處確認語境**再改。不要在譯文端做無範圍的全域取代，同一個中文詞常常同時是一般用詞。

## 目錄結構
```
epub_translate_directly/
├── epubtrans/                程式本體（./.venv/bin/python -m epubtrans <指令> "書名"）
│   ├── __main__.py / cli.py  指令入口與參數分派
│   ├── core/                 共用基礎：config.py（BookConfig、路徑、產出檔名）、store.py（book.json／translations.json 存取）
│   ├── source/               輸入端：原書 → work/book.json（extract 依原檔格式分派）
│   │   ├── import_epub.py    EPUB → book.json
│   │   ├── import_pdf/       PDF → book.json：textlayer.py（讀文字層）、ocr.py（掃描頁）、
│   │   │                     structure.py（書眉頁碼、註腳、段落、斷字、切章）、
│   │   │                     vlm_worker.py（掃描數學書的整頁 VLM OCR，在 .venv-vlm 跑）、vlm.py（讀它的快取 → book.json；
│   │   │                     VLM 沒包 $$ 的 align／equation／gather／multline 自動包成獨立公式，align→aligned）
│   │   ├── fetch_acsm/       ACSM 領書並解密成 EPUB（fetch；移植自 GPLv3 的 acsm-calibre-plugin 與 DeDRM_tools）
│   │   ├── book_index.py     書末索引：原書頁碼對回段落（EPUB 抽取時解析；build 產生連結、pdf 算譯本頁碼）
│   │   └── terms.py          專名候選清單
│   ├── translate/            drafts.py：dump／status／merge（drafts ↔ translations.json）
│   ├── qa/                   譯文檢查：verify.py（漏譯）、zh_lint.py（台灣用語）、glossary.py（譯名一致）、review.py（譯後審閱）
│   ├── output/               輸出端
│   │   ├── export_epub.py    book.json ＋ translations.json → 譯本 EPUB（build）
│   │   ├── math.py、js/      LaTeX 公式 → MathML（temml，Node）；EPUB 嵌入 STIX Two Math；
│   │   │                     localize() 依 drafts/math_text.yaml 把 \text{…} 中文化（譯過的 TeX 寫進 annotation，PDF 由此取回）
│   │   └── export_pdf/       譯本 EPUB → 可列印 PDF（pdf）
│   │       ├── pipeline.py   串起流程、呼叫 Typst
│   │       ├── content/      read_translated_epub.py（讀譯本 EPUB）、prepare.py（整理成排版用書稿）
│   │       ├── layout.py     依紙張算版型
│   │       ├── typst/book.typ   Typst 排版模板；typst/math.typ：公式（mitex 排 LaTeX、行內式、獨立公式＋編號；
│   │       │                    aligned／array 對準數學軸；超出版心的公式先縮到 eq-min-scale=90%，再不夠就式號換到下一行）
│   │       ├── mathcheck.py  公式逐條試排（mitex 一條出錯整本編不出來；排不出的照原樣印）
│   │       └── pagecheck.py  逐頁驗證
│   └── settings/             全域設定（可手動調整）
│       ├── zh_tw_lint.yaml   台灣用語檢查規則
│       ├── print_profile.yaml   PDF 排版預設、自動版型參數、夜讀色調
│       ├── vlm_ocr_prompt.txt   vlm-ocr 給 VLM 的轉寫提示詞（改了會讓快取全部重做）
│       ├── system_prompts.template.yaml   init 產生書本設定用的範本
│       └── system_prompts.template.pdf.yaml   原檔是 PDF 時 init 附上的 pdf: 設定說明
├── tests/                    test_naming.py、test_fetch_acsm.py（離線）、test_import_pdf.py、test_vlm.py、test_layout.py；
│                             fixtures/：make_test_pdfs.py 與兩種英文版面的 Typst 模板（產生 PDF 測試書）
├── experiments/              latex_ocr/（OCR 模型比較與報告）、layout_compare/（版面模型比較）
├── adept/                    Adobe 授權檔（device.xml、activation.xml、devicesalt），ACSM 領書用；不進版控
└── process/{書名}/           一本書一個目錄（`_` 開頭的不是書，是備份之類）；整個目錄不進版控
    ├── 原檔.epub／.pdf        原書（輸入）
    ├── 原書名.acsm            原書是 ACSM 時的領書憑證；fetch 把它領成 {原書名}.epub
    ├── system_prompts.yaml    該書設定：抽取規則、章名覆寫、EPUB metadata；print: 放 PDF 書名頁資訊
    ├── drafts/                人寫的，不可重建
    │   ├── c008.json …        逐章譯稿（長章可分 c008.2.json…）
    │   ├── titles.json        章節標題譯文
    │   ├── review_log.jsonl   review／revise 的審閱紀錄
    │   ├── source_fixes.yaml  原文校正（OCR 誤字、原書錯字），extract 時套用
    │   ├── math_text.yaml     掃描數學書：公式裡英文說明的譯名（text:／sub:／whole:），build 時套用
    │   ├── glossary.yaml      固定譯名表（glossary 據此檢查全書；翻譯前必讀）
    │   └── translation_notes.md   該書語體、譯例、不可洩底的線索、進度（翻譯前必讀）
    ├── work/                  程式產生的，可整個刪掉重建
    │   ├── book.json          extract 抽出的原文結構
    │   ├── images/            原書圖片
    │   ├── extract_report.json   PDF 抽取報告（切章依據、刪掉的書眉頁碼、略過的頁、註腳）
    │   ├── pages/             page 輸出的原書頁面圖
    │   ├── ocr/               掃描頁的 OCR 結果快取（pNNNN.json）
    │   ├── translations.json  merge 由 drafts 合成的譯文（build 讀這個）
    │   ├── verify_report.json verify 的檢查報告
    │   ├── terms.tsv          terms 的專名候選清單
    │   ├── glossary_report.json   glossary 的檢查報告
    │   ├── index_report.tsv   extract 的索引對位報告（每個頁碼對到哪一段、怎麼對的）
    │   └── print/{紙張[-色調][-binding]}/   pdf 的排版中間檔（content.json、config.json、book.typ）
    ├── 《中文書名 原文書名》.epub          build 產出
    ├── 《中文書名 原文書名》（B5）.pdf     pdf 產出，每種紙張一份
    ├── 《中文書名 原文書名》（B5 Light night）.pdf   加 --tone 的夜讀黃底版
    └── 《中文書名 原文書名》（B5 裝訂）.pdf     加 --binding 的裝訂版（內側留寬）
```
- 資料流：（原檔.acsm →`fetch`→）原檔.epub 或 原檔.pdf →`extract`（PDF：文字層／OCR）→ work/book.json ＋ drafts/ →`merge`→ work/translations.json →`build`→ 譯本 EPUB →`pdf`→ PDF。
- 只改 `drafts/` 與 `system_prompts.yaml`；`work/`、EPUB、PDF 都由指令重新產生，不要手改。
- 版控只追蹤程式、skill 與全域設定；整個 `process/`（含各書的 `system_prompts.yaml`、`drafts/`、`work/`、EPUB、PDF）都不進版控。
