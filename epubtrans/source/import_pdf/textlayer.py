"""PDF 文字層 → 版面行（頁內座標、文字、字級、粗斜體）與插圖。

用 PyMuPDF 的 rawdict 拿到逐字位置，文字由這裡自己拼，因為 PDF 裡沒有「字」與「空白」，
只有一個個定位好的字形，MuPDF 依間距猜哪裡該補空白。這一層處理它猜不對的地方：
  - 字距加寬的標題（部名、書眉常見）：字母間距接近字間距，MuPDF 每個字母之間都補空白，
    抽出來是「C o n t e n t s」。改依逐字間距的分布重判字間。
  - 上標（註腳標號）：字級明顯小、基線抬高 → 轉成上標數字 ¹²³，譯稿裡才分得出是標號。
  - 連字（ﬁ ﬂ）、零寬字元、不換行空白 → 正規化；行尾的軟連字號留給段落層判斷斷字。
"""
import hashlib, os, re, statistics
import pymupdf

# 不含 TEXT_PRESERVE_LIGATURES：MuPDF 會把 ﬁ 之類的連字拆回單字母
FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_IMAGES | pymupdf.TEXT_MEDIABOX_CLIP
SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_CHARMAP = str.maketrans({"​": "", "‌": "", "‍": "", "⁠": "", "﻿": "",
                          " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
                          "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})
MIN_IMAGE_AREA = 0.015      # 插圖至少佔頁面面積的比例；更小的多半是裝飾花紋
MIN_IMAGE_PX = 8            # 點陣圖任一邊小於這個像素數，是拉伸的遮罩而不是圖
FULL_PAGE_AREA = 0.85       # 圖蓋住頁面這個比例以上、而且頁上有正文，就是整頁掃描底圖
MIN_SCAN_TEXT = 200         # 判斷底圖時，文字層至少要有這麼多字
FIGURE_DPI = 220            # pdf.figure_boxes 裁出來的圖解析度（掃描底圖是 500 dpi 黑白，裁成 220 dpi 灰階列印才清楚）


def normalize(text):
    """字元正規化。行尾的軟連字號（U+00AD）保留，代表排版斷字，段落層據此接回單字。"""
    text = text.translate(_CHARMAP)
    body, tail = (text[:-1], text[-1]) if text.endswith("­") else (text, "")
    return re.sub(r" {2,}", " ", body.replace("­", "")).strip() + tail


def text_chars(page):
    """頁面文字層的字數（不含空白），用來判斷這頁要不要走 OCR。"""
    return len(re.sub(r"\s", "", page.get_text("text")))


def read_page(page, pno, imgdir, seen_images, boxes=None):
    d = page.get_text("rawdict", flags=FLAGS)
    area = page.rect.width * page.rect.height
    lines, images = [], []
    for b in d["blocks"]:
        if b["type"] == 1:
            img = _image(b, area)
            if img:
                images.append(img)
            continue
        for l in b["lines"]:
            if abs(l["dir"][1]) > 0.1:          # 直排或旋轉的字（頁邊註記之類）不收
                continue
            ln = _line(l)
            if ln:
                lines.append(ln)
    images = _drop_page_scan(images, lines, area, force=bool(boxes))
    for im in images:
        im["file"] = _save(im.pop("data"), im.pop("ext"), imgdir, seen_images)
    if boxes:                                    # pdf.figure_boxes：整頁掃描底圖上的圖表，手動框出來裁圖
        rects = [pymupdf.Rect(*b) & page.rect for b in boxes]
        inside = lambda ln: any(r.contains(pymupdf.Point((ln["x0"] + ln["x1"]) / 2, (ln["y0"] + ln["y1"]) / 2))
                                for r in rects)
        lines = [ln for ln in lines if not inside(ln)]
        for k, r in enumerate(rects):
            name = f"fig_p{pno + 1:04d}_{k}.jpg"
            page.get_pixmap(dpi=FIGURE_DPI, clip=r).save(os.path.join(imgdir, name), jpg_quality=85)
            images.append({"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1, "file": name})
    return {"no": pno, "w": page.rect.width, "h": page.rect.height, "mode": "text",
            "lines": lines, "images": images}


def _drop_page_scan(images, lines, page_area, force=False):
    """「整頁掃描圖＋隱形文字層」（ABBYY Paper Capture 之類）：蓋住整頁的底圖不是插圖，丟掉。
    整頁都是圖、只有一點說明文字的圖版頁照留（文字不到 MIN_SCAN_TEXT 字）；
    手動指定了 figure_boxes 的頁（force）一律丟，圖由框出來的範圍取代。"""
    if not force and sum(len(ln["text"]) for ln in lines) < MIN_SCAN_TEXT:
        return images
    return [im for im in images
            if (im["x1"] - im["x0"]) * (im["y1"] - im["y0"]) < FULL_PAGE_AREA * page_area]


def _image(b, page_area):
    x0, y0, x1, y1 = b["bbox"]
    if (x1 - x0) * (y1 - y0) < MIN_IMAGE_AREA * page_area or not b.get("image"):
        return None
    if min(b.get("width", MIN_IMAGE_PX), b.get("height", MIN_IMAGE_PX)) < MIN_IMAGE_PX:
        return None                              # 1×1 的遮罩拉成大框（表格線、底色）：不是插圖
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "data": b["image"], "ext": b.get("ext") or "png"}


def _save(data, ext, imgdir, seen):
    h = hashlib.sha1(data).hexdigest()[:12]
    if h not in seen:
        seen[h] = f"img_{h}.{ext}"
        with open(os.path.join(imgdir, seen[h]), "wb") as f:
            f.write(data)
    return seen[h]


def _line(l):
    chars = []
    for s in l["spans"]:
        for c in s["chars"]:
            chars.append({"c": c["c"], "x0": c["bbox"][0], "x1": c["bbox"][2], "oy": c["origin"][1],
                          "size": s["size"], "flags": s["flags"], "font": s["font"]})
    ink = [c for c in chars if c["c"].strip()]
    if not ink:
        return None
    base = statistics.median(c["size"] for c in ink)
    baseline = statistics.median(c["oy"] for c in ink if c["size"] >= base * 0.95)
    for c in chars:
        # 上標：字級小於主字級的八成、基線抬高；MuPDF 的 superscript 旗標（bit 0）也算
        c["sup"] = bool(c["c"].strip()) and (
            (c["flags"] & 1) or (c["size"] < base * 0.8 and c["oy"] < baseline - base * 0.2))

    text = _spaced_text(chars, ink, base)
    text = normalize(text)
    if not text:
        return None
    main = [c for c in ink if not c["sup"]] or ink
    bold = sum(bool(c["flags"] & 16) or "bold" in c["font"].lower() for c in main) >= 0.8 * len(main)
    italic = sum(bool(c["flags"] & 2) or re.search("italic|oblique", c["font"], re.I) is not None
                 for c in main) >= 0.8 * len(main)
    x0, y0, x1, y1 = l["bbox"]
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text,
            "size": sum(c["size"] for c in main) / len(main), "bold": bold, "italic": italic,
            "sup_start": ink[0]["sup"]}


def _spaced_text(chars, ink, size):
    """依字距重建文字。一般行直接用 MuPDF 的結果；字距加寬的行改依間距分布判斷字間。"""
    gaps = [b["x0"] - a["x1"] for a, b in zip(ink, ink[1:])]
    spaced = len(ink) >= 4 and statistics.median(gaps) > 0.08 * size
    out = []
    if spaced:
        cut = statistics.median(gaps) + 0.18 * size
        for i, c in enumerate(ink):
            if i and gaps[i - 1] > cut:
                out.append(" ")
            out.append(_char(c))
    else:
        for c in chars:
            out.append(_char(c))
    return "".join(out)


def _char(c):
    return c["c"].translate(SUPERSCRIPT) if c["sup"] else c["c"]
