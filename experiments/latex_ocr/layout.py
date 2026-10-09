import sys, json, time
from mlx_vlm.utils import get_model_path, load_model
from PIL import Image, ImageDraw
m = load_model(get_model_path("HashNuke/pp-doclayout-v3-mlx")); m.eval()
for p in sys.argv[1:]:
    t = time.time(); recs = sorted(m.detect(f"pages/{p}.png", conf=0.5), key=lambda r: r["reading_order"])
    print(p, f"{time.time()-t:.2f}s")
    im = Image.open(f"pages/{p}.png").convert("RGB"); W, H = im.size; d = ImageDraw.Draw(im)
    for r in recs:
        y0, x0, y1, x1 = r["bbox"]; box = (x0*W/1000, y0*H/1000, x1*W/1000, y1*H/1000)
        d.rectangle(box, outline="red", width=3); d.text((box[0]+4, box[1]+2), f'{r["reading_order"]} {r["label"]}', fill="blue")
        print(f'  {r["reading_order"]:2} {r["label"]:18} {r["score"]:.2f} {[round(v) for v in r["bbox"]]}')
    im.resize((W//2, H//2)).save(f"out/layout_{p}.png")
    json.dump(recs, open(f"out/layout_{p}.json", "w"))
