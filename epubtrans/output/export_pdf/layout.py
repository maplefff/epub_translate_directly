"""依紙張尺寸自動算出整套版型。

設定的疊加順序（後者覆寫前者）：
  settings/print_profile.yaml  →  自動版型（依 --paper）  →  system_prompts.yaml 的 print:  →  命令列

為什麼改成用算的：原本的 epub2print 為 B5、A5、A4 各手寫一組邊界與字級，
換一種紙就得再手調一組，沒寫到的紙會退回 B5 的數字，行長因此失控。
中文長篇好讀的條件其實只有幾個，都能從紙張尺寸推出來：
  - 每行 30～38 字（＝ 版心寬 ÷ 字級）
  - 行距＝字級 × 1.7（見 book.typ 的固定行框）
  - 對頁內側邊界大於外側（裝訂會吃掉內側）；不裝訂（預設）就左右等寬
算式用原本手調過的 ISO-B5（11pt）、A4（12pt）、A5（10.5pt）校準，
這三種紙算出來的結果和手調值差 0～0.5pt、邊界差 1～3mm。
"""
import math, os, yaml
from ...core.config import SETTINGS

PROFILE = os.path.join(SETTINGS, "print_profile.yaml")
MM_PER_PT = 25.4 / 72

# 寬×高（mm）與檔名標記。b5、b4 採 JIS —— 台灣市售影印紙（Double A 等）的
# B5 是 182×257、B4 是 257×364；ISO 的 B5/B4 小一號，要明寫 iso-。
PAPERS = {
    "a4":     (210, 297, "A4"),
    "b5":     (182, 257, "B5"),
    "b4":     (257, 364, "B4"),
    "a5":     (148, 210, "A5"),
    "iso-b5": (176, 250, "ISO-B5"),
    "iso-b4": (250, 353, "ISO-B4"),
}


def paper(name):
    key = str(name).lower().strip()
    if key not in PAPERS:
        raise SystemExit(f"不支援的紙張 {name!r}；可用：{'、'.join(PAPERS)}")
    return key


def _half(x):
    return round(x * 2) / 2


def auto(name, prof):
    """紙張 → 邊界（mm）、字級（pt）與各級標題字級。"""
    W, H, _ = PAPERS[name]
    L = prof["layout"]
    inside, outside = W * L["inside_frac"], W * L["outside_frac"]
    top, bottom = H * L["top_frac"], H * L["bottom_frac"]
    tw = W - inside - outside

    # 字級取兩者較大：一是隨紙面放大的基準字級（紙大字就大，校準點見檔頭），
    # 二是讓一行不超過 max_chars 字所需的字級（B4 這種大紙靠這一項撐起來）。
    by_area = L["base_pt"] + (math.sqrt(W * H) - L["base_sqrt_area"]) * L["pt_per_mm"]
    by_width = tw / L["max_chars"] / MM_PER_PT
    body = _half(max(by_area, by_width))

    # 字級四捨五入後若行長仍超過上限，把多出來的寬度按比例還給左右邊界
    need = L["max_chars"] * body * MM_PER_PT
    if tw > need:
        extra = tw - need
        inside += extra * L["inside_frac"] / (L["inside_frac"] + L["outside_frac"])
        outside += extra * L["outside_frac"] / (L["inside_frac"] + L["outside_frac"])
        tw = need

    r = prof["size_ratio"]
    out = {
        "margin_inside": round(inside, 1), "margin_outside": round(outside, 1),
        "margin_top": round(top, 1), "margin_bottom": round(bottom, 1),
        "body_size": body,
    }
    for k, v in r.items():
        out[k] = _half(body * v)
    return out


def tones():
    return yaml.safe_load(open(PROFILE, encoding="utf-8")).get("tones") or {}


def tone(name):
    """夜讀色調名 → {label, page, text}；None 表示白紙黑字。"""
    if name is None:
        return None
    t = tones()
    if name not in t:
        raise SystemExit(f"不支援的色調 {name!r}；可用：{'、'.join(t)}")
    return t[name]


def load(name, book_print=None, cli=None, tone_name=None):
    prof = yaml.safe_load(open(PROFILE, encoding="utf-8"))
    base = {k: v for k, v in prof.items() if k not in ("layout", "size_ratio", "tones")}
    cfg = {**base, **auto(name, prof), **(book_print or {}),
           **{k: v for k, v in (cli or {}).items() if v is not None}}
    W, H, label = PAPERS[name]
    # 散頁閱讀（預設）沒有裝訂側：左右邊界取平均，版心寬與字級都和裝訂版一樣
    if not cfg.get("binding"):
        side = round((float(cfg["margin_inside"]) + float(cfg["margin_outside"])) / 2, 1)
        cfg["margin_inside"] = cfg["margin_outside"] = side
    t = tone(tone_name) or {}
    cfg.update(paper=name, paper_w=W, paper_h=H, paper_label=label,
               page_color=t.get("page"), text_color=t.get("text"), tone_label=t.get("label"))
    return cfg


def summary(cfg):
    """人看的版型摘要：實際尺寸、邊界、字級、理論行長與行數。"""
    tw = cfg["paper_w"] - cfg["margin_inside"] - cfg["margin_outside"]
    th = cfg["paper_h"] - cfg["margin_top"] - cfg["margin_bottom"]
    body_mm = float(cfg["body_size"]) * MM_PER_PT
    pitch_mm = body_mm * (1 + float(cfg["leading_ratio"]))
    tone = f"　色調 {cfg['tone_label']}（底 {cfg['page_color']}／字 {cfg['text_color']}）" if cfg.get("tone_label") else ""
    sides = (f"裝訂 內{cfg['margin_inside']}／外{cfg['margin_outside']}" if cfg.get("binding")
             else f"左右{cfg['margin_inside']}")
    return (f"紙張 {cfg['paper_label']} {cfg['paper_w']}×{cfg['paper_h']}mm{tone}　"
            f"邊界 {sides}／"
            f"上{cfg['margin_top']}／下{cfg['margin_bottom']}mm　"
            f"版心 {tw:.0f}×{th:.0f}mm　正文 {cfg['body_size']}pt　"
            f"每行約 {tw / body_mm:.1f} 字　每頁約 {int((th - body_mm) / pitch_mm) + 1} 行")


def to_typst(cfg, meta, cover_image):
    """版型 → config.json。Typst 只讀這份，不做任何算術。"""
    body = float(cfg["body_size"])
    keys = ("paper_w", "paper_h", "page_color", "text_color", "margin_inside", "margin_outside", "margin_top",
            "margin_bottom", "cjk_font", "latin_font", "title_size", "chapter_size",
            "part_size", "sub_size", "head_size", "folio_size", "chapter_align",
            "chapter_gap", "chapter_top_ratio", "part_top_ratio", "image_width",
            "image_max_height")
    out = {k: cfg[k] for k in keys}
    out.update({
        "body_size": body,
        "leading": round(body * float(cfg["leading_ratio"]), 3),
        "toc": bool(cfg["toc"]), "use_cover": bool(cfg["use_cover"]),
        "cjk_latin_spacing": bool(cfg["cjk_latin_spacing"]),
        "chapter_recto": bool(cfg["chapter_recto"]),
        "cover_image": cover_image,
        "title": cfg.get("title") or meta.get("title", ""),
        "subtitle": cfg.get("subtitle", ""),
        "author": cfg.get("author") or meta.get("author", ""),
        "imprint": cfg.get("imprint", ""),
        "image_natural": bool(cfg.get("image_natural", False)),
        "image_float": bool(cfg.get("image_float", True)),
    })
    return out
