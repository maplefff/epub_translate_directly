# 普通書籍的掃描頁：版面模型找圖的比對實驗

2026-10-08 開始。分支 `latex_OCR_test`。問題：普通書籍（非數學書）的掃描頁，先用 PP-DocLayout-V3 切版面、
文字仍由 Vision OCR 讀，能不能取代現行的墨水區塊推算與手動補圖設定？比完再決定要不要納入管線，
CLAUDE.md 與 skill 都還沒寫進去。

## 現況

- 普通掃描書找圖：頁面扣掉 Vision 的字框後，剩下大片墨水就當圖（`ocr.py` 的 `find_figures`），
  圖名、刻度、圖例一起裁進圖裡；找錯靠三個手動設定補：`plate_pages`、`framed_figures`、`figure_boxes`。
- 《金融煉金術》（380 頁 OCR）用了 5 段 `plate_pages`（共 46 頁）、`framed_figures`、7 頁 `figure_boxes`
  （其中 3 處是 Vision 讀不了的公式），另外整份 `pdf.chapters` 手寫、`footnote_marks` 限定註腳標記。

## 這次加的程式（預設關閉，現有的書不受影響）

- `python -m epubtrans layout "書名" [--pages …]`：只跑版面模型（不載 VLM），框寫進 `work/layout/pNNNN.json`。
  省略 `--pages` 時只跑 extract 會走 OCR 的頁。需要 `.venv-vlm`（跟 `vlm-ocr` 同一個環境、同一個模型）。
- `pdf.layout: true`：extract 用版面框找圖（`layoutbox.py`）；沒有版面快取的頁退回墨水推算；
  `figure_boxes`、`plate_pages` 仍優先。圖說框不裁進圖裡、留作文字段落（跟數學書管線一樣，可以翻譯）；
  多格圖連同 (a)(b) 小標裁成一張（沿用 `vlm.group_figures`）；圖框裡有三行以上長句的（正文被框成圖）不裁，列進報告。
  `pdf.layout_formulas`（預設 true）：獨立公式連同編號也裁成圖。
- 預設關閉時，《金融煉金術》的 extract 結果（book.json、抽取報告、98 張裁圖）與改動前逐位元相同。
- 測試：`tests/test_layout.py`（合成的版面框，不載模型）。

## 在 Mac 上跑

```bash
git pull
N="《金融煉金術 The Alchemy of Finance》"
./.venv/bin/python -m epubtrans layout "$N"                          # 只寫 work/layout/，不動 book.json、drafts
./.venv/bin/python experiments/layout_compare/compare.py "$N"         # → process/$N/work/layout_compare/report.md

for N in "Non-Stop Scan" "Non-Stop Scan B"; do                       # 小說（沒有圖）：看版面模型會不會誤判
  ./.venv/bin/python -m epubtrans layout "$N"
  ./.venv/bin/python experiments/layout_compare/compare.py "$N"
done
```

`compare.py` 不載模型、不跑 Vision，只讀 `work/ocr/`（Vision 快取）和 `work/layout/`，逐頁比三種找圖方式：

| | 做法 |
|---|---|
| 參考 | 這本書現在的設定（手動設定＋墨水推算）＝已經驗過的結果 |
| 墨水 | 拿掉手動設定，只靠墨水推算 |
| 版面 | 拿掉手動設定，只靠版面框（`pdf.layout: true` 的做法） |

報告內容：參考圖被版面框「蓋到」（八成面積）與「貼合」（IoU ≥ 0.5）的比例，依參考圖的來源分列（手動 `figure_boxes`、
`plate_pages`、墨水推算）；版面多找到的框；被裁掉的長句（正文有沒有被吃掉）；圖說行是留作文字還是裁進圖裡；
現有標題有幾個落在版面的標題框裡；註腳框的開頭標記；版面模型每頁幾秒。有差異的頁輸出成 `pNNNN.png`，
框畫在原頁上（綠粗框＝參考、紅＝墨水、藍虛線＝版面、紫虛線＝公式、橘點線＝像正文而沒裁的框）。

## 判斷標準（提案）

1. 《金融煉金術》手動補的圖（7 頁 `figure_boxes`、46 頁 `plate_pages`）被版面框蓋到九成以上。
2. 版面多裁掉、參考留作正文的長句接近 0（不吃正文）。
3. 兩本 Non-Stop：版面多找到的框接近 0（不誤判）。
4. 版面多找到的框逐頁看圖：是參考漏掉的圖，還是誤判。
5. 速度可以接受（每頁秒數見報告）。

都過了，再做端到端：複製一本測試書（不帶 drafts）、`pdf.layout: true`、拿掉手動補圖設定，`extract` → `build` → `pdf`，看圖說與排版；
之後才寫進 CLAUDE.md 與 skill。標題、註腳（版面框的 `paragraph_title`、`footnote`）這次只量、不改程式，看數字再決定值不值得做。

## 結果

（待跑）
