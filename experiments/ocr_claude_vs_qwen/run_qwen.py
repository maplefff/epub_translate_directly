"""對測試 PDF 跑現行的 vlm_worker（PP-DocLayout-V3＋Qwen3.5-27B），可換提示詞；不改專案程式。
  .venv-vlm/bin/python experiments/ocr_claude_vs_qwen/run_qwen.py 測試.pdf 輸出目錄 [提示詞檔]
"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "epubtrans", "source", "import_pdf"))
import vlm_worker
pdf, cache = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3:
    vlm_worker.PROMPT_FILE = os.path.abspath(sys.argv[3])
sys.argv = [sys.argv[0], pdf, cache]
vlm_worker.main()
