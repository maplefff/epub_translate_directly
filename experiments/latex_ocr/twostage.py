"""PP-DocLayout-V3 切區塊 → 每塊裁圖送 VLM → 依閱讀順序組回 markdown。用法：twostage.py tag model textprompt formulaprompt [pages]"""
import sys, os, time, json
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config, get_model_path, load_model
from PIL import Image
tag, mpath, tp, fp = sys.argv[1:5]; pages = sys.argv[5:] or ["p030", "p060", "p515"]
lay = load_model(get_model_path("HashNuke/pp-doclayout-v3-mlx")); lay.eval()
model, proc = load(mpath, trust_remote_code=True); cfg = load_config(mpath, trust_remote_code=True)
os.makedirs(f"out/{tag}", exist_ok=True); stats = {}
SKIP = {"header", "number", "footer", "image", "chart", "formula_number", "seal", "header_image", "footer_image"}
for p in pages:
    t0 = time.time()
    im = Image.open(f"pages/{p}.png").convert("RGB"); W, H = im.size
    recs = sorted(lay.detect(im, conf=0.5), key=lambda r: r["reading_order"])
    # 行內公式框（落在 text 框裡的 formula）不單獨辨識
    blocks = [r for r in recs if r["label"] not in SKIP]
    def inside(a, b):
        return a["bbox"][0] >= b["bbox"][0] - 3 and a["bbox"][2] <= b["bbox"][2] + 3 and a["bbox"][1] >= b["bbox"][1] - 3 and a["bbox"][3] <= b["bbox"][3] + 3
    blocks = [r for r in blocks if not (r["label"] == "formula" and any(o is not r and o["label"] in ("text", "paragraph_title", "footnote", "figure_title", "table") and inside(r, o) for o in blocks))]
    out = []
    for r in blocks:
        y0, x0, y1, x1 = r["bbox"]; pad = 6
        crop = im.crop((max(0, x0*W/1000-pad), max(0, y0*H/1000-pad), min(W, x1*W/1000+pad), min(H, y1*H/1000+pad)))
        isf = r["label"] == "formula"
        prompt = apply_chat_template(proc, cfg, fp if isf else tp, num_images=1)
        res = generate(model, proc, prompt, image=[crop], max_tokens=1500, temperature=0.0, repetition_penalty=1.05, verbose=False).text.strip()
        if isf:
            res = res.strip("$").strip()
            if res.startswith("\\["): res = res[2:]
            if res.endswith("\\]"): res = res[:-2]
            res = f"$${res}$$"
        elif r["label"] in ("paragraph_title", "doc_title"):
            res = "## " + res
        out.append(res)
    if any(r["label"] == "image" for r in recs): pass
    open(f"out/{tag}/{p}.md", "w").write("\n\n".join(out))
    stats[p] = {"sec": round(time.time() - t0, 1), "blocks": len(blocks)}
    print(f"[{tag}] {p} {stats[p]}", flush=True)
json.dump(stats, open(f"out/{tag}/_stats.json", "w"))
