#!/usr/bin/env python3
"""從已抽取的《不停 Non-Stop》節錄約 20 頁，存成 tests/fixtures/non_stop/（進版控）：

  book.json          前付兩章、PART I 與 PART II 各三章（每章只取前 22 段）、書末一章
  images/cover.png   測試自己畫的佔位圖（不放原書封面），封面頁與插圖都用它

make_test_pdfs.py 預設讀這份節錄，所以 clone 下來就能產生 PDF 測試書，不需要原書。
節錄已經在版控裡，只有要換節錄範圍時才需要重跑這支（要先對原書跑過 extract）。

用法：./.venv/bin/python tests/fixtures/make_excerpt.py ["《不停 Non-Stop》"]
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pymupdf
from epubtrans.core.config import PROCESS

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "non_stop")
# 章 id → 取前幾段（None＝整章）。部名頁（c007、c012）要留，切章與書眉才測得到。
# 每部至少三章：版面 B 的章不換頁，部的第一章緊接在部名後面；章名字級有一半以上接在標題後，會被當成副標
KEEP = {"c005": None, "c006": None,
        "c007": None, "c008": 22, "c009": 22, "c010": 22,
        "c012": None, "c013": 22, "c014": 22, "c015": 22,
        "c028": None}


def placeholder(path):
    """直式佔位圖：灰底斜紋加幾何圖形。每一列都要有深淺變化：掃描版找圖遇到整列同色的橫帶，
    會當成空白、把圖切成兩張。"""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=450)
    page.draw_rect(page.rect, color=None, fill=(0.55, 0.55, 0.55))
    for x in range(-450, 300, 12):
        page.draw_line((x, 450), (x + 450, 0), color=(0.25, 0.25, 0.25), width=2)
    page.draw_circle((150, 180), 90, color=(0.2, 0.2, 0.2), fill=(0.8, 0.8, 0.8), width=3)
    page.draw_rect(pymupdf.Rect(40, 320, 260, 400), color=(0.2, 0.2, 0.2), fill=(0.3, 0.3, 0.3), width=3)
    page.get_pixmap(dpi=144).save(path)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "《不停 Non-Stop》"
    book = json.load(open(os.path.join(PROCESS, name, "work", "book.json"), encoding="utf-8"))
    chapters = []
    for c in book["chapters"]:
        if c["id"] in KEEP:
            n = KEEP[c["id"]]
            chapters.append({**c, "items": c["items"][:n] if n else c["items"]})
    os.makedirs(os.path.join(OUT, "images"), exist_ok=True)
    placeholder(os.path.join(OUT, "images", "cover.png"))
    out = {**{k: v for k, v in book.items() if k != "chapters"}, "cover": "cover.png", "chapters": chapters}
    with open(os.path.join(OUT, "book.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    paras = sum(len(c["items"]) for c in chapters)
    print(f"{OUT}/book.json：{len(chapters)} 章、{paras} 個項目、"
          f"{sum(len(it.get('text', '')) for c in chapters for it in c['items']):,} 字元")


if __name__ == "__main__":
    main()
