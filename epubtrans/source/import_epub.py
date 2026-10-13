"""EPUB → work/book.json + work/images/

通用抽取：讀 EPUB 自己的 container.xml → OPF → manifest/spine，依 spine 順序
逐份 XHTML 解析。章節切分預設「一份 spine 文件 = 一章」，本文開始後才出現的
<h1> 會另起一章。書本專屬的結構差異（例如某個 CSS class 的 h1 其實是第二層
詞條）用 system_prompts.yaml 的 extract.heading_levels 表達，不寫進程式碼。

排版工具不一定用 <h*> 排小標。The Dictator's Handbook 的 80 個章內小標是
<p class="H1">，只認標籤就會全部掉進 para，在譯本裡變成縮排的普通段落 ——
分不出哪句是小標。extract.para_headings 就是給這種情況指定「這個 class 的
<p> 其實是章內小標」，語意與 heading_levels 不同：後者切章，這個不切。

item 型別：heading / para / quote / li / image

原書有頁碼標記（<a class="page" id="p33"/>、epub:type="pagebreak"）時，每個 item
另記 page（開始頁）與 page_end（跨頁時的結束頁）；段落裡連到頁碼標記的連結
（書末索引的頁碼）記成 parts：文字與 {"t": 連結文字, "page": 頁碼} 交錯的片段。
這兩樣是重建索引的原料（見 book_index.py）；沒有頁碼標記的書 book.json 不變。
"""
import json, os, re, zipfile, shutil, warnings
from bs4 import BeautifulSoup, NavigableString, Comment, XMLParsedAsHTMLWarning
from . import book_index

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

NS_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"


def _clean(t):
    return re.sub(r"\s+", " ", t).strip()


_TRAILING_NUM = re.compile(r"(\d+)$")
TEXT_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li")
_HIDDEN_STYLE = re.compile(r"visibility\s*:\s*hidden|display\s*:\s*none", re.I)


def _hidden(el):
    """讀者看不到的元素（style 的 visibility:hidden／display:none、hidden 屬性）不進 book.json。
    The Dictator's Handbook 每章結尾都有一個 <p style="visibility:hidden;"> 包著的注號「1」，
    注釋頁各節結尾也有一個，是轉檔殘留；照收會在譯本裡多出孤零零的「1」。"""
    for t in (el, *el.parents):
        if t.name is None or t.name in ("body", "html", "[document]"):
            break
        if t.has_attr("hidden") or _HIDDEN_STYLE.search(t.get("style") or ""):
            return True
    return False


def _page_no(el):
    """原書頁碼標記 → 頁碼（int）；不是標記就回 None。

    認兩種：EPUB 3 的 epub:type="pagebreak"／role="doc-pagebreak"，以及轉檔工具常見的
    空錨點 <a class="page" id="p33"/>（House of Debt）。後者必須是空元素，免得把
    class 剛好叫 page 的外框 div 當成標記。只認阿拉伯數字；前置頁的 xii 不記。
    """
    if el.name not in ("a", "span", "div"):
        return None
    kind = f'{el.get("epub:type") or ""} {el.get("role") or ""}'
    if "pagebreak" in kind:
        v = el.get("title") or el.get("aria-label") or el.get_text(strip=True) or el.get("id") or ""
    elif "page" in (el.get("class") or []) and not el.get_text(strip=True):
        v = el.get("id") or ""
    else:
        return None
    m = _TRAILING_NUM.search(v.strip())
    return int(m.group(1)) if m else None


def _pages_in(el, page):
    """區塊的 (開始頁, 結束頁)。標記前面還沒有文字＝這一段從那一頁開始。"""
    start = end = page
    seen = False
    for d in el.descendants:
        if isinstance(d, NavigableString):
            if not isinstance(d, Comment) and d.strip():
                seen = True
        elif (n := _page_no(d)) is not None:
            if not seen:
                start = n
            end = n
    return start, end


def _parts(el, doc, marks):
    """段落裡連到頁碼標記的連結 → [文字, {"t": 連結文字, "page": 頁碼}, 文字, …]；沒有就回 None。"""
    def target(h):
        f, _, frag = h.partition("#")
        f = os.path.normpath(os.path.join(os.path.dirname(doc), f)).replace("\\", "/") if f else doc
        return marks.get(f"{f}#{frag}")

    links = {id(a): n for a in el.find_all("a", href=True) if (n := target(a["href"])) is not None}
    if not links:
        return None
    out, buf = [], []

    def flush():
        if buf:
            out.append(re.sub(r"\s+", " ", "".join(buf)))
            buf.clear()

    for d in el.descendants:
        if isinstance(d, NavigableString):
            if isinstance(d, Comment) or any(id(p) in links for p in d.parents):
                continue
            buf.append(str(d))
        elif id(d) in links:
            flush()
            out.append({"t": _clean(d.get_text()), "page": links[id(d)]})
    flush()
    if out and isinstance(out[0], str):
        out[0] = out[0].lstrip()
    if out and isinstance(out[-1], str):
        out[-1] = out[-1].rstrip()
    return [x for x in out if x != ""]


def _opf_path(zf):
    x = BeautifulSoup(zf.read("META-INF/container.xml").decode("utf-8"), "xml")
    rf = x.find("rootfile")
    return rf["full-path"]


def _parse_opf(zf, opf_path):
    soup = BeautifulSoup(zf.read(opf_path).decode("utf-8"), "xml")
    manifest, props = {}, {}
    for it in soup.find_all("item"):
        manifest[it.get("id")] = it.get("href")
        props[it.get("id")] = (it.get("properties") or "")
    spine = [ir.get("idref") for ir in soup.find_all("itemref")]
    cover_id = None
    for m in soup.find_all("meta"):
        if (m.get("name") or "").lower() == "cover":
            cover_id = m.get("content")
    if not cover_id:
        for i, p in props.items():
            if "cover-image" in p:
                cover_id = i
    meta = {}
    for tag, key in (("title", "title"), ("creator", "author"), ("language", "language")):
        el = soup.find(re.compile(f"^(dc:)?{tag}$"))
        if el:
            meta[key] = _clean(el.get_text())
    nav_ids = {i for i, p in props.items() if "nav" in p.split()}
    return manifest, spine, cover_id, meta, nav_ids


def run(cfg):
    src = cfg.source_epub()
    outdir = cfg.work
    imgdir = os.path.join(outdir, "images")
    if os.path.isdir(imgdir):
        shutil.rmtree(imgdir)
    os.makedirs(imgdir, exist_ok=True)

    ex = cfg.get("extract", default={}) or {}
    hlevels = {str(k): int(v) for k, v in (ex.get("heading_levels") or {}).items()}
    # 寫成 list（[H1, H2]）時一律當第 3 層章內小標；要分層就寫成 dict（{H1: 3, H2: 4}）。
    _ph = ex.get("para_headings") or {}
    pheads = ({str(k): int(v) for k, v in _ph.items()} if isinstance(_ph, dict)
              else {str(k): 3 for k in _ph})
    skip_pat = [s.lower() for s in (ex.get("skip_files") or [])]
    # 只有圖、沒有標題的 spine 文件併進下一章開頭（Atlas of the Heart 每部前的跨頁照片，
    # 自成一章的話章名只能取 <title>，十三章都叫「Continued」）。
    join_pat = [s.lower() for s in (ex.get("join_next") or [])]
    # spine 檔名含這些字串的文件接在前一章後面，不另起一章：calibre 把過長的章從中間切開
    # （美國貨幣史第 7 章的 part0012_split_001 從 7.4 節開始，沒有章標題）。
    prev_pat = [s.lower() for s in (ex.get("join_prev") or [])]
    # 句中用圖片排的字（帶分數「64 64/99」、特殊符號）：{圖檔名: 替代文字}，換成文字留在段落裡，
    # 不另外收成圖（否則圖會被拉出來另起一行，句子留個缺口）。
    inline_imgs = {str(k): str(v) for k, v in (ex.get("inline_images") or {}).items()}

    zf = zipfile.ZipFile(src)
    names = set(zf.namelist())
    opf = _opf_path(zf)
    opf_dir = os.path.dirname(opf)
    manifest, spine, cover_id, meta, nav_ids = _parse_opf(zf, opf)

    def resolve(href):
        p = os.path.normpath(os.path.join(opf_dir, href)) if opf_dir else href
        return p.replace("\\", "/")

    # --- 封面 ---
    cover_name = cover_path = None
    if cover_id and cover_id in manifest:
        p = resolve(manifest[cover_id])
        if p in names:
            ext = os.path.splitext(p)[1] or ".jpg"
            cover_name, cover_path = "cover" + ext, p
            open(os.path.join(imgdir, cover_name), "wb").write(zf.read(p))

    chapters, seen_img = [], {}
    cid = 0
    carry = []                                   # join_next：等著併進下一章的圖

    def new_ch(level, title):
        nonlocal cid
        c = {"level": level, "title": title, "id": f"c{cid:03d}", "items": carry[:]}
        carry.clear()
        cid += 1
        chapters.append(c)
        return c

    docs = []
    for sid in spine:
        if sid in nav_ids or sid not in manifest:
            continue
        href = resolve(manifest[sid])
        if href not in names or not href.lower().endswith((".xhtml", ".html", ".htm")):
            continue
        try:
            soup = BeautifulSoup(zf.read(href).decode("utf-8", "ignore"), "lxml")
        except Exception:
            continue
        docs.append((href, soup))

    # 頁碼標記先整本掃一遍：索引在書末，連結卻指向前面各章的標記。
    # marks：「檔名#id」→ 頁碼，給 _parts 判斷哪些連結是頁碼。
    marks, has_pages = {}, False
    for href, soup in docs:
        for m in (soup.body or soup).find_all(lambda t: _page_no(t) is not None):
            has_pages = True
            if m.get("id"):
                marks[f"{href}#{m['id']}"] = _page_no(m)
    page = None                                  # 目前所在的原書頁碼

    def wanted(t):
        return t.name in TEXT_TAGS or t.name == "img" or (has_pages and _page_no(t) is not None)

    def paged(item, start, end):
        if end is not None:
            item["page"] = start if start is not None else end
            if item["page"] != end:
                item["page_end"] = end
        return item

    for href, soup in docs:
        if any(s in href.lower() for s in skip_pat):
            continue
        body = soup.body or soup
        cur, title_buf, started = None, [], False
        if prev_pat and chapters and any(j in href.lower() for j in prev_pat):
            cur, started = chapters[-1], True
        for im in body.find_all("img"):
            name = os.path.basename(im.get("src") or "")
            if name in inline_imgs and im.find_parent("p") is not None:
                par = im.find_parent("p")
                im.replace_with(inline_imgs[name])
                par.smooth()

        def ensure():
            nonlocal cur, started
            if cur is None:
                t = _clean(" ".join(title_buf)) if title_buf else \
                    _clean((soup.title.get_text() if soup.title else "") or os.path.basename(href))
                cur = new_ch(1, t)
                title_buf.clear()
            started = True
            return cur

        # h5/h6 也要收：轉檔工具常把獻詞頁、版權頁的整段正文塞進 <h5>
        # （Non-Stop 的 Gollancz 版就是如此，漏掉會整頁消失）。
        for el in body.find_all(wanted):
            name = el.name
            if name not in TEXT_TAGS and name != "img":  # 頁碼標記
                # 段落、標題裡的標記由該區塊自己處理（_pages_in）；這裡只管段落之間的
                if el.find_parent(TEXT_TAGS) is None:
                    page = _page_no(el)
                continue
            if name == "p" and el.find_parent("li") is not None:
                continue                         # 由 <li> 處理，避免重複
            if _hidden(el):
                continue
            if name in TEXT_TAGS and has_pages:
                start, page = _pages_in(el, page)
            else:
                start = page
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                txt = _clean(el.get_text(" ", strip=True))
                if not txt:
                    continue
                classes = el.get("class") or []
                forced = next((hlevels[c] for c in classes if c in hlevels), None)
                if forced:                      # yaml 指定：另起一章，指定層級
                    if cur is None and title_buf:
                        ensure()                # 本文件自己的標題（Notes）先成章，否則會被丟掉
                    cur = new_ch(forced, txt); started = True
                elif name == "h1":
                    if not started:
                        title_buf.append(txt)   # 仍在本文件自己的標題
                    else:
                        cur = new_ch(1, txt); started = True
                else:                            # h2/h3/h4 當章內小標，不切章
                    ensure()
                    cur["items"].append(paged({"type": "heading",
                                               "level": int(name[1]), "text": txt}, start, page))
                continue

            if name == "p":
                txt = _clean(el.get_text(" ", strip=True))
                if not txt:
                    continue
                ensure()
                lvl = next((pheads[c] for c in (el.get("class") or []) if c in pheads), None)
                if lvl:                      # yaml 指定：這個 class 的 <p> 其實是章內小標
                    cur["items"].append(paged({"type": "heading", "level": lvl, "text": txt}, start, page))
                    continue
                t = "quote" if el.find_parent("blockquote") is not None else "para"
                it = paged({"type": t, "text": txt}, start, page)
                if marks and (parts := _parts(el, href, marks)):
                    it["parts"] = parts
                cur["items"].append(it)
                continue

            if name == "li":
                txt = _clean(el.get_text(" ", strip=True))
                if not txt:
                    continue
                ensure()
                it = paged({"type": "li", "text": txt}, start, page)
                if marks and (parts := _parts(el, href, marks)):
                    it["parts"] = parts
                cur["items"].append(it)
                continue

            if name == "img":
                s = el.get("src") or el.get("xlink:href")
                if not s:
                    continue
                p = os.path.normpath(os.path.join(os.path.dirname(href), s)).replace("\\", "/")
                if p not in names:
                    continue
                # 原書封面頁引用的就是封面圖。記成 cover 的檔名，build 才認得出這一章
                # 是封面頁；照原檔名另存一份的話，封面在譯本裡會出現兩次
                # （House of Debt 的封面圖叫 chi-mian-cover.jpg）。
                fn = cover_name if p == cover_path else os.path.basename(p)
                if fn not in seen_img and fn != cover_name:
                    seen_img[fn] = p
                    open(os.path.join(imgdir, fn), "wb").write(zf.read(p))
                ensure()
                cur["items"].append(paged({"type": "image", "file": fn}, page, page))
                continue

        if cur is None and title_buf:
            new_ch(1, _clean(" ".join(title_buf)))
        if (join_pat and cur is not None and any(j in href.lower() for j in join_pat)
                and not title_buf and all(it["type"] == "image" for it in cur["items"])
                and not any(it["file"] == cover_name for it in cur["items"])):
            chapters.pop(); cid -= 1
            carry.extend(cur["items"])

    chapters = [c for c in chapters if c["items"] or c["title"]]
    # 按章節 id 覆寫層級。heading_levels 以 class 指定，同一個 class 的標題只能是
    # 同一層；House of Debt 的十二章都是 h1.ct，但第一章在第一部之前、與各部同層，
    # 二至十二章才掛在部底下 —— 這種例外只能按 id 指定。
    for k, v in (ex.get("chapter_levels") or {}).items():
        for c in chapters:
            if c["id"] == str(k):
                c["level"] = int(v)
    # 章名寫在正文開頭的 <p> 裡、<title> 又全書同名時（When Genius Failed 的「1」「MERIWETHER」
    # 是兩段 <p>，class 又和題詞共用），按章節 id 指定開頭幾段併成章名，不留在正文。
    for k, n in (ex.get("title_items") or {}).items():
        for c in chapters:
            if c["id"] != str(k):
                continue
            # 章號與章名之間夾著裝飾圖（Irrational Exuberance 的「One」、分隔線圖、章名）時，
            # 圖留在原位，只取前 n 段文字。
            head, keep = [], []
            for it in c["items"]:
                if len(head) < int(n) and it["type"] != "image":
                    head.append(it["text"])
                else:
                    keep.append(it)
            if head:
                c["items"] = keep
                c["title"] = _clean(" ".join(head))
    if marks:
        book_index.run(chapters, cfg.wpath("index_report.tsv"))
    book = {
        "title": cfg.book.get("title") or meta.get("title") or cfg.name,
        "author": cfg.book.get("author") or meta.get("author", ""),
        "source_language": cfg.book.get("source_lang") or meta.get("language", ""),
        "cover": cover_name,
        "chapters": chapters,
    }
    json.dump(book, open(cfg.wpath("book.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    cnt = {}
    for c in chapters:
        for it in c["items"]:
            cnt[it["type"]] = cnt.get(it["type"], 0) + 1
    print(f"章節={len(chapters)}  " + "  ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    print(f"圖片={len(seen_img)}  封面={cover_name}")
    print(f"寫入 {cfg.wpath('book.json')}")
