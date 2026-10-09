#!/usr/bin/env python3
"""產出檔名格式：《中文書名 原文書名》.epub

條件分支不多但每一條都會直接影響交付物的檔名，所以釘住。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epubtrans.core.config import BookConfig, safe_filename, _PAREN_TAIL


class Fake(BookConfig):
    """繞過檔案系統，只測命名邏輯。"""
    def __init__(self, name, book):
        self.name = name
        self.raw = {"book": book}


CASES = [
    ("title_zh 帶原文附註 → 砍掉附註",
     {"title": "Atlas of the Heart", "title_zh": "心之地圖（Atlas of the Heart）",
      "author": "Brené Brown"},
     "《心之地圖 Atlas of the Heart》"),
    ("title_zh 本來就沒附註",
     {"title": "Atlas of the Heart", "title_zh": "心之地圖", "author": "Brené Brown"},
     "《心之地圖 Atlas of the Heart》"),
    ("有作者也不進檔名",
     {"title": "Leviathan", "title_zh": "利維坦", "author": "Thomas Hobbes"},
     "《利維坦 Leviathan》"),
    ("沒有作者",
     {"title": "Leviathan", "title_zh": "利維坦"},
     "《利維坦 Leviathan》"),
    ("沒填 title_zh → 退回 title，且不重複成《X X》",
     {"title": "Leviathan", "author": "Thomas Hobbes"},
     "《Leviathan》"),
    ("中文原文書（title 與 title_zh 相同）不重複",
     {"title": "紅樓夢", "title_zh": "紅樓夢"},
     "《紅樓夢》"),
    ("書名含斜線 → 換全形，不會切出目錄",
     {"title": "And/Or", "title_zh": "與／或"},
     "《與／或 And／Or》"),
    ("半形括號附註也要砍掉",
     {"title": "Stretch", "title_zh": "延展 (Stretch)"},
     "《延展 Stretch》"),
]


def main():
    ok = 0
    for label, book, want in CASES:
        got = Fake("dummy", book).output_basename()
        good = got == want
        ok += good
        print(f"  {'PASS' if good else 'FAIL'}  {label}\n        {got}"
              + ("" if good else f"\n        期望 {want}"))

    # 逃生門：output_file 明確指定時仍然說了算
    f = Fake("dummy", {"title": "X", "title_zh": "X", "output_file": "自訂.epub"})
    f.dir = "/tmp"
    got = os.path.basename(f.output_epub())
    good = got == "自訂.epub"
    ok += good
    print(f"  {'PASS' if good else 'FAIL'}  output_file 覆寫\n        {got}")

    total = len(CASES) + 1
    print(f"\n{ok}/{total} 通過")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
