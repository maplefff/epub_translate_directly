"""輸入端：任何格式的原書 → work/book.json（extract 指令入口）。

下游（dump、drafts、merge、verify、build、pdf）只讀 book.json，不管原書是什麼格式：
  .epub → import_epub
  .acsm → 先用 fetch 領成 EPUB（fetch_acsm），再 import_epub
  .pdf  → import_pdf（有文字層的頁直接讀；掃描頁走 OCR）

抽完之後套用 drafts/source_fixes.yaml 的原文校正（OCR 誤字、原書錯字）。校正檔是人工成果，
放在 drafts/；每次 extract 都重新套用，所以重抽不會洗掉。
"""
import os
from collections import Counter

FIXES = "source_fixes.yaml"
SAMPLE = """\
# 原文校正：extract 抽完後套用。old 在該段必須出現；page 是 PDF 原書頁碼，省略＝全書套用。
# 翻譯前就要校好：改到段落開頭會讓已寫的譯稿對位不上。
- {page: 14, old: "another?", new: "another.’"}
- {old: "Cornplain", new: "Complain"}
"""


def run(cfg):
    fmt = cfg.source_format()
    if fmt in ("epub", "acsm"):
        from . import import_epub
        import_epub.run(cfg)
    elif fmt == "pdf":
        from . import import_pdf
        import_pdf.run(cfg)
    else:
        raise SystemExit(f"不支援的原檔格式：.{fmt}")
    apply_source_fixes(cfg)


def apply_source_fixes(cfg):
    path = os.path.join(cfg.drafts, FIXES)
    if not os.path.exists(path):
        return
    import yaml
    from ..core import store
    fixes = yaml.safe_load(open(path, encoding="utf-8")) or []
    book = store.load_book(cfg)
    hits = Counter()
    for k, f in enumerate(fixes):
        old, new, page = f.get("old"), f.get("new"), f.get("page")
        if not old or new is None:
            raise SystemExit(f"{FIXES} 第 {k + 1} 條缺 old 或 new：{f}\n格式範例：\n\n{SAMPLE}")
        on = lambda x: page is None or (x.get("page") or 0) <= page <= (x.get("page_end") or x.get("page") or 0)
        for c in book["chapters"]:
            if old in (c.get("title") or "") and on(c):
                c["title"] = c["title"].replace(old, new)
                hits[k] += 1
            for it in c["items"]:
                if old in (it.get("text") or "") and on(it):
                    it["text"] = it["text"].replace(old, new)
                    hits[k] += 1
            # 校正成空字串的段落拿掉（OCR 把一段拆錯時，把內容併到另一段、這段改成空的）
            c["items"] = [it for it in c["items"] if it["type"] in ("image", "figrow") or (it.get("text") or "").strip()]
    store.save_json(cfg, "book.json", book)
    miss = [f"第 {k + 1} 條 {f.get('old')!r}" for k, f in enumerate(fixes) if not hits[k]]
    print(f"原文校正（drafts/{FIXES}）：{len(fixes) - len(miss)}/{len(fixes)} 條套用，共改 {sum(hits.values())} 處"
          + (f"\n  ※ 沒有對到：{'、'.join(miss)}" if miss else ""))
