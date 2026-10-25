"""版面行 → 章節與段落。文字層與 OCR 共用這一層。

PDF 沒有段落、標題、章節，只有「某個位置有一行多大的字」。這裡依序把結構推回來：
  1. 同一基線的片段併成一行（排版工具與 OCR 常把一行切成好幾段）
  2. 全書統計：正文字級、行距、左右邊界（左右頁分開算，對頁的內外邊界不同）
  3. 刪書眉與頁碼：頁面上下緣、跨多頁重複（數字正規化後）或本身就是頁碼的小字行
  4. 註腳：頁底比正文小、以標號開頭的行 → 收到該章結尾的 Notes（跨頁的註腳接回前一則）
  5. 目錄頁、索引頁：大半行以頁碼結尾 → 整頁略過（譯本的目錄由 build 重建，原書頁碼也對不上）
  6. 逐頁切區塊：標題（字級大，或粗體獨立短行）、段落（空行、首行縮排、上一行沒排滿且句子結束）、
     引文（左右都內縮）、清單（項目符號開頭）、插圖
  7. 跨頁段落接回；行尾連字號依全書詞彙決定是排版斷字（去掉）還是複合字（保留）
  8. 切章：手動指定 > PDF 書籤 > 版面（只有標題的頁＝部扉頁；頁首標題接正文＝章首）

字級在文字層是字型大小（pt），在 OCR 是行框高度，單位不同，所以統計依頁面來源分開算。
"""
import re, statistics
from collections import Counter, defaultdict

TERMINAL = tuple(".!?:;\"'”’)]…*–—")      # 行尾是這些字元：句子（或被打斷的話）結束
STRONG_BULLET = re.compile(r"^[•●◦▪▫■□‣⁃∙]\s")
BULLET = re.compile(r"^([•●◦▪▫■□‣⁃∙·]\s|[-–—*]\s|\(?\d{1,2}[.)]\s|\(?[a-z][.)]\s)")
NOTE_MARK = re.compile(r"^\s*([⁰¹²³⁴⁵⁶⁷⁸⁹]+|\d{1,3}[.)]?(?=\s)|\d{1,3}(?=[A-Z‘“])|[*†‡§¶]+)\s*")
ROMAN = re.compile(r"^[ivxlcdm]{1,7}$")
SUP_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
PLAIN_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
# OCR 把上標註腳標號讀成的雜字（'The ship's… 的那個 '）
STRAY_MARK = re.compile(r"^['‘’`\"°^*]+(?=[A-Z])")
# 正文裡的註腳標號（字型內建上標字形抽出來是一般數字）：緊接在字或標點之後、後面是空白或標點
NOTE_REF = re.compile(r"(?<=[^\s\d])(\d{1,3})(?=[\s,.;:!?’”)\]]|$)")


class Stats:
    """一組頁面（同一來源：文字層或 OCR）的版面統計。"""

    def __init__(self, pages, para_indent="auto"):
        rows = [r for p in pages for r in p["rows"]]
        self.ocr = bool(pages) and pages[0]["mode"] == "ocr"
        if self.ocr:
            long_sizes = sorted(r["size"] for r in rows if len(r["text"]) >= 25)
            self.body = statistics.median(long_sizes) if long_sizes else 10.0
        else:
            sizes = Counter()
            for r in rows:
                sizes[round(r["size"] * 2) / 2] += len(r["text"])
            self.body = sizes.most_common(1)[0][0] if sizes else 10.0
        # 容差：OCR 的字級是估的、座標有抖動，放寬
        self.tol_body = 0.25 if self.ocr else 0.1          # 算不算正文字級
        self.tol_size = 0.3 if self.ocr else 0.12          # 字級變化多大才算換區塊
        self.tol_edge = (0.8 if self.ocr else 0.35) * self.body   # 貼齊邊界的誤差
        self.tol_indent = (0.5 if self.ocr else 0.3) * self.body  # 縮排量的誤差
        body_rows = lambda parity: [r for p in pages if p["no"] % 2 == parity for r in p["rows"]
                                    if self.is_body(r) and len(r["text"]) > 20]
        self.left, self.right = {}, {}
        for parity in (0, 1):
            br = body_rows(parity) or body_rows(1 - parity) or rows
            xs = Counter(round(r["x0"]) for r in br)
            self.left[parity] = xs.most_common(1)[0][0] if xs else 0
            x1s = sorted(r["x1"] for r in br) or [0]
            self.right[parity] = x1s[int(len(x1s) * 0.9)]
        # 掃描頁的版心逐頁位移（掃描時書本放的位置不同），全書一個左邊界會讓縮排判斷失準：逐頁另算
        self.page_margins = {p["no"]: m for p in pages if self.ocr for m in [self._page_margins(p)] if m}
        # 段首縮排量：正文行相對左邊界的縮排，最常見的那個值
        indents = Counter()
        for p in pages:
            for r in p["rows"]:
                d = r["x0"] - self.margins(p)[0]
                if self.is_body(r) and 0.3 * self.body < d < 5 * self.body:
                    indents[round(d * 2) / 2] += 1
        n_body = sum(self.is_body(r) for r in rows)
        # 縮排的行要夠多才算這本書用首行縮排（引文、清單的內縮不算）
        self.para_indent = indents.most_common(1)[0][0] if sum(indents.values()) >= max(5, 0.03 * n_body) else None
        if para_indent != "auto":                       # pdf.para_indent：false＝全書沒有首行縮排；數字＝指定縮排量（點）
            self.para_indent = float(para_indent) if para_indent else None
        # 左右對齊：長的正文行大多排到右邊界
        long_rows = [(p, r) for p in pages for r in p["rows"] if self.is_body(r) and len(r["text"]) > 30]
        full = sum(self.margins(p)[1] - r["x1"] < self.tol_edge for p, r in long_rows)
        self.justified = bool(long_rows) and full / len(long_rows) > 0.5
        deltas = []
        for p in pages:
            prev = None
            for r in p["rows"]:
                if self.is_body(r):
                    if prev is not None and 0 < r["y1"] - prev["y1"] < 3.5 * self.body:
                        deltas.append(r["y1"] - prev["y1"])
                    prev = r
        self.pitch = statistics.median(deltas) if deltas else self.body * 1.2
        # 行距超過 gap_para 就是段落間的空白。行距分布有第二個峰（段距排版）就取兩峰間的谷底
        self.gap_para = self._valley([d / self.pitch for d in deltas]) * self.pitch
        # 段距排版：段落之間空一段（行距大於 gap_para 的比例夠高），靠空白就能分段
        self.spaced = bool(deltas) and sum(d > self.gap_para for d in deltas) >= 0.05 * len(deltas)
        lasts = sorted(p["rows"][-1]["y1"] for p in pages if p["rows"])
        self.bottom = lasts[int(len(lasts) * 0.9)] if lasts else 0      # 版心底部：頁面最後一行通常的位置

    def _valley(self, ratios):
        """行距分布若有第二個峰（段落間空白），取兩峰之間最稀疏處當門檻（0.02 細格、三格平滑）。"""
        default = 1.35 if self.ocr else 1.25
        coarse = Counter(round(r * 20) / 20 for r in ratios)
        second = [(c, b) for b, c in coarse.items() if 1.2 <= b <= 2.2]
        if not second or max(second)[0] < 0.05 * len(ratios):
            return default
        peak = max(second)[1]
        fine = Counter(round(r * 50) for r in ratios)                   # 0.02 一格
        lo, hi = 53, int(round(peak * 50)) - 1                           # 1.06 到第二峰之前
        if hi <= lo:
            return default
        smooth = {k: fine.get(k - 1, 0) + fine.get(k, 0) + fine.get(k + 1, 0) for k in range(lo, hi + 1)}
        low = min(smooth.values())
        return statistics.median(k for k, v in smooth.items() if v == low) / 50

    def is_body(self, r):
        return abs(r["size"] - self.body) <= self.tol_body * self.body

    def _page_margins(self, page):
        """這一頁正文行的左右邊界：最左邊、有四分之一以上的行貼齊的位置當左邊界（縮排行、引文在它右邊）。"""
        rows = [r for r in page["rows"] if self.is_body(r) and len(r["text"]) > 20]
        if len(rows) < 6:
            return None
        tol = 0.3 * self.body
        for x in sorted(r["x0"] for r in rows):
            near = [r["x0"] for r in rows if abs(r["x0"] - x) < tol]
            if len(near) >= max(3, 0.25 * len(rows)):
                x1s = sorted(r["x1"] for r in rows)
                # 右緣：排滿的行最密集的那一群（第 90 百分位會被偶爾伸出去的行拉偏）。
                # 排滿到右緣的行要夠多：置中排的書名頁、長短不一的清單頁量出來的邊界不對，照全書的
                best = max(x1s, key=lambda y: sum(abs(x - y) < self.tol_edge for x in x1s))
                cluster = [x for x in x1s if abs(x - best) < self.tol_edge]
                if len(cluster) < 0.5 * len(x1s):
                    return None
                return statistics.median(near), statistics.median(cluster)
        return None

    def margins(self, page):
        m = self.page_margins.get(page["no"]) if hasattr(self, "page_margins") else None
        return m or (self.left[page["no"] % 2], self.right[page["no"] % 2])


# ── 0. 掃描歪斜 ──────────────────────────────────────────────────────
def deskew(p):
    """掃描頁略微旋轉時，行的左緣沿著頁面往下漂移，下半頁的行看起來像首行縮排。
    用長行的左緣對 y 做直線擬合（反覆剔除縮排行），把每行的左右座標拉回同一條垂直線。"""
    pts = [(r["y1"], r["x0"]) for r in p["rows"] if len(r["text"]) > 40]
    if len(pts) < 8:
        return
    med = statistics.median(x for _, x in pts)
    keep = [(y, x) for y, x in pts if x < med + 4] or pts     # 先只看貼左緣的行，縮排行、置中標題不拿來擬合
    for _ in range(5):
        n = len(keep)
        my, mx = sum(y for y, _ in keep) / n, sum(x for _, x in keep) / n
        vy = sum((y - my) ** 2 for y, _ in keep)
        if vy == 0:
            return
        b = sum((y - my) * (x - mx) for y, x in keep) / vy
        a = mx - b * my
        keep = [(y, x) for y, x in pts if abs(x - (a + b * y)) < 3]
        if len(keep) < 6:
            return
    span = max(y for y, _ in pts) - min(y for y, _ in pts)
    if abs(b) * span < 2 or abs(b) > 0.05:          # 漂移不到兩點不必校；太大多半是擬合錯了
        return
    ym = (max(y for y, _ in pts) + min(y for y, _ in pts)) / 2
    for r in p["rows"]:
        d = b * (r["y1"] - ym)
        r["x0"] -= d
        r["x1"] -= d


# ── 1. 同一基線併行 ──────────────────────────────────────────────────
def merge_rows(lines, page_w, columns=1):
    if columns == 2:
        mid = page_w / 2
        left = [l for l in lines if l["x0"] < mid]
        right = [l for l in lines if l["x0"] >= mid]
        return _merge(left) + _merge(right)
    return _merge(lines)


def _merge(lines):
    rows = []
    for l in sorted(lines, key=lambda l: (l["y1"], l["x0"])):
        for r in reversed(rows[-4:]):
            tol = 0.4 * min(l["size"], r["size"])
            if abs(l["y1"] - r["y1"]) < tol and not any(_overlap_x(l, q) for q in r["parts"]):
                r["parts"].append(l)
                break
        else:
            rows.append({"parts": [l], "y1": l["y1"], "size": l["size"]})
    out = []
    for r in rows:
        parts = sorted(r["parts"], key=lambda l: l["x0"])
        text = parts[0]["text"]
        for a, b in zip(parts, parts[1:]):
            gap = b["x0"] - a["x1"]
            text += ("" if gap < 0.15 * b["size"] else " ") + b["text"]
        n = sum(len(p["text"]) for p in parts)
        out.append({"x0": parts[0]["x0"], "x1": max(p["x1"] for p in parts),
                    "y0": min(p["y0"] for p in parts), "y1": max(p["y1"] for p in parts),
                    "text": text, "size": sum(p["size"] * len(p["text"]) for p in parts) / n,
                    "bold": all(p.get("bold") for p in parts), "italic": all(p.get("italic") for p in parts),
                    "sup_start": parts[0].get("sup_start", False),
                    "size_by_height": any(p.get("size_by_height") for p in parts),
                    "conf": min((p["conf"] for p in parts if p.get("conf") is not None), default=None)})
    return sorted(out, key=lambda r: (r["y0"], r["x0"]))


def _overlap_x(a, b):
    return min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) > 0.3 * min(a["x1"] - a["x0"], b["x1"] - b["x0"])


# ── 3. 書眉與頁碼 ─────────────────────────────────────────────────────
def _key(text):
    words = []
    for w in re.findall(r"[^\W_]+|#", text.lower()):
        words.append("#" if w.isdigit() or ROMAN.match(w) else w)
    return " ".join(words)


def is_page_number(text):
    t = text.strip().lower()
    return bool(re.fullmatch(r"[\[(\-–—\s]*(page\s+)?(\d{1,4}|[ivxlcdm]{1,7})[\])\-–—\s]*", t))


def strip_headers_footers(pages, stats_of):
    cands = []
    for p in pages:
        rows, h, st = p["rows"], p["h"], stats_of(p)
        top_y, bottom_y = 0.13 * h, 0.87 * h
        if st.ocr and rows:
            # 掃描頁常在紙上留一大片白邊，書眉離紙緣很遠：改從這一頁的版面範圍（文字與插圖）量；
            # 半頁空白的章末頁照半頁算，圖版頁的注記才不會落進書眉帶
            y0 = min([rows[0]["y0"]] + [im["y0"] for im in p["images"]])
            y1 = max([r["y1"] for r in rows] + [im["y1"] for im in p["images"]])
            span = max(y1 - y0, 0.5 * h)
            top_y, bottom_y = max(top_y, y0 + 0.13 * span), min(bottom_y, y1 - 0.13 * span)
        top = [r for r in rows[:3] if r["y1"] < top_y]
        bottom = [r for r in rows[-3:] if r["y0"] > bottom_y]
        if st.ocr and rows and is_page_number(rows[-1]["text"]) and rows[-1] not in bottom:
            bottom.append(rows[-1])                 # 圖版頁只剩注記與頁碼，文字範圍量不出頁緣
        for band, rs in (("top", top), ("bottom", bottom)):
            for r in rs:
                if r["size"] <= st.body * 1.15:      # 大字是標題，不會是書眉
                    cands.append((p, r, band, _key(r["text"])))
    pages_with = defaultdict(set)
    for p, r, band, key in cands:
        pages_with[(band, key)].add(p["no"])
    need = max(3, round(0.03 * len(pages)))
    # 書眉帶頁碼（「36 Theory」「The Theory of Reflexivity 35」）：短章只有幾頁，出現三頁就算
    with_number = lambda key: key != "#" and (key.startswith("# ") or key.endswith(" #"))
    removed = Counter()
    printed = {}                                # PDF 頁 → 印在頁上的頁碼（從確定是書眉、頁碼的行讀出）
    removed_keys = set()
    for p, r, band, key in cands:
        arabic = with_number(key) and _edge_number(r["text"]) is not None   # 「PART I」的羅馬數字不算頁碼
        if is_page_number(r["text"]) or len(pages_with[(band, key)]) >= (3 if arabic else need):
            if r in p["rows"]:
                p["rows"].remove(r)
                removed[re.sub(r"\d+", "#", r["text"]) if not is_page_number(r["text"]) else "（頁碼）"] += 1
                removed_keys.add(key)
                n = _edge_number(r["text"])
                if n is not None:
                    printed[p["no"]] = n
    # 書眉有 OCR 錯字、或短章只出現一兩次：邊上的數字和前後頁的頁碼接得上，也是書眉；
    # 頁碼印在頁底的頁，書眉只剩文字（「Foreword」）：和已知書眉去掉頁碼後相同，也是書眉
    for p, r, band, key in cands:
        n = _edge_number(r["text"])
        if r in p["rows"] and n is not None and len(r["text"]) <= 60 and any(
                printed.get(p["no"] + d) == n + d for d in (-3, -2, -1, 1, 2, 3)):
            p["rows"].remove(r)
            removed[re.sub(r"\d+", "#", r["text"])] += 1
            removed_keys.add(key)
    names = {k.replace("#", "").strip() for k in removed_keys if "#" in k} - {""}
    for p, r, band, key in cands:
        if r in p["rows"] and band == "top" and key in names:
            p["rows"].remove(r)
            removed[r["text"]] += 1
    return removed


def _edge_number(text):
    m = re.fullmatch(r"\s*(\d{1,3})\b.*|.*\D(\d{1,3})\s*", text)
    return int(m.group(1) or m.group(2)) if m else None


# ── 4. 註腳 ──────────────────────────────────────────────────────────
def take_footnotes(pages, stats_of, marks=None):
    """marks：只認這些字元開頭的註腳（例 "*†"）；頁底的編號清單、圖片出處、公式就不會被當成註腳。"""
    notes, last_page_had = [], False
    start = _note_start if not marks else \
        lambda r: m if (m := _note_start(r)) and m.group(1).strip()[:1] in marks else None
    for p in pages:
        if p.get("no_notes"):                   # pdf.no_footnote_pages：頁底的小字是表注、出處，不是註腳
            last_page_had = False
            continue
        rows, st = p["rows"], stats_of(p)
        small = lambda r: st.body * 0.5 < r["size"] < st.body * 0.9
        i = len(rows)
        while i > 0 and (small(rows[i - 1]) or (          # 註腳最後一行短，字級估不準，看上一行
                len(rows[i - 1]["text"]) < 25 and i >= 2 and small(rows[i - 2])
                and rows[i - 1]["y1"] - rows[i - 2]["y1"] < 1.3 * st.pitch)):
            i -= 1
        # 註腳上方緊接小字的引文時，小字區會一路往上延伸：從頁底往上找第一個大空白（註腳線）當起點
        for j in range(len(rows) - 1, i, -1):
            if rows[j]["y1"] - rows[j - 1]["y1"] > 1.4 * st.pitch:
                if j > i and rows[i]["y0"] <= 0.5 * p["h"] < rows[j]["y0"]:
                    i = j
                break
        gap = 1.4
        if marks:
            # 指定了註腳標記：OCR 估的字級會被撐開的行拉偏，改從標記找——頁面下半、標記開頭、上方空一行、以下多半是小字
            for j in range(1, len(rows)):
                rest = rows[j:]
                if rows[j]["text"].strip()[:1] in marks and rows[j]["y0"] > 0.5 * p["h"] \
                        and rows[j]["y1"] - rows[j - 1]["y1"] > 1.2 * st.pitch \
                        and 2 * sum(r["size"] < 0.95 * st.body for r in rest) > len(rest):
                    i, gap = j, 1.2
                    break
        zone = rows[i:]
        # 註腳區通常在下半頁；文字層的頁面註腳很長時（編號開頭、或接續上一頁的註腳）可以占到頁面一半以上。
        # OCR 頁的字級是估的，放寬會把正文尾巴誤吃成註腳，維持原規則
        top = 0.25 if zone and not st.ocr and (start(zone[0]) or last_page_had) else 0.5
        ok = (zone and i > 0 and zone[0]["y0"] > top * p["h"]
              and zone[0]["y1"] - rows[i - 1]["y1"] > gap * st.pitch
              and (start(zone[0]) or last_page_had or (st.ocr and not marks)))
        last_page_had = False
        if not ok:
            continue
        for r in zone:
            m = start(r)
            stray = st.ocr and not m and STRAY_MARK.match(r["text"])
            if m or stray or not notes or notes[-1]["page"] < p["no"] - 1:
                mark = (m.group(1) if m else "").strip().rstrip(".)")
                text = r["text"][m.end():] if m else r["text"][stray.end():] if stray else r["text"]
                notes.append({"page": p["no"], "mark": mark.translate(SUP_DIGITS), "lines": [text]})
            else:
                notes[-1]["lines"].append(r["text"])
        p["notes_top"] = zone[0]["y0"]
        del rows[i:]
        last_page_had = True
        on_page = {n["mark"].translate(PLAIN_DIGITS) for n in notes if n["page"] == p["no"]}
        for r in rows:
            r["text"] = NOTE_REF.sub(lambda m: m.group(1).translate(SUP_DIGITS) if m.group(1) in on_page
                                     else m.group(0), r["text"])
    return notes


def _note_start(r):
    m = NOTE_MARK.match(r["text"])
    if m and (r.get("sup_start") or not m.group(1).isdigit() or r["text"][m.end():m.end() + 1].isalpha()):
        return m
    return None


# ── 5. 目錄頁、索引頁 ────────────────────────────────────────────────
TOC_LINE = re.compile(r"(\.\s*){3,}\s*\d{1,4}$|\s\d{1,4}$|\d{1,4}\s*[–-]\s*\d{1,4}$|,\s*\d{1,4}$")


def is_toc_like(rows):
    rows = [r for r in rows if len(r["text"]) >= 2]
    if len(rows) < 5:
        return False
    return sum(bool(TOC_LINE.search(r["text"])) for r in rows) >= 0.5 * len(rows)


# ── 6. 區塊 ──────────────────────────────────────────────────────────
FIGURE_TITLE = re.compile(r"^(figure|table|fig\.|chart|diagram)\b", re.I)


def _alnum(t):
    return re.sub(r"[^0-9a-z]", "", t.lower())


def forced_heading_rows(rows, headings):
    """pdf.headings：字層沒有粗體、字級資訊的書，章內小標由設定列出。回傳哪幾行（索引）是小標。
    小標可以折成兩行；上標註腳標號、標點、大小寫不影響比對。"""
    want = {_alnum(h) for h in headings or [] if _alnum(h)}
    out = set()
    if not want:
        return out
    for i in range(len(rows)):
        acc = ""
        for j in range(i, min(i + 3, len(rows))):
            acc += _alnum(rows[j]["text"])
            if acc in want:
                out.update(range(i, j + 1))
                break
            if not any(w.startswith(acc) for w in want):
                break
    return out


def page_blocks(p, st, headings=None):
    rows = p["rows"]
    forced = forced_heading_rows(rows, headings)
    left, right = st.margins(p)
    width = max(right - left, 1)
    # 懸掛縮排頁（pdf.hanging_pages）：條目頂格、續行內縮；每頁掃描位移不同，頂格位置取這頁最靠左的長行
    hang_left = min((r["x0"] for r in rows if len(r["text"]) >= 10), default=left) if p.get("hanging") else left
    blocks = []
    for i, r in enumerate(rows):
        prev = rows[i - 1] if i else None
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        alone = lambda k: (prev is None or r["y1"] - prev["y1"] > k * st.pitch) \
            and (nxt is None or nxt["y1"] - r["y1"] > k * st.pitch)
        above_gap = lambda k: prev is None or r["y1"] - prev["y1"] > k * st.pitch
        if st.ocr:
            # OCR 的字級是估的：大字還要字少、上下都空一段才算標題；
            # 置中、字少、上下空一大段的也算（章首的「II」字級估不出來）
            above = prev is None or r["y1"] - prev["y1"] > 1.8 * st.pitch
            below = nxt is None or nxt["y1"] - r["y1"] > 1.0 * st.pitch
            head = len(r["text"]) <= 40 and ((r["size"] >= st.body * 1.35 and alone(1.8))
                                            or (is_centered(r, left, right, st) and alone(2.5))
                                            or (above and below and CHAPTER_PAT.match(r["text"])
                                                and not r["text"].endswith(TERMINAL)))
            # 章內小標：短、大寫字母開頭、句子沒結束（可帶註腳星號）、上下都空一段；全大寫的（日記日期）上方空一段就算
            t = r["text"].rstrip(" *†")
            caps = t.upper() == t and re.search(r"[A-Z]{3,}", t) is not None
            minor = not head and (len(t) <= 70 and len(t.split()) <= 10 and re.match(r"[A-Z][A-Za-z'’.]", t) is not None
                                  and not t.endswith(TERMINAL + (",",)) and "→" not in t
                                  and r["x1"] < right - 2.0 * st.body and (alone(1.5) or (caps and above_gap(1.4))))
            head = head or minor
        else:
            minor = False
            head = r["size"] >= st.body * 1.18 or (
                r["bold"] and len(r["text"]) < 100 and not r["text"].endswith((".", ","))
                and (prev is None or r["y0"] - prev["y1"] > 0.6 * st.pitch)
                and (nxt is None or nxt["y0"] - r["y1"] > 0.5 * st.pitch)) or i in forced
        b = blocks[-1] if blocks else None
        if head:
            if b and b["type"] == "heading" and abs(b["size"] - r["size"]) < 0.08 * r["size"] \
                    and r["y1"] - b["rows"][-1]["y1"] < 2.2 * r["size"]:
                b["rows"].append(r)
            else:
                is_forced = i in forced
                blocks.append({"type": "heading", "rows": [r], "size": r["size"], "minor": minor, "forced": is_forced,
                               "level": (4 if FIGURE_TITLE.match(r["text"]) else 3) if is_forced else
                               3 if r["size"] >= st.body * 1.18 and not minor else 4})
            continue
        # 懸掛縮排的條目（「1. Karl R. Popper, …」下一行內縮）：條目裡、上一行排滿、這行內縮一到三個字 → 同一條
        if b and b["type"] == "para" and b.get("bullet") and not BULLET.match(r["text"]) \
                and 0.5 * st.body < r["x0"] - b["rows"][0]["x0"] < 3 * st.body \
                and b["rows"][-1]["x1"] > right - 2.0 * st.body and r["y1"] - b["rows"][-1]["y1"] < st.gap_para:
            b["rows"].append(r)
            continue
        centered = is_centered(r, left, right, st)
        strong = STRONG_BULLET.match(r["text"]) is not None or (   # 條目裡、和條目左緣對齊的編號：下一條
            b is not None and b["type"] == "para" and b.get("bullet") and BULLET.match(r["text"]) is not None
            and abs(r["x0"] - b["rows"][0]["x0"]) < st.tol_indent)
        if p.get("hanging") and b is not None and b["type"] == "para" and not strong:
            new = r["x0"] - hang_left < 0.5 * st.body       # 懸掛縮排的書目：頂格才是新條目，內縮的是上一條的續行
        else:
            new = b is None or b["type"] != "para" or strong or _starts_para(r, b["rows"][-1], st, left, right,
                                                                               width, centered)
        bullet = strong or (new and BULLET.match(r["text"]) is not None)
        if new:
            blocks.append({"type": "para", "rows": [r], "size": r["size"], "bullet": bullet,
                           "centered": centered})
        else:
            b["rows"].append(r)
    for img in p["images"]:
        blocks.append({"type": "image", "file": img["file"], "y0": img["y0"], "rows": []})
    blocks.sort(key=lambda b: b["rows"][0]["y0"] if b["rows"] else b["y0"])
    for b in blocks:
        if b["type"] == "para":
            b["type"] = _para_kind(b, st, left, right)
        b["page"] = p["no"]
    return blocks


def is_centered(r, left, right, st):
    """左右留白都有、而且大致對稱。"""
    gl, gr = r["x0"] - left, right - r["x1"]
    return gl > st.tol_edge and gr > st.tol_edge and abs(gl - gr) < max(st.tol_edge, 0.15 * (gl + gr))


def _starts_para(r, prev, st, left, right, width, centered):
    if r["y1"] - prev["y1"] > st.gap_para:                          # 段落間的空白
        # 上一行排滿、句子沒結束（行尾斷字、句中）：字框高度估錯讓行距看起來大，其實是同一段
        cont = st.justified and not st.spaced and prev["x1"] > right - 2.0 * st.body \
            and (prev["x0"] - left < st.tol_edge or (st.para_indent is not None
                                                     and abs(prev["x0"] - left - st.para_indent) < st.tol_indent)) \
            and r["x0"] - left < st.tol_edge \
            and not prev["text"].endswith(TERMINAL) and r["y1"] - prev["y1"] < 2.5 * st.pitch
        if not cont:
            return True
    if abs(r["size"] - prev["size"]) > st.tol_size * st.body \
            and not (r.get("size_by_height") or prev.get("size_by_height")):
        return True
    indent = r["x0"] - left
    prev_indent = prev["x0"] - left
    # 上一行沒排滿：左右對齊的書看有沒有到右邊界；右邊參差的書每行本來就長短不一，看是不是明顯短
    prev_short = prev["x1"] < right - 2.0 * st.body if st.justified else prev["x1"] - left < 0.7 * width
    # 左右對齊的書裡，置中段落換行的前幾行都排滿，只有最後一行置中：
    # 上一行置中 → 那段已經結束；這一行置中 → 上一行排滿才是同一段
    if st.para_indent is not None and abs(indent - st.para_indent) < st.tol_indent and st.is_body(r):
        return True                                                 # 縮排量等於段首縮排：新段
    # 左緣對齊的內縮區塊（引文、詩）：右邊界是區塊自己的，只在句子結束且明顯短時切段
    if indent > st.body and prev_indent > st.body and abs(indent - prev_indent) < 0.3 * st.body:
        block_w = max(right - prev["x0"], 1)
        return prev["text"].endswith(TERMINAL) and prev["x1"] - prev["x0"] < 0.6 * block_w
    if st.justified and is_centered(prev, left, right, st):
        return True
    if centered:
        full = (prev["x0"] - left < st.tol_edge and right - prev["x1"] < st.tol_edge) or (
            not st.justified and is_centered(prev, left, right, st) and prev["x1"] - prev["x0"] >= 0.85 * width)
        return not full
    if 0.5 * st.body < indent < 6 * st.body and abs(indent - prev_indent) > 0.3 * st.body \
            and (prev_short or prev_indent < 0.5 * st.body):
        return True                                                 # 首行縮排
    if st.spaced and not st.justified:
        return False            # 段距排版、右邊參差：前面的空白規則已經分好段，短行不代表段尾
    if prev_short and (prev["text"].endswith(TERMINAL) or prev["x1"] - left < 0.7 * width):
        return True                                                 # 上一行沒排滿且句子結束
    return False


def _para_kind(b, st, left, right):
    rows = b["rows"]
    if b.get("bullet"):
        return "li"
    # 引文：每一行都內縮、左緣對齊（首行可以多縮一點），右邊也內縮。置中的行左緣會隨行長變動，不算
    rest = rows[1:]
    if rest and all(r["x0"] - left > 1.0 * st.body for r in rows) \
            and all(right - r["x1"] > 0.8 * st.body for r in rows[:-1]) \
            and max(r["x0"] for r in rest) - min(r["x0"] for r in rest) < 0.5 * st.body \
            and rows[0]["x0"] >= min(r["x0"] for r in rest) - 0.3 * st.body:
        return "quote"
    return "para"


# ── 7. 接行與斷字 ─────────────────────────────────────────────────────
def vocabulary(pages):
    """全書詞彙（不含每行頭尾可能被斷開的字），用來判斷行尾連字號要不要保留。"""
    vocab = Counter()
    for p in pages:
        for r in p["rows"]:
            words = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", r["text"])
            for w in words[1:-1]:
                vocab[w.lower()] += 1
    return vocab


def join_lines(texts, vocab, hyphen_is_real=False):
    """接行。hyphen_is_real：這份 PDF 的排版斷字用軟連字號，行尾的一般連字號就是字本身的。"""
    out = texts[0]
    for nxt in texts[1:]:
        if not nxt:
            continue
        if out.endswith("­"):                          # 軟連字號：一定是排版斷字
            out = out[:-1] + nxt
            continue
        m = re.search(r"([^\W\d_]+)[-‐]$", out)
        if m and nxt[:1].isalpha():
            if hyphen_is_real or nxt[:1].isupper() or _keep_hyphen(m.group(1), nxt, vocab):
                out += nxt                                  # 複合字（second-hand、Anglo-Saxon）
            else:
                out = out[:-1] + nxt                        # 排版斷字
        elif out.endswith("—") or nxt.startswith("—"):     # 破折號前後不加空白
            out += nxt
        else:
            out += " " + nxt
    return out.replace("\u00ad", "")


_WORDS = None


def _dictionary():
    """系統英文字典（macOS／Linux 的 /usr/share/dict/words）；沒有就只靠全書詞彙判斷。"""
    global _WORDS
    if _WORDS is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as f:
                _WORDS = {w.strip().lower() for w in f}
        except OSError:
            _WORDS = set()
    return _WORDS


PREFIXES = {"semi", "non", "anti", "pre", "re", "co", "ex", "multi", "sub", "inter", "self", "post", "pro",
            "counter", "mid", "mis", "un", "bi", "tri", "ultra", "neo", "pseudo", "quasi", "de", "dis", "extra"}


def _is_word(w, vocab):
    w = w.lower()
    if w in PREFIXES:
        return True
    words = _dictionary()
    stems = {w, re.sub(r"(es|s|ed|ing|ly)$", "", w), re.sub(r"(s|ed|ing|ly)$", "", w)}
    return vocab.get(w, 0) > 0 or any(s in words for s in stems if len(s) > 1)


def _keep_hyphen(a, nxt, vocab):
    """行尾連字號是複合字本身的（保留）還是排版斷字（去掉）：先看全書其他地方怎麼寫，再查字典。"""
    b = re.match(r"[^\W\d_]+", nxt).group(0)
    hy, joined = f"{a}-{b}".lower(), f"{a}{b}".lower()
    if vocab.get(hy, 0) != vocab.get(joined, 0):
        return vocab.get(hy, 0) > vocab.get(joined, 0)
    if _is_word(joined, vocab):
        return False
    return len(a) > 1 and len(b) > 1 and _is_word(a, vocab) and _is_word(b, vocab)


def _hyphenates(pages, mode, vocab):
    """這份 PDF 有沒有開斷字：行尾連字號裡只要有拆開的兩半都不是單字的（mut-tering），就是有。
    一個都沒有（只剩 second-hand 這種）就是沒開斷字，行尾的連字號都是字本身的。"""
    rows = [r["text"] for p in pages if p["mode"] == mode for r in p["rows"]]
    ends, syllable = 0, 0
    for a, b in zip(rows, rows[1:]):
        m = re.search(r"([A-Za-z]+)-$", a)
        n = re.match(r"[a-z]+", b)
        if m and n:
            ends += 1
            syllable += not (_is_word(m.group(1), vocab) and _is_word(n.group(0), vocab))
    return ends < 3 or syllable >= max(2, 0.2 * ends)


def continue_across_pages(blocks_by_page, stats_of, pages):
    """前一頁最後一段沒結束、下一頁第一行也沒縮排 → 同一段。整頁都是續段時會一路接下去。"""
    last, last_page = None, None
    for p in pages:
        bs = blocks_by_page.get(p["no"]) or []
        if not bs:
            continue
        # 頁首是插圖（日誌表、圖表）與小字圖說時，續段在它們後面：跳過去接，插圖留在接好的段落之後
        st = stats_of(p)
        k = 0
        while k < len(bs) and (bs[k]["type"] == "image" or (
                bs[k]["type"] == "heading" and bs[k].get("forced") and k + 1 < len(bs) and bs[k + 1]["type"] == "image") or (
                bs[k]["type"] == "para" and bs[k]["rows"] and not st.is_body(bs[k]["rows"][0])
                and bs[k]["rows"][0]["size"] < st.body and k > 0)):   # k>0：前面跳過的是圖（連同圖名、表注、出處，可接連幾行小字）
            k += 1
        if k == len(bs):            # 整頁只有圖與它的圖名、表注：沒有續段，上一頁的段落照舊往後傳
            first = None
        else:
            first = bs[k]
        if first is not None and last is not None and last["type"] in ("para", "quote") \
                and first["type"] == last["type"] and last["rows"] and first["rows"]:
            st = stats_of(p)
            left, _ = st.margins(p)
            left_a, right_a = stats_of(last_page).margins(last_page)
            tail, head = last["rows"][-1], first["rows"][0]
            indented = head["x0"] - left > 0.5 * st.body
            ended = tail["text"].endswith(TERMINAL)
            if st.justified:        # 左右對齊：續段的段尾一定排滿
                full = tail["x1"] >= right_a - 2.0 * st.body
                nearly = tail["x1"] - left_a >= 0.8 * (right_a - left_a)
                unfinished = full or (nearly and not ended)
            else:                   # 右邊參差：續段的段尾是排到頁底的長行，而且句子沒結束
                # 段距排版的頁底會浮動一行加一段距；有註腳的頁，正文排到註腳區上方為止
                notes_top = last_page.get("notes_top")
                at_bottom = tail["y1"] >= stats_of(last_page).bottom - 2 * st.pitch or (
                    notes_top is not None and tail["y1"] >= notes_top - 3 * st.pitch)
                unfinished = not ended and at_bottom and tail["x1"] - left_a >= 0.6 * (right_a - left_a)
            # 上一段沒有以句號之類收尾、下一頁頁首（不縮排）又以小寫字或引號後的小寫字開頭：句子還沒完，一定是續段
            unfinished = unfinished or (not ended and head["text"].lstrip("'‘\"“(").startswith(tuple("abcdefghijklmnopqrstuvwxyz")))
            if p.get("hanging") and last_page.get("hanging"):
                # 懸掛縮排的書目：頁首內縮的行是上一頁最後一條的續行，頂格的才是新條目
                hang_left = min((r["x0"] for r in p["rows"] if len(r["text"]) >= 10), default=left)
                if head["x0"] - hang_left >= 0.5 * st.body:
                    last["rows"].extend(first["rows"])
                    bs.pop(k)
            elif not indented and unfinished:
                last["rows"].extend(first["rows"])
                bs.pop(k)
        if bs:
            st = stats_of(p)
            furniture = lambda b: b["type"] == "image" or (b["type"] == "heading" and b.get("forced")) or (
                b["type"] == "para" and b["rows"] and not st.is_body(b["rows"][0]) and b["rows"][0]["size"] < st.body)
            texts = [b for b in bs if b["type"] != "image"]
            if any(b.get("forced") for b in bs) and any(b["type"] == "image" for b in bs) \
                    and all(furniture(b) for b in bs):
                pass                # 整頁只有（pdf.headings 指定的）圖名、圖、表注、出處：上一頁的段落（last）照舊傳下去，續段在圖之後
            elif bs[-1]["type"] == "image":                 # 頁尾插圖（連同它的圖名）之前的段落可能續到下一頁
                while texts and texts[-1].get("forced"):
                    texts.pop()
                last, last_page = (texts[-1] if texts else bs[-1]), p
            else:
                last, last_page = bs[-1], p     # 整頁被接走時，段尾那一行也在這頁


# ── 8. 切章 ──────────────────────────────────────────────────────────
def _norm(t):
    return re.sub(r"[^0-9a-z]", "", t.lower())


def split_chapters(blocks, pages, outline, opts, book_title, inferred, report):
    """回傳 (章節, 切章依據)。讀不到章號而推定的章名記進 inferred。"""
    manual = opts.get("chapters") or []
    if manual:
        marks = [(int(m.get("level", 1)), str(m.get("title") or ""), int(m["page"]) - 1) for m in manual]
        return _split_by_marks(blocks, marks, book_title, manual=True), "system_prompts.yaml 的 pdf.chapters"
    depth = int(opts.get("chapter_levels", 2))
    marks = [(lvl, title, page - 1) for lvl, title, page, *_ in outline if lvl <= depth and page >= 1]
    if opts.get("use_outline", True) and marks:
        return _split_by_marks(blocks, marks, book_title), f"PDF 書籤（{len(marks)} 筆）"
    return _split_by_layout(blocks, pages, book_title, inferred, opts, report), "版面（沒有書籤）"


def _split_by_marks(blocks, marks, book_title, manual=False):
    """manual（pdf.chapters）：章名一律用設定的；章首頁開頭只是重複章名的幾行（章號、分成兩行的大字章名）拿掉。"""
    starts = {}
    used = set()
    for lvl, title, page in marks:
        cands = [i for i, b in enumerate(blocks) if b["page"] == page and i not in used]
        if not cands:
            cands = [i for i, b in enumerate(blocks) if b["page"] > page and i not in used][:1]
        if not cands:
            continue
        if manual:
            i, n = cands[0], 0
            while i + n < len(blocks) and blocks[i + n]["page"] == page and _echoes(blocks[i + n], title):
                n += 1
            used.add(i)
            starts[i] = (min(lvl, 2), title.strip(), n)
            continue
        want = _norm(title)
        hit = next((i for i in cands if blocks[i]["type"] == "heading" and want and _norm(_text(blocks[i]))
                    and (_norm(_text(blocks[i])).startswith(want) or want.startswith(_norm(_text(blocks[i]))))),
                   None)
        i = hit if hit is not None else cands[0]
        used.add(i)
        starts[i] = (min(lvl, 2), _text(blocks[i]) if hit is not None else title.strip(), int(hit is not None))
    return _cut(blocks, starts, book_title)


def _echoes(b, title):
    """這一塊只是在重複章名：每個字都出現在章名裡（章號、羅馬數字也算）。"""
    if b["type"] not in ("heading", "para") or len(_text(b)) > 80:
        return False
    words = re.findall(r"[a-z0-9]+", _text(b).lower())
    have = set(re.findall(r"[a-z0-9]+", title.lower()))
    return bool(words) and all(w in have or w.isdigit() or ROMAN.match(w) for w in words)


CHAPTER_PAT = re.compile(r"^(chapter|part|book)\b.{0,30}$|^[1lI|IVXLC]{1,6}\.?$|^\d{1,3}\.?$", re.I)
PART_PAT = re.compile(r"^(part|book)\b", re.I)


def _size_key(b):
    return round(b["size"] * 2) / 2


def _heading_levels(blocks, info, by_page, title_pages, opts):
    """文字層依字級切章：同一字級反覆出現、而且不是緊接在另一個標題後面（那是副標）的，當章節標題。
    字級大的是第一層；有部扉頁時部名是第一層，章名是第二層。pdf.heading_sizes 可以直接指定。"""
    stats, prev = {}, None
    for b in blocks:
        if b["type"] == "heading" and b["rows"] and info[b["page"]]["mode"] == "text":
            s = stats.setdefault(_size_key(b), {"count": 0, "after_heading": 0, "sized": True, "sample": _text(b)[:30]})
            s["count"] += 1
            s["after_heading"] += prev is not None and prev["type"] == "heading"
            s["sized"] &= b.get("level") == 3          # 字級大的標題；粗體正文字級的小標不拿來切章
        prev = b
    conf = opts.get("heading_sizes")
    if conf:
        levels = {float(k): int(v) for k, v in conf.items()}
    else:
        title_sizes = {_size_key(blocks[by_page[p][0]]) for p in title_pages
                       if blocks[by_page[p][0]]["type"] == "heading"}
        cands = sorted((k for k, s in stats.items() if s["count"] >= 2 and s["sized"]
                        and s["after_heading"] < 0.5 * s["count"] and k not in title_sizes), reverse=True)
        levels = {cands[0]: 2} if title_pages and cands else dict(zip(cands, (1, 2)))
    table = [dict(size=k, level=levels.get(k, 0), **s) for k, s in sorted(stats.items(), reverse=True)]
    return {k: v for k, v in levels.items() if v > 0}, table


def _split_by_layout(blocks, pages, book_title, inferred, opts, report):
    info = {p["no"]: p for p in pages}
    by_page = defaultdict(list)
    for i, b in enumerate(blocks):
        by_page[b["page"]].append(i)

    # 只有標題的頁（部扉頁）：整頁字少、排在頁面中段以下。看頁面原本的所有行，
    # 不看接段後剩下的區塊（頁首的續段接到上一頁後，剩下的一小段不是部名）
    title_pages = set()
    for page, idx in by_page.items():
        p, bs = info[page], [blocks[i] for i in idx]
        rows = p["rows"]
        if not rows or not bs[0]["rows"] or bs[0]["rows"][0] is not rows[0] or p["images"]:
            continue
        low = rows[0]["y0"] > 0.2 * p["h"]
        if low and (all(b["type"] == "heading" for b in bs)
                    or (len(rows) <= 3 and sum(len(r["text"]) for r in rows) <= 60)):
            title_pages.add(page)

    kinds = {by_page[p][0]: ("title", 1) for p in title_pages}
    # 文字層：依字級
    levels, report["heading_sizes"] = _heading_levels(blocks, info, by_page, title_pages, opts)
    for i, b in enumerate(blocks):
        if i not in kinds and b["type"] == "heading" and b["rows"] and info[b["page"]]["mode"] == "text" \
                and _size_key(b) in levels:
            kinds[i] = ("size", levels[_size_key(b)])
    # OCR：字級不可靠，看位置與章名樣式——頁首標題接正文、頁中像章名的標題（Chapter 3、IV、12）
    for page, idx in by_page.items():
        if info[page]["mode"] != "ocr" or page in title_pages:
            continue
        bs = [blocks[i] for i in idx]
        if bs[0]["type"] == "heading" and not bs[0].get("minor") and any(b["type"] in ("para", "quote") for b in bs[1:]):
            kinds.setdefault(idx[0], ("opening", 0))
        for i in idx[1:]:
            if blocks[i]["type"] == "heading" and CHAPTER_PAT.match(_text(blocks[i])):
                kinds.setdefault(i, ("opening", 0))
    # OCR 章首下沉：讀不到章號時，頁面第一行從中段才開始，而且上方不是插圖。
    # 看頁面真正的第一行，不看剩下的第一個區塊：頁首的續段已經被接到上一頁去了。
    starts_pages = {blocks[i]["page"] for i in kinds}
    tops = [p["rows"][0]["y0"] for p in pages if p["mode"] == "ocr" and p["rows"] and p["no"] not in starts_pages]
    top = statistics.median(tops) if tops else None
    for page, idx in by_page.items():
        p, b = info[page], blocks[idx[0]]
        if p["mode"] != "ocr" or page in starts_pages or top is None or not p["rows"] \
                or b["type"] not in ("para", "quote") or not b["rows"] or b["rows"][0] is not p["rows"][0]:
            continue
        y = p["rows"][0]["y0"]
        if y > top + 0.15 * p["h"] and not any(img["y0"] < y for img in p["images"]):
            kinds[idx[0]] = ("sink", 0)

    has_top = any(lv == 1 for _, lv in kinds.values()) or any(
        PART_PAT.match(_text(blocks[i])) for i, (k, _) in kinds.items() if k == "opening")
    roman = sum(bool(re.fullmatch(r"[1lI|VXLC]+", _text(blocks[i]))) for i, (k, _) in kinds.items()
                if k in ("opening", "size")) >= 2
    starts, prev_title = {}, None
    for i in sorted(kinds):
        k, lv = kinds[i]
        if k == "sink":
            title = _next_number(prev_title, roman)
            inferred.append((blocks[i]["page"] + 1, title))
            starts[i] = (2 if has_top else 1, title, False)
        else:
            title = _text(blocks[i])
            if k == "opening":
                lv = 1 if PART_PAT.match(title) else (2 if has_top else 1)
            starts[i] = (lv, title, True)
        prev_title = None if starts[i][0] == 1 and has_top else title
    if any(info[blocks[i]["page"]]["mode"] == "ocr" for i in starts):
        _repair_numbering(blocks, starts, inferred, roman)
    return _cut(blocks, starts, book_title)


def _number(t, roman):
    """章名裡的編號：PART II → 2、IV → 4、12 → 12；看不出編號回傳 None。"""
    m = re.fullmatch(r"(?:(?:part|book|chapter)\s+)?([1lI|IVXLC]+|\d{1,3})\.?", t.strip(), re.I)
    if not m:
        return None
    n = m.group(1)
    if n.isdigit() and not roman:
        return int(n)
    return _from_roman(re.sub(r"[1l|]", "I", n.upper())) if re.fullmatch(r"[1lI|IVXLC]+", n, re.I) else None


def _repair_numbering(blocks, starts, inferred, roman):
    """OCR 讀章號常漏一劃（PART II → PART I）或整個漏掉（部名後的第一章 I）。編號應該連續：
    部號沒遞增就改成前一部加一；部名之後第一個章號是 2，就在第一段正文前補第 1 章。
    章號讀成不合法的羅馬數字（III → ILI）就改成前一章加一。都記進推定章名。"""
    order = sorted(starts)
    last_part, prev = 0, None
    for k, i in enumerate(order):
        lv, title, consumed = starts[i]
        if not PART_PAT.match(title):
            t = re.sub(r"[1l|]", "I", title.strip().upper())
            if roman and re.fullmatch(r"[IVXLC]+", t) and _roman(_from_roman(t)) != t:
                fixed = _next_number(prev, roman)
                if fixed:
                    starts[i] = (lv, fixed, consumed)
                    inferred.append((blocks[i]["page"] + 1, fixed))
                    title = fixed
            prev = title
            continue
        prev = None
        n = _number(title, True)
        if n is not None and n <= last_part:
            fixed = re.sub(r"\S+$", _roman(last_part + 1), title)
            starts[i] = (lv, fixed, consumed)
            inferred.append((blocks[i]["page"] + 1, fixed))
            n = last_part + 1
        last_part = n or last_part
        nxt = next((j for j in order[k + 1:]), None)
        if nxt is None or _number(starts[nxt][1], roman) != 2:
            continue
        body = next((j for j in range(i + 1, nxt) if blocks[j]["type"] in ("para", "quote")
                     and len(_text(blocks[j])) >= 40), None)
        if body is not None and body not in starts:
            first = "I" if roman else "1"
            starts[body] = (starts[nxt][0], first, False)
            inferred.append((blocks[body]["page"] + 1, first))


def _next_number(prev, roman):
    """讀不到章號時依前一章推定：部扉頁之後是 I（或 1），否則前一章加一；前一章不是編號就留空。"""
    if prev is None:
        return "I" if roman else "1"
    t = re.sub(r"[1l|]", "I", prev) if roman else prev
    if re.fullmatch(r"[IVXLC]+", t):
        return _roman(_from_roman(t) + 1)
    if t.isdigit():
        return str(int(t) + 1)
    return ""


def _from_roman(t):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    n = 0
    for a, b in zip(t, t[1:] + " "):
        n += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return n


def _roman(n):
    out = ""
    for v, s in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out, n = out + s, n - v
    return out


def _cut(blocks, starts, book_title):
    chapters, cur, skip = [], None, 0
    for i, b in enumerate(blocks):
        if i in starts:
            lvl, title, skip = starts[i]                       # skip：章名本身佔掉的區塊數
            cur = {"level": lvl, "title": title, "blocks": []}
            chapters.append(cur)
        if skip > 0:
            skip -= 1
            continue
        if cur is None:
            cur = {"level": 1, "title": book_title, "blocks": []}
            chapters.append(cur)
        cur["blocks"].append(b)
    return chapters


def fix_roman_titles(chapters):
    """多數章名是羅馬數字時，把 OCR 讀成 1、l、| 的章名修回 I（1 → I、1V → IV）。"""
    roman = [c for c in chapters if re.fullmatch(r"[IVXLC]+", c["title"])]
    if len(roman) < 2:
        return
    for c in chapters:
        t = c["title"]
        if re.fullmatch(r"[1lI|!IVXLC]+", t) and re.search(r"[1l|!]", t):
            c["title"] = re.sub(r"[1l|!]", "I", t)


def _text(b):
    return b.get("text") or " ".join(r["text"] for r in b["rows"])


# ── 主流程 ───────────────────────────────────────────────────────────
def build(pages, outline, opts, book_title):
    report = {}
    drop = {}                                   # pdf.drop_lines：OCR 讀出來的雜訊行（透印、污漬），分段前拿掉
    for d in opts.get("drop_lines") or []:
        drop.setdefault(int(d["page"]) - 1, []).append(str(d["text"]))
    for p in pages:
        if p["no"] in drop:
            p["lines"] = [l for l in p["lines"] if not any(l["text"].startswith(t) for t in drop[p["no"]])]
        p["rows"] = merge_rows(p["lines"], p["w"], int(opts.get("columns", 1)))
        for r in p["rows"]:
            r["page"] = p["no"]

    for p in pages:
        if p["mode"] == "ocr":
            deskew(p)
    stats = {mode: Stats([p for p in pages if p["mode"] == mode], opts.get("para_indent", "auto"))
             for mode in {p["mode"] for p in pages}}
    stats_of = lambda p: stats[p["mode"]]
    report["removed_headers"] = strip_headers_footers(pages, stats_of)
    notes = take_footnotes(pages, stats_of, opts.get("footnote_marks")) if opts.get("footnotes", "end") != "keep" else []

    report["toc_pages"] = []
    if opts.get("skip_toc_pages", True):
        for p in pages:
            if is_toc_like(p["rows"]):
                report["toc_pages"].append(p["no"] + 1)
                p["rows"], p["images"] = [], []

    vocab = vocabulary(pages)
    # 排版斷字若用軟連字號（Typst、部分 InDesign 輸出），行尾的一般連字號就是複合字本身的
    soft = {m: sum(r["text"].endswith("\u00ad") for p in pages if p["mode"] == m for r in p["rows"]) >= 5
               or not _hyphenates(pages, m, vocab) for m in stats}
    mode_of = {p["no"]: p["mode"] for p in pages}
    blocks_by_page = {p["no"]: page_blocks(p, stats_of(p), opts.get("headings")) for p in pages}
    continue_across_pages(blocks_by_page, stats_of, pages)
    blocks = [b for p in pages for b in blocks_by_page[p["no"]]]
    for b in blocks:
        if b["rows"]:
            b["text"] = join_lines([r["text"] for r in b["rows"]], vocab, soft[mode_of[b["page"]]]) \
                if b["type"] != "heading" \
                else " ".join(r["text"] for r in b["rows"])
            b["conf"] = min((r["conf"] for r in b["rows"] if r.get("conf") is not None), default=None)

    inferred = []
    chapters, source = split_chapters(blocks, pages, outline, opts, book_title, inferred, report)
    fix_roman_titles(chapters)
    report["inferred_titles"] = inferred
    report["chapter_source"] = source
    _attach_notes(chapters, notes, opts.get("footnotes", "end"))
    report["footnotes"] = len(notes)
    report["stats"] = {m: {"body": s.body, "pitch": round(s.pitch, 2), "left": s.left, "right": s.right}
                       for m, s in stats.items()}
    return chapters, report


def _attach_notes(chapters, notes, mode):
    if mode != "end" or not notes:
        return
    first_page = [min((b["page"] for b in c["blocks"]), default=None) for c in chapters]
    for n in notes:
        k = max((i for i, fp in enumerate(first_page) if fp is not None and fp <= n["page"]), default=0)
        c = chapters[k]
        if not c.get("notes"):
            c["notes"] = []
        c["notes"].append(n)
    for c in chapters:
        if c.get("notes"):
            c["blocks"].append({"type": "heading", "rows": [], "text": "Notes", "page": c["notes"][0]["page"],
                                "level": 3})
            for n in c["notes"]:
                body = join_lines(n["lines"], {})
                c["blocks"].append({"type": "para", "rows": [], "page": n["page"],
                                    "text": f"{n['mark']} {body}".strip()})
