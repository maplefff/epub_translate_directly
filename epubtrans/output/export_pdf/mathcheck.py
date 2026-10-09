"""公式逐條試排：mitex 只要一條 LaTeX 出錯，整本書就編不出來。排版前把每條公式單獨編一次，
排不出來的改成照原樣印出（紅色等寬字），並列在 pdf 的輸出裡。結果依 TeX 內容快取，改譯稿重排不必重試。"""
import hashlib, json, os, re, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor
from .content.read_translated_epub import MATH_L, MATH_R

RAW_L, RAW_R = "", ""
MATH_TYP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "typst", "math.typ")
_INLINE = re.compile(f"{MATH_L}(.*?){MATH_R}", re.S)


def prep(tex):
    """LaTeX → mitex 吃得下的寫法（只為排版；EPUB 的 annotation 保留原文）。"""
    tex = tex.replace("\\mathscr", "\\mathcal")       # mitex 不認 \mathscr；Typst 的 cal 就是草寫字形
    return tex.strip()


def _blocks(book):
    for ch in book["chapters"]:
        for b in ch["blocks"]:
            yield b


def _texts(b):
    for k in ("t", "cap"):
        if isinstance(b.get(k), str):
            yield k


def run(book, workdir, typst):
    """原地改寫 book：公式換成 mitex 寫法、試排失敗的標成原樣印出。回傳失敗的 TeX。"""
    if not any(b["k"] == "eq" or MATH_L in (b.get("t") or "") + (b.get("cap") or "") for b in _blocks(book)):
        return []
    texs = set()
    for b in _blocks(book):
        if b["k"] == "eq":
            b["tex"] = prep(b["tex"])
            texs.add(b["tex"])
        for k in _texts(b):
            b[k] = _INLINE.sub(lambda m: MATH_L + prep(m.group(1)) + MATH_R, b[k])
            texs.update(_INLINE.findall(b[k]))
    cache_path = os.path.join(os.path.dirname(workdir.rstrip("/")), "mathcheck.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    key = lambda t: hashlib.sha1(t.encode()).hexdigest()
    todo = [t for t in texs if key(t) not in cache]
    if todo:
        tmp = os.path.join(workdir, "_mathcheck")
        os.makedirs(tmp, exist_ok=True)
        shutil.copy(MATH_TYP, os.path.join(tmp, "math.typ"))

        def one(i_t):
            i, t = i_t
            json.dump({"f": t}, open(os.path.join(tmp, f"f{i}.json"), "w"), ensure_ascii=False)
            open(os.path.join(tmp, f"f{i}.typ"), "w").write(
                f'#import "math.typ": mx\n#let d = json("f{i}.json")\n#mx(d.f)\n')
            r = subprocess.run([typst, "compile", os.path.join(tmp, f"f{i}.typ"), os.path.join(tmp, f"f{i}.pdf")],
                               capture_output=True)
            return t, r.returncode == 0
        print(f"公式試排 {len(todo)} 條（快取 {len(texs) - len(todo)} 條）…")
        with ThreadPoolExecutor(max(4, (os.cpu_count() or 8) - 2)) as ex:
            for t, ok in ex.map(one, enumerate(todo)):
                cache[key(t)] = ok
        json.dump(cache, open(cache_path, "w"))
        shutil.rmtree(tmp, ignore_errors=True)
    bad = sorted(t for t in texs if not cache[key(t)])
    badset = set(bad)
    for b in _blocks(book):
        if b["k"] == "eq":
            b["ok"] = b["tex"] not in badset
        for k in _texts(b):
            b[k] = _INLINE.sub(lambda m: (RAW_L + m.group(1) + RAW_R) if m.group(1) in badset else m.group(0), b[k])
    if bad:
        print(f"※ {len(bad)} 條公式排不出來，照原樣印成紅色等寬字：" + "；".join(x[:50] for x in bad[:5]))
    return bad
