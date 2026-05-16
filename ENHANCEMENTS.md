# Enhancement Plan

Planned improvements for codeloom, based on audit and analysis of the original hedwig-cg codebase.

## Critical Bugs (Phase 1) ✅

- [x] **Wire real 5-signal search**: `hybrid_search()` now separates code_vector and text_vector into distinct signals, adds graph expansion (BFS from vector seeds), and community search (FTS5 on summaries). All 5 signals feed into weighted RRF fusion. Fixed in `codeloom/query/hybrid.py`.
- [x] **Concurrent rebuild protection**: `auto_rebuild.sh` now uses a lock file (`shlock` on macOS, `flock` on Linux, pid fallback) to prevent concurrent rebuilds corrupting the SQLite database. Lock is cleaned up via `trap EXIT`.
- [ ] ~~**Stop hook fires on every tool call**~~: Mitigated by lock file. Stop/SessionEnd hooks only fire at session end regardless of `matcher` value — the lock file prevents concurrent rebuilds in all cases.

## Medium Issues (Phase 2) ✅

- [x] **Align MCP `top_k` defaults**: Changed MCP server default from 10 to 30, matching CLI and skill.md.
- [x] **Tighten AGENTS.md/CLAUDE.md language**: Replaced "Always use" with "You MUST use" across all 7 agent integrations. Replaced "no need to" with "do not". Removed self-undermining "weak at" language from skill.md.
- [x] **Search results lack scores**: `SearchGraph.to_text()` now appends `(score: 0.047)` to each seed in output. Updated skill.md example.
- [x] **Auto-rebuild ignores untracked files**: `auto_rebuild.sh` now also checks `git ls-files --others --exclude-standard` for new files.

## New Features (Phase 3) ✅

- [x] **DOCX support**: Extracts text from `word/document.xml` in DOCX ZIP archives. No new dependencies (stdlib `zipfile` + `xml.etree.ElementTree`).
- [x] **XLSX support**: Extracts cells from `xl/worksheets/sheet*.xml` with shared strings resolution and sheet names from `xl/workbook.xml`.
- [x] **ODT/ODS/ODP support**: Extracts from OpenDocument format ZIP archives — text for ODT/ODP, table structure for ODS.
- [x] **Add scope prompt to `opencode install`**: Symmetrical with `claude install` — supports `--scope user` (global) and `--scope project` (local) with interactive prompt when omitted.

## Polish (Phase 4) ✅

- [x] **Added tests for integrations**: 20 tests covering Claude, Codex, Gemini, Cursor, Windsurf, and Aider — all following the same CliRunner pattern as the existing Cline tests.
- [x] **Added tests for embeddings**: 25 tests covering model config, node text construction, search term extraction, query encoding, streaming embeddings, node filtering, and store round-trip.
- [x] **Auto-register MCP config**: `codeloom opencode install` now writes the MCP config to `opencode.json` (project) or `~/.config/opencode/config.json` (user) automatically. Falls back to printing instructions on error.
- [ ] ~~**Tests for multi-language extraction**:~~ Skipped — tree-sitter parsers required. JS/TS already have dedicated tests.
- [ ] ~~**Incremental build embed test**:~~ Skipped — requires full pipeline with sentencetransformers. The `embed_nodes_streaming` skip_ids parameter is tested individually.

## License

codeloom is MIT licensed. Original copyright: Copyright (c) 2026 Hedwig AI. See LICENSE for details.
