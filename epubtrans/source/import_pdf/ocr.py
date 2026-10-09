"""掃描頁 → 版面行：頁面點陣化後交給 macOS 內建的 Vision 文字辨識（本機執行，不呼叫任何模型端點）。

每頁辨識兩次再合併：
  - accurate 模型（開語言校正）為主，整體最準。
  - fast 模型補 accurate 漏掉的孤立短字：accurate 常把章首的「II」「III」整個略過、把「I」讀成「1」。
    fast 的結果只收 accurate 沒涵蓋到的位置。

OCR 沒有字級。行框高度會隨這行有沒有下伸部（g、p、y）變動約 ±25%，拿來分標題、註腳不可靠，
所以長行用「行寬 ÷ 字數」估字級，短行才用行框高度，依同頁長行的比例換算成同一個單位。

插圖：掃描頁整頁是一張圖，插圖要自己找。頁面縮成低解析度，扣掉文字框蓋住的地方，
剩下有大片墨水的區塊就是插圖：裁成圖片放回原位置，圖裡被 OCR 讀出來的字（封面、圖表上的字）丟掉。

原始辨識結果快取在 work/ocr/pNNNN.json；解析度、語言、自訂詞沒變就不重跑，
調整 pdf: 其他設定後重跑 extract 很快。
"""
import json, os, re, statistics, time
import pymupdf
from . import textlayer

VERSION = 3              # 2：漏行的頁換解析度補讀；3：短行也查
LONG_LINE = 25          # 字數至少這麼多的行，才用字寬估字級
INK_DPI = 36            # 找插圖用的低解析度
FIGURE_DPI = 150        # 裁出來的插圖解析度
FRAME_DPI = 72          # 找表格框線用的解析度


def read_pages(cfg, doc, pnos, opts):
    try:
        import objc, Vision
        from Foundation import NSData
    except ImportError:
        raise SystemExit("掃描頁需要 OCR，但缺少 macOS Vision 的 Python 介面：\n"
                         "  ./.venv/bin/pip install pyobjc-framework-Vision")
    langs = list(opts["ocr_languages"])
    words = _custom_words(cfg)
    key = {"v": VERSION, "dpi": opts["ocr_dpi"], "langs": langs, "words": words}
    cache = cfg.wpath("ocr")
    os.makedirs(cache, exist_ok=True)

    imgdir = cfg.wpath("images")
    from . import parse_pages
    plates = parse_pages(opts.get("plate_pages"), doc.page_count)
    framed = bool(opts.get("framed_figures"))
    boxes = {int(k) - 1: v for k, v in (opts.get("figure_boxes") or {}).items()}
    lay = _layout_opts(cfg, opts)
    pages, todo = [], []
    for pno in pnos:
        data = _load(os.path.join(cache, f"p{pno + 1:04d}.json"))
        if data and data.get("key") == key:
            pages.append(_page_with_figures(doc[pno], pno, data, imgdir, pno in plates, framed,
                                            boxes.get(pno), lay))
        else:
            todo.append(pno)
    if todo:
        print(f"OCR {len(todo)} 頁（macOS Vision，{', '.join(langs)}；第一頁要先載入模型）…")
    t0 = time.time()
    for k, pno in enumerate(todo, 1):
        page = doc[pno]
        png = page.get_pixmap(dpi=_dpi(page, opts["ocr_dpi"]), colorspace=pymupdf.csGRAY).tobytes("png")
        with objc.autorelease_pool():
            acc = _recognize(Vision, NSData, png, langs, words, accurate=True)
            try:
                fast = _recognize(Vision, NSData, png, langs, [], accurate=False)
            except RuntimeError:
                fast = []                       # 有些語言 fast 模型不支援，只用 accurate
            # Vision 偶爾整行漏讀（看解析度）：有墨水卻沒有字框的橫帶，換解析度重讀，只補落在帶裡的行
            for dpi in (200, 400):
                bands = _missing_bands(page, acc)
                if not bands:
                    break
                alt = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")
                for o in _recognize(Vision, NSData, alt, langs, words, accurate=True):
                    yc = (1 - o[3] - o[5] / 2) * page.rect.height
                    if len(o[0].strip()) >= 3 and any(a <= yc <= b for a, b in bands) \
                            and not any(_overlap(o, a) for a in acc):
                        acc.append(o)
        extra = [f for f in fast if re.search(r"\w", f[0]) and f[1] >= 0.5 and len(f[0].strip()) <= 20
                 and not any(_overlap(f, a) for a in acc)]
        data = {"key": key, "w": page.rect.width, "h": page.rect.height, "obs": acc + extra}
        with open(os.path.join(cache, f"p{pno + 1:04d}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        pages.append(_page_with_figures(page, pno, data, imgdir, pno in plates, framed,
                                            boxes.get(pno), lay))
        if k % 25 == 0 or k == len(todo):
            print(f"  {k}/{len(todo)} 頁（{time.time() - t0:.0f} 秒）")
    return pages


def _layout_opts(cfg, opts):
    """pdf.layout: true → 讀 work/layout/ 的版面框找圖（layoutbox）；沒有快取的頁退回墨水區塊推算。"""
    if not opts.get("layout"):
        return None
    from . import layoutbox
    return {"load": lambda pno: layoutbox.load(cfg, pno), "find": layoutbox.find,
            "formulas": opts.get("layout_formulas", True)}


def _page_with_figures(page, pno, data, imgdir, plate=False, framed=False, boxes=None, lay=None):
    figures, source, note = figure_rects(page, pno, data, plate, framed, boxes, lay)
    W, H = data["w"], data["h"]
    inside = lambda o, f: f.contains(pymupdf.Point((o[2] + o[4] / 2) * W, (1 - o[3] - o[5] / 2) * H))
    kept = [o for o in data["obs"] if not any(inside(o, f) for f in figures)]
    p = to_page(pno, dict(data, obs=kept))
    for k, f in enumerate(figures):
        name = f"fig_p{pno + 1:04d}_{k}.jpg"
        page.get_pixmap(dpi=FIGURE_DPI, clip=f).save(os.path.join(imgdir, name), jpg_quality=85)
        p["images"].append({"x0": f.x0, "y0": f.y0, "x1": f.x1, "y1": f.y1, "file": name})
    p["dropped_in_figures"] = len(data["obs"]) - len(kept)
    if lay:
        p["figure_source"], p["layout_note"] = source, note
    return p


def figure_rects(page, pno, data, plate=False, framed=False, boxes=None, lay=None):
    """這頁的插圖範圍（PDF 點）→ ([Rect], 來源, 版面模型的記錄)。來源：manual／plate／layout／ink。"""
    source, note = "ink", None
    if boxes:                                                   # pdf.figure_boxes：手動指定，不再自動找
        figures, source = [pymupdf.Rect(*b) for b in boxes], "manual"
    elif plate:
        figures, source = plate_figure(page, data["obs"]), "plate"
    elif lay and (layout := lay["load"](pno)):
        figures, note = lay["find"](page, layout, data["obs"], lay["formulas"])
        source = "layout"
    else:
        figures = find_figures(page, data["obs"])
    if framed and not plate and not boxes:
        for f in framed_tables(page, data["obs"]):
            for g in [g for g in figures if g.intersects(f)]:
                figures.remove(g)
                f = f | g
            figures.append(f)
    # 找圖用的是低解析度，邊框線可能差一兩點：四周多留 3 點
    return [(f + (-3, -3, 3, 3)) & page.rect for f in figures], source, note


def find_figures(page, obs):
    """扣掉文字框後仍有大片墨水的區塊（至少半吋見方）→ 插圖，再把貼著它的圖名、刻度、圖例併進來。"""
    return _with_labels(_merge_close(_ink_blocks(page, obs)), obs, page.rect.width, page.rect.height)


def plate_figure(page, obs):
    """圖版頁（pdf.plate_pages）：「Note(s):」以上的圖、表、圖名整片當一張圖；書眉、頁碼、注記留作文字。"""
    W, H = page.rect.width, page.rect.height
    labels = _label_boxes(obs, W, H, keep_long=True)
    cut = min((_box(o, W, H)[1] for o in obs if NOTES.match(o[0].strip())), default=H)
    parts = [(r.x0, r.y0, r.x1, r.y1) for r in _ink_blocks(page, obs) if r.y0 < cut]
    parts += [b for b in labels if b[3] <= cut]
    if not parts:
        return []
    return [pymupdf.Rect(min(b[0] for b in parts), min(b[1] for b in parts),
                         max(b[2] for b in parts), max(b[3] for b in parts))]


def framed_tables(page, obs):
    """四邊有框線、框裡幾乎沒有長行（不是框起來的引文）的區塊整塊當圖（pdf.framed_figures）。
    框裡字很少（字框面積不到一成）的是圖表：刻度、圖名在框外，照找圖的規則把貼著的短字併進來；
    表格不併（上方常緊接日期小標）。"""
    W, H = page.rect.width, page.rect.height
    out = []
    for f in _frames(page):
        inside = [o for o in obs if f.contains(pymupdf.Point((o[2] + o[4] / 2) * W, (1 - o[3] - o[5] / 2) * H))]
        if sum(len(o[0].strip()) > 45 for o in inside) > 0.1 * len(inside):
            continue
        chart = sum(o[4] * W * o[5] * H for o in inside) < 0.1 * f.get_area()
        for g in _with_labels([f], obs, W, H) if chart else [f]:
            for e in [e for e in out if e.intersects(g)]:
                out.remove(e)
                g = g | e
            out.append(g)
    return out


def _frames(page):
    """框線：上下各一條長橫線（至少頁寬 35%），兩端有直線相連。掃描歪斜時線會跨兩列，橫線用三列合看。"""
    pix = page.get_pixmap(dpi=FRAME_DPI, colorspace=pymupdf.csGRAY)
    w, h, st, s = pix.width, pix.height, pix.stride, pix.samples
    dark = [bytes(1 if s[y * st + x] < 150 else 0 for x in range(w)) for y in range(h)]
    band = [bytes(a | b | c for a, b, c in zip(dark[max(0, y - 1)], dark[y], dark[min(h - 1, y + 1)]))
            for y in range(h)]
    rules = []
    for y, row in enumerate(band):
        best, start, gap = (0, 0, 0), None, 0
        for x in range(w + 1):
            if x < w and row[x]:
                start, gap = (x if start is None else start), 0
            elif start is not None:
                gap += 1
                if gap > 2 or x == w:                           # 容許兩點的斷線
                    end = x - gap + 1
                    if end - start > best[0]:
                        best = (end - start, start, end)
                    start, gap = None, 0
        if best[0] >= 0.35 * w:
            rules.append((y, best[1], best[2]))
    lines = []
    for y, x0, x1 in rules:                                     # 相連的列併成一條線：(上緣, 下緣, 左, 右)
        if lines and y - lines[-1][1] <= 2:
            t, _, a, b = lines[-1]
            lines[-1] = (t, y, min(a, x0), max(b, x1))
        else:
            lines.append((y, y, x0, x1))

    def vertical(xa, xb, y0, y1):
        """從上角 xa 到下角 xb 的直線（掃描歪斜時是斜的），八成五以上的列有墨水。"""
        hit = 0
        for y in range(y0, y1 + 1):
            x = round(xa + (xb - xa) * (y - y0) / max(1, y1 - y0))
            hit += any(dark[y][max(0, x - 4):x + 5])
        return hit >= 0.85 * (y1 - y0 + 1)

    frames, i = [], 0
    while i < len(lines):
        top, j = lines[i], None
        for k in range(len(lines) - 1, i, -1):                  # 由下往上找最遠、兩邊都有直線相連的那條
            bot = lines[k]
            # 兩端往內找直線：刻度、刻度數字會讓橫線比框長一點；歪斜時直線跟著兩角斜，座標軸伸出框外時直線是直的
            left = [(top[2], bot[2]), (max(top[2], bot[2]),) * 2]
            right = [(top[3], bot[3]), (min(top[3], bot[3]),) * 2]
            if bot[0] - top[1] > 0.5 * FRAME_DPI \
                    and any(vertical(a + d, b + d, top[1], bot[0]) for a, b in left for d in range(1, 27, 3)) \
                    and any(vertical(a - d, b - d, top[1], bot[0]) for a, b in right for d in range(2, 27, 3)):
                j = k
                break
        if j is None:
            i += 1
            continue
        bot, k = lines[j], 72 / FRAME_DPI
        frames.append(pymupdf.Rect(min(top[2], bot[2]) * k, top[0] * k, max(top[3], bot[3]) * k, (bot[1] + 1) * k))
        i = j                                                   # 上下相疊的框共用一條橫線
    return frames


def _ink_blocks(page, obs):
    """扣掉文字框後仍有大片墨水的區塊（至少半吋見方）。頁緣 5% 不看（掃描的黑邊、裝訂陰影）。"""
    pix = page.get_pixmap(dpi=INK_DPI, colorspace=pymupdf.csGRAY)
    w, h, stride, s = pix.width, pix.height, pix.stride, pix.samples
    covered = [bytearray(w) for _ in range(h)]
    for _, _, x, y, bw, bh in obs:
        x0, x1 = max(0, int(x * w) - 1), min(w, int((x + bw) * w) + 2)
        y0, y1 = max(0, int((1 - y - bh) * h) - 1), min(h, int((1 - y) * h) + 2)
        for yy in range(y0, y1):
            covered[yy][x0:x1] = b"\x01" * (x1 - x0)
    mx, my = int(0.05 * w), int(0.05 * h)
    ink = []
    for yy in range(h):
        if yy < my or yy >= h - my:
            ink.append([])
            continue
        row, cov = s[yy * stride:yy * stride + w], covered[yy]
        ink.append([xx for xx in range(mx, w - mx) if row[xx] < 140 and not cov[xx]])
    figures, start, gap = [], None, 0
    for yy in range(h + 1):
        hit = yy < h and len(ink[yy]) >= 0.012 * w           # 線條圖每列只有幾點墨水
        if hit:
            start, gap = (yy if start is None else start), 0
        elif start is not None:
            gap += 1
            if gap > 3 or yy == h:
                end = yy - gap + 1
                xs = [x for r in range(start, end) for x in ink[r]]
                if end - start >= 0.5 * INK_DPI and xs and max(xs) - min(xs) >= 0.5 * INK_DPI:
                    sx, sy = page.rect.width / w, page.rect.height / h
                    figures.append(pymupdf.Rect(min(xs) * sx, start * sy, (max(xs) + 1) * sx, end * sy))
                start, gap = None, 0
    return figures


def _merge_close(figures):
    """上下相鄰（間隔不到 0.3 吋）、左右重疊的插圖片段併成一張：線條圖中段墨水稀疏會被切開。"""
    out = []
    for f in figures:
        g = out[-1] if out else None
        if g and f.y0 - g.y1 < 0.3 * 72 and min(f.x1, g.x1) - max(f.x0, g.x0) > 0.5 * min(f.width, g.width):
            out[-1] = pymupdf.Rect(min(f.x0, g.x0), g.y0, max(f.x1, g.x1), max(f.y1, g.y1))
        else:
            out.append(f)
    return out


NOTES = re.compile(r"(?i)notes?\s*:")


def _box(o, W, H):
    return (o[2] * W, (1 - o[3] - o[5]) * H, (o[2] + o[4]) * W, (1 - o[3]) * H)


def _label_boxes(obs, W, H, keep_long=False):
    """可以併進插圖的字：書眉（和頁碼同一基線的最上一行）、頁碼、注記標題不算；
    keep_long=False 時，長行（正文）與緊接在長行下、左緣對齊的短行（段落最後一行）也不算。"""
    boxes = [(o, _box(o, W, H)) for o in obs if o[0].strip() and o[4] > 0 and o[5] > 0]
    if not boxes:
        return []
    top = min(b[3] for _, b in boxes)
    first = [o for o, b in boxes if abs(b[3] - top) < 0.5 * (b[3] - b[1])]
    header = len(first) > 1 and any(re.fullmatch(r"\d{1,3}", o[0].strip()) for o in first)
    long_ = [b for o, b in boxes if len(o[0].strip()) > 45]
    tail = lambda b: any(0 <= b[1] - q[3] < (b[3] - b[1]) and abs(b[0] - q[0]) < 2 * (b[3] - b[1]) for q in long_)
    out = []
    for o, b in boxes:
        t = o[0].strip()
        if re.fullmatch(r"\d{1,3}", t) or (header and o in first) or NOTES.match(t):
            continue
        if not keep_long and (len(t) > 45 or tail(b)):
            continue
        out.append(b)
    return out


def _with_labels(figures, obs, W, H):
    """把貼著插圖的短字（圖名、刻度、圖例）併進插圖，反覆擴到穩定。"""
    if not figures:
        return figures
    labels = _label_boxes(obs, W, H)
    pad = 0.3 * 72
    union = lambda a, b: (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
    meets = lambda a, b, d=0: a[0] - d < b[2] and b[0] < a[2] + d and a[1] - d < b[3] and b[1] < a[3] + d
    out = []
    for r in figures:
        f, grown = (r.x0, r.y0, r.x1, r.y1), True
        while grown:
            grown = False
            for b in labels:
                if meets(f, b, pad) and union(f, b) != f:
                    f, grown = union(f, b), True
        for g in [g for g in out if meets(g, f)]:             # 擴大後碰到另一張的，併成一張
            out.remove(g)
            f = union(f, g)
        out.append(f)
    return [pymupdf.Rect(*f) for f in out]


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _custom_words(cfg):
    """譯名表的原文專名交給 Vision 當自訂詞，人名、地名比較不會被語言校正改掉。"""
    p = os.path.join(cfg.drafts, "glossary.yaml")
    if not os.path.exists(p):
        return []
    import yaml
    words = set()
    for e in yaml.safe_load(open(p, encoding="utf-8")) or []:
        en = e.get("en")
        for w in ([en] if isinstance(en, str) else en or []):
            words.add(str(w))
    return sorted(words)


def _dpi(page, target):
    """掃描頁用原圖的解析度（放大不會多出資訊），上限是設定值。"""
    native = 0
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            if r.width > 0:
                native = max(native, img[2] / (r.width / 72))
    return int(min(target, max(150, native))) if native else target


def _recognize(Vision, NSData, png, langs, words, accurate):
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        NSData.dataWithBytes_length_(png, len(png)), None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate if accurate
                             else Vision.VNRequestTextRecognitionLevelFast)
    req.setUsesLanguageCorrection_(accurate)
    req.setRecognitionLanguages_(langs)
    if words:
        req.setCustomWords_(words)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR 失敗：{err}")
    out = []
    for o in req.results() or []:
        c = o.topCandidates_(1)
        if not c:
            continue
        bb = o.boundingBox()           # 0～1 的相對座標，原點在左下
        out.append([str(c[0].string()), round(float(c[0].confidence()), 3),
                    bb.origin.x, bb.origin.y, bb.size.width, bb.size.height])
    return out


def _missing_bands(page, obs):
    """文字欄裡有墨水（至少欄寬 3%，段末短行也算；連續 5 點高）卻沒有任何字框蓋到的橫帶（PDF 點）。"""
    if not obs:
        return []
    W, H = page.rect.width, page.rect.height
    pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
    k = pix.height / H
    covered = bytearray(pix.height)
    for _, _, x, y, bw, bh in obs:
        covered[max(0, int((1 - y - bh) * H * k) - 1):int((1 - y) * H * k) + 2] = \
            b"\x01" * len(covered[max(0, int((1 - y - bh) * H * k) - 1):int((1 - y) * H * k) + 2])
    x0 = int(min(o[2] for o in obs) * W * k)
    x1 = int(max(o[2] + o[4] for o in obs) * W * k)
    s, st = pix.samples, pix.stride
    bands, run = [], 0
    for y in range(int(0.08 * pix.height), int(0.92 * pix.height) + 1):
        ink = y < pix.height and not covered[y] and \
            sum(1 for v in s[y * st + x0:y * st + x1] if v < 120) > 0.03 * max(1, x1 - x0)
        if ink:
            run += 1
        else:
            if run >= 5:
                bands.append(((y - run - 2) / k, (y + 2) / k))
            run = 0
    return bands


def _overlap(a, b):
    ax0, ay0, ax1, ay1 = a[2], a[3], a[2] + a[4], a[3] + a[5]
    bx0, by0, bx1, by1 = b[2], b[3], b[2] + b[4], b[3] + b[5]
    iw, ih = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
    return iw > 0 and ih > 0 and iw * ih > 0.3 * min(a[4] * a[5], b[4] * b[5])


def _dedupe(obs):
    """同一行被讀了兩次（一次是亂碼）：和信心較高的字框重疊過半的拿掉。"""
    def inter(a, b):
        iw = min(a[2] + a[4], b[2] + b[4]) - max(a[2], b[2])
        ih = min(a[3] + a[5], b[3] + b[5]) - max(a[3], b[3])
        return max(0, iw) * max(0, ih)
    area = lambda o: max(o[4] * o[5], 1e-9)
    return [o for o in obs if not any(q is not o and q[1] > o[1] and inter(o, q) > 0.5 * min(area(o), area(q))
                                      for q in obs)]


def to_page(pno, data):
    W, H = data["w"], data["h"]
    lines = []
    for text, conf, x, y, w, h in _dedupe(data["obs"]):
        text = textlayer.normalize(text)
        if not text:
            continue
        y0, y1 = (1 - y - h) * H, (1 - y) * H
        if re.search(r"[gjpqy(),;Q]", text):
            y1 -= 0.22 * (y1 - y0)          # 行框底緣含下伸部，改估基線，行距才不會跟著字母抖動
        lines.append({"x0": x * W, "x1": (x + w) * W, "y0": y0, "y1": y1,
                      "text": text, "conf": conf, "bold": False, "italic": False, "sup_start": False})
    # 字級：長行用字寬（行寬 ÷ 字數 × 2 ≈ 字級），短行用行框高度換算成同一個單位
    width_size = lambda l: (l["x1"] - l["x0"]) / len(l["text"]) * 2
    ratios = [width_size(l) / (l["y1"] - l["y0"]) for l in lines if len(l["text"]) >= LONG_LINE]
    k = statistics.median(ratios) if ratios else 0.75
    for l in lines:
        long = len(l["text"]) >= LONG_LINE
        l["size"] = width_size(l) if long else (l["y1"] - l["y0"]) * k
        l["size_by_height"] = not long          # 行高估的字級不準，分段時不拿來比
    return {"no": pno, "w": W, "h": H, "mode": "ocr", "lines": lines, "images": []}
