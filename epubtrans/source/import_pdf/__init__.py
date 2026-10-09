"""PDF → work/book.json（＋ work/images/、work/extract_report.json）。

逐頁判斷來源：有文字層的頁直接讀（textlayer），沒有的（掃描頁）走 OCR（ocr）；兩者都產出
「版面行」，交給 structure 推回段落與章節。book.json 的格式與 EPUB 抽出來的相同，
每個項目多帶 page（原書 PDF 頁碼，從 1 起算），dump／review 時可以對回原頁；下游不讀這個欄位。

書本專屬的調整寫在 system_prompts.yaml 的 pdf: 區（見 DEFAULTS），不寫進程式碼。
抽取結果不對時先看 extract_report.json，再用 `python -m epubtrans page "書名" 頁碼` 看原頁。
"""
import json, os, re, shutil
import pymupdf
from . import structure, textlayer

DEFAULTS = {
    "mode": "auto",            # auto：逐頁判斷；text：只用文字層；ocr：全部重做 OCR（文字層品質差時）；
                               # vlm：掃描數學書，讀 vlm_worker 的整頁 Markdown＋LaTeX 快取（work/vlm/）
    "ocr_languages": None,     # OCR 語言，例：[en-US]；省略時依 book.source_lang 推定
    "ocr_dpi": 300,
    "skip_pages": [],          # 略過的頁（PDF 頁碼，從 1 起算），例：[1, 2, "5-8"]
    "cover_page": "auto",      # auto：第 1 頁幾乎只有圖就當封面；也可寫頁碼，或 null 表示沒有封面
    "columns": 1,              # 雙欄排版寫 2
    "use_outline": True,       # 有 PDF 書籤就依書籤切章
    "chapter_levels": 2,       # 書籤前幾層當章節
    "heading_sizes": {},       # 沒有書籤時依字級切章，自動判斷不對就指定：{22: 1, 15: 2}（字級 pt → 層級，0＝不切）
    "chapters": [],            # 手動切章，優先於書籤：[{page: 12, title: "Chapter One", level: 1}]
    "footnotes": "end",        # end：收到該章結尾；drop：刪掉
    "footnote_marks": None,    # 只認這些標記開頭的註腳，例："*†"（頁底的編號清單、圖片出處被誤認成註腳時）
    "plate_pages": [],         # 掃描書的圖版頁：「Note(s):」以上整片當一張圖（圖表多、自動找圖切不好時），例：["195-204"]
    "figure_boxes": {},        # 掃描書自動找圖失敗的頁，手動指定插圖範圍（PDF 點）：{286: [[117, 212, 512, 458]]}
    "framed_figures": False,
    "drop_lines": [],          # OCR 雜訊行（透印、污漬讀成的亂碼），分段前拿掉：[{page: 151, text: "patre the"}]   # 掃描書裡有框線的表格整塊當圖（框起來的引文不算：框裡幾乎都是長行）
    "skip_toc_pages": True,    # 略過原書的目錄頁與索引頁（大半行以頁碼結尾的頁）
    "min_text_chars": 30,      # auto 模式下，文字層少於這個字數的頁視為掃描頁
    "layout": False,           # 掃描頁用版面模型的框找圖（先跑 `layout` 指令產生 work/layout/）；沒有快取的頁退回墨水區塊推算
    "layout_formulas": True,   # layout: true 時，獨立公式框也裁成圖片（Vision 讀不了公式）
}
LANGS = {"english": "en-US", "french": "fr-FR", "german": "de-DE", "spanish": "es-ES", "italian": "it-IT",
         "portuguese": "pt-BR", "japanese": "ja-JP", "korean": "ko-KR", "chinese": "zh-Hant"}


def options(cfg):
    opts = dict(DEFAULTS)
    opts.update(cfg.get("pdf", default={}) or {})
    if not opts["ocr_languages"]:
        lang = (cfg.book.get("source_lang") or "English").strip().lower()
        opts["ocr_languages"] = [LANGS.get(lang, "en-US")]
    return opts


def parse_pages(spec, n):
    out = set()
    for s in spec or []:
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", str(s))
        if not m:
            raise SystemExit(f"pdf.skip_pages 格式不對：{s!r}（寫頁碼或 \"5-8\"）")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out.update(i - 1 for i in range(a, b + 1) if 1 <= i <= n)
    return out


def _cover_page(doc, opts):
    c = opts["cover_page"]
    if c in (None, False, "none"):
        return None
    if c == "auto":
        page = doc[0]
        area = page.rect.width * page.rect.height
        big = any((r.width * r.height) > 0.5 * area for r in _image_rects(page))
        return 0 if big and textlayer.text_chars(page) <= 80 else None
    return int(c) - 1


def _cover(doc, opts, imgdir):
    pno = _cover_page(doc, opts)
    if pno is None:
        return None
    pix = doc[pno].get_pixmap(dpi=150)
    pix.save(os.path.join(imgdir, "cover.jpg"), jpg_quality=88)
    return pno


def _looks_scanned(page, opts):
    """字很少、而且有一張圖蓋住大半頁面 → 掃描頁。字少但沒有大圖的是部扉頁、空白頁，照讀文字層。"""
    if textlayer.text_chars(page) >= opts["min_text_chars"]:
        return False
    area = page.rect.width * page.rect.height
    return any(r.width * r.height > 0.5 * area for r in _image_rects(page))


def _image_rects(page):
    rects = []
    for img in page.get_images(full=True):
        try:
            rects.extend(page.get_image_rects(img[0]))
        except Exception:
            pass
    return rects


def run(cfg):
    src = cfg.source_file()
    opts = options(cfg)
    doc = pymupdf.open(src)
    imgdir = cfg.wpath("images")
    shutil.rmtree(imgdir, ignore_errors=True)
    os.makedirs(imgdir)

    skip = parse_pages(opts["skip_pages"], len(doc))
    cover = _cover(doc, opts, imgdir)
    if cover is not None:
        skip.add(cover)
    if opts["mode"] == "vlm":
        return _run_vlm(cfg, doc, skip, cover, imgdir)

    pages, seen, ocr_pages = [], {}, []
    for pno in range(len(doc)):
        if pno in skip:
            continue
        page = doc[pno]
        if _page_mode(page, opts) == "text":
            pages.append(textlayer.read_page(page, pno, imgdir, seen))
        else:
            ocr_pages.append(pno)
    if ocr_pages:
        pages += _ocr(cfg, doc, ocr_pages, opts)
        pages.sort(key=lambda p: p["no"])
    ocr_figures = [(p["no"] + 1, len(p["images"]), p.get("dropped_in_figures", 0))
                   for p in pages if p["mode"] == "ocr" and p["images"]]

    meta = doc.metadata or {}
    title = cfg.book.get("title") or meta.get("title") or cfg.name
    chapters, report = structure.build(pages, doc.get_toc(simple=False), opts, title)

    out_chapters = []
    for i, c in enumerate(chapters):
        items = [_item(b) for b in c["blocks"]]
        items = [it for it in items if it]
        out_chapters.append({"level": c["level"], "title": c["title"], "id": f"c{i:03d}",
                             "page": (c["blocks"][0]["page"] + 1) if c["blocks"] else None, "items": items})
    out_chapters = [c for c in out_chapters if c["items"] or c["title"]]
    book = {
        "title": title,
        "author": cfg.book.get("author") or meta.get("author") or "",
        "source_language": cfg.book.get("source_lang") or "",
        "source_format": "pdf",
        "cover": "cover.jpg" if cover is not None else None,
        "chapters": out_chapters,
    }
    json.dump(book, open(cfg.wpath("book.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report["ocr_figures"] = ocr_figures
    if opts["layout"]:
        report["layout"] = _layout_report(pages)
    _report(cfg, book, report, len(doc), skip, cover, ocr_pages)


def _page_mode(page, opts):
    mode = opts["mode"]
    if mode == "auto":
        mode = "ocr" if _looks_scanned(page, opts) else "text"
    return mode


def ocr_page_numbers(cfg):
    """extract 會走 OCR 的頁（從 0 起算）：`layout` 指令只跑這些頁。"""
    opts = options(cfg)
    doc = pymupdf.open(cfg.source_file())
    if opts["mode"] == "vlm":
        return []
    skip = parse_pages(opts["skip_pages"], len(doc)) | {_cover_page(doc, opts)}
    return [p for p in range(len(doc)) if p not in skip and _page_mode(doc[p], opts) != "text"]


def _layout_report(pages):
    ocr = [p for p in pages if p["mode"] == "ocr"]
    by = {}
    for p in ocr:
        by.setdefault(p.get("figure_source"), []).append(p["no"] + 1)
    notes = [(p["no"] + 1, p["layout_note"]) for p in ocr if p.get("layout_note")]
    return {"pages_by_source": {k: v for k, v in by.items() if k},
            "formulas": sum(n["formulas"] for _, n in notes),
            "skipped_boxes": [dict(b, page=pno) for pno, n in notes for b in n["skipped"]]}


def _item(b):
    if b["type"] == "image":
        return {"type": "image", "file": b["file"], "page": b["page"] + 1}
    text = re.sub(r"\s+", " ", b.get("text") or "").strip()
    if not text:
        return None
    if b["type"] == "li":
        text = re.sub(r"^[•●◦▪▫■□‣⁃∙·]\s*", "", text)
    it = {"type": b["type"], "text": text, "page": b["page"] + 1}
    last = max((r["page"] for r in b.get("rows") or [] if "page" in r), default=b["page"])
    if last != b["page"]:
        it["page_end"] = last + 1               # 跨頁的段落
    if b["type"] == "heading":
        it["level"] = b.get("level") or 3
    if b.get("conf") is not None:
        it["conf"] = round(b["conf"], 2)
    return it


def _run_vlm(cfg, doc, skip, cover, imgdir):
    from . import vlm
    pnos = [p for p in range(len(doc)) if p not in skip]
    pages, missing = vlm.load_pages(cfg, doc, pnos)
    chapters, rep = vlm.build_book(cfg, doc, pages, imgdir)
    meta = doc.metadata or {}
    out = [{"level": c["level"], "title": c["title"], "id": f"c{i:03d}", "page": c["page"], "items": c["items"]}
           for i, c in enumerate(chapters)]
    book = {"title": cfg.book.get("title") or meta.get("title") or cfg.name,
            "author": cfg.book.get("author") or meta.get("author") or "",
            "source_language": cfg.book.get("source_lang") or "", "source_format": "pdf",
            "cover": "cover.jpg" if cover is not None else None, "chapters": out}
    json.dump(book, open(cfg.wpath("book.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cnt = {}
    for c in out:
        for it in c["items"]:
            cnt[it["type"]] = cnt.get(it["type"], 0) + 1
    rep.update({"pages": len(doc), "mode": "vlm", "missing_pages": missing, "skipped_pages": sorted(p + 1 for p in skip),
                "cover_page": None if cover is None else cover + 1,
                "chapters": [{"id": c["id"], "level": c["level"], "title": c["title"], "page": c["page"],
                              "items": len(c["items"])} for c in out]})
    json.dump(rep, open(cfg.wpath("extract_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"PDF {len(doc)} 頁：VLM 快取 {len(pages)} 頁（缺 {len(missing)}）　略過 {len(skip)}（封面 {rep['cover_page'] or '無'}）")
    print(f"獨立公式 {rep['math']} 條（沒有編號 {rep['untagged_math']}）　行內公式 {rep['inline_math']} 處　"
          f"圖表裁圖 {rep['images']} 張")
    if rep["figure_mismatch"]:
        print(f"※ VLM 漏寫的圖（依高度推定位置、圖說用 Vision 補讀，請用 page 確認）：第 {rep['figure_mismatch'][:20]} 頁"
              f"{'…' if len(rep['figure_mismatch']) > 20 else ''}")
    if rep["loop_stopped"]:
        print(f"※ OCR 陷入重複、提前結束的頁（內容可能不完整）：{rep['loop_stopped']}")
    if rep["truncated"]:
        print(f"※ OCR 輸出達上限的頁：{rep['truncated']}")
    print(f"章節={len(out)}  " + "  ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    print(f"寫入 {cfg.wpath('book.json')}（抽取報告：{cfg.wpath('extract_report.json')}）")


def _ocr(cfg, doc, pnos, opts):
    from . import ocr
    return ocr.read_pages(cfg, doc, pnos, opts)


def _report(cfg, book, report, n_pages, skip, cover, ocr_pages):
    cnt = {}
    for c in book["chapters"]:
        for it in c["items"]:
            cnt[it["type"]] = cnt.get(it["type"], 0) + 1
    removed = report.pop("removed_headers")
    low = [{"id": c["id"], "page": it["page"], "conf": it["conf"], "text": it["text"][:80]}
           for c in book["chapters"] for it in c["items"] if it.get("conf") is not None and it["conf"] <= 0.5]
    report.update({
        "low_confidence": low,
        "pages": n_pages, "cover_page": None if cover is None else cover + 1,
        "skipped_pages": sorted(p + 1 for p in skip), "ocr_pages": [p + 1 for p in ocr_pages],
        "removed_headers": removed.most_common(30),
        "chapters": [{"id": c["id"], "level": c["level"], "title": c["title"], "page": c["page"],
                      "items": len(c["items"])} for c in book["chapters"]],
    })
    json.dump(report, open(cfg.wpath("extract_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"PDF {n_pages} 頁：文字層 {n_pages - len(skip) - len(ocr_pages)}　OCR {len(ocr_pages)}　"
          f"略過 {len(skip)}（封面 {report['cover_page'] or '無'}）　目錄／索引頁 {report['toc_pages'] or '無'}")
    for m, s in report["stats"].items():
        print(f"版面（{'文字層' if m == 'text' else 'OCR'}）：正文字級 {s['body']}　行距 {s['pitch']}")
    top = ", ".join(f"{t}×{n}" for t, n in removed.most_common(6))
    print(f"刪除書眉／頁碼 {sum(removed.values())} 行：{top or '無'}")
    print(f"切章依據：{report['chapter_source']}　註腳 {report['footnotes']} 則（收到各章結尾）")
    sizes = report.get("heading_sizes") or []
    if sizes and report["chapter_source"].startswith("版面"):
        print("標題字級：" + "；".join(
            f"{s['size']}pt×{s['count']}" + (f" → 第 {s['level']} 層" if s["level"] else
                                             "（接在標題後，當副標）" if s["after_heading"] >= 0.5 * s["count"] else "")
            + f"（{s['sample']}）" for s in sizes[:6]) + "\n  不對就在 pdf.heading_sizes 指定，例：{22: 1, 15: 2}")
    if report["inferred_titles"]:
        shown = "、".join(f"第 {p} 頁「{t or '（空白）'}」" for p, t in report["inferred_titles"])
        print(f"※ 推定章名（看得出是章首、但 OCR 讀不到章號，依前後章推定，請用 page 確認）：{shown}")
    if report["ocr_figures"]:
        figs = sum(n for _, n, _ in report["ocr_figures"])
        dropped = sum(d for _, _, d in report["ocr_figures"])
        print(f"掃描頁插圖 {figs} 張（裁成圖片放回原位；圖裡被 OCR 讀到的 {dropped} 行字已丟掉）："
              + "、".join(f"第 {p} 頁" for p, _, _ in report["ocr_figures"][:10]))
    if "layout" in report:
        lr = report["layout"]
        src = lr["pages_by_source"]
        print(f"版面模型找圖：{len(src.get('layout', []))} 頁用版面框（獨立公式 {lr['formulas']} 條裁成圖）　"
              f"{len(src.get('ink', []))} 頁沒有 work/layout/ 快取、退回墨水推算"
              + (f"　手動 {len(src.get('manual', []) + src.get('plate', []))} 頁" if src.get("manual") or src.get("plate") else ""))
        if lr["skipped_boxes"]:
            print(f"※ 圖框裡有多行長句、當成正文沒裁的框 {len(lr['skipped_boxes'])} 個："
                  + "、".join(f"第 {b['page']} 頁" for b in lr["skipped_boxes"][:10]))
    if low:
        pages_low = sorted({x["page"] for x in low})
        print(f"OCR 低信心段落 {len(low)} 段（extract_report.json 的 low_confidence），"
              f"頁碼：{pages_low[:15]}{'…' if len(pages_low) > 15 else ''}")
    print(f"章節={len(book['chapters'])}  " + "  ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    print(f"寫入 {cfg.wpath('book.json')}（抽取報告：{cfg.wpath('extract_report.json')}）")


def render_page(cfg, page_no, dpi=150):
    """把原書某一頁輸出成 PNG，拿來和抽出的文字對照。"""
    src = cfg.source_file()
    if not src.lower().endswith(".pdf"):
        raise SystemExit("page 指令只適用 PDF 原檔")
    doc = pymupdf.open(src)
    if not 1 <= page_no <= len(doc):
        raise SystemExit(f"頁碼超出範圍：1～{len(doc)}")
    out = cfg.wpath("pages", f"p{page_no:04d}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc[page_no - 1].get_pixmap(dpi=dpi).save(out)
    print(out)
    return out
