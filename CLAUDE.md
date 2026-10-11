# CLAUDE.md

直譯與列印專案：譯文由 Claude 直接逐段寫進 `drafts/`，本機負責抽取、合併、檢查、組裝 EPUB，
並用 Typst 依紙張排版成可列印 PDF。原書可以是 EPUB、PDF（文字層或掃描，掃描頁用 macOS Vision OCR）、
或書店的 ACSM（`fetch` 領書並解密）。**完整流程見 skill `epub_translate_directly`，動手前先讀。**

## 規約
- 一律用 `./.venv/bin/python -m epubtrans <指令> "書名"`；`"書名"` 是 `process/` 底下的目錄名。
  目錄名跟產出檔名一致，用 `《中文書名 原文書名》`（例：`《金融煉金術 The Alchemy of Finance》`）；開新書時譯名還沒定，可以先用原文書名，`title_zh` 定了再改名。
  改名前確認 `system_prompts.yaml` 的 `identifier` 不是空的（空的話會用目錄名代入，改名後閱讀器會當成另一本書）。
- 不呼叫任何模型端點，也不開子代理，除非使用者明確要求。（`vlm-ocr` 在本機程序裡載入 OCR 模型，不算端點；2026-10-07 起用於掃描數學書）
- `process/{書名}/drafts/` 是譯文唯一的真相來源；`work/` 與產出的 EPUB／PDF 都可重建，不要直接改。
- 每章翻完都要用 `review` 對照原文逐段重讀；改譯稿一律用 `revise`（自動記入 `drafts/review_log.jsonl`），不要用 sed。
- 改了 drafts：`merge` → `verify` → `build`；要 PDF 再 `pdf`。
- `zh-lint` 只報告；確認是誤用才回 drafts 改。
- 不要修改 `~/Program/epub_translate`、`~/Program/epub2print`、`~/Program/acsm`（舊專案，只讀；acsm 已在本專案重建成 `fetch`）。
- `process/` 底下 `_` 開頭的目錄不是書（例如 `_system_prompts_backup_2026-10-01/`：合併分支時的設定備份；`_latex_ocr_test/`：OCR 模型比較的產物）。
- 需要在瀏覽器目視檢查（解開的譯本 EPUB 看 MathML、公式與原頁對照的 HTML…）時，檔案一律建在 `process/{書名}/OCR_review/`，不要放到別處。
  `.claude/launch.json` 的 `ocr_review` 以 `process/` 為根開靜態伺服器，網址是 `http://localhost:8765/{書名}/OCR_review/…`。這個目錄是暫存，可整個刪掉，不要放唯一的資料。
- 原書已是中文、只要列印：原書 EPUB 放在 `《書名》.epub`，`source_file`、`output_file` 都指向它，直接 `pdf`；**不要跑 `build`**（會覆寫原書）。見 skill〈原書已是中文：只排版列印〉。
- `adept/` 是 Adobe 授權（ACSM 領書用的私鑰）：不可刪、不可外流、不讀出內容、不進版控。`acsm-register` 會在 Adobe 建帳號，只能由使用者自己執行。
- PDF／掃描書：`extract` 後先看抽取摘要與 `work/extract_report.json`，用 `page` 抽查原頁；**結構定案才開始翻**（之後改抽取設定會讓章節 id、段落切點位移，drafts 對不上）。
- 抽取不對改 `system_prompts.yaml` 的 `pdf:`；原文錯字（OCR 誤字、原書錯字）寫進 `drafts/source_fixes.yaml`。都不要直接改 `work/book.json`，下次 extract 會蓋掉。
- 掃描數學書：獨立公式不進譯稿，公式裡的英文說明（`\text{when}`、`\text{(Gauss's law)}`）寫進 `drafts/math_text.yaml` 中文化，build 時代換（EPUB 與 PDF 都套用）；沒有這個檔的書照原文。

## 指令
| 指令 | 用途 |
|---|---|
| `init` / `extract` | 建立書本目錄、抽取原文（依原檔格式分派：EPUB、PDF 文字層、掃描頁 OCR；最後套用 `drafts/source_fixes.yaml`） |
| `vlm-ocr [--pages 1-50] [--workers 3]` | 掃描數學書：PP-DocLayout-V3 切版面＋Qwen3.5-27B 整頁轉成 Markdown＋LaTeX，快取在 `work/vlm/`（本機 `.venv-vlm`，全書數小時、可續跑；`--workers` 開多個程序以鎖檔分頁，27B 每個約 28GB、最多 3 個）；之後 `pdf.mode: vlm` 的 `extract` 讀它 |
| `fetch [x.acsm] [--force]` | ACSM 領書並解密 → `process/{書名}/{原書名}.epub`，之後 `extract` 自動改讀它 |
| `acsm-register` | `adept/` 沒有授權時註冊匿名 Adobe ID（使用者自己跑） |
| `status` / `dump` | 查進度、印出某章原文 |
| `page 頁碼` | PDF 原書的某一頁輸出成圖（`work/pages/`），對照抽出的文字 |
| `terms [--upto c012] [--missing]` | 專名候選清單；翻譯前通讀全書時對照 notes 用 |
| `merge` / `verify` / `zh-lint` | 併入譯稿、漏譯檢查、台灣用語檢查 |
| `glossary [--term X] [--all]` | 依 `drafts/glossary.yaml` 檢查譯名一致與舊譯殘留 |
| `review [cid lo hi] [--done]` / `revise cid idx --old --new --why` | 譯後審閱：原文譯文並排、定點改譯稿並記錄、審閱進度 |
| `build` | 產出 `《中文書名 原文書名》.epub` |
| `pdf --paper a4 b5 b4` | 依紙張自動排版（預設書本式：內側留寬），產出 `《…》（B5）.pdf` 等，並自動逐頁驗證 |
| `pdf --tone light cream wheat honey amber` | 夜讀黃底版，產出 `《…》（B5 Light night）.pdf` 等 |
| `pdf --document` | 文件式：左右邊界等寬，產出 `《…》（B5 Document）.pdf`（預設書本式 `book`：內側比外側寬、左右頁鏡像，裝訂或釘書針都適用） |

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
└── process/《中文書名 原文書名》/   一本書一個目錄（`_` 開頭的不是書，是備份之類）；整個目錄不進版控
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
    │   ├── vlm/               vlm-ocr 的整頁 Markdown＋LaTeX 與版面框快取（pNNNN.json；跑一次要數小時，別刪）
    │   ├── translations.json  merge 由 drafts 合成的譯文（build 讀這個）
    │   ├── verify_report.json verify 的檢查報告
    │   ├── terms.tsv          terms 的專名候選清單
    │   ├── glossary_report.json   glossary 的檢查報告
    │   ├── index_report.tsv   extract 的索引對位報告（每個頁碼對到哪一段、怎麼對的）
    │   └── print/{紙張[-色調][-document]}/   pdf 的排版中間檔（content.json、config.json、book.typ）
    ├── OCR_review/            Claude 目視檢查用的暫存檔（解開的 EPUB、公式對照 HTML…），可整個刪掉
    ├── 《中文書名 原文書名》.epub          build 產出
    ├── 《中文書名 原文書名》（B5）.pdf     pdf 產出（書本式），每種紙張一份
    ├── 《中文書名 原文書名》（B5 Light night）.pdf   加 --tone 的夜讀黃底版
    └── 《中文書名 原文書名》（B5 Document）.pdf   加 --document 的文件式（左右等寬）
```
- 資料流：（原檔.acsm →`fetch`→）原檔.epub 或 原檔.pdf →`extract`（PDF：文字層／OCR）→ work/book.json ＋ drafts/ →`merge`→ work/translations.json →`build`→ 譯本 EPUB →`pdf`→ PDF。
- 只改 `drafts/` 與 `system_prompts.yaml`；`work/`、EPUB、PDF 都由指令重新產生，不要手改。
- 版控只追蹤程式、skill 與全域設定；整個 `process/`（含各書的 `system_prompts.yaml`、`drafts/`、`work/`、EPUB、PDF）都不進版控。

## 開發慣例
- 輸入端放 `source/`、檔名用 `import_*`（或 `fetch_*`）；輸出端放 `output/`、檔名用 `export_*`。同一種格式的輸入與輸出模組，光看檔名就要分得出方向。
- 新增一種原書格式：寫 `source/import_xxx`，產出同一份 `work/book.json`，再到 `source/__init__.py` 分派、`core/config.py` 的 `SOURCE_EXTS` 加副檔名。下游不必改。
- `book.json`：`{title, author, source_language, cover, chapters: [{id, level, title, items}]}`；item 是 `{type: heading|para|quote|li, text, level?}` 或 `{type: image, file}`；
  掃描數學書另有獨立公式 `{type: math, text: LaTeX, tag?}`（不進譯稿），行內式以 `$…$` 留在段落文字裡、譯文照抄；
  各有圖說的並排圖是圖列 `{type: figrow, cells: [{file, cap}]}`（cap＝這格有沒有圖說），圖說依序是接在後面的段落。PDF 抽出的 item 多帶 `page`／`page_end`（原書頁碼）與 `conf`（OCR 信心值），下游不讀。
- 書本專屬的差異寫進 `system_prompts.yaml`（`extract:`、`pdf:`、`book:`），不寫進程式碼。
- PDF 抽取的規則改了，四本測試書（兩種版面 × 文字層／掃描）都要重跑 `tests/test_import_pdf.py`；只對一種版面調規則很容易顧此失彼。

## 環境
`brew install typst`；`/opt/homebrew/bin/python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`。
掃描數學書另需：`/opt/homebrew/bin/python3.12 -m venv .venv-vlm && .venv-vlm/bin/pip install -r requirements-vlm.txt`（mlx-vlm，模型首次執行時從 Hugging Face 下載）、
`brew install node && npm install --prefix epubtrans/output/js`（temml，EPUB 的 MathML）。
掃描 PDF 的 OCR 用 macOS 內建的 Vision（pyobjc），只能在 macOS 上跑。
測試：`./.venv/bin/python tests/test_naming.py`、`tests/test_fetch_acsm.py`（離線）、
`tests/test_pipeline.py`（合成小書走完 extract→build→pdf，需要 typst）、`tests/test_vlm.py`（掃描數學書：VLM 快取 → book.json → MathML，不載模型）、`tests/test_index.py`（書末索引：解析、對位、EPUB 連結、PDF 頁碼）、
`tests/test_import_pdf.py`（先跑 `tests/fixtures/make_test_pdfs.py` 與 `--style b` 產生兩種版面的測試書，各含文字層版與掃描版）。
