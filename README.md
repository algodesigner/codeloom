<p align="center">
<h1 align="center">codeloom</h1>
  <p align="center">
    "With codeloom, your coding agent knows what to read."
    <br />
    <a href="#quick-start">Quick Start</a> · <a href="docs/README_ko.md">한국어</a> · <a href="docs/README_ja.md">日本語</a> · <a href="docs/README_zh.md">中文</a> · <a href="docs/README_de.md">Deutsch</a>
  </p>
</p>

<p align="center">
  <a href="https://github.com/algodesigner/codeloom/actions"><img src="https://img.shields.io/github/actions/workflow/status/algodesigner/codeloom/ci.yml?branch=main" alt="CI"></a>
  <a href="https://pypi.org/project/codeloom/"><img src="https://img.shields.io/pypi/v/codeloom?cache_bust=2" alt="PyPI"></a>
  <a href="https://github.com/algodesigner/codeloom/blob/main/LICENSE"><img src="https://img.shields.io/github/license/algodesigner/codeloom?cache_bust=2" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
</p>

---

## Why codeloom?

> raw data from a given number of sources is collected, then compiled by an LLM into a .md wiki, then operated on by various CLIs by the LLM to do Q&A and to incrementally enhance the wiki - Andrej Karpathy

codeloom builds a queryable code graph and knowledge base from codebases with 10,000+ files and knowledge documents, powered by lightweight local LLM models. Hybrid vector + keyword search with subgraph response (vector + keyword → RRF fusion with MST subgraph) lets coding agents truly understand your entire project, not just search keywords. Install it, and Claude Code sees the full picture — no extra tokens, no extra commands, everything runs 100% locally.

## Quick Start

```bash
pip install codeloom

cd your-project/
codeloom opencode install    # for OpenCode
# or: codeloom claude install  # for Claude Code
```

Then tell Claude Code or OpenCode:

> "Build a code graph for this project"

That's it. Your agent will build the graph, and from then on, consult it before every search. The graph auto-rebuilds when your session ends.

## AI Agent Integrations

codeloom integrates with major AI coding agents in one command:

| Agent | Install | What it does |
|-------|---------|-------------|
| **Claude Code** | `codeloom claude install` | Skill + CLAUDE.md + PreToolUse hook |
| **OpenCode** | `codeloom opencode install` | Skill in `.opencode/skills/` |
| **Codex CLI** | `codeloom codex install` | AGENTS.md + PreToolUse hook |
| **Gemini CLI** | `codeloom gemini install` | GEMINI.md + BeforeTool hook |
| **Cursor IDE** | `codeloom cursor install` | `.cursor/rules/` rule file |
| **Windsurf IDE** | `codeloom windsurf install` | `.windsurf/rules/` rule file |
| **Cline** | `codeloom cline install` | `.clinerules` file |
| **Aider CLI** | `codeloom aider install` | CONVENTIONS.md + `.aider.conf.yml` |
| **MCP Server** | `claude mcp add codeloom -- codeloom mcp` | 5 tools over Model Context Protocol |

Each `install` does two things: writes a context file with rules, and (where supported) registers a hook that fires before tool calls. To remove: `codeloom <platform> uninstall`.

## Supported Languages

### Structural Extraction (20+ languages)

codeloom extracts functions, classes, methods, calls, imports, and inheritance from source code using tree-sitter and native parsers.

| | | | |
|:---:|:---:|:---:|:---:|
| Python | JavaScript | TypeScript | Go |
| Rust | Java | C | C++ |
| C# | Ruby | Swift | Scala |
| Lua | PHP | Elixir | Kotlin |
| Objective-C | Terraform/HCL | | |

Also extracts structure from config and document formats: YAML, JSON, TOML, Markdown, PDF, HTML, CSV, Shell, R, and more.

### Multilingual Natural Language

Text nodes (docs, comments, markdown) are embedded with `intfloat/multilingual-e5-small` supporting **100+ natural languages** — Korean, Japanese, Chinese, German, French, and more. Search in your language, find results in any language.

---

## Features

### Auto-Rebuild

When integrated with AI coding agents (Claude Code, Codex, etc.), codeloom **automatically rebuilds** the graph when code changes. The Stop/SessionEnd hook detects modified files via `git diff` and triggers an incremental rebuild in the background — zero manual intervention.

### Git-Accelerated Deltas

Uses `git diff` to bypass heavy I/O of full filesystem scans. Only changed files are processed, enabling sub-second updates for typical logic changes. Toggle with `--git`.

### Smart Ignore & Pruning

codeloom respects ignore patterns from three sources and explicitly **prunes deleted files**, ensuring no "ghost nodes" remain in your graph after files are removed or renamed.

| Source | Description |
|--------|-------------|
| Built-in | `.git`, `node_modules`, `__pycache__`, `dist`, `build`, etc. |
| `.gitignore` | Auto-read from project root — your existing git ignores just work |
| `.codeloom-ignore` | Project-specific overrides for the code graph |

### Incremental Builds

SHA-256 content hashing per file and **hot-start PageRank**. Only changed files are re-extracted and re-embedded, while previous importance scores are reused for rapid convergence — typically **95%+ faster** than a full rebuild.

### Memory Management

4GB memory budget with stage-wise release. The pipeline generates → stores → frees at each stage: extraction results are freed after graph build, embeddings are streamed in batches and freed after DB write, and the full graph is released after persistence. GC triggers proactively at 75% threshold.

### 100% Local

No cloud services, no API keys, no telemetry. SQLite + FAISS for storage, sentence-transformers for embeddings. All data stays on your machine.

---

## Hybrid Search with Subgraph Response

Every query returns seed nodes and a subgraph showing how they connect:

**Search Pipeline**

| Signal | What it finds |
|--------|---------------|
| **Vector Search** | Semantically similar code and documents (dual-model: code + text) |
| **Keyword Search** | Exact name matches via FTS5 (BM25) |

Results are fused via Weighted Reciprocal Rank Fusion (RRF), then connected through MST-based shortest paths to reveal how seed nodes relate.

**Smart Test Demotion:** By default, test files are penalised in ranking (0.3× score multiplier) so that source-code results surface first. The heuristic detects test files across 8+ language conventions (Python `test_*.py`, Java `*Test.java`, JS `*.test.ts`, Go `*_test.go`, Rust `*_test.rs`, C# `*Test.cs`, Ruby `*_spec.rb`, and more) plus directory patterns (`test/`, `tests/`, `spec/`, `src/test/`). When results mix source and test files, a hint reports the split. Disable with `--include-tests`.

**Context Snippets:** The top 3 seed results include an inline snippet of source code (up to 5 lines) to help you immediately decide whether a result is relevant — no separate Read call needed. Configure with `--snippets N` (default 3, 0 to disable).

**Response Format**
```
seeds:
codeloom/core/pipeline.py:71
  │ def run_pipeline(source_dir: Path, ...) -> PipelineResult:
  │     """Run the full code graph build pipeline."""
  │     source_dir = Path(source_dir).resolve()
storage/store.py:20
  │ class KnowledgeStore:

edges:
codeloom/core/pipeline.py:71 -calls-> storage/store.py:20
codeloom/core/pipeline.py:0 -co_change-> storage/store.py:0
codeloom/core/pipeline.py:0 -defines-> codeloom/core/pipeline.py:71
```

- `seeds`: Node IDs (file:line) found by search, with optional source snippets
- `edges`: Subgraph connecting seeds through shortest paths (intermediate nodes appear in edges)

## CLI Reference

All commands output compact text by default (designed for AI agent consumption).

| Command | Description |
|---------|-------------|
| `build <dir>` | Build code graph (`--incremental`, `--git`) |
| `watch <dir>` | Real-time file system monitor for instant graph sync |
| `impact <id>` | Analyze "blast radius" — find all downstream dependents |
| `dependencies <id>` | Analyze upstream dependencies for a given symbol |
| `setup` | One-step automated setup for all detected agents |
| `search <query>` | Hybrid vector + keyword search with subgraph and snippets (`--top-k`, `--fast`, `--kind`, `--file`, `--include-tests`, `--snippets`) |
| `search-vector <query>` | Vector similarity only (code + text dual model) |
| `search-keyword <query>` | FTS5 keyword matching only (BM25 ranking) |
| `query` | Interactive search REPL |
| `communities` | List and search communities (`--search`, `--level`) |
| `stats` | Graph statistics |
| `node <id>` | Node details with fuzzy matching |
| `export` | Export as JSON, GraphML, or D3.js |
| `visualize` | Interactive HTML visualization |
| `clean` | Remove .codeloom/ database |
| `doctor` | Check installation health |
| `mcp` | Start MCP server (stdio) |
| `claude install\|uninstall` | Manage Claude Code integration |
| `codex install\|uninstall` | Manage Codex CLI integration |
| `gemini install\|uninstall` | Manage Gemini CLI integration |
| `cursor install\|uninstall` | Manage Cursor IDE integration |
| `windsurf install\|uninstall` | Manage Windsurf IDE integration |
| `cline install\|uninstall` | Manage Cline integration |
| `aider install\|uninstall` | Manage Aider CLI integration |
| `opencode install\|uninstall` | Manage OpenCode integration |

## Performance

Benchmarks on codeloom's own codebase (~3,500 lines, 90 files, 1,300 nodes):

| Operation | Time |
|-----------|------|
| Full build | ~14s |
| Incremental (changes) | ~4s |
| Incremental (no changes) | ~0.4s |
| Cold search (dual model) | ~2.8s |
| Cold search (`--fast`) | ~0.2s |
| Warm search | ~0.08s |
| Cached search | <1ms |

- **Embedding models**: ~180MB, downloaded once to `~/.codeloom/models/`
- **Database**: ~2MB (SQLite + FTS5 + FAISS indices)
- **Incremental builds**: SHA-256 hashing, 95%+ faster than full rebuild

## Requirements

- Python 3.10+
- ~180MB disk for embedding models (cached on first use)

```bash
# Optional: PDF extraction
pip install codeloom[docs]
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check codeloom/
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
