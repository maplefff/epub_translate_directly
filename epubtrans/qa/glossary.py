"""譯名表檢查：依 drafts/glossary.yaml 逐段比對 drafts 的原文與譯文，只報告不改稿。

每條譯名只看「原文含這個專名」的段落：譯文要有現行譯名，且不得殘留 old 列出的舊譯名。
只在相關段落裡找舊譯名，是因為舊譯名常常也是一般用詞（「班」「推車」），全書掃會淹沒在誤報裡。
翻到一半改譯名時，把舊譯名移進 old，這裡就會列出已翻章節裡所有要回頭改的段落。
缺譯名不一定是錯 —— 譯文可能用代名詞帶過 —— 逐條判斷。
"""
import os, re, yaml
from ..core import store
from ..translate import drafts

SAMPLE = """\
# 譯名表：python -m epubtrans glossary 據此逐段檢查 drafts。語體、譯例寫在 translation_notes.md。
# en：原文（字串或清單）。有大寫字母的區分大小寫，全小寫的不分；所有格自動涵蓋，複數請另列。
# zh：現行譯名（字串或清單，譯文含其中任一個就算符合）。
# old：改譯前用過的譯名。改譯名時把舊的移到這裡，glossary 會列出所有還沒改的段落。
- en: [Giants, Giant]
  zh: 巨人
  old: []
  note: 不可譯成「地球人」，會提前揭曉
"""


def _as_list(v):
    return [] if v is None else [v] if isinstance(v, str) else list(v)


def _pattern(terms):
    # 有大寫的區分大小寫，但全大寫的部名扉頁（DEADWAYS）也要算
    terms = set(terms) | {t.upper() for t in terms if any(c.isupper() for c in t)}
    alts = [re.escape(t) if any(c.isupper() for c in t) else f"(?i:{re.escape(t)})"
            for t in sorted(terms, key=len, reverse=True)]
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(alts) + r")(?![A-Za-z])")


def load(cfg):
    p = os.path.join(cfg.drafts, "glossary.yaml")
    if not os.path.exists(p):
        raise SystemExit(f"找不到 {p}\n格式範例：\n\n{SAMPLE}")
    entries = []
    for i, e in enumerate(yaml.safe_load(open(p, encoding="utf-8")) or []):
        en, zh = _as_list(e.get("en")), _as_list(e.get("zh"))
        if not en or not zh:
            raise SystemExit(f"glossary.yaml 第 {i + 1} 條缺 en 或 zh：{e}")
        entries.append({"en": en, "zh": zh, "old": _as_list(e.get("old")), "note": e.get("note"),
                        "re": _pattern(en), "label": f"{en[0]} → {zh[0]}"})
    return entries


def _around(s, start, end, width=24):
    a, b = max(0, start - width), min(len(s), end + width)
    return ("…" if a else "") + s[a:b].replace("\n", " ") + ("…" if b < len(s) else "")


def run(cfg, term=None, show_all=False, per_entry=5):
    entries = load(cfg)
    if term:
        t = term.lower()
        keys = lambda e: [x.lower() for x in e["en"] + e["zh"] + e["old"]]
        entries = ([e for e in entries if t in keys(e)]
                   or [e for e in entries if any(t in x for x in keys(e))])
        if not entries:
            raise SystemExit(f"glossary.yaml 沒有含「{term}」的條目")
    rows, skipped = drafts.aligned(cfg)

    report = []
    for e in entries:
        hits, missing, stale, elsewhere = 0, [], [], []
        for cid, i, src, zh in rows:
            m = e["re"].search(src)
            if not m:
                if any(o in zh for o in e["old"]):
                    elsewhere.append(f"{cid} #{i}")
                continue
            hits += 1
            where = f"{cid} #{i}"
            olds = [(o, zh.find(o)) for o in e["old"] if o in zh]
            if olds:
                o, k = olds[0]
                stale.append({"at": where, "old": o, "zh": _around(zh, k, k + len(o))})
            if not any(z in zh for z in e["zh"]):
                missing.append({"at": where, "src": _around(src, m.start(), m.end()), "zh": zh[:60]})
        report.append({"entry": e["label"], "en": e["en"], "zh": e["zh"], "old": e["old"], "hits": hits,
                       "missing": missing, "stale": stale, "old_elsewhere": elsewhere})

    bad = [r for r in report if r["missing"] or r["stale"]]
    print(f"譯名表 {len(entries)} 條；比對 {len(rows)} 段"
          + (f"（略過對位不符的章：{', '.join(skipped)}，先跑 merge --dry-run 修好）" if skipped else ""))
    unused = [r["entry"] for r in report if not r["hits"]]
    if bad:
        w = max(len(r["entry"]) for r in bad)
        print(f"\n{'條目'.ljust(w)}  出現段  缺譯名  舊譯殘留")
        for r in bad:
            print(f"{r['entry'].ljust(w)}  {r['hits']:>6}  {len(r['missing']):>6}  {len(r['stale']):>8}")
    print(f"\n其餘 {len(report) - len(bad) - len(unused)} 條全數一致"
          + (f"；{len(unused)} 條在原文裡找不到（en 拼錯？）：{', '.join(unused[:8])}" if unused else ""))

    stale = [(r, s) for r in report for s in r["stale"]]
    if stale:
        print("\n--- 舊譯殘留（要回 drafts 改）---")
        for r, s in stale:
            print(f"  [{s['at']}] {r['entry']}　舊譯「{s['old']}」：{s['zh']}")
    other = [r for r in report if r["old_elsewhere"]]
    if other and not (term or show_all):
        print(f"\n另有 {len(other)} 條的舊譯名出現在原文沒有該專名的段落，多半是一般用詞；"
              f"改譯時用 --term 查看。")
    elif other:
        print("\n--- 舊譯名也出現在原文沒有這個專名的段落（多半是一般用詞，改譯時仍要掃過）---")
        for r in other:
            at = r["old_elsewhere"]
            print(f"  {r['entry']}　舊譯「{'／'.join(r['old'])}」{len(at)} 段："
                  + ", ".join(at if show_all else at[:6]) + ("" if show_all or len(at) <= 6 else " …（--all 全列）"))
    if any(r["missing"] for r in report):
        print("\n--- 缺譯名（可能是代名詞帶過或省略，逐條判斷）---")
        for r in report:
            for s in (r["missing"] if show_all else r["missing"][:per_entry]):
                print(f"  [{s['at']}] {r['entry']}｜原文 {s['src']}｜譯文 {s['zh']}")
            if not show_all and len(r["missing"]) > per_entry:
                print(f"  …{r['entry']} 另有 {len(r['missing']) - per_entry} 筆（--all 全列）")

    store.save_json(cfg, "glossary_report.json", {"skipped": skipped, "entries": report})
    print(f"\n舊譯殘留 {len(stale)} 處；詳細報告：{cfg.wpath('glossary_report.json')}")
    return len(stale)
