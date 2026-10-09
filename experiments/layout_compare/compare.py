"""普通書籍的掃描頁：版面模型（PP-DocLayout-V3）找圖 vs 現行做法，逐頁比對。不載入模型、不跑 Vision。

用法（先在 Mac 上跑 `python -m epubtrans layout "書名"` 產生 work/layout/）：
  ./.venv/bin/python experiments/layout_compare/compare.py "《金融煉金術 The Alchemy of Finance》"
輸出到 process/{書名}/work/layout_compare/：report.md（摘要與逐頁差異）、data.json、pNNNN.png（有差異的頁，框畫在原頁上）。

比的三種找圖方式（文字都用 work/ocr/ 的 Vision 快取，只比「哪裡是圖」）：
  現行  這本書目前的設定（figure_boxes、plate_pages、framed_figures 等手動設定＋墨水推算）＝參考答案
  墨水  拿掉所有手動設定，只靠墨水推算
  版面  拿掉所有手動設定，只靠版面框（pdf.layout: true 時 extract 的做法）
另外看版面框能不能幫上標題、註腳：書裡已切好的標題有幾個落在 paragraph_title／doc_title 框裡，註腳框的開頭標記。
"""
import argparse, json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pymupdf                                                              # noqa: E402
from epubtrans.core.config import BookConfig                               # noqa: E402
from epubtrans.source.import_pdf import options, parse_pages, ocr_page_numbers, ocr, layoutbox   # noqa: E402

COVER, TIGHT, OVERLAP = 0.8, 0.5, 0.2
COLORS = {"ref": (0, 0.6, 0), "ink": (0.9, 0, 0), "layout": (0, 0.3, 1), "formula": (0.6, 0, 0.7), "skipped": (1, 0.6, 0)}
CAPTION = re.compile(r"^(Figure|Fig\.|Table|Chart|Exhibit)\s+\S", re.I)


def area(r):
    return max(0.0, r.width) * max(0.0, r.height) if not r.is_empty else 0.0


def covered(r, rects):
    """r 被 rects 蓋住的比例（用細格點估，rects 彼此重疊也不會重複算）。"""
    if area(r) == 0:
        return 0.0
    n, hit = 24, 0
    for i in range(n):
        for j in range(n):
            p = pymupdf.Point(r.x0 + (i + .5) * r.width / n, r.y0 + (j + .5) * r.height / n)
            hit += any(q.contains(p) for q in rects)
    return hit / (n * n)


def iou(a, b):
    i = area(a & b)
    return i / (area(a) + area(b) - i) if i else 0.0


def lines_in(rects, obs, W, H):
    c = lambda o: pymupdf.Point((o[2] + o[4] / 2) * W, (1 - o[3] - o[5] / 2) * H)
    return [o for o in obs if any(r.contains(c(o)) for r in rects)]


def key(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--no-images", action="store_true", help="不輸出逐頁的框線圖")
    a = ap.parse_args()
    cfg = BookConfig(a.book)
    opts = options(cfg)
    doc = pymupdf.open(cfg.source_file())
    out_dir = cfg.wpath("layout_compare")
    os.makedirs(out_dir, exist_ok=True)

    plates = parse_pages(opts.get("plate_pages"), doc.page_count)
    framed = bool(opts.get("framed_figures"))
    boxes = {int(k) - 1: v for k, v in (opts.get("figure_boxes") or {}).items()}
    lay = {"load": lambda pno: layoutbox.load(cfg, pno), "find": layoutbox.find,
           "formulas": opts.get("layout_formulas", True)}
    try:
        book = json.load(open(cfg.wpath("book.json"), encoding="utf-8"))
    except (OSError, ValueError):
        book = {"chapters": []}
    headings = {}
    for c in book["chapters"]:
        for it in c["items"]:
            if it["type"] == "heading" and it.get("page"):
                headings.setdefault(it["page"] - 1, []).append(it["text"])
        if c.get("page") and c.get("title"):
            headings.setdefault(c["page"] - 1, []).append(c["title"])

    pages, secs, missing = [], [], []
    for pno in ocr_page_numbers(cfg):
        data = ocr._load(cfg.wpath("ocr", f"p{pno + 1:04d}.json"))
        L = layoutbox.load(cfg, pno)
        if not data or not L:
            missing.append(pno + 1)
            continue
        secs.append(L.get("sec") or 0)
        page, W, H, obs = doc[pno], data["w"], data["h"], data["obs"]
        ref, ref_src, _ = ocr.figure_rects(page, pno, data, pno in plates, framed, boxes.get(pno))
        ink, _, _ = ocr.figure_rects(page, pno, data)
        lay_r, _, note = ocr.figure_rects(page, pno, data, lay=lay)
        n_form = note["formulas"]
        figs, forms = lay_r[:len(lay_r) - n_form], lay_r[len(lay_r) - n_form:]
        rec = {"page": pno + 1, "ref_source": ref_src if ref else None, "ref": [], "extra_layout": [], "extra_ink": [],
               "formulas": len(forms), "skipped": note["skipped"]}
        for r in ref:
            rec["ref"].append({"rect": list(r), "src": ref_src,
                               "layout_cover": round(covered(r, lay_r), 2),
                               "layout_iou": round(max((iou(r, f) for f in lay_r), default=0), 2),
                               "ink_cover": round(covered(r, ink), 2),
                               "ink_iou": round(max((iou(r, f) for f in ink), default=0), 2)})
        for name, rs in (("extra_layout", figs), ("extra_ink", ink)):
            for f in rs:
                if area(f) and sum(area(f & r) for r in ref) < OVERLAP * area(f):
                    rec[name].append(list(f))
        # 字：被裁進圖裡（從正文消失）的行，特別是長句；圖說行留作文字還是被裁進圖
        for name, rs in (("ref", ref), ("ink", ink), ("layout", lay_r)):
            inside = lines_in(rs, obs, W, H)
            rec[f"dropped_{name}"] = len(inside)
            rec[f"dropped_long_{name}"] = [o[0][:70] for o in inside if len(o[0].strip()) > layoutbox.LONG_LINE]
            rec[f"captions_in_{name}"] = [o[0][:50] for o in inside if CAPTION.match(o[0].strip())]
        # 標題、註腳
        titles = [x for x in L["layout"] if x["label"] in ("doc_title", "paragraph_title") and x["score"] >= 0.5]
        ttext = [" ".join(o[0] for o in lines_in([layoutbox.to_rect(x["bbox"], W, H)], obs, W, H)) for x in titles]
        rec["headings"] = [{"text": h[:60], "in_title_box": any(key(h)[:20] and key(h)[:20] in key(t) or
                                                                 (key(t) and key(t) in key(h)) for t in ttext)}
                           for h in headings.get(pno, [])]
        rec["title_boxes"] = [t[:60] for t in ttext]
        foot = [x for x in L["layout"] if x["label"] in ("footnote", "vision_footnote") and x["score"] >= 0.5]
        rec["footnotes"] = [" ".join(o[0] for o in lines_in([layoutbox.to_rect(x["bbox"], W, H)], obs, W, H))[:60]
                            for x in foot]
        rec["differs"] = bool(any(r["layout_cover"] < COVER for r in rec["ref"]) or rec["extra_layout"]
                              or rec["skipped"] or rec["dropped_long_layout"] != rec["dropped_long_ref"])
        pages.append(rec)
        if rec["differs"] and not a.no_images:
            draw(doc, pno, ref, ink, figs, forms, note["skipped"], W, H, out_dir)

    json.dump({"pages": pages, "missing": missing, "sec": secs}, open(os.path.join(out_dir, "data.json"), "w"),
              ensure_ascii=False, indent=1)
    report = summarize(cfg, pages, missing, secs, opts)
    open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8").write(report)
    print(report.split("## 逐頁")[0])
    print(f"完整報告：{os.path.join(out_dir, 'report.md')}")


def draw(doc, pno, ref, ink, figs, forms, skipped, W, H, out_dir):
    """參考（綠，粗）、墨水（紅）、版面（藍）、公式（紫）、像正文而沒裁的框（橘，虛線）畫在原頁上。"""
    d = pymupdf.open()
    d.insert_pdf(doc, from_page=pno, to_page=pno)
    pg = d[0]
    for rs, c, w, dash in ((ref, "ref", 3, None), (ink, "ink", 1.2, None), (figs, "layout", 1.2, "[4] 0"),
                           (forms, "formula", 1.2, "[4] 0"),
                           ([layoutbox.to_rect(s["bbox"], W, H) for s in skipped], "skipped", 1.5, "[2] 0")):
        for r in rs:
            pg.draw_rect(r, color=COLORS[c], width=w, dashes=dash)
    pg.get_pixmap(dpi=90).save(os.path.join(out_dir, f"p{pno + 1:04d}.png"))


def summarize(cfg, pages, missing, secs, opts):
    refs = [r for p in pages for r in p["ref"]]
    by_src = {}
    for r in refs:
        by_src.setdefault(r["src"], []).append(r)
    L = [f"# 版面模型找圖比對：{cfg.name}", "",
         f"比對 {len(pages)} 頁（OCR 頁裡同時有 Vision 快取與版面快取的）；缺快取 {len(missing)} 頁"
         + (f"：{missing[:15]}{'…' if len(missing) > 15 else ''}" if missing else "") + "。",
         f"版面模型每頁 {statistics.mean(secs):.2f} 秒（中位數 {statistics.median(secs):.2f}）。" if secs else "", "",
         "## 摘要", "",
         "現行做法找到的圖（含手動設定）當參考答案。「蓋到」＝參考圖八成以上的面積落在該方法的圖框裡；「貼合」＝和其中一個框 IoU ≥ 0.5。", "",
         "| 參考圖的來源 | 張數 | 版面：蓋到 | 版面：貼合 | 墨水：蓋到 | 墨水：貼合 |", "|---|---|---|---|---|---|"]
    names = {"manual": "手動 figure_boxes", "plate": "圖版頁 plate_pages", "ink": "墨水推算（含 framed_figures）"}
    for src, rs in sorted(by_src.items()) + [("全部", refs)]:
        n = len(rs)
        f = lambda k, t: f"{sum(r[k] >= t for r in rs)}（{sum(r[k] >= t for r in rs) / n:.0%}）" if n else "–"
        L.append(f"| {names.get(src, src)} | {n} | {f('layout_cover', COVER)} | {f('layout_iou', TIGHT)} | "
                 f"{f('ink_cover', COVER)} | {f('ink_iou', TIGHT)} |")
    extra_l = [(p["page"], len(p["extra_layout"])) for p in pages if p["extra_layout"]]
    extra_i = [(p["page"], len(p["extra_ink"])) for p in pages if p["extra_ink"]]
    skipped = [(p["page"], s) for p in pages for s in p["skipped"]]
    long_l = [(p["page"], x) for p in pages for x in p["dropped_long_layout"] if x not in p["dropped_long_ref"]]
    long_r = [(p["page"], x) for p in pages for x in p["dropped_long_ref"] if x not in p["dropped_long_layout"]]
    heads = [h for p in pages for h in p["headings"]]
    foot = [t for p in pages for t in p["footnotes"]]
    marks = opts.get("footnote_marks") or ""
    L += ["",
          f"- 版面多找到、參考沒有的圖框：{sum(n for _, n in extra_l)} 個，{len(extra_l)} 頁"
          f"（另裁了獨立公式 {sum(p['formulas'] for p in pages)} 條，不算在內）。可能是參考漏掉的圖，也可能是誤判，看逐頁圖。",
          f"- 墨水推算（不加手動設定）多找到、參考沒有的：{sum(n for _, n in extra_i)} 個，{len(extra_i)} 頁。",
          f"- 版面框裡有多行長句、判定為正文沒裁的框：{len(skipped)} 個。",
          f"- 版面多裁掉、參考留作正文的長句：{len(long_l)} 行；參考裁掉、版面留作正文的長句：{len(long_r)} 行。",
          f"- 圖說行：參考裁進圖裡 {sum(len(p['captions_in_ref']) for p in pages)} 行，"
          f"版面裁進圖裡 {sum(len(p['captions_in_layout']) for p in pages)} 行（其餘留作文字段落，可以翻譯）。",
          f"- 標題：現有 book.json 的標題與章名 {len(heads)} 個，落在 paragraph_title／doc_title 框裡的 "
          f"{sum(h['in_title_box'] for h in heads)} 個。",
          f"- 註腳框 {len(foot)} 個" + (f"，開頭是 pdf.footnote_marks（{marks}）的 {sum(t.strip()[:1] in marks for t in foot if t.strip())} 個"
                                        if marks else "") + "。", "",
          "圖例（逐頁 PNG）：綠粗框＝參考，紅＝墨水推算，藍虛線＝版面，紫虛線＝公式，橘點線＝像正文、沒裁的版面框。", "",
          "## 逐頁差異", ""]
    for p in pages:
        if not p["differs"]:
            continue
        bits = []
        miss = [r for r in p["ref"] if r["layout_cover"] < COVER]
        if miss:
            bits.append("版面沒蓋到參考圖：" + "、".join(f"{r['src']}（蓋到 {r['layout_cover']:.0%}）" for r in miss))
        if p["extra_layout"]:
            bits.append(f"版面多 {len(p['extra_layout'])} 個框")
        if p["skipped"]:
            bits.append(f"像正文、沒裁 {len(p['skipped'])} 個（{p['skipped'][0]['sample']!r}）")
        lo = [x for x in p["dropped_long_layout"] if x not in p["dropped_long_ref"]]
        if lo:
            bits.append(f"版面多裁掉長句 {len(lo)} 行（{lo[0]!r}）")
        lr = [x for x in p["dropped_long_ref"] if x not in p["dropped_long_layout"]]
        if lr:
            bits.append(f"參考裁掉、版面留作正文 {len(lr)} 行（{lr[0]!r}）")
        L.append(f"- 第 {p['page']} 頁 [圖](p{p['page']:04d}.png)：" + "；".join(bits))
    missed_heads = [(p["page"], h["text"], p["title_boxes"]) for p in pages for h in p["headings"] if not h["in_title_box"]]
    if missed_heads:
        L += ["", "## 沒落在標題框裡的標題", ""]
        L += [f"- 第 {pg} 頁「{t}」；這頁的標題框：{tb or '無'}" for pg, t, tb in missed_heads[:60]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
