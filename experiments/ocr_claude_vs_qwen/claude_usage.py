"""從子代理的對話紀錄（JSONL）抽出 token 用量與每頁時間，不印出內容。
  python3 experiments/ocr_claude_vs_qwen/claude_usage.py 代理紀錄.jsonl [標籤] [--json 輸出.json]
token：依 message.id 去重後加總 usage（input／cache_creation／cache_read／output）。
每頁時間：讀某頁圖片的 Read 呼叫 → 寫該頁的 Write 完成；另給「從啟動到全部寫完」的總時間。
"""
import json, sys, re
from datetime import datetime

f = sys.argv[1]; label = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else f
ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
msgs, order, first_t, reads, writes, pending = {}, [], None, {}, {}, {}
for line in open(f):
    d = json.loads(line)
    t = ts(d["timestamp"]) if "timestamp" in d else None
    if first_t is None and t: first_t = t
    m = d.get("message")
    if d.get("type") == "assistant" and isinstance(m, dict):
        if m["id"] not in msgs: order.append(m["id"])
        msgs[m["id"]] = (m.get("model"), m.get("usage") or {}, t)
        for c in m.get("content") or []:
            if c.get("type") == "tool_use":
                p = (c.get("input") or {}).get("file_path", "")
                name = re.sub(r"\.(png|md)$", "", p.rsplit("/", 1)[-1])
                pending[c["id"]] = (c["name"], name, m["id"])
    if d.get("type") == "user" and isinstance(m, dict) and isinstance(m.get("content"), list):
        for c in m["content"]:
            if c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                kind, name, mid = pending[c["tool_use_id"]]
                if kind == "Read": reads.setdefault(name, (msgs[mid][2], t))
                if kind == "Write": writes[name] = (msgs[mid][2], t, mid)

tot = {k: 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
models = set()
for mid in order:
    model, u, _ = msgs[mid]; models.add(model)
    for k in tot: tot[k] += u.get(k) or 0
pages = {}
for name, (wt0, wt1, mid) in sorted(writes.items()):
    rt0 = reads.get(name, (None, None))[0]
    pages[name] = {"sec": round(wt1 - rt0, 1) if rt0 else None, "out_tok": msgs[mid][1].get("output_tokens")}
last = max((w[1] for w in writes.values()), default=first_t)
res = {"label": label, "models": sorted(x for x in models if x), "turns": len(order), **tot,
       "all_input": tot["input_tokens"] + tot["cache_creation_input_tokens"] + tot["cache_read_input_tokens"],
       "wall_sec": round(last - first_t, 1), "pages": pages}
print(f"{label}: 模型 {res['models']}，{res['turns']} 輪；輸入 {res['input_tokens']:,}＋快取寫 {res['cache_creation_input_tokens']:,}"
      f"＋快取讀 {res['cache_read_input_tokens']:,}＝{res['all_input']:,}；輸出 {res['output_tokens']:,}；總時間 {res['wall_sec']} 秒")
for n, p in pages.items(): print(f"  {n}: {p['sec']} 秒，該輪輸出 {p['out_tok']} tok")
if "--json" in sys.argv:
    json.dump(res, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
