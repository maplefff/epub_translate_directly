"""譯後審閱：原文與譯文逐段並排、定點修改譯稿、記錄審閱進度。

為什麼要有這一關：對位檢查、verify、zh-lint 都是機械檢查，抓不到語意錯誤。
例如 “You can kill him and ask questions after.” 被譯成「你可以先殺了他再問問題」，
多出的「先」和前文「先叫他說話」互相矛盾，只有對照原文逐句讀才看得出來。

改譯稿一律走 revise，不手動 sed：它要求舊字串在該段裡恰好出現一次才替換，
並把每一處改動（原句、新句、理由）寫進 drafts/review_log.jsonl。
"""
import os, re, json, glob, datetime
from ..core import store
from ..translate import drafts as D


def _log_path(cfg):
    return os.path.join(cfg.drafts, "review_log.jsonl")


def _log(cfg):
    p = _log_path(cfg)
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def _append(cfg, rec):
    rec = {"at": datetime.datetime.now().isoformat(timespec="seconds"), **rec}
    with open(_log_path(cfg), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _rows_with_origin(cfg, cid):
    """[(檔案, 檔內序號, row)…]，把分段檔接成一章。"""
    files = D._chapter_files(cfg).get(cid)
    if not files:
        raise SystemExit(f"沒有 {cid} 的譯稿")
    out = []
    for p in files:
        for i, row in enumerate(json.load(open(p, encoding="utf-8"))):
            out.append((p, i, row))
    return out


def show(cfg, cid, lo=0, hi=None):
    book = store.load_book(cfg)
    ch = next((c for c in book["chapters"] if c["id"] == cid), None)
    if ch is None:
        raise SystemExit(f"book.json 沒有章節 {cid}")
    items = D._text_items(ch)
    rows = _rows_with_origin(cfg, cid)
    if len(rows) != len(items):
        raise SystemExit(f"{cid}: 譯稿 {len(rows)} 筆 ≠ 原文 {len(items)} 筆，先修對位")
    for i, (it, (_, _, row)) in enumerate(zip(items, rows)):
        if i < lo or (hi is not None and i >= hi):
            continue
        zh = it["text"] if row[1] is None else row[1]
        print(f"[{i}] {it['text']}\n     {zh}\n")


def revise(cfg, cid, idx, old, new, why, quiet=False):
    rows = _rows_with_origin(cfg, cid)
    if not 0 <= idx < len(rows):
        raise SystemExit(f"{cid} 沒有第 {idx} 段（共 {len(rows)} 段）")
    path, j, row = rows[idx]
    zh = row[1] or ""
    n = zh.count(old)
    if n != 1:
        raise SystemExit(f"{cid}[{idx}]：舊字串出現 {n} 次（必須恰好 1 次），未修改\n  段落：{zh}")
    data = json.load(open(path, encoding="utf-8"))
    data[j][1] = zh.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n]\n")
    _append(cfg, {"cid": cid, "idx": idx, "old": old, "new": new, "why": why})
    if not quiet:
        print(f"{cid}[{idx}] 已修改：{old} → {new}")


_TOKENS = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[A-Za-z]{2,}|[⁰¹²³⁴⁵⁶⁷⁸⁹]+")


def _tokens(t):
    """段落裡的數字、英文字與注號（排序後比對）：改句式不該動到它們。"""
    return sorted(_TOKENS.findall(t or ""))


def revise_whole(cfg, cid, idx, new, why):
    """整段換掉（改寫幅度大時用），舊段落整段記進紀錄。"""
    rows = _rows_with_origin(cfg, cid)
    if not 0 <= idx < len(rows):
        raise SystemExit(f"{cid} 沒有第 {idx} 段（共 {len(rows)} 段）")
    path, j, row = rows[idx]
    data = json.load(open(path, encoding="utf-8"))
    old = data[j][1] or ""
    data[j][1] = new
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n]\n")
    _append(cfg, {"cid": cid, "idx": idx, "old": old, "new": new, "why": why})


def revise_batch(cfg, cid, path, why):
    """一次套用多處修改。檔案每行「段號<TAB>舊字串<TAB>新字串[<TAB>理由]」，# 開頭與空行略過；
    每處照 revise 的規則（舊字串在該段恰好出現一次）逐一套用並記錄，失敗的列出來、不中斷。
    舊字串寫「*」＝整段換成新字串。改完逐段比對數字與英文字，有出入就警告（改句式不該動到數據）。"""
    ok, bad = 0, []
    rows = _rows_with_origin(cfg, cid)
    before = {i: _tokens(r[2][1]) for i, r in enumerate(rows)}
    touched = set()
    for ln, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 3 or not f[0].strip().isdigit():
            bad.append(f"第 {ln} 行格式不對：{line[:60]}")
            continue
        w = f[3] if len(f) > 3 and f[3] else why
        try:
            if f[1] == "*":
                revise_whole(cfg, cid, int(f[0]), f[2], w)
            else:
                revise(cfg, cid, int(f[0]), f[1], f[2], w, quiet=True)
            ok += 1
            touched.add(int(f[0]))
        except SystemExit as e:
            bad.append(f"第 {ln} 行：{str(e).splitlines()[0]}")
    rows = _rows_with_origin(cfg, cid)
    warn = [i for i in sorted(touched) if _tokens(rows[i][2][1]) != before[i]]
    print(f"{cid}：套用 {ok} 處，失敗 {len(bad)} 處，數字／英文有出入 {len(warn)} 段")
    for b in bad:
        print("  ✗ " + b)
    for i in warn:
        a, b = before[i], _tokens(rows[i][2][1])
        gone = [x for x in a if x not in b or a.count(x) > b.count(x)]
        new = [x for x in b if x not in a or b.count(x) > a.count(x)]
        print(f"  ⚠ [{i}] 少了 {sorted(set(gone))}　多了 {sorted(set(new))}")


def done(cfg, cid, note=""):
    _append(cfg, {"cid": cid, "done": True, "note": note})
    n = sum(1 for r in _log(cfg) if r.get("cid") == cid and "old" in r)
    print(f"{cid} 標記為已審（本章修改 {n} 處）")


def progress(cfg):
    book = store.load_book(cfg)
    log = _log(cfg)
    fixed, reviewed = {}, set()
    for r in log:
        if r.get("done"):
            reviewed.add(r["cid"])
        elif "old" in r:
            fixed[r["cid"]] = fixed.get(r["cid"], 0) + 1
    for c in book["chapters"]:
        items = D._text_items(c)
        if not items:
            continue
        mark = "✓" if c["id"] in reviewed else "·"
        print(f"{mark} {c['id']}\t{len(items)} 段\t修改 {fixed.get(c['id'], 0)} 處")
    print(f"\n已審 {len(reviewed)} 章，修改共 {sum(fixed.values())} 處（紀錄：{_log_path(cfg)}）")
