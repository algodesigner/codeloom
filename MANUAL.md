# codeloom Manual

**codeloom** is a local-first code graph builder and hybrid search engine for AI coding agents. It maps your entire codebase — every function, class, import, call, and document — into a queryable knowledge graph that runs 100% on your machine. No data leaves your computer. No telemetry. No API keys.

---

## Table of Contents

1. [Why codeloom?](#1-why-codeloom)
2. [Quick Start](#2-quick-start)
3. [How the Graph Is Built](#3-how-the-graph-is-built)
4. [The Search Engine](#4-the-search-engine)
5. [Maintaining the Graph](#5-maintaining-the-graph)
6. [AI Agent Integration](#6-ai-agent-integration)
7. [Reference](#7-reference)

---

## 1. Why codeloom?

### The problem

AI coding agents (Claude Code, OpenCode, Cursor, etc.) are powerful but fundamentally blind to your codebase structure. When an agent edits `UserService.validate()`, it doesn't know that 47 functions depend on its return type. When it searches for "database connection", it greps blindly through every file.

Without a code graph, agents work like a surgeon operating without an X-ray — skilled, but guessing at what's inside.

Typical approaches fail in different ways:

- **Grep** finds exact strings but misses semantic connections. Searching for "database" won't find a class named `PoolManager` that has nothing to do with pools.
- **File search** (Glob) finds filenames but not what's inside them.
- **Full-text search** finds keywords but not structure or relationships.
- **External APIs** (GitNexus, GraphRAG services) send your code to third parties.

### The codeloom approach

codeloom builds a **queryable map** of your codebase — every function, class, method, call, import, and document — and exposes it through:

1. **5-signal hybrid search** (code vector + text vector + graph expansion + keyword + community) with RRF fusion
2. **Subgraph responses** showing how results connect
3. **Cross-file reference resolution** (edges resolve to containing definitions)
4. **Filtered search** by symbol kind and file location

The core philosophy: *codeloom tells agents what the codebase looks like and what to read next.* It doesn't answer questions directly. It points to the right files and lines.

### When codeloom shines

- **Exploring unfamiliar codebases**: "What does the auth module look like?" without reading every file.
- **Impact analysis**: "What calls this function?" without manually tracing imports.
- **Cross-service discovery**: "Find all payment-related code across 12 microservices."
- **Onboarding**: New team members understand architecture in minutes, not days.
- **Documentation audit**: "Which modules have no docstrings?" via filtered search.

---

## 2. Quick Start

### Installation

```bash
pip install codeloom
```

Verify it works:

```bash
codeloom --version      # Should show 0.1.0
codeloom --help         # Lists all 23 commands
```

### Build a code graph

```bash
cd your-project/
codeloom build .
```

On first run, codeloom will download two small embedding models (~150MB total, cached to `~/.codeloom/models/`). The build scans every file, extracts structural nodes and edges, builds the graph, and persists everything to `.codeloom/knowledge.db`.

You'll see stage progress:

```
  detect: Scanning /Users/me/project
  detect: Found 142 files
  extract: Extracting from 142 files
  extract: Extracted 1,204 nodes
  build: Building code graph
  resolve: Resolved 47 references to definitions
  pagerank: Computing importance scores
  cluster: Found 12 communities
  embed: Generated 832 embeddings
  store: Done
  {"files_detected": 142, "nodes": 1204, "edges": 3800, ...}
```

### Search

```bash
codeloom search "database connection pool"
```

Returns something like:

```
seeds:
  core/db.py:42 (score: 0.047)
  storage/pool.py:15 (score: 0.032)

edges:
  core/db.py:42 -calls-> storage/pool.py:15
  core/db.py:0 -co_change-> storage/pool.py:0
  core/db.py:0 -defines-> core/db.py:42
```

This tells the agent (or you): "The relevant code is in `core/db.py:42` and `storage/pool.py:15`. The database module calls the connection pool. They're frequently committed together."

### Nested filtering

```bash
codeloom search "validate" --kind function          # Functions only
codeloom search "" --kind class --file "api/*"     # Browse API classes
codeloom search "connect" --kind method            # Methods only
codeloom search "handler" --file "src/*.ts"        # TypeScript handlers only
```

### JSON output

```bash
codeloom search "database" --json
```

Returns structured data for machine consumption:

```json
{
  "seeds": [
    {"id": "core/db.py:42", "label": "connectToDatabase", "kind": "function",
     "file": "core/db.py", "line": 42, "score": 0.047, "signature": "(config) -> Conn"}
  ],
  "edges": [
    {"from": "core/db.py:42", "to": "storage/pool.py:15", "relation": "calls"}
  ],
  "isolated": [],
  "hint": "8 of 12 results are functions. Use `--kind function` to narrow."
}
```

---

## 3. How the Graph Is Built

Building a code graph is a multi-stage pipeline. Each stage feeds into the next, and the output persists to a SQLite database.

### Stage 1: Detection

**File**: `codeloom/core/detect.py`

codeloom walks your source directory, classifying every file by type. It respects three layers of ignore rules:

1. **DEFAULT_IGNORE**: `.git`, `node_modules`, `__pycache__`, `.venv`, `.codeloom`, `.DS_Store`, and other common non-source directories
2. **`.gitignore`**: Your project's standard gitignore rules
3. **`.codeloom-ignore`**: Project-specific overrides (same gitignore spec format)

Sensitive files (`.env`, `*.pem`, `*.key`, `*credentials*`) are always excluded.

Files are classified into:
- **code**: 20+ programming languages (see below)
- **doc**: Markdown, PDF, HTML, CSV, DOCX, XLSX, ODT, ODS, ODP
- **config**: JSON, YAML, TOML, INI
- **other**: Skipped

### Stage 2: Extraction

**File**: `codeloom/core/extract.py`, `codeloom/core/ts_extract.py`, `codeloom/core/tags_extract.py`

Each detected file is extracted using one of three methods, tried in priority order:

#### 1. Universal tags.scm extractor (165+ languages)

The most powerful method. Uses each tree-sitter grammar's standard `tags.scm` query file to extract definitions, references, and imports. Requires zero per-language code — just a tree-sitter grammar package with a `tags.scm` file.

Languages using this method: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP, Swift, Kotlin, C#, Objective-C, Scala, Lua, Elixir, and more.

#### 2. Legacy tree-sitter AST walkers

For Python, JavaScript, and TypeScript, dedicated AST walkers extract richer structural data: decorators, call graphs, inheritance chains, method containment.

#### 3. Regex fallback

For languages without tree-sitter support (Shell, R, Object Pascal via `.pas`/`.pp`), regex patterns extract function and class definitions.

#### Document extraction

Non-code formats use specialized extractors:
- **Markdown**: Headings become section nodes, internal links become reference edges
- **PDF**: Pages become section nodes with extracted text (requires `pymupdf`)
- **HTML**: Headings (h1-h6) become hierarchical section nodes
- **CSV/TSV**: Rows become section nodes
- **DOCX/XLSX/ODT/ODS/ODP**: ZIP + XML parsing, zero dependencies (stdlib only)

#### What each extraction produces

**Nodes** — the entities in your codebase:

```
Node ID: "core/db.py:42"         # file:line format
  label: "connectToDatabase"     # The function/class name
  kind: "function"               # function, class, method, module, section, etc.
  file_path: "core/db.py"        # Relative to source root
  start_line: 42                 # 1-based line number
  end_line: 58                   # End of definition
  signature: "(config: Config) -> Connection"  # For callables
  docstring: "Create a database connection with retry logic."
  pagerank: 0.047                # Importance score (computed later)
  community_ids: [3, 7]          # Community membership (computed later)
```

**Edges** — the relationships between entities:

| Relation | Meaning | Example |
|----------|---------|---------|
| `calls` | Function A calls function B | `auth.py:15` -calls-> `db.py:42` |
| `imports` | Module imports another module | `app.py:1` -imports-> `config.py:0` |
| `defines` | File/section contains a definition | `db.py:0` -defines-> `db.py:42` |
| `contains` | Class contains a method | `db.py:10` -contains-> `db.py:42` |
| `inherits` | Class extends another class | `Car.py:1` -inherits-> `Vehicle.py:1` |
| `references` | Cross-file symbol reference | `docs/readme.md:5` -references-> `config.py:10` |
| `co_change` | Files frequently committed together | `db.py` -co_change-> `pool.py` |

### Stage 3: Graph Build

**File**: `codeloom/core/build.py`

Extraction results are assembled into a **NetworkX DiGraph** (directed graph):

- All nodes registered with their metadata
- All edges registered with relation type and confidence
- Graph density, connected components, and clustering coefficient calculated

The graph is the central data structure — everything else (search, analysis, communities) operates on it.

### Stage 3.5: Cross-file Reference Resolution

**File**: `codeloom/core/resolve.py`

Edges often point to raw file:line positions (e.g. `b.py:20` — a line inside a function). This stage resolves them to containing definitions using a **spatial index**:

1. Collect all definition nodes (function, class, method, etc.) grouped by file
2. Sort definitions within each file by start_line
3. For each edge, binary-search the target position against the sorted spans

If `b.py:20` falls inside `Database.query()` spanning `b.py:15`-`b.py:30`, the edge target is updated to `b.py:15`. This means agents always get pointed to the actual definition, not an arbitrary line inside it.

### Stage 4: PageRank

Every node gets a **PageRank score** — the same algorithm Google used for web pages. Nodes that are referenced by many other nodes (imported frequently, called by many functions) get higher scores. This helps the search engine rank important code higher.

### Stage 5: Community Detection

**File**: `codeloom/core/cluster.py`

The **Leiden algorithm** (an improvement over Louvain) clusters the graph into communities at multiple hierarchical resolutions:

| Level | Resolution | Community size | What it finds |
|-------|-----------|----------------|---------------|
| 0 | 0.5 | Broad | Entire subsystems (auth, billing, etc.) |
| 1 | 1.0 | Default | Module-level groups |
| 2 | 2.0 | Focused | Class/function clusters |
| 3 | 4.0 | Tight | Very specific groupings |

Each community gets a **summary** — extracted text from member node docstrings and labels. These summaries become the 5th search signal (community search).

### Stage 6: Embeddings

**File**: `codeloom/query/embeddings.py`

Every text-bearing node is embedded into a 384-dimensional vector using two **sentence-transformers** models:

| Model | Purpose | Size |
|-------|---------|------|
| `BAAI/bge-small-en-v1.5` | Code semantics (function names, signatures) | ~33MB |
| `intfloat/multilingual-e5-small` | Natural language text (docs, comments) | ~118MB |

The dual-model approach is deliberate:
- The **code model** understands programming patterns — "connectToDatabase", `(config) -> Conn`
- The **text model** understands natural language — "Create a database connection with retry logic"

Embedding text is crafted per kind to improve search:
- Methods get `"method of ClassName: functionName signature: docstring"`
- Files get `"file: path/to/file.py: imports list..."` 
- Markdown sections get their full heading and body text

Embeddings are batched (batch size 64) and streamed to the database, keeping memory usage predictable.

### Stage 7: Storage

**File**: `codeloom/storage/store.py`

Everything persists to a **SQLite database** at `.codeloom/knowledge.db`:

```
nodes (id, label, kind, file_path, start_line, end_line,
       signature, docstring, pagerank, community_ids, hash)
edges (source, target, relation, confidence, weight)
fts_nodes (node_id, label, doc, signature)        -- FTS5 virtual table
embeddings (node_id, model_name, vector BLOB)     -- numpy float32
communities (id, level, resolution, summary, node_ids TEXT)
faiss_index_code                                   -- FAISS IVFFlat index
faiss_index_text                                   -- FAISS IVFFlat index
metadata (key, value)                              -- build config, model names
```

Two **FAISS indices** enable approximate nearest-neighbor search in ~1ms:
- `faiss_index_code`: 384-dim vectors from bge-small-en-1.5
- `faiss_index_text`: 384-dim vectors from multilingual-e5-small

---

## 4. The Search Engine

```bash
codeloom search "database connection pool"
```

This single command fires **5 independent search signals** in parallel, then fuses the results:

### Signal 1: Code Vector Search

The query is embedded with bge-small-en-1.5 and searched against the FAISS code index. Returns nodes whose *code identifiers* and *signatures* match the query concept.

*Example*: "database pool" matches `PoolManager`, `createPool`, `ConnectionPool`.

### Signal 2: Text Vector Search

The query is embedded with multilingual-e5-small and searched against the FAISS text index. Returns nodes whose *documentation* and *comments* match the query.

*Example*: "database pool" matches "Manages a pool of database connections."

### Signal 3: Graph Expansion

Starting from the top vector seeds, BFS expands outward through the graph (up to 2 hops). Nodes found via traversal get scores weighted by distance (hop 1: 1.0, hop 2: 0.5).

This finds related code that vector search alone would miss — callers of the pool, classes that use it, files that co-change with it.

### Signal 4: Keyword Search (FTS5)

Query terms are stopword-filtered and matched against the `fts_nodes` virtual table using BM25 ranking. This catches exact name matches that vector search might miss.

*Example*: Searching "StripeClient" finds the exact class name even if no surrounding code mentions payment processing.

### Signal 5: Community Search

Query terms are matched against community summaries via FTS5. If a community's summary matches, all member nodes in that community bubble up. This enables discovery of "payment" code even if individual node docs don't mention payment — because the community summary does.

### RRF Fusion

All 5 result sets are fused via **Weighted Reciprocal Rank Fusion**:

```python
score = sum(weight[s] * 1 / (60 + rank[s][node]) for s in signals if node in rank[s])
```

| Signal | Weight | Rationale |
|--------|--------|-----------|
| Code Vector | 1.0 | Semantic code matching |
| Text Vector | 1.0 | Semantic text matching |
| Graph Expansion | 0.8 | Structural proximity |
| Keyword | 1.5 | Exact name matches are most reliable |
| Community | 0.7 | Most indirect signal |

### Subgraph Response

After fusion, the top seed nodes are connected through an **MST-based shortest path** algorithm (Steiner Tree approximation):

1. Compute shortest distances between every pair of seed nodes
2. Build a minimum spanning tree (MST) connecting all seeds via Kruskal's algorithm
3. Expand MST edges to actual shortest paths through the graph
4. Isolated seeds (unreachable from others) are separated

The result is a **subgraph** — the minimum structure connecting all relevant results. Seeds that connect tell the agent "these files are related." Isolated seeds tell the agent "this is relevant but separate."

### Filtering

Post-fusion, you can narrow results:

```
--kind function          Only functions
--kind class             Only classes  
--kind method            Only methods
--file "src/auth/*"      Only files matching glob
--kind method --file "db/*"  Combined
```

This is useful because vector search finds *meaning* but struggles with *structure*. The filters handle the structural part: "I only want functions in the auth module."

### Contextual Hints

When >5 results are returned without a filter, codeloom appends a hint:

```
Hint: 8 of 12 results are functions. Use `--kind function` to narrow.
```

This provides continuous feedback to AI agents, encouraging them to use filters naturally.

---

## 5. Maintaining the Graph

### Full rebuild

```bash
codeloom build .
```

Scans every file, re-extracts everything, rebuilds from scratch. Takes ~14s for a 3,500-line project.

### Incremental rebuild

```bash
codeloom build . --incremental
```

Only re-extracts files that changed (detected via SHA-256 content hashing). Unchanged files are merged from the existing database. Takes ~4s when files changed, ~0.4s when nothing changed.

### Auto-rebuild via agent hooks

When integrated with Claude Code, Codex, or Gemini, codeloom registers Stop/SessionEnd hooks. When your coding session ends, the hook detects changed files via `git diff` and triggers an incremental rebuild in the background. A lock file prevents concurrent rebuilds.

```bash
codeloom claude install --scope project
```

### Auto-rebuild via git hooks (planned)

Future: `codeloom watch` will use filesystem watchers to trigger rebuilds when files change, eliminating the need for agent-specific hooks.

### Manual rebuild after major changes

After a branch merge, dependency update, or large refactor, run a full rebuild:

```bash
codeloom build .
```

### Checking graph health

```bash
codeloom stats           # Node count, edges, communities, density
codeloom doctor          # 21-point health check
codeloom node "Auth"     # Find a specific node and see its edges
```

---

## 6. AI Agent Integration

codeloom integrates with 9 AI coding agents in one command each:

```bash
codeloom opencode install          # Semantic Workbench / OpenCode
codeloom claude install            # Claude Code (Anthropic)
codeloom codex install             # OpenAI Codex CLI
codeloom gemini install            # Google Gemini CLI
codeloom cursor install            # Cursor IDE
codeloom windsurf install          # Windsurf IDE
codeloom cline install             # Cline VS Code extension
codeloom aider install             # Aider CLI
```

Each `install` does:

1. **Writes a context file** (CLAUDE.md, AGENTS.md, GEMINI.md, etc.) with rules teaching the agent to use codeloom search before grepping
2. **Registers hooks** (PreToolUse, Stop, BeforeTool) that nudge the agent toward filtered search
3. **Installs a skill file** (for agents that support skill discovery)
4. **Writes MCP configuration** (for agents that support the Model Context Protocol)

### MCP Server

```bash
codeloom mcp
```

Starts a **Model Context Protocol** server over stdio, exposing 5 tools:

| Tool | Description |
|------|-------------|
| `search` | 5-signal hybrid search + subgraph — PRIMARY tool |
| `node` | Node details with incoming/outgoing edges |
| `stats` | Graph statistics |
| `communities` | List or search communities |
| `build` | Trigger incremental rebuild |

Configure in your agent's MCP settings:

```json
{
  "mcp": {
    "codeloom": {
      "type": "local",
      "command": ["codeloom", "mcp"]
    }
  }
}
```

### How agents should use codeloom

The skill file teaches agents this workflow:

```
Step 1: codeloom search → identify relevant files and services
Step 2: Read → deeply understand architecture and data flow
Step 3: Grep → find specific symbols, types, constants
```

Agents are instructed to **always search before grepping** — one search call covers 5 signals that would require multiple grep queries. The subgraph response shows how results connect, giving the agent a map of the relevant code region.

---

## 7. Reference

### Commands

| Command | Description |
|---------|-------------|
| `build <dir>` | Build code graph from a source directory |
| `search <query>` | 5-signal hybrid search with subgraph response |
| `stats` | Graph statistics (nodes, edges, communities, density) |
| `node <id>` | Node details with incoming/outgoing edges |
| `export` | Export graph in JSON, D3, or GraphML format |
| `visualize` | Generate interactive HTML visualization |
| `clean` | Remove database directory |
| `doctor` | 21-point installation health check |
| `query` | Interactive search REPL |
| `mcp` | Start MCP server (stdio transport) |
| `claude install\|uninstall` | Manage Claude Code integration |
| `opencode install\|uninstall` | Manage OpenCode integration |
| `codex install\|uninstall` | Manage Codex CLI integration |
| `gemini install\|uninstall` | Manage Gemini CLI integration |
| `cursor install\|uninstall` | Manage Cursor IDE integration |
| `windsurf install\|uninstall` | Manage Windsurf IDE integration |
| `cline install\|uninstall` | Manage Cline integration |
| `aider install\|uninstall` | Manage Aider CLI integration |

### Common options

| Option | Applies to | Description |
|--------|-----------|-------------|
| `--top-k N` | search | Number of results (default 30) |
| `--fast` | search | Text model only (faster, slightly less accurate) |
| `--json` | search | Structured JSON output |
| `--kind K` | search | Filter by symbol kind |
| `--file GLOB` | search | Filter by file path glob |
| `--incremental` | build | Only changed files |
| `--scope user\|project` | install | Global vs. local installation |

### Supported formats

**Code (17+ languages)**: Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, Ruby, PHP, Swift, Kotlin, C#, Objective-C, Scala, Shell, Lua, R, Elixir, Terraform/HCL

**Document**: Markdown, YAML, JSON, TOML, PDF, HTML, CSV/TSV

**Office**: DOCX, XLSX, ODT, ODS, ODP

### Files and directories

| Path | Purpose |
|------|---------|
| `.codeloom/knowledge.db` | SQLite database with all node, edge, and embedding data |
| `.codeloom/faiss_code.index` | FAISS index for code embeddings |
| `.codeloom/faiss_text.index` | FAISS index for text embeddings |
| `.codeloom/rebuild.lock` | Lock file preventing concurrent rebuilds |
| `~/.codeloom/models/` | Cached embedding model files |
| `.codeloom-ignore` | Project-specific file exclusion rules |
| `.opencode/skills/codeloom/SKILL.md` | OpenCode skill file |
| `.claude/skills/codeloom/SKILL.md` | Claude Code skill file |

### Environment variables

| Variable | Purpose |
|----------|---------|
| `CODELOOM_DB` | Override path to knowledge.db |

### Release notes

| Version | Date | Summary |
|---------|------|---------|
| 0.1.0 | 2026-05-16 | Initial release |

### License

codeloom is MIT licensed.
Original copyright: Copyright (c) 2026 Hedwig AI.
Additional copyright: Copyright (c) 2026 Vlad Shurupov.
