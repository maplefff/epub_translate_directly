"""普通書籍的掃描頁：只跑 PP-DocLayout-V3 切版面（圖、表、圖說、公式、書眉頁碼、註腳、標題），逐頁快取。

跟 vlm_worker 用同一個版面模型、同一種框格式，但不載入 VLM：文字仍由 Vision OCR 讀，
extract（pdf.layout: true）拿這裡的框找圖、裁圖。要在 .venv-vlm 裡跑，不 import epubtrans：
  .venv-vlm/bin/python epubtrans/source/import_pdf/layout_worker.py 原檔.pdf work/layout --pages 9-380
每頁寫一個 work/layout/pNNNN.json；key 相同的頁跳過，中斷後重跑會接著做。
"""
import argparse, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vlm_worker import LAYOUT_MODEL, LAYOUT_CONF, native_dpi, parse_pages   # noqa: E402

VERSION = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("cache")
    ap.add_argument("--pages", default="")
    a = ap.parse_args()

    import pymupdf
    from PIL import Image
    from mlx_vlm.utils import get_model_path, load_model

    key = {"v": VERSION, "layout": LAYOUT_MODEL, "conf": LAYOUT_CONF}
    os.makedirs(a.cache, exist_ok=True)
    doc = pymupdf.open(a.pdf)
    todo = []
    for pno in parse_pages(a.pages, doc.page_count):
        try:
            if json.load(open(os.path.join(a.cache, f"p{pno + 1:04d}.json"))).get("key") == key:
                continue
        except (OSError, ValueError):
            pass
        todo.append(pno)
    print(f"版面模型：{len(todo)} 頁待做（{LAYOUT_MODEL}）", flush=True)
    if not todo:
        return

    t0 = time.time()
    lay = load_model(get_model_path(LAYOUT_MODEL)); lay.eval()
    print(f"模型載入 {time.time() - t0:.0f} 秒", flush=True)
    t_start = time.time()
    for k, pno in enumerate(todo, 1):
        t = time.time()
        page = doc[pno]
        dpi = native_dpi(page)
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples).convert("RGB")
        recs = sorted(lay.detect(img, conf=LAYOUT_CONF), key=lambda r: r["reading_order"])
        data = {"key": key, "w": page.rect.width, "h": page.rect.height, "dpi": dpi,
                "img_w": img.width, "img_h": img.height,
                "layout": [{"label": x["label"], "bbox": x["bbox"], "score": x["score"],
                            "order": x["reading_order"]} for x in recs],
                "sec": round(time.time() - t, 2)}
        name = f"p{pno + 1:04d}.json"
        tmp = os.path.join(a.cache, f".{name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(a.cache, name))
        if k % 25 == 0 or k == len(todo):
            print(f"  {k}/{len(todo)} 頁，平均每頁 {(time.time() - t_start) / k:.2f} 秒", flush=True)
    print(f"完成：{len(todo)} 頁，{(time.time() - t0) / 60:.1f} 分鐘", flush=True)


if __name__ == "__main__":
    sys.exit(main())
