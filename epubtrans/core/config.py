"""載入 process/{書名}/system_prompts.yaml 與 epubtrans/settings/zh_tw_lint.yaml。

這個專案不呼叫任何模型端點，所以沒有 endpoint / model / prompts 這些設定層；
書本設定只剩 extract 與 build 用得到的欄位。
"""
import os, re, yaml

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PKG)
PROCESS = os.path.join(ROOT, "process")
SETTINGS = os.path.join(PKG, "settings")
LINT_RULES = os.path.join(SETTINGS, "zh_tw_lint.yaml")
# Adobe 授權檔（ACSM 領書用），不進版控；可用環境變數改放別處
ADEPT_DIR = os.environ.get("EPUBTRANS_ADEPT_DIR") or os.path.join(ROOT, "adept")
# 可以當原檔的格式；《》開頭的是本專案的產出，不算
SOURCE_EXTS = (".epub", ".pdf", ".acsm")


# title_zh 同時是 EPUB 的 dc:title，習慣寫成「心之地圖（Atlas of the Heart）」；
# 檔名要的是不含附註的那一半，所以砍掉尾端那組括號。
_PAREN_TAIL = re.compile(r'\s*[（(][^（()）]*[）)]\s*$')


def safe_filename(s):
    """砍掉檔名不能用的字元。'/' 在 macOS 檔名裡會被 Finder 顯示成 ':'，換成全形；
    ':' 在 Windows 直接非法，一併換掉。《》全形括號本身是合法的。"""
    s = s.replace("/", "／").replace("\\", "＼").replace(":", "：")
    s = re.sub(r'[\x00-\x1f]', '', s)
    return re.sub(r'\s+', ' ', s).strip(' .')


class BookConfig:
    def __init__(self, name):
        self.name = name
        self.dir = os.path.join(PROCESS, name)
        if not os.path.isdir(self.dir):
            raise SystemExit(f"找不到書本目錄：{self.dir}\n先跑 `python -m epubtrans init \"{name}\"`")
        self.work = os.path.join(self.dir, "work")
        os.makedirs(self.work, exist_ok=True)
        spath = os.path.join(self.dir, "system_prompts.yaml")
        if not os.path.exists(spath):
            raise SystemExit(f"找不到 {spath}\n先跑 `python -m epubtrans init \"{name}\"` 產生範本")
        self.raw = yaml.safe_load(open(spath, encoding="utf-8")) or {}

    def get(self, *path, default=None):
        cur = self.raw
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    @property
    def book(self):
        return self.raw.get("book", {})

    @property
    def translator(self):
        """翻譯模型的名稱（book.translator，例「Claude Opus 5.5」）。"""
        return str(self.book.get("translator") or "").strip()

    def fill_translator(self, text):
        """colophon 與 print.imprint 裡的 {translator} 代入 book.translator。
        沒填就停：佔位字印進譯本，比少印一行更糟。"""
        if not text or "{translator}" not in text:
            return text
        if not self.translator:
            raise SystemExit(
                "system_prompts.yaml 的 book.translator 還沒填（翻譯模型的名稱，例：Claude Opus 5.5），"
                "colophon／print.imprint 裡的 {translator} 無從代入。\n"
                "原書已是中文、不必翻譯的話，把含 {translator} 的那幾行刪掉。")
        return text.replace("{translator}", self.translator)

    @property
    def lint_rules(self):
        """台灣用語檢查規則（順序即比對順序）。"""
        if not os.path.exists(LINT_RULES):
            return []
        rules = (yaml.safe_load(open(LINT_RULES, encoding="utf-8")) or {}).get("rules") or []
        return [r for r in rules if r.get("find") and r.get("replace") is not None]

    def wpath(self, *parts):
        return os.path.join(self.work, *parts)

    @property
    def drafts(self):
        return os.path.join(self.dir, "drafts")

    def source_file(self):
        """原檔路徑（.epub／.pdf／.acsm）。book.source_file 沒寫時，目錄裡要剛好只有一個候選。"""
        f = self.book.get("source_file")
        if f:
            p = os.path.join(self.dir, f)
            if os.path.exists(p):
                return p
            raise SystemExit(f"system_prompts.yaml 指定的 source_file 不存在：{p}")
        cands = [x for x in sorted(os.listdir(self.dir))
                 if x.lower().endswith(SOURCE_EXTS) and not x.startswith("《")]
        # ACSM 領回來的 EPUB 和 ACSM 並存時，以 ACSM 為準
        acsm = [x for x in cands if x.lower().endswith(".acsm")]
        if len(acsm) == 1:
            return os.path.join(self.dir, acsm[0])
        if len(cands) == 1:
            return os.path.join(self.dir, cands[0])
        raise SystemExit(f"請在 system_prompts.yaml 的 book.source_file 指明原檔"
                         f"（目錄內有 {len(cands)} 個 {'／'.join(SOURCE_EXTS)}）")

    def source_format(self):
        return os.path.splitext(self.source_file())[1].lower().lstrip(".")

    def source_epub(self):
        """要抽取的 EPUB；原檔是 ACSM 時是 fetch 領回來、解密後的那份。"""
        src = self.source_file()
        fmt = os.path.splitext(src)[1].lower()
        if fmt == ".epub":
            return src
        if fmt == ".acsm":
            from ..source.fetch_acsm import fetched_epub_name
            p = os.path.join(self.dir, fetched_epub_name(src))
            if os.path.exists(p):
                return p
            raise SystemExit(f"還沒領書：{p}\n先跑 `python -m epubtrans fetch \"{self.name}\"`")
        raise SystemExit(f"原檔不是 EPUB：{src}")

    def zh_title(self):
        """純中文書名 —— title_zh 去掉尾端的原文括號附註；沒填就退回 title。"""
        t = (self.book.get("title_zh") or "").strip()
        if not t:
            return (self.book.get("title") or self.name).strip()
        return _PAREN_TAIL.sub("", t).strip() or t

    def output_basename(self):
        """固定的產出檔名：《中文書名 原文書名》。原文與中文相同時省略；作者不進檔名。"""
        zh = self.zh_title()
        en = (self.book.get("title") or "").strip()
        stem = f"{zh} {en}" if en and en != zh else zh
        return "《" + safe_filename(stem) + "》"

    def output_epub(self):
        f = self.book.get("output_file") or (self.output_basename() + ".epub")
        return os.path.join(self.dir, f)
