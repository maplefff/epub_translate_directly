"""book.json + translations.json → 譯本 EPUB。

還有段落沒進快取時預設**拒絕出貨**（--allow-partial 才放行）。
"""
import os, re, html, json
from ebooklib import epub
from ..core import store
from ..qa import verify
from ..source import book_index
from . import math as texmath

CSS = """
body{font-family:"Noto Serif CJK TC","Songti TC",serif;line-height:1.85;
  margin:1.2em 1.4em;color:#1a1a1a;}
h1{font-size:1.7em;margin:1.2em 0 .8em;line-height:1.4;text-align:center;}
h2{font-size:1.35em;margin:1.2em 0 .7em;line-height:1.4;text-align:center;}
h3{font-size:1.12em;margin:1.1em 0 .5em;color:#333;}
h4{font-size:1.02em;margin:1em 0 .4em;color:#444;}
p{margin:0 0 .9em;text-align:justify;text-indent:2em;}
p.nia{text-indent:0;}
blockquote{margin:1em 2em;padding-left:1em;border-left:3px solid #ccc;
  color:#444;font-style:italic;}
blockquote p{text-indent:0;margin:0 0 .3em;}
ul{margin:0 0 .9em;padding-left:2em;}
li{margin:0 0 .4em;text-align:justify;}
figure{margin:1.4em 0;text-align:center;}
img{max-width:100%;height:auto;}
.imgcap{color:#777;font-size:.85em;margin-top:.4em;}
figcaption{color:#444;font-size:.92em;margin-top:.5em;text-align:center;text-indent:0;}
.figrow{display:flex;flex-wrap:wrap;justify-content:space-around;align-items:flex-end;gap:0 1.5em;margin:1.4em 0;}
.figrow figure{margin:0;flex:0 1 auto;min-width:0;}
sup{font-size:.7em;line-height:0;vertical-align:super;}
.cover{margin:0;padding:0;text-align:center;}
.cover img{max-height:100%;}
p.ix{text-indent:-2em;padding-left:2em;margin:0 0 .3em;text-align:left;}
p.ixfirst{margin-top:1.3em;}
p.ixnote{text-indent:0;color:#666;font-size:.9em;margin-bottom:1.2em;}
a.ixr{text-decoration:none;}
.eq{display:flex;align-items:center;margin:.7em 0;text-indent:0;}
.eq math{flex:1;}
.eqno{margin-left:1em;white-space:nowrap;}
.texerr{font-family:monospace;color:#a00;}
"""

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def index_zh(zh, entry):
    """索引條目的譯稿 → (各欄譯文, 參見譯文)。

    譯稿格式：條目與各子條目的譯名以「；」隔開，參見（See／See also）放在「｜」之後，
    例如「銀行危機；銀行擠兌；經常帳赤字｜另見 the Depression（大蕭條）」。
    頁碼不寫進譯稿，由 build 依對位結果補上。欄位數不符回 None。
    """
    main, bar, see = zh.partition("｜")
    parts = [x.strip() for x in main.split("；")]
    if len(parts) != len(book_index.slots(entry)) or bool(bar) != bool(entry.get("see")):
        return None
    return parts, (see.strip() or None)

# 注號：譯稿用 Unicode 上標數字（「……計畫。¹」），這裡轉成 <sup>1</sup>。
# 不直接把上標字元送進 EPUB：宋體、Charter 只有 ¹²³ 是上標字形，⁴–⁹ 由別的字型
# 補字，大小、粗細、基線都對不齊（實測）。PDF 端由 read_translated_epub 把 <sup> 轉回上標字元，
# 再交給 Typst 的 super 排。
SUPS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUP_RUN = re.compile(f"[{SUPS}]+")
_TO_DIGIT = str.maketrans(SUPS, "0123456789")


def inline(s):
    """段落文字 → XHTML：跳脫後把上標數字串包成 <sup>。"""
    return _SUP_RUN.sub(lambda m: f"<sup>{m.group(0).translate(_TO_DIGIT)}</sup>", html.escape(s))


# 圖說：緊跟在圖後面、原文以「Figure 2.1:」「Fig. A.2:」開頭的段落。抽取時它和圖是兩個
# item；build 把兩者放進同一個 <figure>，PDF 端才能把圖和圖說排在同一頁。
# 掃描數學書（Griffiths）的圖說沒有冒號，只有「Figure 1.43」或「Table 6.1 Magnetic …」：編號後接句尾、
# 或接大寫開頭的圖題才算；「Figure 3.27 summarizes …」這種內文句子不算。
# 中文原書（美國貨幣史）的圖說是「圖1　1867-1960年的存款和通貨」：編號後隔一個空白才算，
# 「圖1顯示……」這種內文句子不算；表名在表的上方，不是圖說，只認「圖」。
_CAPTION = re.compile(r"^(?:Figure|Fig\.|Table)\s*[A-Z]?\d*(?:\.\d+)?\s*:"
                      r"|^(?:Figure|Fig\.|Table)\s+[A-Z]?\d+(?:\.\d+)?(?:\s*$|\s+[A-Z(“\"])"
                      r"|^圖\s?[A-Z]?\d+(?:[.\-]\d+)?\s")


def is_caption(items, n):
    return (n > 0 and items[n - 1]["type"] == "image" and items[n]["type"] == "para"
            and bool(_CAPTION.match(items[n]["text"])))


def figrow_captions(items, n):
    """圖列（掃描數學書裡各有圖說的並排圖）：cells 的 cap 標了有圖說的格子，圖說依序接在圖列後面。
    回傳 [每一格的圖說 item 序號或 None]。"""
    out, k = [], n + 1
    for cell in items[n]["cells"]:
        if cell.get("cap") and k < len(items) and items[k]["type"] == "para" and _CAPTION.match(items[k]["text"]):
            out.append(k); k += 1
        else:
            out.append(None)
    return out


def inline_math(s, mml):
    """段落文字（可能含 $…$ 行內式）→ XHTML。mml：texmath.to_mathml 的結果；轉不了的公式照原樣標紅。"""
    if not mml or "$" not in s:
        return inline(s)
    out = []
    for is_math, part in texmath.split_inline(s):
        if not is_math:
            out.append(inline(part))
        else:
            m = mml.get((part, False))
            out.append(m if m else f'<span class="texerr">${html.escape(part)}$</span>')
    return "".join(out)


def is_cover_chapter(ch, cover):
    """整章只有封面圖一張（原書的封面頁）→ 它就是譯本的封面頁，不另外產生一頁。"""
    items = ch["items"]
    return bool(cover) and len(items) == 1 and items[0]["type"] == "image" and items[0]["file"] == cover


MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp"}


def run(cfg, allow_partial=False):
    book_data = store.load_book(cfg)
    cache = store.load_cache(cfg)

    blocking = verify.run(cfg, verbose=False)
    if blocking and not allow_partial:
        raise SystemExit(f"\n有 {blocking} 個未解決的翻譯問題，拒絕出貨。\n"
                         f"補齊 drafts/ 後重跑 `merge`，或加 --allow-partial 強制產出。")

    def tr(s):
        return cache.get(store.h(s), s)

    # 公式（掃描數學書）：整本書的 LaTeX 一次轉成 MathML
    mml = {}
    if texmath.has_math(book_data):
        pairs = []
        for c in book_data["chapters"]:
            for it in c["items"]:
                if it["type"] == "math":
                    pairs.append((it["text"], True))
                elif it["type"] in store.TEXT_TYPES:
                    pairs += [(t, False) for m, t in texmath.split_inline(tr(it["text"])) if m]
        mml = texmath.to_mathml(pairs, texmath.load_text_table(cfg))
        bad = sorted(t for (t, d), v in mml.items() if v is None)
        if bad:
            print(f"※ {len(bad)} 條公式 temml 轉不了（EPUB 裡以紅字原樣顯示）：" + "；".join(b[:60] for b in bad[:5]))

    out = cfg.output_epub()
    b = epub.EpubBook()
    tgt = cfg.book.get("target_lang", "zh-TW")
    title = cfg.book.get("title_zh") or cfg.book.get("title") or cfg.name
    b.set_identifier(cfg.book.get("identifier") or f"epubtrans-{cfg.name}-{tgt}")
    b.set_title(title)
    b.set_language(tgt)
    if cfg.book.get("author"):
        b.add_author(cfg.book["author"])
    if cfg.book.get("description"):
        b.add_metadata("DC", "description", cfg.book["description"])

    css_text = CSS
    if mml:
        font, math_css = texmath.epub_font_and_css()
        css_text += math_css
        if font:
            b.add_item(epub.EpubItem(uid="mathfont", file_name="fonts/STIXTwoMath.otf",
                                     media_type="font/otf", content=font))
        else:
            print(f"※ 找不到數學字型 {texmath.MATH_FONT}：EPUB 的公式改用閱讀器的預設字型，括號等可能拉不高")
    css = epub.EpubItem(uid="style", file_name="style/main.css",
                        media_type="text/css", content=css_text)
    b.add_item(css)

    imgdir = cfg.wpath("images")
    cover = book_data.get("cover")
    # 原書自己的封面頁（整章只有封面圖）就當譯本封面：不讓 ebooklib 另生一頁封面，
    # 否則讀者會先看到 ebooklib 的封面、翻過目錄再看到一次原書封面（或一張只有
    # 「封面」二字的空白頁 —— Non-Stop 第一版就是這樣）。
    cover_ch = next((c for c in book_data["chapters"] if is_cover_chapter(c, cover)), None)
    img_items = {}
    if os.path.isdir(imgdir):
        for fn in sorted(os.listdir(imgdir)):
            data = open(os.path.join(imgdir, fn), "rb").read()
            if fn == cover:
                b.set_cover(f"images/{fn}", data, create_page=cover_ch is None)
                continue
            media = MEDIA.get(os.path.splitext(fn)[1].lower(), "image/jpeg")
            it = epub.EpubItem(uid=fn, file_name=f"images/{fn}",
                               media_type=media, content=data)
            b.add_item(it)
            img_items[fn] = it

    def render(ch):
        if any("entry" in it for it in ch["items"]):
            return render_index(ch)
        parts, first, in_q, in_l = [], True, False, False

        def txt(s):
            return item_ov.get((ch["id"], s)) or tr(s)

        def close_q():
            nonlocal in_q
            if in_q:
                parts.append("</blockquote>"); in_q = False

        def close_l():
            nonlocal in_l
            if in_l:
                parts.append("</ul>"); in_l = False

        items = ch["items"]
        done = set()                              # 圖列已經一起輸出的圖說

        def figure(file, k):
            if k is None:
                return f'<figure><img src="images/{file}" alt="原書插圖"/></figure>'
            cid = f' id="i{k}"' if (ch["id"], k) in targets else ""
            cap = f"<figcaption{cid}>{inline_math(txt(items[k]['text']), mml)}</figcaption>"
            return f'<figure><img src="images/{file}" alt="原書插圖"/>{cap}</figure>'

        for n, it in enumerate(items):
            t = it["type"]
            # 索引連到的段落加錨點（i＋item 序號）；PDF 端由 read_translated_epub 讀成 Typst 標籤
            aid = f' id="i{n}"' if (ch["id"], n) in targets else ""
            if is_caption(items, n) or n in done:
                continue                          # 已經和上面那張圖一起輸出
            if t != "quote":
                close_q()
            if t != "li":
                close_l()
            if t == "heading":
                tag = f"h{min(4, max(3, it.get('level', 3)))}"
                parts.append(f"<{tag}{aid}>{inline_math(txt(it['text']), mml)}</{tag}>")
            elif t == "para":
                # 公式後面接小寫開頭的段落＝同一句話的延續，不縮排
                cont = n > 0 and items[n - 1]["type"] == "math" and it["text"][:1].islower()
                cls = ' class="nia"' if first or cont else ""
                parts.append(f"<p{cls}{aid}>{inline_math(txt(it['text']), mml)}</p>")
                first = False
            elif t == "quote":
                if not in_q:
                    parts.append("<blockquote>"); in_q = True
                parts.append(f"<p{aid}>{inline_math(txt(it['text']), mml)}</p>")
            elif t == "li":
                if not in_l:
                    parts.append("<ul>"); in_l = True
                parts.append(f"<li{aid}>{inline_math(txt(it['text']), mml)}</li>")
            elif t == "image" and it["file"] in img_items:
                if n + 1 < len(items) and is_caption(items, n + 1):
                    cid = f' id="i{n + 1}"' if (ch["id"], n + 1) in targets else ""
                    cap = f"<figcaption{cid}>{inline_math(txt(items[n + 1]['text']), mml)}</figcaption>"
                else:
                    cap = '<div class="imgcap">（原書插圖，保留原樣）</div>'
                parts.append(f'<figure><img src="images/{it["file"]}" alt="原書插圖"/>{cap}</figure>')
            elif t == "figrow":
                caps = figrow_captions(items, n)
                done.update(k for k in caps if k is not None)
                cells = [figure(c["file"], k) for c, k in zip(it["cells"], caps) if c["file"] in img_items]
                if cells:
                    parts.append(f'<div class="figrow">{"".join(cells)}</div>')
            elif t == "math":
                m = mml.get((it["text"], True))
                body = m if m else f'<span class="texerr">$${html.escape(it["text"])}$$</span>'
                no = f'<span class="eqno">({html.escape(it["tag"])})</span>' if it.get("tag") else ""
                parts.append(f'<div class="eq"{aid}>{body}{no}</div>')
            first = first and t != "para"
        close_q(); close_l()
        return "\n".join(parts) or "<p class='nia'></p>"

    # ── 書末索引（book_index 已把原書頁碼對到段落）─────────────────────
    # 譯本沒有原書的頁碼。EPUB 的每個頁碼換成連到段落的連結，連結文字用章名
    # （同一章好幾處就寫「第八章①②③」）；PDF 由 read_translated_epub 讀出連結目標，
    # Typst 再算出段落所在的頁碼。條目依原書英文字母順序，英文在前、譯名在後。
    chmap = {c["id"]: c for c in book_data["chapters"]}
    targets = set()
    for c in book_data["chapters"]:
        for it in c["items"]:
            for sg in (it.get("entry") or {}).get("segs", []):
                for r in sg["refs"]:
                    for k in ("to", "end"):
                        if r.get(k):
                            targets.add(tuple(r[k]))
    index_bad = []

    def short_title(cid):
        return (overrides.get(cid) or tr(chmap[cid]["title"])).split("　")[0]

    def ref_label(r):
        cid, i = r["to"]
        if not r.get("notes"):
            return short_title(cid)
        items = chmap[cid]["items"]
        h = next((items[j]["text"] for j in range(i, -1, -1) if items[j]["type"] == "heading"), None)
        return f"{tr(h) if h else short_title(cid)}注{'–'.join(map(str, r['notes']))}"

    def ref_links(refs):
        groups = []                                  # [(章名, [ref…])]，相鄰同章併一組
        for r in refs:
            if not r.get("to"):
                continue
            lb = ref_label(r)
            if groups and groups[-1][0] == lb and not r.get("notes"):
                groups[-1][1].append(r)
            else:
                groups.append((lb, [r]))

        def a(r, text):
            href = f'{r["to"][0]}.xhtml#i{r["to"][1]}'
            attrs = ""
            if r.get("end"):
                attrs += f' data-end="{r["end"][0]}.xhtml#i{r["end"][1]}"'
            if r.get("notes"):
                attrs += f' data-note="{"–".join(map(str, r["notes"]))}"'
            if r.get("fig"):
                attrs += ' data-fig="1"'
            return f'<a class="ixr" href="{href}"{attrs}>{text}</a>'
        out = []
        for lb, rs in groups:
            if len(rs) == 1:
                out.append(a(rs[0], html.escape(lb)))
            else:
                out.append(html.escape(lb) + "".join(
                    a(r, CIRCLED[k] if k < len(CIRCLED) else f"({k + 1})") for k, r in enumerate(rs)))
        return "、".join(out)

    def render_index(ch):
        parts = ['<p class="ixnote">條目依原書英文字母順序排列；點選章名可跳到內文。</p>']
        letter = None
        for it in ch["items"]:
            e = it.get("entry")
            if e is None:
                parts.append(f"<p>{inline(tr(it['text']))}</p>")
                continue
            zh = tr(it["text"])
            got = index_zh(zh, e) if zh != it["text"] else None
            if got is None:
                if zh != it["text"]:
                    index_bad.append((ch["id"], it["text"], zh))
                got = (book_index.slots(e), e.get("see"))  # 未譯：退回原文
            names, see = got
            first = e["head"][:1].upper()
            first = first if first.isalpha() else "#"
            cls = "ix ixfirst" if first != letter else "ix"
            letter = first
            k = 1
            # 譯名與原文相同（只出現在注釋書目裡、正文沒有中文名的人名）就只寫一次
            zh_head = "" if names[0] == e["head"] else f'　<span class="ixzh">{inline(names[0])}</span>'
            h = [f'<span class="ixen">{html.escape(e["head"])}</span>{zh_head}']
            has_refs = False
            for n, sg in enumerate(e["segs"]):
                label = ""
                if sg["label"]:
                    label = f'<span class="ixzh">{inline(names[k])}</span>　'
                    k += 1
                sep = ("：" if sg["label"] else "　") if n == 0 else "；"
                links = ref_links(sg["refs"])
                has_refs = has_refs or bool(links)
                h.append(f'{sep}<span class="ixseg">{label}{links}</span>')
            if see:
                h.append(f'{"。" if has_refs else "　"}<span class="ixsee">{inline(see)}</span>')
            parts.append(f'<p class="{cls}">{"".join(h)}</p>')
        return "\n".join(parts)

    # 同一個原文字串當作兩章的標題時（例如 Atlas 的 "Gratitude" 既是情緒詞條
    # 也是書末致謝），md5 快取只會有一份譯文。用 YAML 的 book.title_overrides
    # 按章節 id 指定，避免把書本專屬事實寫進程式碼。
    overrides = cfg.book.get("title_overrides") or {}
    # 通用覆寫：[{cid, source, zh}]。source 省略時等同該章標題。
    # 用於 md5 快取去重的固有盲點 —— 同一個原文字串在不同位置需要不同譯文。
    item_ov = {}
    for o in (cfg.book.get("overrides") or []):
        item_ov[(o.get("cid"), o.get("source"))] = o["zh"]

    # 閱讀順序是「封面 → 目錄 → 內文」。封面那一頁不能只是把 "cover" 塞進 spine ——
    # ebooklib 的 EpubCoverHtml 建構時就寫死 is_linear=False，writer 查到這個旗標會
    # 補上 linear="no"（「不在主要閱讀順序」），閱讀器照樣跳過，翻開書還是目錄頁。
    # 要當第一頁就得連旗標一起翻掉。沒有封面的書 get_item_with_id 回 None，退回 ["nav"]。
    head = ["nav"]
    cover_page = b.get_item_with_id("cover")     # set_cover(create_page=True) 建的那頁
    if cover_page is not None:
        cover_page.is_linear = True
        head = ["cover", "nav"]
    elif cover_ch is not None:
        head = []                                # 封面章自己排在 nav 之前，見下
    # 不要往 b.guide 塞 cover。ebooklib 的 epub3_landmark 預設開著，book.guide 一有東西
    # 就會在 nav.xhtml 尾巴長出 <nav epub:type="landmarks">，而閱讀器把它當**可見內容**
    # 渲染 —— 目錄頁下面會多出一個「Guide → 封面」的區塊。封面能當第一頁靠的是上面的
    # spine 順序，guide 對此毫無貢獻。

    spine, toc, section, children = head, [], None, None
    for ch in book_data["chapters"]:
        zh = overrides.get(ch["id"]) or tr(ch["title"])
        c = epub.EpubHtml(title=zh, file_name=f"{ch['id']}.xhtml", lang=tgt)
        tag = "h1" if ch["level"] == 1 else "h2"
        if ch is cover_ch:
            # 封面頁只放圖、不放標題，排在目錄（nav）之前；目錄裡仍列「封面」一筆
            c.content = (f'<html><head></head><body><div class="cover">'
                         f'<img src="images/{cover}" alt="{html.escape(zh)}"/></div></body></html>')
        else:
            c.content = ("<html><head></head><body>"
                         f"<{tag}>{html.escape(zh)}</{tag}>\n" + render(ch) + "</body></html>")
        c.add_item(css)
        if "<math" in c.content:
            c.properties.append("mathml")
        b.add_item(c)
        if ch is cover_ch:
            spine.insert(0, c)
            spine.insert(1, "nav")
        else:
            spine.append(c)
        if ch["level"] == 1:
            if section is not None:
                toc.append((section, children))
            children = []
            section = c
        else:
            (children if section is not None else toc).append(c)
    if section is not None:
        toc.append((section, children))

    colo = cfg.fill_translator(cfg.book.get("colophon"))
    if colo:
        p = epub.EpubHtml(title="版權頁", file_name="colophon.xhtml", lang=tgt)
        p.content = "<html><head></head><body><h2>版權頁</h2>" + \
                    "".join(f'<p class="nia">{html.escape(x)}</p>' for x in colo.splitlines() if x.strip()) + \
                    "</body></html>"
        p.add_item(css)
        b.add_item(p); spine.append(p); toc.append(p)

    if index_bad:
        rows = "\n".join(f"  [{c}] {s[:50]}\n      → {z[:60]}" for c, s, z in index_bad[:10])
        msg = (f"\n索引有 {len(index_bad)} 條譯稿的欄位數與原文不符（「；」分隔條目與子條目、"
               f"「｜」後接參見），先改 drafts 再 build：\n{rows}")
        if not allow_partial:
            raise SystemExit(msg)
        print(msg)

    b.toc = toc
    b.add_item(epub.EpubNcx())
    b.add_item(epub.EpubNav())
    b.spine = spine
    epub.write_epub(out, b)

    total = translated = 0
    for ch in book_data["chapters"]:
        total += 1
        translated += store.h(ch["title"]) in cache
        for it in ch["items"]:
            if it["type"] in store.TEXT_TYPES:
                total += 1
                translated += store.h(it["text"]) in cache
    print(f"\n寫入 {out}")
    print(f"章節={len(book_data['chapters'])}　圖片={len(img_items)}　"
          f"封面={cover}　譯出段落={translated}/{total}")
