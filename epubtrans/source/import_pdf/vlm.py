"""pdf.mode: vlm —— 掃描數學書：讀 vlm_worker 的逐頁快取（work/vlm/pNNNN.json）→ book.json。

快取是 VLM 把整頁轉成的 Markdown＋LaTeX，加上 PP-DocLayout-V3 的版面框。這裡：
  1. 每頁的 Markdown 切成區塊：標題、段落、獨立公式（$$…$$，\\tag 抽成 tag）、圖片佔位、註腳、表格
  2. 圖與表用版面框從原頁裁圖（多格圖連同 (a)(b) 小標裁成一張），放在 VLM 寫的位置：同號圖說之前、
     ![](figure) 佔位、Markdown 表格（裁圖取代它）；VLM 完全沒寫的圖才依高度推算
  3. 書眉頁碼拿掉；行內式維持 $…$ 留在段落文字裡；粗斜體標記拿掉；正文的註腳標號轉成上標數字
  4. 跨頁段落接回；切章：「Chapter N」頁開第一層，# 標題（1.1 …）開第二層；註腳收到各節結尾的 Notes

獨立公式是 {"type": "math", "text": LaTeX, "tag": "1.83"}：不進譯稿（store.TEXT_TYPES 不含 math），
但 text 欄放 LaTeX，drafts/source_fixes.yaml 也能拿來校正公式。
"""
import json, os, re

LAYOUT_MIN = 0.5                  # 版面框信心門檻（快取存到 0.3）
CROP_LABELS = ("image", "chart", "table")
# 編號後的句點不能接數字：不然「Figure 3.18 is a plot …」會在「Figure 3.」回溯成圖說（第 147、170 頁）
CAPTION = re.compile(r"^(Figure|Fig\.|Table)\s+[A-Z]?\d+(\.\d+)?(\s*[:.](?!\d)|\s*$|\s+[A-Z(“\"])")
TERMINAL = tuple(".!?:;\"'”’)]…")
SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
HEADER = re.compile(r"^(\d{1,3}\s+)?((CHAPTER|APPENDIX)\s+[\dA-Z]+\.?\s.*|INDEX|CONTENTS|"
                    r"[\dA-Z]+(\.\d+)*\.\s+[A-Z][A-Z0-9 ,.'’\-:/()&]+)(\s+\d{1,3})?$")
# 標題的角色看編號，不看 # 的數量：VLM 在章首頁會把層級整個往下移一階（## 1.1、### 1.1.1）
SECTION = re.compile(r"^([A-Z]|\d+)\.\d+\s+\S")                 # 1.1 Vector Algebra、A.1 …：開第二層
SUBSECTION = re.compile(r"^([A-Z]|\d+)\.\d+\.\d+\s+\S")         # 1.1.1 …：節內小標
# 沒有編號、但也是一節的標題（其他沒編號的 # 標題，像 Example 1.3，當節內小標）
UNNUMBERED_SECTION = re.compile(r"^(Preface|Advertisement|Foreword|Introduction|Acknowledgments?|"
                                r"More Problems on Chapter \d+|Index|Bibliography|References)\b", re.I)
BLANK_PAGE = re.compile(r"^\W*(this page (is |has been )?(intentionally )?(left )?blank|blank page)\W*$", re.I)

# 頁首這些開頭是新的段落／小題，不是上一頁段落的延續
NEW_BLOCK = re.compile(r"(Problem|Example|Figure|Fig\.|Table|Solution|Proof)\b|\(?[a-z]{1,3}\)\s|•")
CHAPTER = re.compile(r"^(Chapter|CHAPTER)\s+(\d+|[IVX]+)\s*$")
APPENDIX = re.compile(r"^(Appendix|APPENDIX)\s+([A-Z])\s*$")


def load_pages(cfg, doc, pnos):
    """回傳 ([(pno, 快取)], 缺快取的頁碼)。"""
    pages, missing = [], []
    for pno in pnos:
        f = cfg.wpath("vlm", f"p{pno + 1:04d}.json")
        try:
            pages.append((pno, json.load(open(f, encoding="utf-8"))))
        except (OSError, ValueError):
            missing.append(pno + 1)
    if missing:
        print(f"※ 有 {len(missing)} 頁還沒有 OCR 快取（work/vlm/），這次先略過，book.json 不完整："
              f"{missing[:12]}{'…' if len(missing) > 12 else ''}\n  補跑：.venv-vlm/bin/python "
              f"epubtrans/source/import_pdf/vlm_worker.py \"{cfg.source_file()}\" \"{cfg.wpath('vlm')}\"")
    return pages, missing


# ── 一頁 Markdown → 區塊 ─────────────────────────────────────────────

# VLM 偶爾把多行推導寫成沒包 $$ 的 \begin{align*}…\end{align*}（第 334、449 頁），
# 不處理會逐行切成段落、印出原始碼。改包成 $$ 的獨立公式；align／gather 換成可放進 $$ 的 aligned／gathered。
BARE_ENV = re.compile(r"\\begin\{(align|equation|gather|multline)(\*?)\}(.*?)\\end\{\1\2\}", re.S)
_INNER_ENV = {"align": "aligned", "gather": "gathered"}


def _wrap_bare_env(m):
    env, body = _INNER_ENV.get(m.group(1)), m.group(3).strip()
    return "$$" + (f"\\begin{{{env}}}{body}\\end{{{env}}}" if env else body) + "$$"


def _normalize(md):
    md = re.sub(r"^\s*```[a-z]*\s*\n", "", md)              # VLM 偶爾把整頁包在 ```markdown … ``` 裡
    md = re.sub(r"\n\s*```\s*$", "", md)
    md = re.sub(r"\\\[(.+?)\\\]", lambda m: "$$" + m.group(1) + "$$", md, flags=re.S)
    md = re.sub(r"\\\((.+?)\\\)", lambda m: "$" + m.group(1) + "$", md, flags=re.S)
    parts = re.split(r"(\$\$.+?\$\$)", md, flags=re.S)        # 已經在 $$ 裡的不動
    md = "".join(p if k % 2 else BARE_ENV.sub(_wrap_bare_env, p) for k, p in enumerate(parts))
    return md


def _split_math(text):
    """段落文字 → [(是否公式, 片段)]，公式是 $…$。"""
    out, pos = [], 0
    for m in re.finditer(r"\$(.+?)\$", text):
        out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    out.append((False, text[pos:]))
    return out


def clean_inline(text):
    """拿掉粗斜體標記、HTML；註腳標號轉上標。公式（$…$）內不動。"""
    parts = []
    for is_math, s in _split_math(text):
        if is_math:
            m = re.fullmatch(r"\$\s*\^\{?(\d{1,3})\}?\s*\$", s)       # $^5$、$^{15}$：註腳標號
            parts.append(m.group(1).translate(SUP) if m else s)
            continue
        s = re.sub(r"<sup>(\d{1,3})</sup>", lambda m: m.group(1).translate(SUP), s)
        s = re.sub(r"\^\{?(\d{1,3})\}?", lambda m: m.group(1).translate(SUP), s)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"\1", s)
        s = re.sub(r"<[^>]+>", "", s)
        parts.append(s)
    out = "".join(parts)
    out = re.sub(r"\s+([⁰¹²³⁴⁵⁶⁷⁸⁹]+)(?=[\s,.;:)]|$)", r"\1", out)      # 「H: ⁵」→「H:⁵」
    return re.sub(r"\s+", " ", out).strip()


# VLM 偶爾把表格寫成 LaTeX（第 393 頁 Table 9.1），表名包在 \begin{center} 裡
TABULAR = re.compile(r"(?:\\begin\{center\}(.*?)\\end\{center\}\s*)?\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}", re.S)


def _tabular_rows(m):
    """LaTeX tabular → Markdown 表格的列（| a | b |），之後和 Markdown 表格一樣處理。"""
    rows = []
    if m.group(1):
        rows.append("| " + re.sub(r"\\textbf\{(.*?)\}", r"\1", m.group(1)).strip() + " |")
    for r in re.split(r"\\\\", m.group(2)):
        r = r.replace("\\hline", "").strip()
        if r:
            rows.append("| " + " | ".join(c.strip() for c in r.split("&")) + " |")
    return "\n" + "\n".join(rows) + "\n"


def parse_markdown(md):
    """一頁 Markdown → 區塊 list：{kind: heading|para|math|fig|note|table, …}。"""
    md = _normalize(md)
    blocks, pending_tag = [], None
    pos = 0
    chunks = []
    for m in re.finditer(r"\$\$(.+?)\$\$", md, flags=re.S):
        chunks.append(("text", md[pos:m.start()]))
        chunks.append(("math", m.group(1)))
        pos = m.end()
    chunks.append(("text", md[pos:]))
    for kind, s in chunks:
        if kind == "math":
            tex = s.strip()
            tags = re.findall(r"\\tag\s*\{([^}]*)\}", tex)
            tex = re.sub(r"\\tag\s*\{[^}]*\}", "", tex).strip()
            blocks.append({"kind": "math", "text": tex, "tag": tags[-1] if tags else None})
            continue
        s = TABULAR.sub(_tabular_rows, s)
        for line in s.split("\n"):
            t = line.strip()
            if not t or re.fullmatch(r"[-*_]{3,}", t):
                continue
            num = re.fullmatch(r"\((\d+\.\d+[a-z]?|[A-C]\.\d+)\)", t)
            if num and blocks and blocks[-1]["kind"] == "math" and not blocks[-1]["tag"]:
                blocks[-1]["tag"] = num.group(1)                          # 公式編號寫在 $$ 外面
                continue
            if re.match(r"!\[[^\]]*\]\([^)]*\)", t):
                blocks.append({"kind": "fig"}); continue
            if t.startswith("|"):
                if blocks and blocks[-1]["kind"] == "table":
                    blocks[-1]["rows"].append(t)
                else:
                    blocks.append({"kind": "table", "rows": [t]})
                continue
            note = re.match(r"\[\^(\d+|\*)\]:\s*(.*)", t)
            if note:
                mark = note.group(1)
                blocks.append({"kind": "note", "mark": mark.translate(SUP) if mark.isdigit() else mark,
                               "text": clean_inline(note.group(2))}); continue
            h = re.match(r"(#{1,6})\s+(.*)", t)
            if h:
                blocks.append({"kind": "heading", "level": len(h.group(1)), "text": clean_inline(h.group(2))})
                continue
            t = re.sub(r"^[*\-]\s{1,}(?=\S)", "• ", t)                     # VLM 的清單符號（原書習題前的 •）
            blocks.append({"kind": "para", "text": clean_inline(t)})
    return [b for b in blocks if b["kind"] in ("math", "fig", "table") or b.get("text")]


def strip_header(blocks):
    """頁首的書眉（章名＋頁碼）、單獨的頁碼。VLM 提示要它別寫，偶爾還是會寫。"""
    while blocks and blocks[0]["kind"] in ("para", "heading") and (
            HEADER.match(blocks[0]["text"]) or re.fullmatch(r"[\divxlc]{1,4}", blocks[0]["text"])):
        blocks = blocks[1:]
    while blocks and blocks[-1]["kind"] == "para" and re.fullmatch(r"[\divxlc]{1,4}", blocks[-1]["text"]):
        blocks = blocks[:-1]
    return blocks


# ── 圖、表：版面框裁圖、依圖說對位 ──────────────────────────────────

def _area(b):
    y0, x0, y1, x1 = b
    return max(0, y1 - y0) * max(0, x1 - x0)


def _inter(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _same_row(a, b):
    """兩個框垂直重疊超過較矮者的一半＝同一列。"""
    h = min(a[2] - a[0], b[2] - b[0])
    return h > 0 and min(a[2], b[2]) - max(a[0], b[0]) > 0.5 * h


def reading_rows(items, box=lambda x: x):
    """依閱讀順序分列：同一列的由左到右，列與列由上到下。只看 (y0, x0) 排會出錯：
    並排的 (a)(b) 頂端差 1，(b) 就排到 (a) 前面（Griffiths 第 33 頁）。"""
    rows = []
    for it in sorted(items, key=lambda x: box(x)[0]):
        if rows and any(_same_row(box(it), box(o)) for o in rows[-1]):
            rows[-1].append(it)
        else:
            rows.append([it])
    return [sorted(r, key=lambda x: box(x)[1]) for r in rows]


SUBLABEL = re.compile(r"^\(?[a-z]\)?\.?$|^\([a-z]\)\s")         # 多格圖每一格下的 (a)、(b)
SUBLABEL_W = 40                   # 格子小標框的寬度上限（0～1000）：「Figure 1.18」約 80


def _is_sublabel(t):
    """圖說框是不是格子小標。Vision 讀這種一兩個字的小框不可靠（第 33 頁的 (a)(c) 讀成空白、「(э)」），
    所以窄框只要沒讀出「Figure N」也算。"""
    text = (t.get("text") or "").strip()
    if SUBLABEL.match(text):
        return True
    return t["bbox"][3] - t["bbox"][1] <= SUBLABEL_W and len(text) <= 4 and not _cap_key(text)


def _near(bbox, label, t):
    """圖說框 t 在圖的正下方（表格：正上方或正下方）、水平有重疊 → (是否, 距離)。"""
    iy0, ix0, iy1, ix1 = bbox
    ty0, tx0, ty1, tx1 = t["bbox"]
    overlap = min(ix1, tx1) - max(ix0, tx0) > 0
    below = -15 <= ty0 - iy1 <= 70
    above = label == "table" and -15 <= iy0 - ty1 <= 70
    return overlap and (below or above), abs(ty0 - iy1) if below else abs(iy0 - ty1)


def group_figures(layout):
    """版面框 → 圖組 [{label, bbox, title, cap, row}]，依閱讀順序（座標 0～1000，[y0, x0, y1, x1]）。

    - 被另一個框幾乎整個包住的框拿掉（同一張圖被框兩次）
    - 「(a)」「(b)」格子小標（_is_sublabel；text 是 crop_figures 用 Vision 讀的）、圖內的小標題併進正上方的圖框
    - 每個圖框（連同它的小標）配正下方（表格：正上方或正下方）最近、水平上有重疊的圖說框
    - 沒配到圖說的框：和某張有圖說的圖同一列 → 併進去（(a)(b)(c) 並排、只有一個圖說的多格圖；
      同列有兩張時，有小標的格子併進也有小標的那張）；
      有格子小標、在某張有圖說的圖正上方 → 也併進去（(a)(b) 在上、(c) 在下，共用一個 Figure 1.18）；
      沒有小標但貼在正上方（間距 ≤10、水平重疊過半）的也是
    - row：同一頁的第幾列；同一列有兩組以上＝各有圖說的並排圖
    """
    boxes = [x for x in layout if x["label"] in CROP_LABELS and x["score"] >= LAYOUT_MIN]
    boxes = [x for x in boxes if not any(o is not x and _area(o["bbox"]) > _area(x["bbox"])
                                         and _inter(o["bbox"], x["bbox"]) > 0.85 * _area(x["bbox"]) for o in boxes)]
    titles = [x for x in layout if x["label"] == "figure_title" and x["score"] >= LAYOUT_MIN]
    keyed = [t for t in titles if _cap_key(t.get("text"))]
    # 圖內的小標題（第 82 頁「Equal but opposite charges」）：讀得到字、沒有圖號，緊貼在某個「Figure N」正上方
    inner = lambda t: t.get("text") and not _cap_key(t["text"]) and any(
        0 <= k["bbox"][0] - t["bbox"][2] <= 30 and min(t["bbox"][3], k["bbox"][3]) - max(t["bbox"][1], k["bbox"][1]) > 0
        for k in keyed)
    subs = [t for t in titles if _is_sublabel(t) or inner(t)]
    caps = [t for t in titles if not any(t is s for s in subs)]

    panel = {id(b): b["bbox"] for b in boxes}              # 圖框連同它的格子小標
    cells = set()
    for s in subs:
        cands = [(d, b) for b in boxes for ok, d in [_near(b["bbox"], b["label"], s)] if ok]
        if cands:
            b = min(cands, key=lambda x: x[0])[1]
            panel[id(b)] = _union([panel[id(b)], s["bbox"]])
            cells.add(id(b))

    groups = [{"title": t, "boxes": []} for t in caps
              if any(_near(panel[id(b)], b["label"], t)[0] for b in boxes)]
    free = []
    for b in boxes:
        best = min(((d, g) for g in groups for ok, d in [_near(panel[id(b)], b["label"], g["title"])] if ok),
                   default=None, key=lambda x: x[0])
        if best:
            best[1]["boxes"].append(b)
        else:
            free.append(b)
    groups = [g for g in groups if g["boxes"]]

    def joins(b, g):
        pb = panel[id(b)]
        if any(_same_row(pb, panel[id(o)]) for o in g["boxes"]):
            return True
        gb = _union([panel[id(o)] for o in g["boxes"]])
        xo = min(pb[3], gb[3]) - max(pb[1], gb[1])
        if -15 <= gb[0] - pb[2] <= 10 and xo > 0.5 * min(pb[3] - pb[1], gb[3] - gb[1]):
            return True                           # 貼在正上方（第 320 頁 Figure 7.22 的 (a)，小標在圖框裡）
        above = -15 <= gb[0] - pb[2] <= 70 or (not g["title"] and -15 <= pb[0] - gb[2] <= 70)
        return id(b) in cells and above and xo > 0

    changed = True
    while changed:                                # 一格併進去之後，它上面的格子才接得上
        changed = False
        for b in list(free):
            hit = [g for g in groups if g["title"] and joins(b, g)]
            if len(hit) > 1 and id(b) in cells:   # 格子和兩張圖同列：併進也是多格圖的那張（第 193 頁 Figure 4.19 的 (a)）
                hit = [g for g in hit if any(id(o) in cells for o in g["boxes"])]
            if len(hit) == 1:
                hit[0]["boxes"].append(b)
                free.remove(b)
                changed = True
    for b in free:                                # 沒有圖說的格子彼此相連的併成一張
        g = next((g for g in groups if not g["title"] and id(b) in cells
                  and all(id(o) in cells for o in g["boxes"]) and joins(b, g)), None)
        if g:
            g["boxes"].append(b)
        else:
            groups.append({"title": None, "boxes": [b]})
    for g in groups:                              # 多格圖的圖說置中、和哪一格都不重疊（第 168 頁 Figure 3.34）：看整組
        if not g["title"] and len(g["boxes"]) > 1:
            u = _union([panel[id(b)] for b in g["boxes"]])
            best = min(((d, t) for t in caps if not any(o["title"] is t for o in groups)
                        for ok, d in [_near(u, "image", t)] if ok), default=None, key=lambda x: x[0])
            if best:
                g["title"] = best[1]
    out = []
    for g in groups:
        bb = _union([panel[id(b)] for b in g["boxes"]])
        label = "table" if any(b["label"] == "table" for b in g["boxes"]) else "image"
        t = g["title"]
        out.append({"label": label, "bbox": bb, "title": t["bbox"] if t else None, "cap": t.get("text") if t else None})
    rows = reading_rows(out, lambda g: g["bbox"])
    for r, row in enumerate(rows):
        for g in row:
            g["row"] = r
    return [g for row in rows for g in row]


def _ocr_caption(page, bbox, dpi):
    """圖說框用 macOS Vision 讀（只是「Figure 1.7」這種短字）；VLM 漏掉圖說時補上。"""
    try:
        import objc, Vision, pymupdf
        from Foundation import NSData
        from .ocr import _recognize
    except ImportError:
        return None
    W, H = page.rect.width, page.rect.height
    y0, x0, y1, x1 = bbox
    r = pymupdf.Rect(x0 * W / 1000 - 3, y0 * H / 1000 - 3, x1 * W / 1000 + 3, y1 * H / 1000 + 3) & page.rect
    png = page.get_pixmap(dpi=max(dpi, 200), clip=r, colorspace=pymupdf.csGRAY).tobytes("png")
    with objc.autorelease_pool():
        obs = _recognize(Vision, NSData, png, ["en-US"], [], True)
    obs.sort(key=lambda o: (-round(o[3] + o[5], 2), o[2]))
    text = " ".join(o[0] for o in obs).strip()
    return re.sub(r"\s+", " ", text) or None


def crop_figures(page, data, pno, imgdir):
    """版面框分組後裁成 PNG（原書解析度）；回傳依閱讀順序排的 [{file, label, y, cap, row}]。

    圖說框先全部用 Vision 讀：分組要靠文字分出「(a)」「(b)」這種格子小標（併進圖裡一起裁，不當圖說）。"""
    import pymupdf
    W, H, pad = page.rect.width, page.rect.height, 2
    dpi = data.get("dpi") or 200
    layout = [dict(x, text=_ocr_caption(page, x["bbox"], dpi))
              if x["label"] == "figure_title" and x["score"] >= LAYOUT_MIN else x for x in data["layout"]]
    out = []
    for k, g in enumerate(group_figures(layout)):
        y0, x0, y1, x1 = g["bbox"]                     # 0～1000，相對頁面
        r = pymupdf.Rect(x0 * W / 1000 - pad, y0 * H / 1000 - pad, x1 * W / 1000 + pad, y1 * H / 1000 + pad) & page.rect
        if r.width < 10 or r.height < 10:
            continue
        fn = f"p{pno + 1:04d}_{k + 1}.png"
        pix = page.get_pixmap(dpi=dpi, clip=r, colorspace=pymupdf.csGRAY)
        pix.set_dpi(dpi, dpi)                      # PNG 記下原書解析度：PDF 可照原書實際尺寸印（print.image_natural）
        pix.save(os.path.join(imgdir, fn))
        out.append({"file": fn, "label": g["label"], "y": (y0 + y1) / 2000, "cap": g["cap"], "row": g["row"]})
    return out


def _cap_key(text):
    m = re.match(r"(Figure|Fig\.|Table)\s+([A-Z]?\d+(\.\d+)?)", text or "")
    return (m.group(1)[:3].replace("Fig", "Fig"), m.group(2)) if m else None


# VLM 把多格圖每一格的小標寫成單獨一行「(a)」，緊貼在 ![](figure) 前後
SUBLABEL_LINE = re.compile(r"^(\(?[a-z]\)\.?\s*)+$|^[a-z]$")


INNER_MAX = 60                    # 夾在佔位與圖說之間、當成圖內文字拿掉的行，長度上限


def drop_figure_text(blocks):
    """整理 VLM 寫在圖旁邊的文字。圖內文字都已經裁在圖裡，留著會變成正文段落，把句子切斷、擋住跨頁接段：
      - 緊貼 ![](figure) 的「(a)」「(b)」行（第 33 頁）拿掉
      - 夾在 ![](figure) 與圖說之間的短行：像標籤的（圖內小標題，第 82 頁「Equal but opposite charges」）拿掉；
        像句子的（有句點）是寫在圖號上方的圖說本文（第 295 頁「Ferromagnetic domains. (Photo courtesy …)」），
        版面模型沒框到、不在裁圖裡，併進圖說：「Figure 6.26 Ferromagnetic domains. …」"""
    fig = lambda j: 0 <= j < len(blocks) and blocks[j]["kind"] == "fig"
    drop, merged = {i for i, b in enumerate(blocks)
                    if b["kind"] == "para" and SUBLABEL_LINE.match(b["text"]) and (fig(i - 1) or fig(i + 1))}, {}
    for i, b in enumerate(blocks):
        if b["kind"] != "fig":
            continue
        j = i + 1
        while j < len(blocks) and blocks[j]["kind"] == "para" and len(blocks[j]["text"]) <= INNER_MAX \
                and not CAPTION.match(blocks[j]["text"]):
            j += 1
        if j > i + 1 and j < len(blocks) and blocks[j]["kind"] == "para" and CAPTION.match(blocks[j]["text"]):
            drop.update(range(i + 1, j))
            body = [blocks[k]["text"] for k in range(i + 1, j) if re.search(r"\.(\s|$)", blocks[k]["text"])]
            if body:
                merged[j] = dict(blocks[j], text=" ".join([blocks[j]["text"]] + body))
    return [merged.get(i, b) for i, b in enumerate(blocks) if i not in drop]


def place_figures(blocks, crops):
    """把裁好的圖放回區塊序列。回傳 (blocks, 對位是否乾淨)。

    VLM 寫在哪裡，圖就放在哪裡：
      1. Vision 讀到圖說（Figure 1.7），VLM 的輸出裡有同號的圖說 → 插在圖說前面，緊鄰的 ![](figure) 佔位一併用掉；
         表格則取代緊鄰圖說的 Markdown 表格
      2. 其餘依序用 VLM 的佔位：圖用 ![](figure)、表用 Markdown 表格（裁圖取代它）；
         讀不到圖說的，再用還沒配到圖的同類圖說（圖配 Figure、表配 Table）；最後才用另一類的佔位
      3. VLM 完全沒提到這張圖（第 19 頁連圖帶圖說都沒寫）：依圖在頁面上的高度推算位置，列進報告
    Vision 讀到、VLM 卻沒寫的圖說，接在圖後面補上。沒配到圖的 Markdown 表格：這頁有表的裁圖就拿掉，否則當段落留著。
    同一列有兩張以上（各有圖說的並排圖）：合成一個圖列（figrow），放在最前面那張的位置，
    各自的圖說依序接在圖列後面（仍是可翻譯的段落）；cells 的 cap 記這一格有沒有圖說。
    """
    blocks = drop_figure_text(blocks)
    caps = {i: _cap_key(b["text"]) for i, b in enumerate(blocks) if b["kind"] == "para" and CAPTION.match(b["text"])}
    used, at, extra_caps, capidx = set(), {}, {}, {}   # at：crop 檔名 → 插在第幾個區塊之前；capidx：配到的圖說
    # 還沒用的佔位；讀得到圖說號碼的圖，不用緊接著別號圖說的佔位（那是另一張圖的，第 168 頁）
    hold = lambda kind, key=None: [i for i, b in enumerate(blocks) if b["kind"] == kind and i not in used
                                   and not (key and caps.get(i + 1) and caps[i + 1] != key)]
    holder_kind = lambda c: "table" if c["label"] == "table" else "fig"

    def by_caption(c, i):
        kind = holder_kind(c)
        run = []                                  # 圖說前面連續的佔位（多格圖有好幾個）
        j = i - 1
        while j >= 0 and blocks[j]["kind"] == kind and j not in used:
            run.append(j); j -= 1
        if not run and i + 1 < len(blocks) and blocks[i + 1]["kind"] == kind and i + 1 not in used:
            run.append(i + 1)
        used.add(i); used.update(run)
        capidx[c["file"]] = i
        at[c["file"]] = min(run) if kind == "table" and run else i

    def by_holder(c, h):
        """用佔位對位：緊接在佔位後面（表格也看前面）、還沒配到圖的同類圖說，也是這張圖的。"""
        used.add(h)
        at[c["file"]] = h
        kind = "Tab" if c["label"] == "table" else "Fig"
        for j in (h + 1, h - 1) if c["label"] == "table" else (h + 1,):
            if j in caps and j not in used and caps[j] and caps[j][0] == kind:
                used.add(j)
                capidx[c["file"]] = j
                break

    rest = []
    for c in crops:
        key = _cap_key(c.get("cap"))
        hit = next((i for i, k in caps.items() if key and k == key and i not in used), None)
        if hit is None:
            rest.append(c)
        else:
            by_caption(c, hit)
    ok, guessed = True, set()
    for c in rest:
        key = _cap_key(c.get("cap"))
        h = hold(holder_kind(c), key)
        if h:
            by_holder(c, h[0])
            continue
        if not key:
            kind = "Tab" if c["label"] == "table" else "Fig"
            hit = next((i for i in sorted(caps) if i not in used and caps[i] and caps[i][0] == kind), None)
            if hit is not None:
                by_caption(c, hit)
                continue
        h = hold("fig" if holder_kind(c) == "table" else "table", key)
        if h:
            used.add(h[0]); at[c["file"]] = h[0]      # 另一類的佔位：不認領旁邊的圖說
            continue
        ok = False                                # VLM 沒寫這張圖：位置是推定的
        guessed.add(c["file"])
        at[c["file"]] = min(len(blocks), round(c["y"] * len(blocks)))
    for c in rest:                                # VLM 沒寫的圖說（「Figure N」，或位置推定的圖讀到的任何圖說）
        if c.get("cap") and c["file"] not in capidx and (_cap_key(c["cap"]) or c["file"] in guessed):
            extra_caps[c["file"]] = c["cap"]
    has_table = any(c["label"] == "table" for c in crops)
    rows = {}
    for c in crops:
        rows.setdefault(c.get("row", c["file"]), []).append(c)
    inserts, moved = {}, set()
    for cs in rows.values():
        if len(cs) == 1:
            inserts.setdefault(at[cs[0]["file"]], []).append(cs)
        else:
            inserts.setdefault(min(at[c["file"]] for c in cs), []).append(cs)
            moved.update(capidx[c["file"]] for c in cs if c["file"] in capidx)
    cap_of = lambda c: blocks[capidx[c["file"]]] if c["file"] in capidx else (
        {"kind": "para", "text": extra_caps[c["file"]]} if c["file"] in extra_caps else None)
    out = []
    for i, b in enumerate(blocks + [None]):
        for cs in inserts.get(i, []):
            if len(cs) == 1:
                out.append({"kind": "image", "file": cs[0]["file"]})
                if cs[0]["file"] in extra_caps:
                    out.append({"kind": "para", "text": extra_caps[cs[0]["file"]]})
                continue
            out.append({"kind": "figrow", "cells": [{"file": c["file"], "cap": cap_of(c) is not None} for c in cs]})
            out += [cap_of(c) for c in cs if cap_of(c) is not None]
        if b is None or i in moved or b["kind"] == "fig" or (b["kind"] == "table" and (i in used or has_table)):
            continue
        out.append(b if b["kind"] != "table" else {"kind": "para", "text": " ".join(b["rows"])})
    return out, ok


# ── 全書：接跨頁段落、切章 ────────────────────────────────────────

def build_book(cfg, doc, pages, imgdir):
    """pages：[(pno, 快取)]。回傳 (chapters, report)。"""
    report = {"figure_mismatch": [], "loop_stopped": [], "truncated": [], "math": 0, "inline_math": 0,
              "untagged_math": 0, "images": 0}
    seq = []                                       # [(pno, block)]
    for pno, data in pages:
        if data.get("loop_stopped"):
            report["loop_stopped"].append(pno + 1)
        if data.get("truncated"):
            report["truncated"].append(pno + 1)
        if BLANK_PAGE.match(data["md"].strip()):
            continue
        blocks = strip_header(parse_markdown(data["md"]))
        crops = crop_figures(doc[pno], data, pno, imgdir)
        blocks, ok = place_figures(blocks, crops)
        if not ok:
            report["figure_mismatch"].append(pno + 1)
        report["images"] += sum(1 if b["kind"] == "image" else len(b["cells"]) for b in blocks
                                if b["kind"] in ("image", "figrow"))
        # 跨頁段落：上一頁最後一段（略過圖與圖說）夠長、沒有句尾標點；這頁第一段（略過頁首的圖與圖說）
        # 不是習題／例題／小題，而且是第一個區塊或小寫開頭 → 接起來
        is_fig = lambda b: b["kind"] in ("image", "figrow", "fig", "note") or (b["kind"] == "para" and CAPTION.match(b["text"]))
        if seq and blocks:
            last_i = max((k for k, (_, b) in enumerate(seq) if not is_fig(b)), default=None)
            j = next((k for k, b in enumerate(blocks) if not is_fig(b)), None)
            if last_i is not None and j is not None and blocks[j]["kind"] == "para":
                lb, first = seq[last_i][1], blocks[j]["text"]
                if lb["kind"] == "para" and not lb["text"].endswith(TERMINAL) and len(lb["text"]) > 40 \
                        and not NEW_BLOCK.match(first) and (j == 0 or first[:1].islower()):
                    joiner = "" if lb["text"].endswith("-") and first[:1].isalpha() else " "
                    text = (lb["text"][:-1] if joiner == "" else lb["text"]) + joiner + first
                    seq[last_i] = (seq[last_i][0], dict(lb, text=text, page_end=pno + 1))
                    blocks = blocks[:j] + blocks[j + 1:]
        seq += [(pno, b) for b in blocks]

    chapters, cur, notes = [], None, []

    def close():
        if cur is not None and notes:
            cur["items"].append({"type": "heading", "text": "Notes", "level": 3})
            cur["items"] += [{"type": "para", "text": n["mark"] + n["text"], "page": n["page"]} for n in notes]
        notes.clear()

    def open_chapter(title, level, pno):
        nonlocal cur
        close()
        cur = {"title": title, "level": level, "page": pno + 1, "items": []}
        chapters.append(cur)

    manual = {int(c["page"]) - 1: c for c in (cfg.get("pdf", default={}) or {}).get("chapters") or []}
    k = 0
    while k < len(seq):
        pno, b = seq[k]
        if pno in manual and (cur is None or cur.get("_manual") != pno):
            c = manual[pno]
            open_chapter(c["title"], int(c.get("level", 1)), pno)
            cur["_manual"] = pno
        if b["kind"] == "heading" or (b["kind"] == "para" and len(b["text"]) < 20):
            m = CHAPTER.match(b["text"]) or APPENDIX.match(b["text"])
            if m and not manual:
                title = m.group(0)
                if k + 1 < len(seq) and seq[k + 1][1]["kind"] == "heading":
                    title += " " + seq[k + 1][1]["text"]
                    k += 1
                open_chapter(title, 1, pno)
                k += 1
                continue
        if b["kind"] == "heading" and not manual and not SUBSECTION.match(b["text"]) and (
                SECTION.match(b["text"]) or UNNUMBERED_SECTION.match(b["text"])):
            open_chapter(b["text"], 2 if chapters and any(c["level"] == 1 for c in chapters) else 1, pno)
            k += 1
            continue
        if cur is None:
            open_chapter("", 1, pno)
        if b["kind"] == "note":
            notes.append(dict(b, page=pno + 1))
        elif b["kind"] == "image":
            cur["items"].append({"type": "image", "file": b["file"], "page": pno + 1})
        elif b["kind"] == "figrow":
            cur["items"].append({"type": "figrow", "cells": b["cells"], "page": pno + 1})
        elif b["kind"] == "math":
            it = {"type": "math", "text": b["text"], "page": pno + 1}
            if b.get("tag"):
                it["tag"] = b["tag"]
            else:
                report["untagged_math"] += 1
            cur["items"].append(it)
            report["math"] += 1
        else:
            it = {"type": b["kind"], "text": b["text"], "page": pno + 1}
            if b["kind"] == "heading":
                it["level"] = 3                    # 1.1.1 小標、Example 1.3 都是節內小標（第 4 層在 PDF 會排成置中的排印行）
            if b.get("page_end"):
                it["page_end"] = b["page_end"]
            report["inline_math"] += len(re.findall(r"\$(.+?)\$", b["text"]))
            cur["items"].append(it)
        k += 1
    close()
    for c in chapters:
        c.pop("_manual", None)
    return chapters, report
