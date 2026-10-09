"""逐頁核對排出來的 PDF，不靠肉眼。

為什麼需要：Typst 的書眉、頁碼、目錄都是「版面內省」（query / counter）算出來的，
版面迭代沒收斂時它只給一行 warning，PDF 照樣產出。第一版就是這樣 —— 零錯誤、
199 頁，但目錄第一筆印著「第 0 頁」，書眉在五輪迭代間於 47/48/49 頁來回震盪。
那種錯誤看幾頁抽樣是看不出來的，要全書逐頁比對。

判準全部從 PDF 本身與 content.json 推出來，不讀 Typst 的任何內部狀態：
  - 文字的 y 座標落在上邊界內＝書眉，落在下邊界內＝頁碼
  - 章節起始頁＝本文開頭就是下一個預期的章名
  - 預期章名順序來自 content.json
"""
import json, os, re
from pypdf import PdfReader

MM = 72 / 25.4


def _norm(s):
    return re.sub(r"[\s　]+", "", s or "")


def _zones(page, top_pt, bot_pt):
    H = float(page.mediabox.height)
    frags = []

    def v(text, cm, tm, fd, fs):
        if text.strip():
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            # 公式的上下限（頁底積分式的 −∞）會伸進頁碼區，不能算成頁碼
            if fd is not None and "Math" in str(fd.get("/BaseFont", "")) and (y > H - top_pt or y < bot_pt):
                return
            frags.append((y, text))

    page.extract_text(visitor_text=v)
    head = "".join(t for y, t in frags if y > H - top_pt)
    foot = "".join(t for y, t in frags if y < bot_pt)
    body = "".join(t for y, t in frags if bot_pt <= y <= H - top_pt)
    return _norm(head), _norm(foot), _norm(body)


def _baselines(page, top_pt, bot_pt, body_size):
    """本文區每一行的基線 y（同一行的片段 y 可能差零點幾，2pt 內合併）。

    上標注號（字級約 0.6 倍、上移 3pt）不算一行：不排除的話，每個注號都會被
    量成「16.5pt＋3.1pt」兩個假行距（House of Debt 一本就有五百多處）。
    """
    H = float(page.mediabox.height)
    ys = []

    def v(text, cm, tm, fd, fs):
        if text.strip() and fs * abs(tm[3] * cm[3]) >= body_size * 0.8:
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            if bot_pt < y < H - top_pt:
                ys.append(y)

    page.extract_text(visitor_text=v)
    out = []
    for y in sorted(ys, reverse=True):
        if not out or out[-1] - y >= 2:
            out.append(y)
    return out


def check_pitch(reader, pages_info, cfg, top_pt, bot_pt):
    """行距均勻度：一般正文頁的每個基線間距都該等於 字級 × (1 + leading_ratio)。

    第一版看起來「差不多」，量了才知道含破折號的行比別行高 3.1pt ——
    Typst 依字型度量算行框，破折號由西文字型排就把那一行撐開。
    章首頁、部扉頁、空白頁不在檢查範圍；節標題與引文前後本來就該多留空，
    所以只數「比常態更窄」或「多出不到半行」的偏差，那兩種才是行框被撐歪。
    """
    bs, lead = float(cfg["body_size"]), float(cfg["leading"])
    pitch = bs + lead
    # 引文（book.typ 的 quote-block：字級 0.95 倍、前後各多留 0.2 倍行間空隙）本來就是
    # 另一種行距：引文內部、正文→引文、引文→正文三種間距都是版型設計的，不算撐歪。
    # Atlas of the Heart 的多行引文多，不排除會被誤報兩百多處。
    allowed = [pitch, bs * 0.95 + lead, lead * 1.2 + bs * 0.95, lead * 1.2 + bs]
    bad = []
    checked = 0
    math_pages = 0
    for i, kind in pages_info:
        if kind != "normal":
            continue
        # 有公式的頁（掃描數學書）：分式、上下標、獨立公式本來就會撐開行距，不量
        if _has_math_font(reader.pages[i - 1]):
            math_pages += 1
            continue
        ys = _baselines(reader.pages[i - 1], top_pt, bot_pt, float(cfg["body_size"]))
        for a, b in zip(ys, ys[1:]):
            g = a - b
            checked += 1
            if min(abs(g - a) for a in allowed) > 0.3 and g < pitch * 1.5:
                bad.append((i, round(g, 1)))
    return pitch, checked, bad, math_pages


def _has_math_font(page):
    try:
        fonts = page["/Resources"]["/Font"]
    except (KeyError, TypeError):
        return False
    return any("Math" in str(f.get_object().get("/BaseFont", "")) for f in fonts.values())


def run(workdir, pdf):
    book = json.load(open(os.path.join(workdir, "content.json"), encoding="utf-8"))
    cfg = json.load(open(os.path.join(workdir, "config.json"), encoding="utf-8"))
    title = _norm(cfg["title"])
    top_pt, bot_pt = cfg["margin_top"] * MM, cfg["margin_bottom"] * MM

    # 預期的章節順序：(正規化章名, 是否部扉頁, 層級)
    chaps = [(_norm(c["title"]), c.get("is_part", False), c["level"])
             for c in book["chapters"] if c["title"]]

    reader = PdfReader(pdf)
    pages = [_zones(p, top_pt, bot_pt) for p in reader.pages]
    errs, starts = [], {}
    kinds = []                  # (實體頁, 類別)，給行距檢查用
    k = 0                       # 下一個預期章節的索引
    part, cur = None, None      # 目前所在的部、目前的章／附件
    first_body = None
    front = _front_matter_end(pages)

    for i, (head, foot, body) in enumerate(pages, 1):
        # 書名頁與目錄頁不可能是章首：半書名頁的章名就是書名（House of Debt 的「房債」），
        # 只比對開頭的話，排版產生的書名頁會被當成那一章的起始頁。
        is_start = i > front and k < len(chaps) and body.startswith(chaps[k][0])
        # 內文恰好以下一章的章名開頭（Atlas of the Heart 第十三部的導言以「自豪，是……」起頭，
        # 下一章就叫「自豪」）：有書眉、而緊接幾頁內另有沒書眉又以章名開頭的頁，真正的章首在後面。
        if is_start and head and any(
                not h2 and b2.startswith(chaps[k][0]) for h2, _, b2 in pages[i:i + 4]):
            is_start = False
        if is_start:
            name, is_part, level = chaps[k]
            # 部扉頁之後的第一個章節必須落在右頁：扉頁在右、背面留白、正文再從右頁起
            if k > 0 and chaps[k - 1][1] and i % 2 == 0:
                errs.append(f"第 {i} 頁：部扉頁之後的「{name}」落在左頁")
            starts[name + f"#{k}"] = (i, foot)
            if first_body is None:
                first_body = i
            if is_part:
                part, cur = name, None
            elif level == 2:
                cur = name
            else:
                # 第一層的非扉頁章節底下也可能有第二層（Atlas of the Heart 的引言、注釋、各部）：
                # 書眉模板對第二層一律冠上前一個第一層標題，這裡跟著把它當成「部」。
                part, cur = name, None
            k += 1

        if first_body is None:          # 書名頁、目錄：不該有書眉頁碼
            if head or foot:
                errs.append(f"第 {i} 頁：前置頁不該有書眉或頁碼（書眉={head!r} 頁碼={foot!r}）")
            continue

        blank = not (head or foot or body)
        exp_folio = str(i - first_body + 1)

        if blank:
            if i % 2 == 1:
                errs.append(f"第 {i} 頁：空白頁落在右頁（應只出現在左頁當補位）")
            continue
        if is_start and chaps[k - 1][1]:        # 部扉頁
            if i % 2 == 0:
                errs.append(f"第 {i} 頁：部扉頁「{name}」落在左頁")
            if head or foot:
                errs.append(f"第 {i} 頁：部扉頁不該有書眉或頁碼（書眉={head!r} 頁碼={foot!r}）")
            nxt = pages[i] if i < len(pages) else None
            if nxt and any(nxt):
                errs.append(f"第 {i+1} 頁：部扉頁背面應留白")
            continue

        if foot != exp_folio:
            errs.append(f"第 {i} 頁：頁碼應為 {exp_folio}，實為 {foot!r}")
        if is_start:
            if head:
                errs.append(f"第 {i} 頁：章首頁不該有書眉（{head!r}）")
            continue
        if i % 2 == 0:
            exp_head = title
        else:
            exp_head = (part + cur) if (part and cur) else (cur or part or "")
        if head != exp_head:
            errs.append(f"第 {i} 頁：書眉應為 {exp_head!r}，實為 {head!r}")
        kinds.append((i, "normal"))

    if k != len(chaps):
        errs.append(f"只在 PDF 裡找到 {k}/{len(chaps)} 個章節起始頁，"
                    f"第一個沒找到的是「{chaps[k][0]}」")

    # 目錄：每一筆的頁碼要等於該章實際起始頁的頁碼
    toc_errs = _check_toc(pages, chaps, starts)
    errs += toc_errs

    pitch, n_gaps, bad, math_pages = check_pitch(reader, kinds, cfg, top_pt, bot_pt)
    for pg, g in bad[:15]:
        errs.append(f"第 {pg} 頁：行距 {g}pt，常態應為 {pitch:.1f}pt（行框被撐歪）")
    if len(bad) > 15:
        errs.append(f"……行距異常共 {len(bad)} 處，僅列前 15")

    body_pages = len(pages) - (first_body or 1) + 1
    print(f"逐頁核對：共 {len(pages)} 頁（正文自第 {first_body} 頁起，{body_pages} 頁）"
          f"　章節起始頁 {k}/{len(chaps)}　目錄 {len(chaps) - len(toc_errs)}/{len(chaps)} 筆相符"
          f"　行距 {n_gaps - len(bad)}/{n_gaps} 處均勻（{pitch:.1f}pt）"
          + (f"　含公式的頁 {math_pages} 頁不量行距" if math_pages else ""))
    if errs:
        print(f"發現 {len(errs)} 個問題：")
        for e in errs[:40]:
            print("  ✗", e)
    else:
        print("  ✓ 書眉、頁碼、空白頁、部扉頁位置、目錄頁碼、行距全部正確")
    return errs


def _toc_pages(pages):
    """目錄頁的索引（0 起算）：開頭是「目錄」的那一頁，加上後面有點線、無書眉頁碼的續頁。"""
    out = []
    for n, (head, foot, body) in enumerate(pages):
        if body.startswith("目錄") or (out and "......" in body and not head and not foot):
            out.append(n)
        elif out:
            break
    return out


def _front_matter_end(pages):
    """前置頁（封面圖、書名頁、目錄）的最後一頁頁號（1 起算）。沒有目錄時只算到書名頁。"""
    toc = _toc_pages(pages)
    if toc:
        return toc[-1] + 1
    return next((n for n, z in enumerate(pages, 1) if any(z)), 0)


def _check_toc(pages, chaps, starts):
    toc = ""
    for head, foot, body in pages:
        if body.startswith("目錄") or (toc and "......" in body and not head and not foot):
            toc += body
        elif toc:
            break
    if not toc:
        return ["找不到目錄頁"]
    errs = []
    pos = 0
    for idx, (name, _, _) in enumerate(chaps):
        # 目錄文字去掉空白後，頁碼緊接下一筆章名；下一筆以數字開頭（「1.5 The Dirac …」）時
        # 貪婪比對會把「4」＋「1.5…」讀成 41：先以下一筆章名為界，比對不到再退回貪婪
        nxt = chaps[idx + 1][0] if idx + 1 < len(chaps) else None
        m = None
        if nxt and nxt[:1].isdigit():
            m = re.compile(re.escape(name) + r"\.{3,}(\d+?)(?=" + re.escape(nxt) + ")").search(toc, pos)
        m = m or re.compile(re.escape(name) + r"\.{3,}(\d+)").search(toc, pos)
        if not m:
            errs.append(f"目錄裡找不到「{name}」")
            continue
        pos = m.end()
        want = starts.get(name + f"#{idx}")
        if want is None:
            continue
        # 部扉頁本身不印頁碼，目錄上的數字是它「應有」的頁碼
        _, foot = want
        page_i = want[0]
        if foot and m.group(1) != foot:
            errs.append(f"目錄「{name}」印 {m.group(1)}，實際在第 {foot} 頁")
        elif not foot:
            base = next(i - int(f) + 1 for n, (i, f) in starts.items() if f)
            if int(m.group(1)) != page_i - base + 1:
                errs.append(f"目錄「{name}」印 {m.group(1)}，實際應為 {page_i - base + 1}")
    return errs
