"""EPUB → content.json（結構化書稿）。

為什麼不直接把 EPUB 的 XHTML 餵給排版器：EPUB 的樣式是為了螢幕捲動而寫的，
裡面混雜了閱讀器專用的 class、錨點、空 span。印刷版心要的是「純粹的結構」——
這是第幾層標題、這是正文段、這是引文、這是圖——版面規則由 book.typ 一處決定。
所以這一層只負責把結構抽乾淨，不帶任何樣式。

抽出來的結構走 JSON 交給 Typst（`json()` 讀檔），不是把文字串成 Typst 原始碼。
理由是逃脫字元：書裡到處是 # * _ [ ] < > @ ~ $ 這些 Typst 的標記符號，
串字串遲早會炸；走 JSON 則完全不經過 Typst 的 markup 解析器。
"""
import json, os, re, zipfile, warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "img", "blockquote"]
# 這些 class 一望即知是版面殘留，不是內容
NOISE_CLASS = re.compile(r"kobo|pagebreak|page-?num", re.I)

# 注號：build 把譯稿的上標數字寫成 <sup>1</sup>，這裡轉回上標字元（¹），
# 文字才能維持一個純字串走 JSON；book.typ 再用 show 規則把上標字元排成 super。
SUPS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SPLIT = re.compile(r"^(.*)_split_(\d+)$")
_TO_SUP = str.maketrans("0123456789", SUPS)


# 公式（掃描數學書）：build 把 LaTeX 轉成 MathML、annotation 附 TeX 原文。這裡取回 TeX：
# 行內式換成「私用區字元包住的 TeX」留在段落字串裡（MATH_L…MATH_R），book.typ 再切開交給 mitex；
# 獨立公式（div.eq）成為 {"k": "eq", "tex", "tag"} 區塊。
MATH_L, MATH_R = "\ue000", "\ue001"


def _tex(m):
    a = m.find("annotation")
    return a.get_text() if a is not None else m.get_text()


def _math_to_text(soup, body):
    for div in body.find_all("div", class_="eq"):
        m = div.find("math")
        no = div.find("span", class_="eqno")
        p = soup.new_tag("p")
        p["class"] = "__eq"
        p["data-tex"] = _tex(m) if m is not None else ""
        if no is not None:
            p["data-tag"] = no.get_text().strip().strip("()")
        if div.get("id"):
            p["id"] = div["id"]
        div.replace_with(p)
    for m in body.find_all("math"):
        parent = m.parent
        m.replace_with(MATH_L + _tex(m) + MATH_R)
        # 不併的話公式是獨立的文字節點，get_text(" ") 會在它前後插空格（「2𝓇 .」）
        parent.smooth()


# 原書就是中文的 EPUB（只排版列印）常把注號寫成 <sup>[1]</sup> 或
# <span class="math-super"><a href="#ff1">[1]</a></span>：方括號一併拿掉，照樣排成上標。
# 注文開頭那個連回正文的「[1]」不在上標裡，維持原樣。
_NOTE_REF = re.compile(r"^\[?(\d+)\]?$")


def _is_sup(tag):
    return tag.name == "sup" or (tag.name == "span" and "super" in " ".join(tag.get("class") or []))


def _sup_to_chars(el):
    hit = False
    for sup in el.find_all(_is_sup):
        m = _NOTE_REF.match(sup.get_text().strip())
        if m:
            sup.replace_with(m.group(1).translate(_TO_SUP))
            hit = True
    if hit:
        # 不併的話上標字元是獨立的文字節點，get_text(" ") 會在它前面插一個空格
        el.smooth()


# 原書就是中文的 EPUB 不用 <figure>：圖和圖說包在同一個 div 裡（<div class="tupian"><img/><p>圖1　…</p></div>）。
# 圖說不綁住圖，PDF 讓圖浮到頁頂、圖說卻留在正文裡，兩者隔著幾段字。
_CAP_CLASS = re.compile(r"caption|tushuo|figcap|picnote", re.I)
_CAP_TEXT = re.compile(r"^(圖|表|Figure|Fig\.|Table)\s*[\dA-Z０-９]", re.I)


def _div_caption(img):
    """img 所在的 div 裡緊接在圖後面、看起來是圖說的那個 <p>；沒有就 None。"""
    box = img.parent
    if box is None or box.name != "div" or len(box.find_all("img")) != 1:
        return None
    p = img.find_next_sibling("p")
    if p is None or p.find("img") is not None:
        return None
    if _CAP_CLASS.search(" ".join(p.get("class") or [])) or _CAP_TEXT.match(_clean(p.get_text())):
        return p
    return None


def _anchor(href, doc):
    """「c010.xhtml#i12」→ Typst 標籤名「c010-i12」（檔名去副檔名＋錨點）。"""
    if not href:
        return None
    f, _, frag = href.partition("#")
    return f"{os.path.splitext(os.path.basename(f or doc))[0]}-{frag}"


def _index_entry(el, doc):
    """build 產生的索引條目（p.ix）→ 結構。頁碼由 Typst 依連結目標算，連結文字（章名）不用。"""
    zh = el.find("span", class_="ixzh", recursive=False)
    segs = []
    for sg in el.find_all("span", class_="ixseg"):
        z = sg.find("span", class_="ixzh")
        segs.append({"zh": _clean(z.get_text()) if z else None,
                     "refs": [{"to": _anchor(a.get("href"), doc), "end": _anchor(a.get("data-end"), doc),
                               "note": a.get("data-note"), "fig": a.get("data-fig") == "1"}
                              for a in sg.find_all("a", class_="ixr")]})
    see = el.find("span", class_="ixsee")
    return {"k": "ix", "en": _clean(el.find("span", class_="ixen").get_text()),
            "zh": _clean(zh.get_text()) if zh else "", "segs": segs,
            "see": _clean(see.get_text()) if see else None,
            "first": "ixfirst" in (el.get("class") or [])}


def _clean(t):
    # 全形空格（U+3000）不能跟著壓。Python 的 \s 會匹配到它，第一版因此把
    # 「第一部　艙區」壓成「第一部 艙區」，目錄與書眉的部名都擠在一起。
    return re.sub(r"[^\S　]+", " ", t or "").strip(" \t\r\n")


def _is_rule_image(data):
    """一兩個像素高的裝飾線（Irrational Exuberance 每章章首、各部扉頁的分隔線圖）。
    螢幕上照原尺寸顯示只是一道細線；排版時圖寬按版心比例放大，會變成一條粗黑槓，
    部扉頁上的那張還會被擠到下一頁，讓後面的章首落到左頁。這種圖沒有內容，PDF 不印。"""
    import pymupdf
    shown = pymupdf.TOOLS.mupdf_display_errors()
    pymupdf.TOOLS.mupdf_display_errors(False)   # 有些圖的 ICC 設定檔 MuPDF 會抱怨，與判斷無關
    try:
        pm = pymupdf.Pixmap(data)
    except Exception:
        return False
    finally:
        pymupdf.TOOLS.mupdf_display_errors(shown)
    return pm.height <= 4 and pm.width >= 8 * pm.height


class Epub:
    def __init__(self, path):
        self.zf = zipfile.ZipFile(path)
        self.names = set(self.zf.namelist())
        self.opf = self._opf_path()
        self.opf_dir = os.path.dirname(self.opf)
        self._parse_opf()
        self.inline_images, self.unmapped_inline = {}, []

    # ── 骨架 ─────────────────────────────────────────────────────────
    def _opf_path(self):
        x = BeautifulSoup(self.zf.read("META-INF/container.xml").decode("utf-8"), "xml")
        return x.find("rootfile")["full-path"]

    def _res(self, href):
        href = href.split("#")[0]
        p = os.path.normpath(os.path.join(self.opf_dir, href)) if self.opf_dir else href
        return p.replace("\\", "/")

    def _parse_opf(self):
        s = BeautifulSoup(self.zf.read(self.opf).decode("utf-8"), "xml")
        self.manifest = {i.get("id"): i.get("href") for i in s.find_all("item")}
        self.props = {i.get("id"): (i.get("properties") or "") for i in s.find_all("item")}
        self.spine = [r.get("idref") for r in s.find_all("itemref")]
        self.meta = {}
        for tag, key in (("title", "title"), ("creator", "author"),
                         ("language", "language"), ("publisher", "publisher")):
            el = s.find(re.compile(rf"^(dc:)?{tag}$"))
            if el:
                self.meta[key] = _clean(el.get_text())
        # 封面圖：<meta name="cover"> 優先，其次 properties="cover-image"
        cid = next((m.get("content") for m in s.find_all("meta")
                    if (m.get("name") or "").lower() == "cover"), None)
        if not cid:
            cid = next((i for i, p in self.props.items() if "cover-image" in p), None)
        self.cover_href = self._res(self.manifest[cid]) if cid in self.manifest else None
        self.nav_ids = {i for i, p in self.props.items() if "nav" in p.split()}

    # ── 目錄層級 ─────────────────────────────────────────────────────
    def toc_levels(self):
        """從 nav.xhtml 的巢狀 <ol> 推出每份文件的層級：{檔名: 層級}。

        EPUB 的章節層級在 XHTML 本身常常看不出來（同樣是 <h2>，可能是部標題也
        可能是章標題），但 nav 的縮排一定是對的，所以這裡以 nav 為準、
        文件內的 h1/h2 當退路。
        """
        nid = next((i for i in self.nav_ids if i in self.manifest), None)
        if not nid:
            return {}
        soup = BeautifulSoup(self.zf.read(self._res(self.manifest[nid])).decode("utf-8"), "lxml")
        nav = soup.find("nav") or soup
        out = {}
        for a in nav.find_all("a"):
            href = a.get("href")
            if not href:
                continue
            depth = len(a.find_parents("ol"))
            out[self._res(href)] = (max(1, depth), _clean(a.get_text()))
        return out

    # ── 段落中的小圖 ─────────────────────────────────────────────────
    def _inline_images(self, body, href):
        """夾在句子裡的小圖（原書用圖片排的帶分數「64 64/99」、特殊符號）。
        版面只排純文字段落，圖會被拉出來另起一行、句子留個缺口；
        print.inline_images 指定替代文字（{檔名: 文字}）的就換成字，沒指定的列出來提醒。"""
        for img in body.find_all("img"):
            p = img.find_parent("p")
            if p is None or not _clean(p.get_text()):
                continue
            name = os.path.basename(img.get("src") or "")
            if name in self.inline_images:
                img.replace_with(str(self.inline_images[name]))
                p.smooth()
            else:
                self.unmapped_inline.append(f"{os.path.basename(href)}:{name}")

    # ── 內容 ─────────────────────────────────────────────────────────
    def read(self):
        levels = self.toc_levels()
        chapters, images = [], {}
        prev_title_level = None

        for sid in self.spine:
            if sid in self.nav_ids or sid not in self.manifest:
                continue
            href = self._res(self.manifest[sid])
            if href not in self.names or not href.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            soup = BeautifulSoup(self.zf.read(href).decode("utf-8", "ignore"), "lxml")
            body = soup.body or soup
            _math_to_text(soup, body)
            self._inline_images(body, href)

            blocks, title, title_level, row_el = [], None, None, None
            taken = set()      # 已收成圖說的 <p>，不再當正文段
            for el in body.find_all(BLOCK_TAGS):
                # blockquote 只當容器，內容由它底下的 p 負責
                if el.name == "blockquote" or id(el) in taken:
                    continue
                if el.find_parent("blockquote") is not None and el.name == "p":
                    kind = "quote"
                elif el.name == "li":
                    kind = "li"
                elif el.name == "img":
                    # src 相對於這份 XHTML，不是相對於 OPF。href 已經含 OPF 目錄，
                    # 再走 _res 會多疊一層（EPUB/EPUB/images/…），圖全部找不到 ——
                    # House of Debt 的 18 張圖表第一版就這樣從 PDF 裡整批消失。
                    src = os.path.normpath(os.path.join(os.path.dirname(href), el.get("src") or ""))
                    src = src.replace("\\", "/")
                    if src in self.names and _is_rule_image(self.zf.read(src)):
                        continue
                    if src in self.names:
                        name = os.path.basename(src)
                        images[name] = src
                        blk = {"k": "img", "file": name}
                        # 圖說跟著圖走（build 把兩者放進同一個 <figure>）：排版時才能綁在同一頁
                        fig = el.find_parent("figure")
                        cap = fig.find("figcaption") if fig is not None else None
                        if cap is None:
                            cap = _div_caption(el)
                            if cap is not None:
                                taken.add(id(cap))
                        if cap is not None:
                            blk["cap"] = _clean(cap.get_text(" ", strip=True))
                            if cap.get("id"):
                                blk["id"] = _anchor("#" + cap["id"], href)
                        # 圖列（div.figrow，各有圖說的並排圖）：同一列的圖收成一個區塊，PDF 並排
                        row = el.find_parent("div", class_="figrow")
                        if row is None:
                            blocks.append(blk)
                        elif blocks and blocks[-1]["k"] == "figrow" and row is row_el:
                            blocks[-1]["cells"].append(blk)
                        else:
                            blocks.append({"k": "figrow", "cells": [blk]})
                            row_el = row
                    continue
                elif el.name[0] == "h":
                    kind = "h"
                else:
                    kind = "p"

                if NOISE_CLASS.search(" ".join(el.get("class") or [])):
                    continue
                if el.name == "p" and "__eq" in (el.get("class") or []):
                    blk = {"k": "eq", "tex": el.get("data-tex") or "", "tag": el.get("data-tag")}
                    if el.get("id"):
                        blk["id"] = _anchor("#" + el["id"], href)
                    blocks.append(blk)
                    continue
                if el.name == "p" and "ix" in (el.get("class") or []):
                    _sup_to_chars(el)
                    blocks.append(_index_entry(el, href))
                    continue
                if el.name == "p" and "ixnote" in (el.get("class") or []):
                    blocks.append({"k": "ixnote"})     # 說明文字由 book.typ 依紙本改寫
                    continue
                _sup_to_chars(el)
                txt = _clean(el.get_text(" ", strip=True))
                if not txt:
                    continue

                if kind == "h":
                    lv = int(el.name[1])
                    if title is None:          # 本文件第一個標題＝章標題
                        title, title_level = txt, lv
                        continue
                    blocks.append({"k": "h", "level": lv, "t": txt})
                else:
                    blocks.append({"k": kind, "t": txt})
                # 索引連到的段落（build 加的 id="i12"）→ Typst 標籤，給索引算頁碼
                if el.get("id") and blocks and blocks[-1].get("t") == txt:
                    blocks[-1]["id"] = _anchor("#" + el["id"], href)

            nav_hit = levels.get(href)
            if nav_hit:
                level, nav_title = nav_hit
                title = title or nav_title
            else:
                level = 1 if (title_level or 1) <= 1 else 2
            if title is None and not blocks:
                continue
            # calibre 把過長的 XHTML 從中間切開（part0012_split_000、_split_001…）：
            # 後半段以節標題（比前半段的章標題深一層以上）開頭，是同一章的續篇，不是新章。
            # 《美國貨幣史》第 7 章因此在目錄裡多出一個「7.4」章，章首另起新頁。
            stem = os.path.splitext(os.path.basename(href))[0]
            sm = _SPLIT.match(stem)
            prev = chapters[-1] if chapters else None
            if (sm and int(sm.group(2)) > 0 and prev and not nav_hit
                    and _SPLIT.match(prev["id"]) and _SPLIT.match(prev["id"]).group(1) == sm.group(1)
                    and title_level and prev_title_level and title_level > prev_title_level):
                prev["blocks"].append({"k": "h", "level": title_level, "t": title})
                prev["blocks"].extend(blocks)
                continue
            prev_title_level = title_level
            chapters.append({
                "id": os.path.splitext(os.path.basename(href))[0],
                "level": level,
                "title": title or "",
                "blocks": blocks,
            })

        return {"meta": self.meta, "chapters": chapters}, images

    def extract_images(self, images, outdir):
        os.makedirs(outdir, exist_ok=True)
        for name, src in images.items():
            open(os.path.join(outdir, name), "wb").write(self.zf.read(src))
        if self.cover_href and self.cover_href in self.names:
            ext = os.path.splitext(self.cover_href)[1] or ".jpg"
            open(os.path.join(outdir, "cover" + ext), "wb").write(self.zf.read(self.cover_href))
            return "cover" + ext
        return None


def run(epub_path, workdir, inline_images=None):
    ep = Epub(epub_path)
    ep.inline_images = inline_images or {}
    book, images = ep.read()
    if ep.unmapped_inline:
        print(f"⚠ 段落中的小圖 {len(ep.unmapped_inline)} 張會另起一行（print.inline_images 可指定替代文字）："
              + "、".join(ep.unmapped_inline[:10]))
    cover = ep.extract_images(images, os.path.join(workdir, "images"))
    book["cover"] = cover
    n_blocks = sum(len(c["blocks"]) for c in book["chapters"])
    print(f"章節={len(book['chapters'])}　區塊={n_blocks}　圖片={len(images)}　封面={cover or '無'}")
    return book
