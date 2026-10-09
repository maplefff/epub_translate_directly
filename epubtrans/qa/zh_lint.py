"""台灣用語檢查 —— 依 epubtrans/settings/zh_tw_lint.yaml 的規則掃 work/translations.json，只報告不改稿。

為什麼不自動替換：譯文的真相來源是 drafts/，translations.json 每次 merge 都會被
drafts 覆寫，在這裡改了也留不住。而且規則再怎麼用負向界定圈，也有誤報 ——
Non-Stop 的「刀刃水平一掠」「水平地掃過去」就會被「水平→程度」命中。
命中的地方逐一判斷，確認是陸／港用語才回 drafts/ 改那一句，再重新 merge。
"""
import re
from ..core import store


def run(cfg):
    rules = cfg.lint_rules
    if not rules:
        print("zh_tw_lint.yaml 沒有規則。")
        return
    cache = store.load_cache(cfg)
    if not cache:
        raise SystemExit("沒有譯文可檢，先跑 merge。")
    book = store.load_book(cfg)
    where = {store.h(it["text"]): it["cid"] for it in store.source_items(book)}

    total = 0
    for r in rules:
        rx = re.compile(r["find"] if r.get("regex") else re.escape(r["find"]))
        hits = [(where.get(hh, "?"), v, m) for hh, v in cache.items() for m in rx.finditer(v)]
        if not hits:
            continue
        total += len(hits)
        print(f"  {r['find']} → {r['replace']}　×{len(hits)}" + (f"　（{r['note']}）" if r.get("note") else ""))
        for cid, v, m in hits[:6]:
            j = m.start()
            print(f"      [{cid}] …{v[max(0, j - 20):j + len(m.group(0)) + 20]}…")
    print(f"規則={len(rules)}　命中={total}（只報告；確認是誤用的，回 drafts/ 修改後重新 merge）")
