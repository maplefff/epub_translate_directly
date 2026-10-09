"""把 read_translated_epub 抽出來的結構整理成「排版用」的書稿。

EPUB 的結構是為了重排螢幕而存在的，直接拿去印會有三類雜訊：
  1. 空章節（閱讀器用的封面頁，本身沒有內容）
  2. h4 以下的「假標題」—— 轉檔工具常把獻詞、版權頁的正文塞進 <h5>，
     它們不是段落層級的標題，是置中的排印行
  3. 部扉頁裡重複一次部名（EPUB 的扉頁是「PART I」＋「QUARTERS」兩行，
     章標題已經把兩者合起來了）
這一層把它們清掉，並標出哪些章是「部扉頁」——只有部扉頁需要整頁留白、
翻到右頁、背面空白這種紙本才有的待遇。
"""
import re

# 中文與西文之間的手動半形空格。譯稿為了螢幕閱讀會自己加，但 Typst 的
# cjk-latin-spacing 會再插一個 1/4 em，兩者疊加會變成過寬的空隙。
# 正確做法是剝掉手動的，讓排版器用字型度量算出精準間距。
CJK = r"㐀-䶿一-鿿豈-﫿"
_SP_AFTER = re.compile(rf"([{CJK}])[ \t]+(?=[A-Za-z0-9])")
_SP_BEFORE = re.compile(rf"([A-Za-z0-9%）)\].,;:!?])[ \t]+(?=[{CJK}])")


def strip_manual_spacing(t):
    t = _SP_AFTER.sub(r"\1", t)
    t = _SP_BEFORE.sub(r"\1", t)
    return t


# 兩個中文字（含全形標點）之間的半形空格。中文行文裡它不可能有意義，
# 幾乎一定是原書 <br> 被抽取成空格的殘跡 —— 例如《不停》的告示牌
# 「僅限值勤人員 貨物艙口——氣鎖 危險！」原文是三行（CREW ONLY／
# CARGO HATCH—AIRLOCK／DANGER!）。排印行把它還原成換行；正文段落裡則直接刪掉。
_CJK_GAP = re.compile(rf"(?<=[{CJK}　-〿＀-￯—…])[ \t]+(?=[{CJK}　-〿＀-￯—…])")


def _looks_like_part(ch):
    """部扉頁＝一個第一層章節，除了重複部名之外沒有內容。

    用「內容量」判斷而不是比對標題文字（「第一部」「PART I」「卷一」各書不同），
    書本專屬的例外交給 system_prompts.yaml 的 print.part_ids 覆寫。
    """
    if ch["level"] != 1 or not ch["title"]:
        return False
    body = [b for b in ch["blocks"] if b["k"] != "h"]
    if body:
        return False
    return len(ch["blocks"]) <= 1


def _is_cover(ch, cover):
    """整章只有封面圖（原書的封面頁，build 讓它當 EPUB 的封面）。印刷版的封面由
    use_cover 決定、書名頁另外排，這一章不能再當一頁正文印出來。"""
    blocks = ch["blocks"]
    return (ch["level"] == 1 and bool(cover) and bool(blocks)
            and all(b["k"] == "img" and b["file"] == cover for b in blocks))


def run(book, cfg):
    part_ids = set(cfg.get("part_ids") or [])
    drop_ids = set(cfg.get("drop_ids") or [])
    # 第一層、卻要照正文章排版的章節（大字章名、章首留白）。第一層在目錄裡與各部同層，
    # 前後附件（獻詞、版權頁）也是第一層，兩者的差別只能按 id 指定：
    # House of Debt 的第一章在第一部之前，原書目錄就把它和各部並列。
    chapter_ids = set(cfg.get("chapter_ids") or [])
    stats = {"cjk_gap": 0}
    out = []

    for ch in book["chapters"]:
        if ch["id"] in drop_ids or _is_cover(ch, book.get("cover")):
            continue
        ch["title"] = strip_manual_spacing(ch["title"])
        blocks = []
        for b in ch["blocks"]:
            if b["k"] in ("img", "ixnote", "eq", "figrow"):
                for x in b.get("cells") or [b]:
                    if x.get("cap"):
                        x["cap"] = strip_manual_spacing(x["cap"])
                blocks.append(b)
                continue
            if b["k"] == "ix":
                for k in ("en", "zh", "see"):
                    if b[k]:
                        b[k] = strip_manual_spacing(b[k])
                for sg in b["segs"]:
                    if sg["zh"]:
                        sg["zh"] = strip_manual_spacing(sg["zh"])
                blocks.append(b)
                continue
            src = b
            t = strip_manual_spacing(b["t"])
            if not t:
                continue
            if b["k"] == "h":
                # 第一個標題若只是把章標題再講一次（部扉頁的「艙區」），丟掉
                if not blocks and t and t in ch["title"]:
                    continue
                # h4 以下不是章節層級，是排印行：獻詞、題辭、簽名、版權條文、告示
                if b.get("level", 3) <= 3:
                    b = {"k": "h", "t": t}
                else:
                    b = {"k": "display", "lines": _CJK_GAP.split(t)}
            else:
                n_gap = len(_CJK_GAP.findall(t))
                if n_gap:
                    stats["cjk_gap"] += n_gap
                    t = _CJK_GAP.sub("", t)
                b = {"k": b["k"], "t": t}
            if src.get("id"):
                b["id"] = src["id"]
            blocks.append(b)
        ch["blocks"] = blocks

        if not blocks and not ch["title"]:
            continue
        # 空的第一層章節（閱讀器封面頁）直接丟掉，封面由 use_cover 決定
        if not blocks and ch["level"] == 1 and ch["id"] in ("cover", "c000"):
            continue

        # 排印行多到近千字的前後附件是版權頁、出版資訊這類法律條文，該用小字密排；
        # 少的（獻詞、題辭）才疏排。第一版一律疏排加窄版心，《不停》的原書版權頁
        # 因此溢出成兩頁，第二頁只剩半句 “otherwise circulated…”。
        disp = sum(len("".join(b["lines"])) for b in blocks if b["k"] == "display")
        ch["fine_print"] = ch["level"] == 1 and disp > cfg.get("fine_print_chars", 400)

        ch["is_part"] = ch["id"] in part_ids or (not part_ids and _looks_like_part(ch))
        ch["as_chapter"] = ch["level"] == 1 and ch["id"] in chapter_ids
        if ch["is_part"]:
            # 部扉頁只留部名。上面那個「與章標題重複就丟」的比對不夠：
            # 《不停》第四部的章標題曾人工指定為「第四部　那個大東西」，扉頁上那行
            # THE BIG SOMETHING 卻被模型另外譯成「龐然大物」，比對不上就漏網，
            # 單獨佔掉一頁、還把第一章擠到左頁（譯本後來統一為「那件大事」）。
            # 譯文不一致在任何一本書都可能發生，部扉頁本來就不該有第二個標題。
            ch["blocks"] = [b for b in ch["blocks"] if b["k"] not in ("h", "display")]
        out.append(ch)

    book["chapters"] = out
    n_part = sum(1 for c in out if c["is_part"])
    n_ch = sum(1 for c in out if c["level"] == 2 or c["as_chapter"])
    print(f"整理後：章節={len(out)}（部扉頁={n_part}　正文章={n_ch}　前後附件={len(out)-n_part-n_ch}）"
          + (f"　刪除中文字間的殘留空格 {stats['cjk_gap']} 處" if stats["cjk_gap"] else ""))
    return book
