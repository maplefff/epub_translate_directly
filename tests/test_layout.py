#!/usr/bin/env python3
"""普通書籍的掃描頁用版面模型找圖（pdf.layout: true）：layoutbox 與 ocr.figure_rects。

不載入模型、不跑 Vision：用合成的版面框（work/layout/ 的格式，bbox＝[y0, x0, y1, x1]，0～1000）與 Vision 行
（[文字, 信心, x, y, w, h]，0～1、原點在左下）。檢查：
  - 圖框裁成圖、圖說框不裁進圖裡，圖說的字從 Vision 行撿（不另外辨識）
  - 多格圖：(a)(b) 小標併進圖裡，兩格裁成一張
  - 圖框裡有多行長句（正文被框成圖）→ 不裁，記進 skipped
  - 獨立公式連同同一列的公式編號裁成一張；layout_formulas: false 時不裁
  - figure_rects 的優先序：figure_boxes（手動）> plate_pages > 版面框 > 墨水推算；沒有版面快取的頁退回墨水推算
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf
from epubtrans.source.import_pdf import ocr, layoutbox

CHECKS = []
W, H = 500.0, 800.0


def check(label, cond, detail=""):
    CHECKS.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not cond else ""))


def box(label, y0, x0, y1, x1, score=0.9):
    return {"label": label, "bbox": [y0, x0, y1, x1], "score": score, "order": 0}


def line(text, y0, x0, y1, x1):
    """0～1000 的 [y0, x0, y1, x1] → Vision 的行（相對座標、原點在左下）。"""
    return [text, 0.99, x0 / 1000, 1 - y1 / 1000, (x1 - x0) / 1000, (y1 - y0) / 1000]


def page():
    doc = pymupdf.open()
    return doc.new_page(width=W, height=H)


def near(r, bb, tol=1.0):
    e = layoutbox.to_rect(bb, W, H)
    return all(abs(a - b) <= tol for a, b in zip(r, e))


def unit_find():
    print("版面框 → 插圖範圍")
    pg = page()
    long_ = "This is a long line of body text that the layout model wrongly boxed as image"
    obs = [line("Figure 2.1 The boom and bust sequence", 420, 150, 440, 750),
           line("Price", 200, 120, 215, 180),                            # 圖裡的刻度字
           line(long_, 600, 100, 615, 900), line(long_, 620, 100, 635, 900), line(long_, 640, 100, 655, 900)]
    lay = {"layout": [box("image", 150, 100, 400, 800), box("figure_title", 418, 140, 442, 760),
                      box("image", 590, 90, 670, 910),                   # 正文被框成圖
                      box("formula", 720, 300, 760, 700), box("formula_number", 728, 850, 752, 900)]}
    rects, note = layoutbox.find(pg, lay, obs)
    check("圖框裁成一張，範圍不含圖說框", len(rects) == 2 and near(rects[0], [150, 100, 400, 800]), rects)
    check("正文被框成圖：不裁，記進 skipped",
          len(note["skipped"]) == 1 and note["skipped"][0]["long_lines"] == 3, note["skipped"])
    check("公式連同同一列的編號裁成一張", note["formulas"] == 1 and near(rects[1], [720, 300, 760, 900]), rects)
    rects2, note2 = layoutbox.find(pg, lay, obs, formulas=False)
    check("layout_formulas: false 不裁公式", len(rects2) == 1 and note2["formulas"] == 0, rects2)

    print("多格圖")
    obs = [line("(a)", 410, 230, 425, 270), line("(b)", 410, 630, 425, 670),
           line("Figure 3.4 Two panels", 440, 300, 460, 700)]
    lay = {"layout": [box("image", 150, 100, 400, 450), box("image", 152, 550, 400, 900),
                      box("figure_title", 408, 225, 427, 275), box("figure_title", 408, 625, 427, 675),
                      box("figure_title", 438, 290, 462, 710)]}
    rects, _ = layoutbox.find(pg, lay, obs)
    check("(a)(b) 兩格連同小標裁成一張", len(rects) == 1 and near(rects[0], [150, 100, 427, 900]), rects)

    print("表格：裡面的長句照裁（表格本來就是一行行的字）")
    obs = [line(long_, 200 + 20 * k, 100, 215 + 20 * k, 900) for k in range(5)]
    rects, note = layoutbox.find(pg, {"layout": [box("table", 190, 90, 310, 910)]}, obs)
    check("表格不因長句被跳過", len(rects) == 1 and not note["skipped"], note)


def unit_priority():
    print("figure_rects 的優先序與退回")
    pg = page()
    data = {"w": W, "h": H, "obs": []}
    lay_hit = {"load": lambda pno: {"layout": [box("image", 100, 100, 300, 900)]}, "find": layoutbox.find,
               "formulas": True}
    lay_miss = dict(lay_hit, load=lambda pno: None)
    _, src, note = ocr.figure_rects(pg, 0, data, lay=lay_hit)
    check("有版面快取 → layout", src == "layout" and note is not None, src)
    rects, src, note = ocr.figure_rects(pg, 0, data, lay=lay_miss)
    check("沒有版面快取 → 墨水推算（空白頁沒有圖）", src == "ink" and rects == [] and note is None, src)
    rects, src, _ = ocr.figure_rects(pg, 0, data, boxes=[[10, 20, 110, 220]], lay=lay_hit)
    check("figure_boxes 優先於版面框", src == "manual" and len(rects) == 1, src)
    _, src, _ = ocr.figure_rects(pg, 0, data, plate=True, lay=lay_hit)
    check("plate_pages 優先於版面框", src == "plate", src)
    _, src, _ = ocr.figure_rects(pg, 0, data)
    check("沒開 layout → 墨水推算", src == "ink", src)


if __name__ == "__main__":
    unit_find()
    unit_priority()
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} 通過")
    sys.exit(0 if all(CHECKS) else 1)
