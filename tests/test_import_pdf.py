#!/usr/bin/env python3
"""PDF 抽取的準確度：拿 tests/fixtures/make_test_pdfs.py 產生的測試書，和標準答案逐段比對。

測試書是把一本英文 EPUB 排成真實書籍版面（書眉、頁碼、斷字、註腳、目錄頁、書籤）再抽回來，
所以標準答案就是原 EPUB 的文字。比對項目：
  - 段落：依閱讀順序逐段比對，完全相同的比例；另算全書字元相似度（OCR 用）
  - 章節：部與章的標題序列要完全一致
  - 註腳：每則都要出現在所屬章節結尾的 Notes，且正文裡不能殘留
  - 插圖數
  - 書眉、頁碼沒有混進正文

用法：./.venv/bin/python tests/test_import_pdf.py ["Non-Stop PDF" "Non-Stop Scan"]
      （測試書不存在時先跑 tests/fixtures/make_test_pdfs.py）
"""
import difflib, io, json, os, re, sys
from contextlib import redirect_stdout
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from epubtrans.core.config import PROCESS, BookConfig
from epubtrans import source

# 門檻：文字層應該近乎完美；OCR 允許少量辨識錯誤
THRESHOLDS = {"text": {"para_exact": 0.99, "char_sim": 0.999},
              # OCR：誤字不算分段錯誤，另看字元相似度。版面 B（右邊參差、段間空一行）跨頁時句尾剛好落在
              # 頁底，版面上分不出段落有沒有結束，文字層也有 5 處；掃描版再加上頁底標點被 OCR 讀掉，實測 96.9%
              "scan": {"para_aligned": 0.96, "char_sim": 0.99}}
SUP = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")


LOOSE = False       # 掃描版：OCR 把彎引號轉成直引號、破折號轉成「 - 」，比對前先統一（對翻譯沒有影響）


def norm(t):
    t = re.sub(r"\s+", " ", SUP.sub("", t)).strip()
    if LOOSE:
        t = re.sub(r"\s*[-—–]\s*", "-", t.translate(str.maketrans("‘’“”", "''\"\"")))
    return t


def expected_sequence(fx):
    seq, titles, notes = [], [], []
    for s in fx["sections"]:
        if s["kind"] in ("part", "chapter"):
            titles.append(s["title"])
            seq.append(s["title"])
        seq.extend(s["texts"])
        notes.extend((s.get("title"), n) for n in s["footnotes"])
    return [norm(t) for t in seq], titles, notes


def actual_sequence(book):
    seq, titles, notes, images = [], [], [], 0
    for i, c in enumerate(book["chapters"]):
        items = c["items"]
        k = max((j for j, it in enumerate(items) if it["type"] == "heading" and it["text"] == "Notes"), default=None)
        body, tail = (items[:k], items[k + 1:]) if k is not None else (items, [])
        if not (i == 0 and c["title"] == book["title"]):       # 前付那一章的標題是自動補的書名
            titles.append(c["title"])
            seq.append(c["title"])
        for it in body:
            if it["type"] == "image":
                images += 1
            else:
                seq.append(it["text"])
        notes.extend((c["title"], it["text"]) for it in tail)
    return [norm(t) for t in seq], titles, notes, images


def evaluate(name):
    global LOOSE
    LOOSE = "Scan" in name
    d = os.path.join(PROCESS, name)
    fx = json.load(open(os.path.join(d, "fixture.json"), encoding="utf-8"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        source.run(BookConfig(name))
    print("  " + buf.getvalue().strip().replace("\n", "\n  "))
    book = json.load(open(os.path.join(d, "work", "book.json"), encoding="utf-8"))
    exp, exp_titles, exp_notes = expected_sequence(fx)
    act, act_titles, act_notes, images = actual_sequence(book)

    sm = difflib.SequenceMatcher(None, exp, act, autojunk=False)
    exact = sum(b.size for b in sm.get_matching_blocks())
    diffs = [op for op in sm.get_opcodes() if op[0] != "equal"]
    # 字元相似度：相同的段落整段算數，不一致的片段才逐字元比（整本逐字元比是 O(n²)，跑不動）
    matched = sum(len(exp[b.a + k]) for b in sm.get_matching_blocks() for k in range(b.size))
    for _, i1, i2, j1, j2 in diffs:
        a, b = "\n".join(exp[i1:i2]), "\n".join(act[j1:j2])
        matched += sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    char_sim = 2 * matched / (sum(map(len, exp)) + sum(map(len, act)))

    kind = "scan" if "Scan" in name else "text"
    th = THRESHOLDS[kind]
    results = []

    def check(label, ok, detail=""):
        results.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))

    # 分段一致：兩邊段落一一對上，且每段相似度 ≥ 95%（OCR 的誤字不算分段錯誤）
    aligned = exact + sum(
        sum(difflib.SequenceMatcher(None, exp[i1 + k], act[j1 + k], autojunk=False).ratio() >= 0.95
            for k in range(i2 - i1))
        for tag, i1, i2, j1, j2 in diffs if tag == "replace" and i2 - i1 == j2 - j1)
    if kind == "text":
        check(f"段落逐段相同 {exact}/{len(exp)}（{exact / len(exp):.2%}，門檻 {th['para_exact']:.0%}）",
              exact / len(exp) >= th["para_exact"])
    else:
        print(f"  ----  段落逐字相同 {exact}/{len(exp)}（{exact / len(exp):.2%}，OCR 誤字會拉低，僅供參考）")
        check(f"分段一致 {aligned}/{len(exp)}（{aligned / len(exp):.2%}，門檻 {th['para_aligned']:.0%}）",
              aligned / len(exp) >= th["para_aligned"])
    check(f"全書字元相似度 {char_sim:.4%}（門檻 {th['char_sim']:.1%}）", char_sim >= th["char_sim"])
    check(f"部與章的標題序列一致（{len(exp_titles)} 個）", [norm(t) for t in act_titles] == [norm(t) for t in exp_titles],
          f"期望 {exp_titles}\n        實際 {act_titles}")
    found = [any(norm(t) in norm(a) for _, a in act_notes) for _, t in exp_notes]
    check(f"註腳收到章尾 {sum(found)}/{len(exp_notes)}", all(found), str(act_notes))
    leaked = [t for t in act if any(norm(n)[:40] in t for _, n in exp_notes)]
    check("註腳沒有殘留在正文", not leaked, str(leaked[:2]))
    exp_images = sum(s.get("images", 0) for s in fx["sections"])
    check(f"插圖 {images}/{exp_images}", images == exp_images)
    heads = [t for t in act if re.fullmatch(r"(QUARTERS|DEADWAYS|FORWARDS|THE BIG SOMETHING|NON-STOP)?\s*\d{0,3}", t,
                                            re.I) and t.strip()]
    check("書眉與頁碼沒有混進正文", len(heads) <= 4, str(heads[:10]))    # 4 個部名本身是正文
    kinds = {}
    for c in book["chapters"]:
        for it in c["items"]:
            kinds[it["type"]] = kinds.get(it["type"], 0) + 1
    exp_q = sum(s.get("quotes", 0) for s in fx["sections"])
    exp_li = sum(s.get("lists", 0) for s in fx["sections"])
    check(f"引文 {kinds.get('quote', 0)}/{exp_q}、清單項目 {kinds.get('li', 0)}/{exp_li}",
          kinds.get("quote", 0) == exp_q and kinds.get("li", 0) == exp_li, str(kinds))

    if diffs:
        print(f"  不一致的片段（共 {len(diffs)} 處，列前 8 處）：")
        for tag, i1, i2, j1, j2 in diffs[:8]:
            print(f"    [{tag}] 期望 {exp[i1:i2][:2]}\n           實際 {act[j1:j2][:2]}")
    return results


def main():
    names = sys.argv[1:] or ["Non-Stop PDF", "Non-Stop Scan", "Non-Stop PDF B", "Non-Stop Scan B"]
    results = []
    for n in names:
        if not os.path.exists(os.path.join(PROCESS, n, "fixture.json")):
            print(f"略過 {n}：測試書不存在，先跑 ./.venv/bin/python tests/fixtures/make_test_pdfs.py")
            continue
        print(f"\n== {n}")
        results += evaluate(n)
    print(f"\n{sum(results)}/{len(results)} 通過")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
