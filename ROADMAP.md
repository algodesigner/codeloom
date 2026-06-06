# Roadmap

## Phase 1 — Foundation (current)

- [x] Defensive error handling in all 15 MCP tools
- [x] Impact/dependencies improvements (kind filtering, snippets,
      risk scoring, cross-file grouping, JSON output)
- [x] `--explain` mode on search (per-signal score breakdown)
- [x] `doctor --deep` (cycles, dangling edges, embedding coverage,
      cross-ref resolution rate)
- [ ] Property-based tests for graph traversal
- [ ] Stress test harness

## Phase 2 — Trust (next)

- [ ] Scale documentation with verified limits
- [ ] Auto-repair: detect and rebuild missing FTS5/FAISS indexes
- [ ] Observability hooks for debugging search ranking

## Phase 3 — Hardening

- [ ] Parallel extraction (multi-threaded tree-sitter parsing)
- [ ] Graph DB backend option (beyond NetworkX for 500k+ nodes)
- [ ] Streaming build for monorepos
- [ ] CI-optimised build mode

## Phase 4 — Growth

- [ ] Community contribution guide with good-first-issue tags
- [ ] Public plugin API for custom extractors
- [ ] Language server protocol (LSP) integration

---

*This roadmap is a living document. Priority shifts based on user feedback.*
