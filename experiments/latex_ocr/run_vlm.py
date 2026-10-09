"""整頁送進 VLM，輸出 markdown，記時間。用法：run_vlm.py tag model prompt [pages…] [--max-side N]"""
import sys, os, time, json, argparse
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("tag"); ap.add_argument("model"); ap.add_argument("prompt")
ap.add_argument("pages", nargs="*", default=["p030", "p060", "p515", "p040", "p162", "p290", "p551", "p578"])
ap.add_argument("--max-side", type=int, default=0)
ap.add_argument("--max-tokens", type=int, default=6000)
ap.add_argument("--patch", default="")
a = ap.parse_args()
if a.patch:
    import importlib; sys.path.insert(0, os.path.dirname(a.patch)); importlib.import_module(os.path.basename(a.patch)[:-3])
os.makedirs(f"out/{a.tag}", exist_ok=True)
t0 = time.time()
model, processor = load(a.model, trust_remote_code=True)
config = load_config(a.model, trust_remote_code=True)
print(f"[{a.tag}] load {time.time()-t0:.1f}s", flush=True)
stats = {}
for p in a.pages:
    img = f"pages/{p}.png"
    if a.max_side:
        im = Image.open(img); s = a.max_side / max(im.size)
        if s < 1:
            img = f"out/{a.tag}/_{p}.png"; im.resize((int(im.width*s), int(im.height*s)), Image.LANCZOS).save(img)
    prompt = apply_chat_template(processor, config, a.prompt, num_images=1)
    t = time.time()
    r = generate(model, processor, prompt, image=[img], max_tokens=a.max_tokens, temperature=0.0,
                 repetition_penalty=1.05, verbose=False)
    dt = time.time() - t
    open(f"out/{a.tag}/{p}.md", "w").write(r.text)
    stats[p] = {"sec": round(dt, 1), "gen_tokens": r.generation_tokens, "prompt_tokens": r.prompt_tokens}
    print(f"[{a.tag}] {p} {dt:.1f}s {r.generation_tokens} tok", flush=True)
json.dump(stats, open(f"out/{a.tag}/_stats.json", "w"), indent=1)
