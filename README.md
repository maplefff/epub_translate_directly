# epub_translate_directly

直譯流程：原文由本機抽取，**譯文由 Claude 在對話中直接逐段寫成**（不呼叫任何模型端點），
再組裝成譯本 EPUB，並可依紙張自動排版成可列印的 PDF。

原書可以是：EPUB；有文字層的 PDF（自動去書眉頁碼、接回跨頁段落與斷字、註腳收到章尾、依書籤或字級切章）；
掃描 PDF（macOS 內建 Vision OCR，本機執行）；書店的 ACSM 領書憑證（`fetch` 領書並解密，限自己購買的書）。
原書已是中文時可以跳過翻譯，直接用 `pdf` 排版列印（見 skill〈原書已是中文：只排版列印〉）。

完整操作流程寫在 skill：[.claude/skills/epub_translate_directly/SKILL.md](.claude/skills/epub_translate_directly/SKILL.md)。

| 指令 | 做什麼 |
|---|---|
| `init` | 建立 `process/{書名}/`、`system_prompts.yaml`、`drafts/`（書本目錄命名成 `《中文書名 原文書名》`） |
| `fetch` | ACSM 領書並解密 → `process/{書名}/{原書名}.epub`（Adobe 授權放在 `adept/`） |
| `extract` | 原檔（EPUB／PDF；PDF 逐頁判斷文字層或 OCR，掃描頁用 macOS Vision）→ `work/book.json`，並套用 `drafts/source_fixes.yaml` 的原文校正 |
| `page` | PDF 原書的某一頁輸出成圖，對照抽出的文字 |
| `status` | 每章段數、字數、譯稿進度 |
| `dump` | 印出某章原文（序號＋原文） |
| `merge` | `drafts/` → `work/translations.json`，對位不符整章拒收 |
| `verify` | 漏譯檢查；① 未進快取會阻擋 build |
| `zh-lint` | 依 `epubtrans/settings/zh_tw_lint.yaml` 檢查台灣用語，只報告 |
| `build` | 產出 `《中文書名 原文書名》.epub` |
| `pdf` | 依 `--paper`（a4 / b5 / b4 …）自動排版，產出 `《…》（B5）.pdf`，並逐頁驗證 |
| `pdf --tone …` | 夜讀黃底版：`light`／`cream`／`wheat`／`honey`／`amber`，產出 `《…》（B5 Light night）.pdf` |
| `pdf --document` | 文件式：左右邊界等寬，產出 `《…》（B5 Document）.pdf`（預設書本式：內側比外側寬、左右頁鏡像） |
| `pdf-verify` | 重新逐頁驗證已產出的 PDF |
| `fonts` | 列出可用的中文字型 |

## PDF 紙張與自動版型

邊界、字級、標題字級由紙張尺寸算出（`epubtrans/settings/print_profile.yaml` 的 `layout:`）：每行不超過 38 字、
行距 1.7 倍字級。預設書本式（`style: book`）：內側比外側寬、左右頁鏡像，裝訂成冊或用釘書針都留得出內側；
加 `--document`（或書本 `print:` 設 `style: document`）改排文件式，左右等寬。兩者版心寬與字級相同，下表數字不受影響。《不停》的實測：

| 紙張 | 尺寸 | 正文 | 每行（實測） | 每頁 | 總頁數 |
|---|---|---|---|---|---|
| `a4` | 210×297 | 12.5pt | 37～38 字 | 33 行 | 178 |
| `b5`（JIS） | 182×257 | 11.5pt | 35～36 字 | 31 行 | 195 |
| `b4`（JIS） | 257×364 | 15pt | 37～39 字 | 34 行 | 170 |

`b5`、`b4` 是 JIS 規格，與台灣市售影印紙（如 Double A）一致；ISO 規格用 `iso-b5`（176×250）、
`iso-b4`（250×353）。列印時選「實際大小／100%」，用和版面相同尺寸的紙。

PDF 排版移植自 `~/Program/epub2print`（Typst）；以原版的 ISO-B5 手調數字重排，
186 頁逐頁文字與原版完全相同。

## 環境

```bash
brew install typst
/opt/homebrew/bin/python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python tests/test_naming.py
./.venv/bin/python tests/test_fetch_acsm.py
./.venv/bin/python tests/test_pipeline.py      # 合成小書走完 extract→build→pdf（需要 typst）
./.venv/bin/python tests/test_index.py         # 書末索引：解析、對位、EPUB 連結、PDF 頁碼（需要 typst）
./.venv/bin/python tests/fixtures/make_test_pdfs.py             # 用《不停 Non-Stop》產生測試書：小說版面（需先 extract 原書）
./.venv/bin/python tests/fixtures/make_test_pdfs.py --style b   # 第二種版面：段落不縮排、右邊參差、章不換頁、沒有書籤
./.venv/bin/python tests/test_import_pdf.py
```
