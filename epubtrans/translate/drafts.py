"""直譯稿的讀寫：傾印原文、查進度、把 drafts/ 併進 translations.json。

譯稿格式 —— process/{書名}/drafts/{cid}.json，JSON 陣列，依序對應該章每一個文字項目
（para / heading / quote / li；image 跳過），每筆 `[原文開頭, 譯文]`：
  - 原文開頭：原文前幾個字，只用來校驗對位（只比英數字元，引號破折號打錯不算錯）。
  - 譯文 null：照抄原文（書目清單、ISBN、網址）。
長章可拆成 {cid}.json、{cid}.2.json、{cid}.3.json…，合併時依序接起來。
章節標題另寫在 drafts/titles.json：`[完整原文標題, 譯文]`。

為什麼要對位檢查：譯稿不帶 md5，少寫或多寫一段，後面整章會靜默位移一格。
所以對不上就整章拒收，不做部分寫入。
"""
import os, re, glob, json
from ..core import store
from ..source import book_index


def _alnum(s):
    return re.sub(r"[^0-9a-z]", "", s.lower())


def _text_items(ch):
    return [it for it in ch["items"] if it["type"] in store.TEXT_TYPES]


def _chapter_files(cfg):
    """{cid: [檔案…]}，分段檔依編號排序。"""
    out = {}
    for p in glob.glob(os.path.join(cfg.drafts, "*.json")):
        stem = os.path.basename(p)[:-5]
        cid, _, n = stem.partition(".")
        out.setdefault(cid, []).append((int(n or 1), p))
    return {k: [p for _, p in sorted(v)] for k, v in out.items()}


def _load_rows(files):
    rows = []
    for p in files:
        rows.extend(json.load(open(p, encoding="utf-8")))
    return rows


def aligned(cfg):
    """直接從 drafts 逐段產出 (cid, 序號, 原文, 譯文)，不必先 merge。

    回傳 (rows, skipped)；筆數或對位對不上的章整章略過，列在 skipped。譯文 null（照抄原文）不列。
    """
    book = store.load_book(cfg)
    chapters = {c["id"]: c for c in book["chapters"]}
    rows, skipped = [], []
    for cid, files in sorted(_chapter_files(cfg).items()):
        drows = _load_rows(files)
        if cid == "titles":
            rows += [("titles", i, src, zh) for i, (src, zh) in enumerate(drows) if zh]
            continue
        items = _text_items(chapters[cid]) if cid in chapters else []
        if len(drows) != len(items) or any(not _alnum(it["text"]).startswith(_alnum(pre))
                                           for (pre, _), it in zip(drows, items)):
            skipped.append(cid)
            continue
        rows += [(cid, i, it["text"], zh) for i, ((_, zh), it) in enumerate(zip(drows, items)) if zh]
    return rows, skipped


def dump(cfg, cid, lo=0, hi=None):
    book = store.load_book(cfg)
    ch = next((c for c in book["chapters"] if c["id"] == cid), None)
    if ch is None:
        raise SystemExit(f"book.json 沒有章節 {cid}")
    for i, it in enumerate(_text_items(ch)):
        if i >= lo and (hi is None or i < hi):
            if "entry" in it:
                # 索引條目：印出譯稿要填的樣板（「；」分隔條目與子條目，「｜」後接參見）
                e = it["entry"]
                print(f"{i}\tIX " + "；".join(book_index.slots(e)) + (f"｜{e['see']}" if e.get("see") else ""))
                continue
            tag = "H " if it["type"] == "heading" else ""
            print(f"{i}\t{tag}{it['text']}")


def status(cfg):
    """每章段數、字數、譯稿筆數。最容易漏的是只有一段的部名扉頁。"""
    book = store.load_book(cfg)
    files = _chapter_files(cfg)
    todo = 0
    for c in book["chapters"]:
        items = _text_items(c)
        if not items:
            continue
        words = sum(len(it["text"].split()) for it in items)
        got = len(_load_rows(files[c["id"]])) if c["id"] in files else 0
        mark = "✓" if got == len(items) else ("…" if got else "·")
        todo += got != len(items)
        print(f"{mark} {c['id']}\t{c['title'][:24]}\t{len(items)} 段\t{words} 字\t譯稿 {got}")
    titles = {c["title"] for c in book["chapters"] if c.get("title")}
    done = {r[0] for r in _load_rows(files["titles"])} if "titles" in files else set()
    miss = titles - done
    print(f"\n未完成章節 {todo}；章節標題未譯 {len(miss)}" + (f"：{sorted(miss)}" if miss else ""))


def merge(cfg, only=None, dry_run=False):
    book = store.load_book(cfg)
    chapters = {c["id"]: c for c in book["chapters"]}
    titles = {c["title"] for c in book["chapters"] if c.get("title")}
    cache = store.load_cache(cfg)
    ok, bad = 0, []
    for cid, files in sorted(_chapter_files(cfg).items()):
        if only and cid not in only:
            continue
        rows = _load_rows(files)
        if cid == "titles":
            for src, zh in rows:
                if src in titles:
                    cache[store.h(src)] = zh; ok += 1
                else:
                    bad.append(f"titles: 找不到章名 {src!r}")
            continue
        if cid not in chapters:
            bad.append(f"{cid}: book.json 沒有這個章節 id"); continue
        items = _text_items(chapters[cid])
        errs = []
        if len(rows) != len(items):
            errs.append(f"譯稿 {len(rows)} 筆 ≠ 原文 {len(items)} 筆")
        for i, (row, it) in enumerate(zip(rows, items)):
            pre, zh = row
            if not _alnum(it["text"]).startswith(_alnum(pre)):
                errs.append(f"第 {i} 筆起錯位：譯稿開頭 {pre!r} / 原文 {it['text'][:40]!r}")
                break
            if zh is not None and not isinstance(zh, str):
                errs.append(f"第 {i} 筆譯文型別錯誤"); break
        if errs:
            bad.append(f"{cid}: " + "；".join(errs)); continue
        for (_, zh), it in zip(rows, items):
            cache[store.h(it["text"])] = it["text"] if zh is None else zh
        ok += len(rows)
        print(f"  {cid}: {len(rows)} 筆 OK")
    if bad:
        print("拒收：\n  " + "\n  ".join(bad))
    if ok and not dry_run:
        store.save_cache(cfg, cache)
        print(f"寫入 {cfg.wpath('translations.json')}（本次 {ok} 筆，快取共 {len(cache)} 筆）")
    if bad:
        raise SystemExit(1)
