"""書末索引：把原書索引的每個頁碼對回段落，譯本才能重建索引。

原書索引的頁碼都是連到頁碼標記的連結（extract 記成 item["parts"]）。譯本的版面
與原書無關 —— 原書第 32 頁在 B5 可能是第 30 頁，EPUB 則根本沒有頁 —— 所以頁碼
不能照抄，要先對到「那一頁上講到這個詞的那一段」，再由 build 與 Typst 換成譯本
自己的位置：EPUB 連到段落，PDF 由 Typst 算出段落所在的頁碼。

條目格式（Chicago 手冊的 run-in 格式，House of Debt 即是）：
  head, 頁碼, 頁碼; 子條目, 頁碼; 子條目, 頁碼. See also 其他條目
  head: 子條目, 頁碼; …               條目本身沒有頁碼
  head. See 其他條目                  純參見
頁碼：32、32–33、107–8（迄頁省略前綴）、130f（圖）、193n7（注）、195nn7–8。
結果寫回 item["entry"]：{"head", "segs": [{"label", "refs"}], "see"}，
每個 ref 帶 to（[章節 id, item 序號]）、跨頁時的 end、對位方式 how。

對位規則：
  - 一般頁碼：該頁的段落裡找條目與子條目的關鍵字，分數最高的第一段；
    一個都沒有就取「從那一頁開始的第一段」。範圍的迄頁取最後一段有詞的。
  - 圖（f）：該頁以 Figure 開頭的段落（圖說）。
  - 注（n）：注釋章裡「以注號 N 開頭」的段落，依關鍵字與頁碼距離挑。
    House of Debt 的索引沒有為平裝版更新：平裝版在注釋前插入新的後記，注釋頁
    整批往後移了十幾頁，193n7 其實在另一頁。頁差從「關鍵字只對上一條注」的
    那些頁碼統計（中位數），不寫死在程式裡。
"""
import re
import statistics

TEXT = ("para", "quote", "li", "heading")
_SUFFIX = re.compile(r"^(?:[–-]\d+f?|f|nn?\d+(?:[–-]\d+)?)(?![A-Za-z0-9])")
_NOTE_NO = r"(\d+)\.?\s"                  # 注釋段落開頭的注號：「7 」或「7. 」
_REF = re.compile(r"^(\d+)(?:[–-](\d+))?(f)?(?:nn?(\d+)(?:[–-](\d+))?)?$")
_SEE = re.compile(r"^(.*?)\.\s+(See\b.*)$", re.S)
# 「Title: Subtitle (Author)」是書名、論文名裡的冒號，不是「條目: 子條目」
_BYLINE = re.compile(r"\([A-Z][a-z]+(?:,? (?:and )?[A-Z][a-z]+)*\)$")
STOP = set("""a an and as at by during e.g for from in into its of on or the their to under
    vs with see also his her they them this that these those than""".split())


# ── 解析 ────────────────────────────────────────────────────────────
def _expand(p, s):
    """107–8 → 108；111–13 → 113；7–9 → 9。"""
    if s is None:
        return p
    return int(str(p)[:-len(s)] + s) if len(s) < len(str(p)) else int(s)


def parse_ref(tok):
    m = _REF.match(tok["t"])
    if not m:
        return {"t": tok["t"], "p": tok["page"], "q": tok["page"], "fig": False, "notes": None, "bad": True}
    p = tok["page"]
    notes = None
    if m.group(4):
        a = int(m.group(4))
        notes = [a, _expand(a, m.group(5))] if m.group(5) else [a]
    return {"t": tok["t"], "p": p, "q": _expand(p, m.group(2)), "fig": bool(m.group(3)), "notes": notes}


def _plain(piece):
    """「borrower default rates in, 101–3」：原書漏了連結、頁碼只是文字的子條目。"""
    m = re.match(r"^(.*?),\s*(\d+(?:[–-]\d+)?(?:,\s*\d+(?:[–-]\d+)?)*)$", piece)
    if not m:
        return piece.rstrip(",").strip(), []
    refs = [parse_ref({"t": t, "page": int(re.match(r"\d+", t).group(0))})
            for t in re.split(r",\s*", m.group(2))]
    return m.group(1).strip(), refs


def parse(parts):
    """parts（文字與頁碼連結交錯）→ 條目結構。認不得的分隔記進 warn。"""
    toks = []
    for x in parts:
        if isinstance(x, dict):
            toks.append(dict(x))
            continue
        # 連結後面緊跟的 f／nn7–8／–51 屬於頁碼本身（原書把它們放在連結外）
        if toks and isinstance(toks[-1], dict) and (m := _SUFFIX.match(x)):
            toks[-1]["t"] += m.group(0)
            x = x[m.end():]
        if x:
            toks.append(x)

    warn = []
    pre = toks[0] if toks and isinstance(toks[0], str) else ""
    rest = toks[1:] if pre else toks
    if not any(isinstance(t, dict) for t in rest):
        m = _SEE.match(pre.strip())
        head, see = (m.group(1), m.group(2)) if m else (pre.strip(), None)
        return {"head": head.strip(), "segs": [], "see": see}

    pre = pre.rstrip().rstrip(",").rstrip()
    head, _, label = pre.partition(": ")
    if head.count("“") > head.count("”") or _BYLINE.search(label):
        head, label = pre, ""
    seg = {"label": label.strip() or None, "refs": []}
    segs, see = [], None
    for t in rest:
        if isinstance(t, dict):
            seg["refs"].append(parse_ref(t))
            continue
        s = t.strip()
        if s == ",":
            continue
        if s.startswith(";"):
            # 分號之間若夾著完整的「子條目, 頁碼」，是原書漏了連結（House of Debt 有一處
            # 連結被轉檔換成頁碼標記），頁碼照文字收
            pieces = [x.strip() for x in s[1:].split(";")]
            for piece in pieces[:-1]:
                segs.append(seg)
                label, refs = _plain(piece)
                seg = {"label": label, "refs": refs}
            segs.append(seg)
            seg = {"label": pieces[-1].rstrip(",").strip(), "refs": []}
        elif m := re.match(r"^\.\s*(See\b.*)$", s, re.S):
            see = m.group(1).strip()
        else:
            warn.append(s)
    segs.append(seg)
    e = {"head": head.strip(), "segs": segs, "see": see}
    if warn:
        e["warn"] = warn
    return e


def slots(entry):
    """譯稿要填的欄位：條目本身＋每個有名稱的子條目；see 另計。"""
    return [entry["head"]] + [s["label"] for s in entry["segs"] if s["label"]]


# ── 對位 ────────────────────────────────────────────────────────────
def _keys(s):
    return [w.lower() for w in re.findall(r"[A-Za-z]+|\d{4}", s or "")
            if len(w) >= 2 and w.lower() not in STOP]


def _pattern(k):
    stem = k if len(k) <= 5 else k[:max(5, len(k) - 3)]
    return re.compile(r"\b" + re.escape(stem), re.I)


def _scorer(head, label):
    hk = [_pattern(k) for k in dict.fromkeys(_keys(head))]
    lk = [_pattern(k) for k in dict.fromkeys(_keys(label))]

    def score(text):
        return 2 * sum(1 for p in lk if p.search(text)) + sum(1 for p in hk if p.search(text))
    return score


def _is_index(ch):
    items = [it for it in ch["items"] if it["type"] in ("para", "li")]
    return bool(items) and sum("parts" in it for it in items) >= len(items) / 2


def _is_notes(ch):
    items = [it for it in ch["items"] if it["type"] == "para"]
    return bool(items) and sum(bool(re.match(_NOTE_NO, it["text"])) for it in items) >= len(items) * 0.6


def run(chapters, report=None):
    idx_chs = [c for c in chapters if _is_index(c)]
    if not idx_chs:
        return
    body = [c for c in chapters if c not in idx_chs]

    on_page = {}                                  # 頁碼 → [(cid, 序號, item)]，依書中順序
    for c in body:
        for i, it in enumerate(c["items"]):
            if it["type"] in TEXT and "page" in it:
                for p in range(it["page"], it.get("page_end", it["page"]) + 1):
                    on_page.setdefault(p, []).append((c["id"], i, it))
    notes = {}                                    # 注號 → [(cid, 序號, item)]
    for c in body:
        if _is_notes(c):
            for i, it in enumerate(c["items"]):
                m = re.match(_NOTE_NO, it["text"]) if it["type"] == "para" else None
                if m:
                    notes.setdefault(int(m.group(1)), []).append((c["id"], i, it))
    note_keys = {x[:2] for xs in notes.values() for x in xs}
    order = {(c["id"], i): n for n, (c, i) in
             enumerate((c, i) for c in chapters for i in range(len(c["items"])))}

    entries = []
    for c in idx_chs:
        for it in c["items"]:
            if it["type"] not in ("para", "li"):
                continue
            it["entry"] = parse(it.pop("parts", None) or [it["text"]])
            entries.append(it["entry"])

    # 注釋頁的頁差：關鍵字只對上一條同號注釋的，拿它的頁碼減索引上的頁碼
    diffs = []
    for e in entries:
        for s in e["segs"]:
            sc = _scorer(e["head"], s["label"])
            for r in s["refs"]:
                if r["notes"] and r["notes"][0] in notes:
                    got = [(sc(x[2]["text"]), x) for x in notes[r["notes"][0]]]
                    top = max(g for g, _ in got)
                    hits = [x for g, x in got if g == top]
                    if top >= 2 and len(hits) == 1:
                        diffs.append(hits[0][2]["page"] - r["p"])
    offset = round(statistics.median(diffs)) if diffs else 0

    def near(p):
        for d in range(0, 4):
            for q in (p + d, p - d):
                if on_page.get(q):
                    return on_page[q]
        return []

    def pick_page(r, sc, last=False):
        p = r["q"] if last else r["p"]
        cands = on_page.get(p) or near(p)
        if not cands:
            return None, "無"
        if r["fig"] and not last:
            figs = [x for x in cands if x[2]["text"].startswith("Figure")]
            if figs:
                return max(figs, key=lambda x: sc(x[2]["text"])), "圖"
        scored = [(sc(x[2]["text"]), x) for x in cands]
        top = max(g for g, _ in scored)
        if top > 0:
            hits = [x for g, x in scored if (g > 0 if last else g == top)]
            return (hits[-1] if last else hits[0]), "詞"
        starts = [x for x in cands if x[2]["page"] == p]
        return (starts or cands)[0], "頁"

    def dist(x, p):
        lo, hi = x[2]["page"], x[2].get("page_end", x[2]["page"])
        return 0 if lo <= p <= hi else min(abs(lo - p), abs(hi - p))

    def pick_note(r, sc):
        # 頁碼比關鍵字可靠：注釋多半是書目，詞不一定出現在注文裡，而同一頁附近
        # 常有好幾條同號注（各章的注 7）。先取「同號、落在推得的那一頁」的，
        # 關鍵字只用來在同頁的幾條之間挑；第一版關鍵字優先，錯了 16 處。
        want = r["p"] + offset
        cands = notes.get(r["notes"][0]) or []
        exact = [x for x in cands if dist(x, want) == 0]
        if exact:
            best, how = max(exact, key=lambda x: sc(x[2]["text"])), "注"
        else:
            # 那一頁沒有這個注號：原書索引自己寫錯了（House of Debt 的 192n29，
            # 第一章只有 22 條注）。改在那一頁的注釋裡找詞，對位方式標成「注?」待查。
            page = [x for x in on_page.get(want, []) if x[:2] in note_keys and sc(x[2]["text"]) > 0]
            if page:
                best, how = max(page, key=lambda x: sc(x[2]["text"])), "注?"
            elif cands:
                best, how = min(cands, key=lambda x: (dist(x, want), -sc(x[2]["text"]))), "注近"
            else:
                return None, None, "無"
        end = None
        if len(r["notes"]) > 1:                   # 195nn7–8：往後找同一節裡的注 8
            ch = next(c for c in chapters if c["id"] == best[0])
            for i in range(best[1] + 1, len(ch["items"])):
                t = ch["items"][i]
                if t["type"] == "heading":
                    break
                if (m := re.match(_NOTE_NO, t["text"])) and int(m.group(1)) == r["notes"][1]:
                    end = (best[0], i, t)
                    break
        return best, end, how

    rows, stats = [], {}
    for e in entries:
        for s in e["segs"]:
            sc = _scorer(e["head"], s["label"])
            for r in s["refs"]:
                if r["notes"]:
                    start, end, how = pick_note(r, sc)
                else:
                    start, how = pick_page(r, sc)
                    end = None
                    if r["q"] > r["p"]:
                        end, _ = pick_page(r, sc, last=True)
                stats[how] = stats.get(how, 0) + 1
                r["how"] = how
                if start is None:
                    continue
                r["to"] = [start[0], start[1]]
                if end and order[end[:2]] > order[start[:2]]:
                    r["end"] = [end[0], end[1]]
                rows.append((e["head"], s["label"] or "", r["t"], how, f"{start[0]}#{start[1]}",
                             start[2]["text"][:90]))

    n_ref = sum(len(s["refs"]) for e in entries for s in e["segs"])
    n_sub = sum(1 for e in entries for s in e["segs"] if s["label"])
    n_warn = sum(1 for e in entries if e.get("warn"))
    print(f"索引：條目 {len(entries)}（子條目 {n_sub}）　頁碼 {n_ref}　對位 "
          + "／".join(f"{k} {v}" for k, v in sorted(stats.items(), key=lambda kv: -kv[1]))
          + (f"　注釋頁差 {offset:+d}（{len(diffs)} 筆推得）" if diffs else "")
          + (f"　⚠ 認不得的分隔 {n_warn} 條" if n_warn else ""))
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write("條目\t子條目\t原頁碼\t對位\t段落\t段落開頭\n")
            for row in rows:
                f.write("\t".join(str(x).replace("\t", " ") for x in row) + "\n")
