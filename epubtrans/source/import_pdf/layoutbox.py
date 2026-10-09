"""pdf.layout: true —— 普通書籍的掃描頁用版面模型（PP-DocLayout-V3）的框找圖，取代墨水區塊推算。

框來自 layout_worker 的快取（work/layout/pNNNN.json），格式與數學書的 work/vlm/ 相同
（bbox 是 [y0, x0, y1, x1]，0～1000，相對頁面）。分組沿用 vlm.group_figures：多格圖連同 (a)(b) 小標裁成一張，
圖說框不裁進圖裡，留作文字段落（接在圖後面，build 時跟圖放進同一個 <figure>，照常翻譯）。
文字一律來自 Vision OCR：圖說框裡的字也是從整頁的 Vision 結果撿，不另外辨識。

pdf.layout_formulas（預設 true）：獨立公式框（連同同一列的公式編號）也裁成圖片——Vision 讀不了的公式
原本要靠 pdf.figure_boxes 手動指定。
"""
import json
import pymupdf
from . import vlm

LONG_LINE = 45          # 圖框裡出現幾行這麼長的字，多半是正文被框成圖
LONG_LINES_MAX = 2


def load(cfg, pno):
    try:
        with open(cfg.wpath("layout", f"p{pno + 1:04d}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def to_rect(bbox, W, H):
    y0, x0, y1, x1 = bbox
    return pymupdf.Rect(x0 * W / 1000, y0 * H / 1000, x1 * W / 1000, y1 * H / 1000)


def _center(o, W, H):
    return pymupdf.Point((o[2] + o[4] / 2) * W, (1 - o[3] - o[5] / 2) * H)


def _lines_in(r, obs, W, H):
    """Vision 的行（中心點落在 r 裡），由上而下。"""
    inside = [o for o in obs if r.contains(_center(o, W, H))]
    return sorted(inside, key=lambda o: (-round(o[3] + o[5], 3), o[2]))


def find(page, layout, obs, formulas=True):
    """回傳 (插圖範圍 [Rect]（PDF 點）, 記錄)。記錄：skipped（像正文、沒裁的框）、formulas（裁了幾條公式）。"""
    W, H = page.rect.width, page.rect.height
    boxes = []
    for x in layout["layout"]:
        if x["label"] == "figure_title" and x["score"] >= vlm.LAYOUT_MIN:
            text = " ".join(o[0] for o in _lines_in(to_rect(x["bbox"], W, H), obs, W, H)).strip()
            x = dict(x, text=text or None)
        boxes.append(x)
    out, note = [], {"skipped": [], "formulas": 0}
    for g in vlm.group_figures(boxes):
        r = to_rect(g["bbox"], W, H)
        long_ = [o[0] for o in _lines_in(r, obs, W, H) if len(o[0].strip()) > LONG_LINE]
        if g["label"] != "table" and len(long_) > LONG_LINES_MAX:
            note["skipped"].append({"label": g["label"], "bbox": g["bbox"], "long_lines": len(long_),
                                    "sample": long_[0][:60]})
            continue
        out.append(r)
    if formulas:
        nums = [x for x in layout["layout"] if x["label"] == "formula_number" and x["score"] >= vlm.LAYOUT_MIN]
        for x in layout["layout"]:
            if x["label"] != "formula" or x["score"] < vlm.LAYOUT_MIN:
                continue
            bb = x["bbox"]
            row = [n["bbox"] for n in nums if min(bb[2], n["bbox"][2]) - max(bb[0], n["bbox"][0])
                   > 0.5 * (n["bbox"][2] - n["bbox"][0])]
            r = to_rect(vlm._union([bb] + row), W, H)
            if any(f.contains(r) for f in out):
                continue
            out.append(r)
            note["formulas"] += 1
    return out, note
