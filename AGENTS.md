# AGENTS.md

給 Claude Code 以外的 coding agent（Codex、Cursor…）。這個專案的規約與流程寫在兩份檔案，動手前都要讀：

- `CLAUDE.md`：專案規約、指令、目錄結構、開發慣例。
- `.claude/skills/epub_translate_directly/SKILL.md`：翻譯一本書的完整流程（抽取、翻譯、審閱、build、排 PDF）；
  `references/general_rules.md` 是譯文規則。

安裝與測試見 `README.md`〈安裝〉。只支援 macOS（Apple Silicon）。

最容易出錯的幾條：
- 指令一律用 `./.venv/bin/python -m epubtrans <指令> "書名"`，`"書名"` 是 `process/` 底下的目錄名。
- `process/{書名}/drafts/` 是譯文唯一的真相來源；`work/`、產出的 EPUB／PDF 都可重建，不要手改。
- 改譯稿用 `revise`，不要用 sed；改了 drafts 要 `merge` → `verify` → `build`。
- `adept/` 是 Adobe 授權私鑰：不讀、不刪、不外流、不進版控。
