"""專名候選清單：通讀全書時對照用，確保低頻專名不被漏掉。

候選＝在句中（非句首）以大寫開頭出現過的詞或連續大寫詞組。只在句首大寫的詞是一般用詞，
不列。小寫出現次數一併列出，Forwards／forwards 這種專名兼一般詞要靠人判斷。
"""
import collections, os, re
from ..core import store

WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
SENT_END = re.compile(r"[.!?:;…—–\"“”‘’()\[\]]\s*$")
POSS = re.compile(r"['’](s|ll|d|re|ve)$")
STOP = {"I", "I'm", "I’m", "I'll", "I’ll", "I've", "I’ve", "I'd", "I’d", "O", "OK",
        "Mr", "Mrs", "Ms", "Dr", "St"}
# 句中偶爾大寫的虛詞（稱神的 You、版權行等），不是專名
FUNC = set("""A An The And But Or Nor So Yet If Then Than As At By For From In Into Of On
Onto To With Without About After Before Under Over Up Down Out Off Not No Yes Oh Ah
All Any Some Each Every Both Either Neither This That These Those There Here
What When Where Which Who Whom Whose Why How
He She It We They You Me Him Her Us Them My Your His Its Our Their Mine Yours""".split())


def _runs(text):
    """回傳 [(詞組, 是否句中)]。"""
    out, run, run_mid, prev_end = [], [], False, 0
    for m in WORD.finditer(text):
        w = POSS.sub("", m.group(0)).rstrip("'’-")
        gap = text[prev_end:m.start()]
        cap = w[:1].isupper() and w not in STOP and w not in FUNC
        if run and (not cap or gap.strip()):
            out.append((" ".join(run), run_mid)); run = []
        if cap:
            if not run:
                before = text[:m.start()]
                run_mid = bool(before.strip()) and not SENT_END.search(before)
            run.append(w)
        prev_end = m.end()
    if run:
        out.append((" ".join(run), run_mid))
    return out


def collect(book):
    cap_mid = collections.Counter()
    cap_all = collections.Counter()
    first = {}
    chapters = collections.defaultdict(set)
    lower = collections.Counter()
    for it in store.source_items(book):
        if it["kind"] == "title":
            continue
        for w in WORD.findall(it["text"]):
            if w.islower():
                lower[w.rstrip("'’-")] += 1
        for term, mid in _runs(it["text"]):
            if term.isupper() and len(term) > 1 and " " not in term:
                continue  # 全大寫多半是強調或扉頁標題
            cap_all[term] += 1
            if mid:
                cap_mid[term] += 1
            first.setdefault(term, (it["ci"], it["cid"]))
            chapters[term].add(it["cid"])
    rows = []
    for term, n in cap_all.items():
        if not cap_mid[term]:
            continue
        low = lower[term.lower()] if " " not in term else 0
        rows.append({"term": term, "n": n, "mid": cap_mid[term], "lower": low,
                     "ci": first[term][0], "cid": first[term][1], "spread": len(chapters[term])})
    return rows


def run(cfg, upto=None, missing=False, min_n=1, sort="first"):
    book = store.load_book(cfg)
    rows = [r for r in collect(book) if r["n"] >= min_n]
    if upto:
        ids = [c["id"] for c in book["chapters"]]
        if upto not in ids:
            raise SystemExit(f"找不到章節 {upto}")
        rows = [r for r in rows if r["ci"] <= ids.index(upto)]

    notes = ""
    for name in ("glossary.yaml", "translation_notes.md"):
        p = os.path.join(cfg.drafts, name)
        if os.path.exists(p):
            notes += open(p, encoding="utf-8").read() + "\n"
    for r in rows:
        r["noted"] = bool(notes) and re.search(rf"(?<![A-Za-z]){re.escape(r['term'])}(e?s)?(?![A-Za-z])", notes) is not None
    if missing:
        rows = [r for r in rows if not r["noted"]]

    key = {"first": lambda r: (r["ci"], -r["n"]), "count": lambda r: (-r["n"], r["ci"]),
           "alpha": lambda r: r["term"].lower()}[sort]
    rows.sort(key=key)

    print(f"專名候選 {len(rows)} 個"
          + (f"（首次出現 ≤ {upto}）" if upto else "")
          + ("（僅列 glossary／notes 都未收）" if missing else "")
          + ("" if notes else "　※ 尚無 glossary.yaml 與 translation_notes.md"))
    print("收\t次數\t小寫\t章數\t首見\t候選")
    for r in rows:
        print(f"{'✓' if r['noted'] else '·'}\t{r['n']}\t{r['lower'] or ''}\t{r['spread']}\t{r['cid']}\t{r['term']}")
    with open(cfg.wpath("terms.tsv"), "w", encoding="utf-8") as f:
        f.write("noted\tcount\tlower\tchapters\tfirst\tterm\n")
        for r in rows:
            f.write(f"{int(r['noted'])}\t{r['n']}\t{r['lower']}\t{r['spread']}\t{r['cid']}\t{r['term']}\n")
    print(f"\n小寫欄有數字＝同一個詞也當一般詞用，譯名要看語境。清單另存：{cfg.wpath('terms.tsv')}")
