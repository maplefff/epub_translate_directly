"""book.json / translations.json 的共用存取。"""
import json, os, hashlib


def h(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def load_book(cfg):
    p = cfg.wpath("book.json")
    if not os.path.exists(p):
        raise SystemExit(f"找不到 {p}\n先跑 `python -m epubtrans extract \"{cfg.name}\"`")
    return json.load(open(p, encoding="utf-8"))


TEXT_TYPES = ("para", "heading", "quote", "li")


def source_items(book):
    """依文件順序回傳 [{"text":…, "ci":章序, "cid":章id, "kind":…}]。

    章節標題一律納入 —— CCRU 根目錄版就是漏了這一步，導致 42 個目錄標題落回英文。
    """
    out = []
    for ci, c in enumerate(book["chapters"]):
        if c.get("title"):
            out.append({"text": c["title"], "ci": ci, "cid": c["id"], "kind": "title"})
        for it in c["items"]:
            if it["type"] in TEXT_TYPES:
                out.append({"text": it["text"], "ci": ci, "cid": c["id"], "kind": it["type"]})
    return out


def unique_sources(book):
    seen, out = set(), []
    for it in source_items(book):
        if it["text"] not in seen:
            seen.add(it["text"])
            out.append(it)
    return out


def load_cache(cfg, name="translations.json"):
    p = cfg.wpath(name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def save_cache(cfg, cache, name="translations.json"):
    p = cfg.wpath(name)
    tmp = p + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, p)


def load_json(cfg, name, default=None):
    p = cfg.wpath(name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save_json(cfg, name, obj):
    p = cfg.wpath(name)
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
