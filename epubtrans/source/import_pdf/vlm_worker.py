"""掃描數學書的整頁 OCR：PP-DocLayout-V3 切版面、Qwen VLM 把整頁轉成 Markdown＋LaTeX，逐頁快取。

要在裝了 mlx-vlm 的獨立環境裡跑（.venv-vlm，見 requirements-vlm.txt），不 import epubtrans：
  .venv-vlm/bin/python epubtrans/source/import_pdf/vlm_worker.py 原檔.pdf work/vlm [--pages 1-596] [--batch 4]
每頁寫一個 work/vlm/pNNNN.json；key 相同的頁跳過，所以中斷後重跑會接著做。
extract（pdf.mode: vlm）只讀這些快取，不載入模型。

多程序：可以同時開幾個 worker 跑同一本書，每頁先建鎖檔（.pNNNN.lock）搶頁，不會重複做。
M5 Max 實測：--batch 4 的總吞吐量和單頁差不多（MLX 的 8bit 量化矩陣乘在小批次效率不好），
開 3 個單頁程序比較快；Qwen3.5-27B 8bit 每個約 28GB，GPU 工作集上限約 115GB，最多開 3 個。
迴圈偵測：模型偶爾卡在目錄點線之類的重複片段，輸出尾端出現週期性重複就強制結束該頁，事後再從輸出尾端判斷、標 loop_stopped。
"""
import argparse, hashlib, json, os, sys, time

VERSION = 1
MODEL = "mlx-community/Qwen3.5-27B-8bit"
LAYOUT_MODEL = "HashNuke/pp-doclayout-v3-mlx"
LAYOUT_CONF = 0.3            # 存下較低信心的框，extract 再依門檻取捨，不必重跑
MAX_TOKENS = 30000
PROMPT_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "settings", "vlm_ocr_prompt.txt")


def parse_pages(spec, n):
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += range(int(a) - 1, int(b or a))
    return [p for p in out if 0 <= p < n]


def native_dpi(page, cap=300):
    """掃描頁用原圖解析度（放大不會多出資訊）；數位頁用上限。"""
    best = 0
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            if r.width > 0:
                best = max(best, img[2] / (r.width / 72))
    return int(min(cap, best)) if best else cap


def periodic_tail(tail, max_period=150, min_len=200, min_repeats=4):
    """輸出尾端是否由同一段（長度 ≤ max_period 個 token）連續重複組成。
    短週期（點線、同一符號）要重複滿 min_len 個 token；長週期（整行重複）要重複 min_repeats 次。"""
    n = len(tail)
    for p in range(1, max_period + 1):
        need = max(min_len, min_repeats * p)
        if need > n:
            break
        seg = tail[n - need:]
        if all(seg[i] == seg[i + p] for i in range(need - p)):
            return True
    return False


class LoopGuard:
    """logits processor：偵測到重複迴圈就把下一個 token 強制成結束符號。"""

    def __init__(self, eos_ids, every=8):
        self.eos_ids, self.every, self.hit, self.calls = list(eos_ids), every, False, 0

    def clone(self):
        return LoopGuard(self.eos_ids, self.every)

    def __call__(self, tokens, logits):
        import mlx.core as mx
        self.calls += 1
        if not self.hit and self.calls % self.every == 0:
            self.hit = periodic_tail(tokens[-600:].tolist())
        if not self.hit:
            return logits
        keep = mx.zeros(logits.shape[-1], dtype=mx.bool_)
        keep[mx.array(self.eos_ids)] = True
        return mx.where(keep, logits, mx.array(-1e9, dtype=logits.dtype))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("cache")
    ap.add_argument("--pages", default="")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--no-guard", action="store_true")
    ap.add_argument("--prompt", default=PROMPT_FILE, help="轉寫提示詞檔（書本目錄有 vlm_ocr_prompt.txt 時由 vlm-ocr 傳入）")
    a = ap.parse_args()

    import pymupdf
    from PIL import Image
    from mlx_vlm import load, batch_generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.sample_utils import make_logits_processors
    from mlx_vlm.utils import load_config, get_model_path, load_model

    prompt_text = open(a.prompt, encoding="utf-8").read().strip()
    key = {"v": VERSION, "model": a.model, "layout": LAYOUT_MODEL,
           "prompt": hashlib.sha1(prompt_text.encode()).hexdigest()[:12]}
    os.makedirs(a.cache, exist_ok=True)
    doc = pymupdf.open(a.pdf)
    todo = []
    for pno in parse_pages(a.pages, doc.page_count):
        f = os.path.join(a.cache, f"p{pno + 1:04d}.json")
        try:
            d = json.load(open(f))
            if d.get("key") == key and not d.get("truncated"):
                continue
        except (OSError, ValueError):
            pass
        todo.append(pno)
    print(f"VLM OCR：{len(todo)} 頁待做（模型 {a.model}，同時 {a.batch} 頁）", flush=True)
    if not todo:
        return

    t0 = time.time()
    lay = load_model(get_model_path(LAYOUT_MODEL)); lay.eval()
    model, proc = load(a.model)
    cfg = load_config(a.model)
    tok = proc.tokenizer if hasattr(proc, "tokenizer") else proc
    ids = getattr(tok, "eos_token_ids", None)
    eos = {tok.eos_token_id} | ({ids} if isinstance(ids, int) else set(ids or []))
    prompt = apply_chat_template(proc, cfg, prompt_text, num_images=1)
    print(f"模型載入 {time.time() - t0:.0f} 秒", flush=True)

    def cached(pno):
        try:
            d = json.load(open(os.path.join(a.cache, f"p{pno + 1:04d}.json")))
            return d.get("key") == key and not d.get("truncated")
        except (OSError, ValueError):
            return False

    def claim(pno):
        """多個程序同時跑：先建鎖檔（O_EXCL）搶頁，搶到才做；鎖檔的主人已經不在就接手。"""
        lock = os.path.join(a.cache, f".p{pno + 1:04d}.lock")
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode()); os.close(fd)
                return True
            except FileExistsError:
                try:
                    os.kill(int(open(lock).read() or 0), 0)
                    return False                       # 別的程序正在做
                except (ProcessLookupError, ValueError):
                    os.remove(lock)                    # 主人已經結束（中斷過）：清掉重搶
                except PermissionError:
                    return False
        return False

    def release(pno):
        try:
            os.remove(os.path.join(a.cache, f".p{pno + 1:04d}.lock"))
        except OSError:
            pass

    done, t_start, queue = 0, time.time(), list(todo)
    while True:
        chunk = []
        while queue and len(chunk) < a.batch:
            pno = queue.pop(0)
            if not cached(pno) and claim(pno):
                chunk.append(pno)
        if not chunk:
            break
        try:
            t = time.time()
            pages = []
            for pno in chunk:
                page = doc[pno]
                dpi = native_dpi(page)
                pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
                img = Image.frombytes("L", (pix.width, pix.height), pix.samples).convert("RGB")
                recs = sorted(lay.detect(img, conf=LAYOUT_CONF), key=lambda r: r["reading_order"])
                pages.append((pno, page, dpi, img, recs))
            procs = make_logits_processors(repetition_penalty=1.05) + ([] if a.no_guard else [LoopGuard(eos)])
            r = batch_generate(model, proc, images=[x[3] for x in pages], prompts=[prompt] * len(pages),
                               max_tokens=MAX_TOKENS, greedy_sampling=True, logits_processors=procs, verbose=False)
            sec = (time.time() - t) / len(pages)
            for (pno, page, dpi, img, recs), text in zip(pages, r.texts):
                n = len(tok.encode(text, add_special_tokens=False))
                looped = periodic_tail(list(text[-1200:]), max_period=300, min_len=300, min_repeats=4)
                data = {"key": key, "w": page.rect.width, "h": page.rect.height, "dpi": dpi,
                        "img_w": img.width, "img_h": img.height,
                        "layout": [{"label": x["label"], "bbox": x["bbox"], "score": x["score"],
                                    "order": x["reading_order"]} for x in recs],
                        "md": text, "sec": round(sec, 1), "gen_tokens": n,
                        "truncated": n >= MAX_TOKENS, "loop_stopped": looped}
                name = f"p{pno + 1:04d}.json"
                tmp = os.path.join(a.cache, f".{name}.{os.getpid()}.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, os.path.join(a.cache, name))
                done += 1
                flag = "  ⚠ 重複迴圈，已提前結束" if looped else "  ⚠ 達輸出上限" if data["truncated"] else ""
                rate = (time.time() - t_start) / done
                print(f"[pid {os.getpid()}] 第 {pno + 1} 頁 {n} tok｜本程序已做 {done} 頁，平均每頁 {rate:.0f} 秒{flag}",
                      flush=True)
        finally:
            for pno in chunk:
                release(pno)
    print(f"完成：本程序做了 {done} 頁，{(time.time() - t0) / 3600:.2f} 小時", flush=True)

if __name__ == "__main__":
    sys.exit(main())
