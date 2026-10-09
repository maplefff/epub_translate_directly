"""多個獨立指標取代單一 X/Y 完成度。

只查「key 在不在快取裡」會漏掉「譯稿寫成原文」或「整段幾乎沒翻」的段落，
它們在統計上一樣算完成。這裡拆成幾項，並把可疑段落逐條列出來讓人判斷。
① 未進快取會阻擋 build。
"""
import re
from ..core import store

CJK = re.compile(r'[一-鿿]')
CONNECTIVE = re.compile(r'(?<=[一-鿿])\s+(and|of|the|with|in|to|is|are|or|but|for|as|by)\s+(?=[一-鿿])', re.I)
PAREN = re.compile(r'[（(][^）)]*[）)]')
# 指標③ 的中文密度下限。譯文中文字數低於這個比例就當作沒翻。
CJK_MIN_RATIO = 0.05


def run(cfg, verbose=True):
    book = store.load_book(cfg)
    cache = store.load_cache(cfg)
    items = store.unique_sources(book)

    # 同一原文字串當作多章標題 → 快取只有一份譯文，其中至少一章會拿到錯的譯名
    import collections
    tmap = collections.defaultdict(list)
    for c in book["chapters"]:
        if c.get("title"):
            tmap[c["title"]].append(c["id"])
    dup_titles = {k: v for k, v in tmap.items() if len(v) > 1}
    # 已在 YAML 用 title_overrides / overrides 處理過的就不再嘮叨
    handled = set((cfg.book.get("title_overrides") or {}).keys())
    handled |= {o.get("cid") for o in (cfg.book.get("overrides") or [])}
    dup_titles = {k: v for k, v in dup_titles.items() if not set(v) & handled}

    # 大小寫／空白正規化後相同的原文，卻拿到不同譯文。md5 快取是逐字元比對，
    # 所以書中同一個標題的大寫版與正常版會被當成兩段各翻一次，譯法因此分岔
    # （Atlas 的 13 個部別標題在正文與書末索引各出現一次，其中 #5 一邊譯成
    # 「當事不如表象時」、另一邊譯成「當事與願違時」—— 後者是錯的）。
    norm = collections.defaultdict(dict)
    for it in items:
        z = cache.get(store.h(it["text"]))
        if z:
            norm[" ".join(it["text"].split()).lower()][it["text"]] = z
    inconsistent = {k: v for k, v in norm.items()
                    if len(v) > 1 and len({x.strip() for x in v.values()}) > 1}

    missing, same, nocjk, leak = [], [], [], []
    for it in items:
        s = it["text"]
        z = cache.get(store.h(s))
        if z is None:
            missing.append(it); continue
        if z == s:
            same.append(it); continue
        stripped = PAREN.sub("", z)
        # 「有沒有中文」太寬鬆：Non-Stop 的作者簡介整段沒翻，1,906 字裡只有
        # 「後者」兩個中文字，照樣過關。改問中文密度 —— 真的翻過的段落密度遠高於
        # 5%，而合法保留原文的整段（書目、版權、網址）會先被指標②接走。
        if len(s) > 25 and len(CJK.findall(z)) < max(1, len(z) * CJK_MIN_RATIO):
            nocjk.append((it, z))
        m = CONNECTIVE.search(stripped)
        if m:
            leak.append((it, z, m.group(0).strip()))

    n = len(items)
    print(f"段落總數（含章節標題）= {n}")
    print(f"  ① 未進快取           = {len(missing)}")
    print(f"  ② 譯文完全等於原文    = {len(same)}")
    print(f"  ③ 長段落但譯文幾乎無中文= {len(nocjk)}")
    print(f"  ④ 中文夾心英文連接詞  = {len(leak)}")
    print(f"  ⑥ 同名標題共用譯文    = {len(dup_titles)}"
          + ("　（用 book.title_overrides 按章節 id 指定正確譯名）" if dup_titles else ""))
    for k, v in list(dup_titles.items())[:6]:
        print(f"       「{k[:40]}」→ {v}　目前譯為「{cache.get(store.h(k), '')[:24]}」")
    print(f"  ⑦ 同文異譯（僅大小寫/空白之差）= {len(inconsistent)}")
    for k, v in list(inconsistent.items())[:8]:
        zs = list(v.values())
        print(f"       「{k[:44]}」")
        for z in zs[:3]:
            print(f"          → {z[:44]}")

    if verbose:
        def show(title, rows, fmt):
            if not rows:
                return
            print(f"\n--- {title}（列出前 12 筆，請人工判斷是「合理保留」還是「翻譯失敗」）---")
            for r in rows[:12]:
                print("   " + fmt(r))
        show("① 未進快取", missing, lambda it: f"[{it['cid']}|{it['kind']}] {it['text'][:80]}")
        show("② 譯文==原文", same, lambda it: f"[{it['cid']}|{it['kind']}] {it['text'][:80]}")
        show("③ 譯文無中文", nocjk, lambda r: f"[{r[0]['cid']}] {r[0]['text'][:60]} -> {r[1][:50]}")
        show("④ 夾心英文", leak, lambda r: f"[{r[0]['cid']}] …{r[2]}… : {r[1][:70]}")

    store.save_json(cfg, "verify_report.json", {
        "total": n,
        "missing": [{"cid": i["cid"], "kind": i["kind"], "text": i["text"][:300]} for i in missing],
        "same_as_source": [{"cid": i["cid"], "kind": i["kind"], "text": i["text"][:300]} for i in same],
        "no_cjk": [{"cid": i["cid"], "text": i["text"][:200], "zh": z[:200]} for i, z in nocjk],
        "english_leak": [{"cid": i["cid"], "hit": w, "zh": z[:200]} for i, z, w in leak],
        "duplicate_titles": {k: v for k, v in dup_titles.items()},
        "inconsistent_variants": {k: list(v.values()) for k, v in inconsistent.items()},
    })
    blocking = len(missing)
    print(f"\n阻擋出貨的問題數（①）= {blocking}")
    print(f"詳細報告：{cfg.wpath('verify_report.json')}")
    return blocking
