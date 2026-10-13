import argparse, os, textwrap


def cmd_init(a):
    from .core.config import PROCESS, SETTINGS, SOURCE_EXTS
    d = os.path.join(PROCESS, a.book)
    os.makedirs(os.path.join(d, "drafts"), exist_ok=True)
    p = os.path.join(d, "system_prompts.yaml")
    if os.path.exists(p) and not a.force:
        print(f"已存在，未覆寫：{p}")
        return
    srcs = [x for x in sorted(os.listdir(d)) if x.lower().endswith(SOURCE_EXTS) and not x.startswith("《")]
    # ACSM 領回來的 EPUB 和 ACSM 並存時，原檔記 ACSM
    src = next((x for x in srcs if x.lower().endswith(".acsm")), srcs[0] if srcs else "")
    tpl = open(os.path.join(SETTINGS, "system_prompts.template.yaml"), encoding="utf-8").read()
    tpl = tpl.replace("{name}", a.book).replace("{src}", src)
    if src.lower().endswith(".pdf"):
        tpl += open(os.path.join(SETTINGS, "system_prompts.template.pdf.yaml"), encoding="utf-8").read()
    open(p, "w", encoding="utf-8").write(tpl)
    print(f"建立 {d}（原檔：{src or '尚未放入，source_file 留空＝自動偵測'}）")


def _vlm_python():
    from .core.config import ROOT
    py = os.path.join(ROOT, ".venv-vlm", "bin", "python")
    if not os.path.exists(py):
        raise SystemExit("缺少 VLM 環境：\n  /opt/homebrew/bin/python3.12 -m venv .venv-vlm && "
                         ".venv-vlm/bin/pip install -r requirements-vlm.txt")
    return py, os.path.join(ROOT, "epubtrans", "source", "import_pdf")


def cmd_layout(a):
    """普通書籍的掃描頁：在 .venv-vlm 裡只跑版面模型，框寫進 work/layout/（pdf.layout: true 的 extract 用）。"""
    import subprocess, sys
    cfg = _cfg(a)
    py, here = _vlm_python()
    if a.pages:
        pages = a.pages
    else:
        from .source.import_pdf import ocr_page_numbers
        nos = ocr_page_numbers(cfg)
        if not nos:
            raise SystemExit("沒有要走 OCR 的頁（全是文字層，或 pdf.mode 是 vlm）")
        runs = []
        for n in nos:
            if runs and n == runs[-1][1] + 1:
                runs[-1][1] = n
            else:
                runs.append([n, n])
        pages = ",".join(f"{x + 1}-{y + 1}" if x != y else f"{x + 1}" for x, y in runs)
    sys.exit(subprocess.call([py, os.path.join(here, "layout_worker.py"), cfg.source_file(), cfg.wpath("layout"),
                              "--pages", pages]))


def cmd_vlm_ocr(a):
    """掃描數學書的整頁 OCR：在 .venv-vlm 裡跑 vlm_worker（模型只在那個環境），結果寫進 work/vlm/。"""
    import subprocess, sys
    cfg = _cfg(a)
    py, here = _vlm_python()
    worker = os.path.join(here, "vlm_worker.py")
    args = [py, worker, cfg.source_file(), cfg.wpath("vlm"), "--batch", str(a.batch)]
    if a.pages:
        args += ["--pages", a.pages]
    # 多個程序各自搶頁（vlm_worker 用鎖檔分工），錯開幾秒啟動，免得同時載入模型
    import time
    procs = []
    for k in range(max(1, a.workers)):
        procs.append(subprocess.Popen(args))
        if k + 1 < a.workers:
            time.sleep(20)
    sys.exit(max(p.wait() for p in procs))


def _cfg(a):
    from .core.config import BookConfig
    return BookConfig(a.book)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m epubtrans", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="EPUB 直譯流程：原文由本機抽取，譯文由 Claude 直接寫進 drafts/，不呼叫模型端點",
        epilog=textwrap.dedent("""\
            流程：
              python -m epubtrans init    "書名"            建立骨架與 system_prompts.yaml
              python -m epubtrans fetch   "書名" [x.acsm]   ACSM 領書並解密 → process/書名/{原書名}.epub
              python -m epubtrans vlm-ocr "書名" [--pages 1-50] [--workers 3]   掃描數學書：整頁 OCR 成 Markdown＋LaTeX（work/vlm/，pdf.mode: vlm 用）
              python -m epubtrans layout  "書名" [--pages 9-380]   掃描頁只跑版面模型（work/layout/，pdf.layout: true 用；實驗中）
              python -m epubtrans extract "書名"            原檔 → work/book.json
              python -m epubtrans status  "書名"            每章段數／字數／譯稿進度
              python -m epubtrans page    "書名" 37         把 PDF 原書第 37 頁輸出成圖，對照抽出的文字
              python -m epubtrans dump    "書名" c008 [起 迄] 印出某章原文（序號<TAB>原文）
              python -m epubtrans terms   "書名" [--upto c012] [--missing]   專名候選清單（通讀時對照 glossary／notes）
              python -m epubtrans merge   "書名" [cid…]     drafts/ → work/translations.json（對位檢查）
              python -m epubtrans verify  "書名"            漏譯檢查
              python -m epubtrans zh-lint "書名"            台灣用語檢查（只報告，修改請回 drafts/）
              python -m epubtrans glossary "書名" [--term X] [--all]   依 drafts/glossary.yaml 檢查譯名一致與舊譯殘留
              python -m epubtrans build   "書名"            產出譯本 EPUB
              python -m epubtrans pdf     "書名" --paper b5 [b4 a4]   依紙張自動排版，產出可列印 PDF
              python -m epubtrans pdf     "書名" --paper b5 --tone light   夜讀黃底版（light/cream/wheat/honey/amber）
              python -m epubtrans pdf     "書名" --paper b5 --document     文件式（左右等寬；預設書本式，內側留寬）
              python -m epubtrans pdf-verify "書名" --paper b5       重新逐頁驗證已產出的 PDF
              python -m epubtrans fonts                         列出可用的中文字型
              python -m epubtrans acsm-register                 註冊匿名 Adobe ID（adept/ 沒有授權時才需要）

            紙張：a4＝210×297、b5＝JIS 182×257、b4＝JIS 257×364、a5、iso-b5、iso-b4（mm）
        """))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help):
        s = sub.add_parser(name, help=help)
        s.add_argument("book")
        return s

    s = add("init", "建立書本目錄骨架"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)
    s = add("fetch", "ACSM 領書並解密")
    s.add_argument("acsm", nargs="?", help="ACSM 路徑；會複製進書本目錄。省略時用書本目錄裡的 .acsm")
    s.add_argument("--force", action="store_true", help="ACSM 過期也硬試一次")
    s.set_defaults(fn=lambda a: __import__("epubtrans.source.fetch_acsm", fromlist=["run"]).run(
        _cfg(a), a.acsm, a.force))
    s = add("vlm-ocr", "掃描數學書的整頁 OCR（PP-DocLayout-V3＋Qwen3.5-27B，本機，結果快取在 work/vlm/）")
    s.add_argument("--pages", default="", help="只做這些頁，例 1-50,61（PDF 頁碼）")
    s.add_argument("--batch", type=int, default=1, help="同一程序同時解碼幾頁（M5 Max 上批次沒有比較快；要加速改開多個程序）")
    s.add_argument("--workers", type=int, default=1, help="同時開幾個 OCR 程序（各載一份模型，27B 8bit 每個約 28GB）")
    s.set_defaults(fn=cmd_vlm_ocr)
    s = add("layout", "掃描頁只跑版面模型 PP-DocLayout-V3（本機，結果快取在 work/layout/；實驗中）")
    s.add_argument("--pages", default="", help="只做這些頁，例 9-50,61（PDF 頁碼）；省略＝extract 會走 OCR 的頁")
    s.set_defaults(fn=cmd_layout)
    add("extract", "抽取原文結構").set_defaults(
        fn=lambda a: __import__("epubtrans.source", fromlist=["run"]).run(_cfg(a)))
    s = add("page", "把 PDF 原書某一頁輸出成圖")
    s.add_argument("page_no", type=int); s.add_argument("--dpi", type=int, default=150)
    s.set_defaults(fn=lambda a: __import__("epubtrans.source.import_pdf", fromlist=["render_page"]).render_page(
        _cfg(a), a.page_no, a.dpi))
    add("status", "譯稿進度").set_defaults(
        fn=lambda a: __import__("epubtrans.translate.drafts", fromlist=["status"]).status(_cfg(a)))
    s = add("dump", "印出某章原文")
    s.add_argument("cid"); s.add_argument("lo", nargs="?", type=int, default=0)
    s.add_argument("hi", nargs="?", type=int)
    s.set_defaults(fn=lambda a: __import__("epubtrans.translate.drafts", fromlist=["dump"]).dump(_cfg(a), a.cid, a.lo, a.hi))
    s = add("terms", "專名候選清單")
    s.add_argument("--upto", metavar="CID", help="只列首次出現在這一章（含）之前的")
    s.add_argument("--missing", action="store_true", help="只列 glossary.yaml 與 translation_notes.md 都還沒收的")
    s.add_argument("--min", type=int, default=1, dest="min_n", help="至少出現幾次")
    s.add_argument("--sort", choices=["first", "count", "alpha"], default="first")
    s.set_defaults(fn=lambda a: __import__("epubtrans.source.terms", fromlist=["run"]).run(
        _cfg(a), a.upto, a.missing, a.min_n, a.sort))
    s = add("merge", "併入譯稿"); s.add_argument("only", nargs="*", metavar="CID")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=lambda a: __import__("epubtrans.translate.drafts", fromlist=["merge"]).merge(
        _cfg(a), a.only, a.dry_run))
    add("verify", "漏譯檢查").set_defaults(
        fn=lambda a: __import__("epubtrans.qa.verify", fromlist=["run"]).run(_cfg(a)))
    add("zh-lint", "台灣用語檢查（只報告）").set_defaults(
        fn=lambda a: __import__("epubtrans.qa.zh_lint", fromlist=["run"]).run(_cfg(a)))
    s = add("review", "譯後審閱：原文譯文並排；不給 cid 則列審閱進度")
    s.add_argument("cid", nargs="?"); s.add_argument("lo", nargs="?", type=int, default=0)
    s.add_argument("hi", nargs="?", type=int)
    s.add_argument("--done", action="store_true", help="把這一章標記為已審")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_review)
    s = add("revise", "修改譯稿中的一句並記錄（舊字串須在該段恰好出現一次）")
    s.add_argument("cid"); s.add_argument("idx", type=int, nargs="?")
    s.add_argument("--old"); s.add_argument("--new")
    s.add_argument("--why", help="修改理由（--batch 時是檔案裡沒寫理由的預設值）")
    s.add_argument("--batch", help="一次套用多處：每行「段號<TAB>舊字串<TAB>新字串[<TAB>理由]」")
    s.set_defaults(fn=cmd_revise)
    s = add("glossary", "譯名一致性檢查（只報告）")
    s.add_argument("--term", help="只看含這個字串的條目（原文、譯名或舊譯名）")
    s.add_argument("--all", action="store_true", dest="show_all", help="缺譯名全部列出（預設每條 5 筆）")
    s.set_defaults(fn=lambda a: __import__("epubtrans.qa.glossary", fromlist=["run"]).run(
        _cfg(a), a.term, a.show_all))
    s = add("build", "產出譯本 EPUB"); s.add_argument("--allow-partial", action="store_true")
    s.set_defaults(fn=lambda a: __import__("epubtrans.output.export_epub", fromlist=["run"]).run(_cfg(a), a.allow_partial))

    s = add("pdf", "產出可列印 PDF（每種紙張一份）")
    s.add_argument("--paper", nargs="+", default=["b5"], help="a4 / b5 / b4 / a5 / iso-b5 / iso-b4")
    s.add_argument("--body-size", type=float, dest="body_size", help="覆寫正文字級（pt）")
    s.add_argument("--cjk-font", dest="cjk_font", help="覆寫中文字型")
    s.add_argument("--no-toc", action="store_const", const=False, dest="toc", help="不排目錄")
    s.add_argument("--cover", action="store_const", const=True, dest="use_cover", help="用原書封面圖當第一頁")
    s.add_argument("--tone", nargs="+", default=[None],
                   help="夜讀黃底色調：light / cream / wheat / honey / amber（見 settings/print_profile.yaml）")
    s.add_argument("--document", action="store_const", const="document", dest="style",
                   help="文件式：左右邊界等寬（預設書本式：內側比外側寬、左右頁鏡像）")
    s.set_defaults(fn=cmd_pdf)
    s = add("pdf-verify", "重新逐頁驗證已產出的 PDF")
    s.add_argument("--paper", nargs="+", default=["b5"])
    s.add_argument("--tone", nargs="+", default=[None])
    s.add_argument("--document", action="store_const", const="document", dest="style", help="驗證文件式")
    s.set_defaults(fn=lambda a: [__import__("epubtrans.output.export_pdf.pipeline", fromlist=["check"]).check(
        _cfg(a), p, t, a.style) for p in a.paper for t in a.tone] and None)
    sub.add_parser("fonts", help="列出可用的中文字型").set_defaults(fn=cmd_fonts)
    sub.add_parser("acsm-register", help="註冊匿名 Adobe ID（會在 Adobe 建帳號，由使用者自己執行）").set_defaults(
        fn=lambda a: __import__("epubtrans.source.fetch_acsm", fromlist=["register"]).register())

    a = ap.parse_args(argv)
    a.fn(a)


def cmd_revise(a):
    from .qa import review
    if a.batch:
        return review.revise_batch(_cfg(a), a.cid, a.batch, a.why or "")
    if a.idx is None or a.old is None or a.new is None or not a.why:
        raise SystemExit("revise 需要 段號、--old、--new、--why（或用 --batch 檔案）")
    review.revise(_cfg(a), a.cid, a.idx, a.old, a.new, a.why)


def cmd_review(a):
    from .qa import review
    cfg = _cfg(a)
    if not a.cid:
        return review.progress(cfg)
    if a.done:
        return review.done(cfg, a.cid, a.note)
    review.show(cfg, a.cid, a.lo, a.hi)


def cmd_pdf(a):
    from .output.export_pdf import pipeline
    cfg = _cfg(a)
    cli = {"body_size": a.body_size, "cjk_font": a.cjk_font, "toc": a.toc, "use_cover": a.use_cover,
           "style": a.style}
    for p in a.paper:
        for t in a.tone:
            print(f"\n{'=' * 60}\n{p}{' ' + t if t else ''}\n{'=' * 60}")
            pipeline.run(cfg, p, cli, t)


def cmd_fonts(a):
    import re, subprocess
    from .output.export_pdf.pipeline import TYPST
    out = subprocess.run([TYPST, "fonts"], capture_output=True, text=True).stdout
    pat = re.compile(r"song|ping|hei|kai|ming|yuanti|hiragino|noto|source han|lisong|biau", re.I)
    for line in sorted(set(out.splitlines())):
        if pat.search(line):
            print(" ", line)
