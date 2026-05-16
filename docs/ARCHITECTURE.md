# codeloom Architecture

codeloom is a local-first code graph builder and hybrid search engine for AI coding agents. It combines structural code analysis (AST extraction), semantic embeddings (vector search), graph theory (PageRank, community detection, MST subgraphs), and keyword indexing (FTS5) into a single queryable database — all running 100% locally.

---

## Design Philosophy

- **Map builder, not answer finder**. codeloom tells agents *what the codebase looks like* and *what to read next*. It does not answer questions — it points to the files and lines that contain the answer.
- **Search first, grep second**. A single hybrid search call covers 5 orthogonal signals (vector + graph + keyword + community) with RRF fusion. Grep is for finding exact symbols after you know where to look.
- **No network, no telemetry, no API keys**. All data stays on your machine. The only network access is a one-time download of embedding model weights from Hugging Face.
- **Incremental by design**. SHA-256 content hashing means only changed files are re-extracted and re-embedded. Typical incremental builds are 95%+ faster than full rebuilds.

---

## Pipeline

```
Source Directory
       │
       ▼
┌──────────────────┐
│    Extraction    │  ◄── tree-sitter AST parsers (17+ languages)
│                  │       Regex fallback, document parsers
│  nodes + edges   │       SHA-256 hashing per file
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Graph Build    │  ◄── NetworkX DiGraph
│                  │       PageRank, connected components
│  knowledge.db    │       clustering coefficient, density
└────────┬─────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────────┐
│Embed   │ │Community   │  ◄── Leiden hierarchical clustering
│dings   │ │Detection   │       LLM-generated summaries
│        │ │            │
│bge-small│ │5 resolution  │
│e5-small│ │levels       │
└───┬────┘ └──────┬─────┘
    │             │
    ▼             ▼
┌──────────────────────────────┐
│      Knowledge Store         │  ◄── SQLite + FTS5 + FAISS indices
│                              │
│  nodes │ edges │ communities │
│  embeddings │ fts_nodes      │
│  faiss_code │ faiss_text     │
│  metadata                     │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────┐
│  Hybrid Search   │  ◄── 5 signals → weighted RRF fusion
│                  │       MST shortest-path subgraph
│  results + graph │
└──────────────────┘
```

---

## Stage 1: Extraction

**File**: `codeloom/core/extract.py`

For every file in the source directory (respecting `.gitignore`, `.codeloom-ignore`, and built-in ignores), codeloom applies the appropriate extractor:

### Structural Extraction (17+ languages)

Uses **tree-sitter** AST parsers for deep structural extraction. Each parser walks the concrete syntax tree and produces typed nodes.

| Language | Tree-sitter Package |
|----------|-------------------|
| Python | `tree_sitter_python` |
| JavaScript | `tree_sitter_javascript` |
| TypeScript | `tree_sitter_typescript` |
| Go | `tree_sitter_go` |
| Rust | `tree_sitter_rust` |
| Java | `tree_sitter_java` |
| C | `tree_sitter_c` |
| C++ | `tree_sitter_cpp` |
| C# | `tree_sitter_c_sharp` |
| Ruby | `tree_sitter_ruby` |
| Swift | `tree_sitter_swift` |
| Scala | `tree_sitter_scala` |
| Lua | `tree_sitter_lua` |
| PHP | `tree_sitter_php` |
| Elixir | `tree_sitter_elixir` |
| Kotlin | `tree_sitter_kotlin` |
| Objective-C | `tree_sitter_objc` |
| Terraform/HCL | `python_hcl2` |

If a tree-sitter parser is missing, codeloom falls back to **regex-based extraction** (function/class patterns).

### Document Extraction

Text formats like Markdown, YAML, JSON, TOML, PDF, HTML, CSV, Shell, and R scripts are parsed for structure and text content. Each file becomes a node; sections, headings, and keys become child nodes with containment edges.

### Output

Each extracted entity becomes a **node**:

```json
{
  "label": "connectToDatabase",
  "kind": "function",
  "file_path": "src/services/db.py",
  "start_line": 42,
  "end_line": 58,
  "signature": "(config: Config) -> Connection",
  "doc": "Create a database connection with retry logic.",
  "hash": "sha256:a1b2c3..."
}
```

Relations between nodes become **edges**:

| Relation | Description |
|----------|-------------|
| `calls` | Function A calls function B |
| `imports` | Module imports another module |
| `inherits` | Class extends another class |
| `defines` | File defines a symbol |
| `contains` | Class contains a method |
| `co_change` | Files frequently committed together (git history) |
| `references` | Cross-file symbol references |

### Incremental Hashing

Every file gets a SHA-256 hash of its contents. The hash is compared against the stored value in the database. Unchanged files skip re-extraction entirely — their existing nodes and edges are merged into the new build.

---

## Stage 2: Graph Build

**File**: `codeloom/core/build.py`

Extraction results are assembled into a **NetworkX DiGraph** (directed graph):

- All nodes registered with their metadata
- All edges registered with relation type and confidence
- **PageRank** computed — identifies the most "important" nodes (highly referenced functions, core modules)
- Connected components counted
- Graph density and average clustering coefficient calculated
- Memory management: stage-wise release (extraction freed after graph build, embeddings freed after DB write)

The graph is **not** the final product — it is an intermediate representation that powers search signals and subgraph construction.

---

## Stage 3: Embeddings

**File**: `codeloom/query/embeddings.py`

Every text-bearing node gets two embedding vectors using **sentence-transformers**:

| Model | Purpose | Size | Dimensions |
|-------|---------|------|------------|
| `BAAI/bge-small-en-v1.5` | Code semantics (identifiers, signatures) | ~33MB | 384 |
| `intfloat/multilingual-e5-small` | Natural language (docs, comments) | ~118MB | 384 |

### Text Construction

The embedding text is carefully crafted to improve search quality:

- Methods/functions get signature prepended: `"connectToDatabase(config: Config) -> Connection: Create a database..."` — the code-model sees meaningful tokens.
- Methods get class context: `"method of DatabaseService: connectToDatabase..."` — so "database" queries find method nodes.
- Files get path context: `"file: src/services/db.py: imports: ..."` — for path-based queries.
- Document nodes (markdown, etc.) get full text.

### Batching

Embeddings are computed in batches of 32 to balance memory use and throughput. The pipeline streams embeddings to the database after each batch, freeing the batch from memory immediately.

### Caching

Query embeddings are cached (LRU, 256 entries), eliminating re-encoding for repeated queries (291ms → 0ms per repeated query).

---

## Stage 4: Community Detection

**File**: `codeloom/core/pipeline.py` → calls `leidenalg` (Leiden algorithm)

The graph is clustered at multiple hierarchical resolutions:

| Level | Resolution | Community granularity |
|-------|-----------|---------------------|
| 0 | 0.5 | Broad topics (entire subsystems) |
| 1 | 1.0 | Default — module-level groups |
| 2 | 2.0 | Class/function clusters |
| 3 | 4.0 | Fine-grained groupings |
| 4 | 8.0 | Very tight cliques |

Each community gets:
- A **summary** — generated by extracting the most descriptive docstrings and code identifiers from member nodes (ollama or local transformer). This is not an LLM call per community — it's a heuristic text extraction.
- A **resolution level** — higher = smaller, tighter communities
- A **community ID** — for quick lookup

These summaries become a **5th search signal**: matching query terms against community summary text via FTS5.

---

## Stage 5: Storage

**File**: `codeloom/storage/store.py`

Everything is persisted to **SQLite** at `.codeloom/knowledge.db`:

### Schema

```sql
-- Core graph data
nodes (id, label, kind, file_path, start_line, end_line,
       signature, doc, pagerank, community_ids, hash)
edges (source, target, relation, confidence, weight)
fts_nodes (node_id, label, doc, signature)  -- FTS5 virtual table

-- Embeddings
embeddings (node_id, model_name, vector BLOB)  -- numpy float32
embeddings_code (node_id, vector BLOB)         -- FAISS-optimized
embeddings_text (node_id, vector BLOB)

-- Communities
communities (id, level, resolution, summary, node_ids TEXT)

-- FAISS indices
faiss_index_code       -- FAISS IVFFlat index on code embeddings
faiss_index_text       -- FAISS IVFFlat index on text embeddings

-- Metadata
metadata (key, value)  -- build config, model names, source dir
```

### FAISS Indices

Two **FAISS IVFFlat** indices are stored alongside the database:
- `faiss_index_code` — 384-dim vectors from bge-small-en-1.5
- `faiss_index_text` — 384-dim vectors from multilingual-e5-small

These enable approximate nearest-neighbor search in **~1ms** per query (vs. linear scan of all vectors would take seconds).

### Incremental Merge

On incremental builds, the store:
1. Reads the hash table for the existing build
2. Extracts only changed/new files
3. Removes old nodes/edges/embeddings for changed files
4. Inserts new data
5. Rebuilds FAISS indices from scratch (fast enough for incremental sizes)
6. Updates metadata

This is why incremental builds are 95%+ faster — the expensive steps (tree-sitter parsing, embedding computation) only touch changed files.

---

## Stage 6: Hybrid Search

**File**: `codeloom/query/rank.py`, `codeloom/query/embeddings.py`

When the agent runs `codeloom search "database connection pool"`, the pipeline fires 5 independent search signals in parallel:

### Signal 1: Code Vector Search

The query is embedded with bge-small-en-1.5 and searched against the FAISS code index. Returns the top-K most semantically similar code nodes (by function name, signature, code context).

### Signal 2: Text Vector Search

The query is embedded with multilingual-e5-small and searched against the FAISS text index. Returns the top-K nodes whose documentation, comments, or natural language context match the query.

### Signal 3: Graph Expansion

Starting from the top vector search seeds, BFS expands outward through the graph (up to 2 hops). Nodes found via graph traversal get a score weighted by distance from seed (hop 1: 1.0, hop 2: 0.5). This finds structurally related code — callers, callees, sibling modules — that vector search alone would miss.

### Signal 4: FTS5 Keyword Search

The query terms are stopword-filtered and matched against the `fts_nodes` virtual table using BM25 ranking. This catches exact name matches that vector search might miss (e.g., `StripeClient` vs. "payment processing").

### Signal 5: Community Search

Query terms are matched against community summaries via FTS5. If the query matches a community summary, all member nodes in that community are surfaced. This enables discovery of "payment" code even if individual node docs don't mention payment — because the community summary does.

### RRF Fusion

All 5 result sets are fused via **Weighted Reciprocal Rank Fusion**:

```python
score = sum(
    weight[s] * (1 / (60 + rank[s][node]))
    for s in signals
    if node in rank[s]
)
```

Per-signal weights (tuned empirically):

| Signal | Weight |
|--------|--------|
| Code Vector | 1.0 |
| Text Vector | 1.0 |
| Graph | 0.8 |
| Keyword | 1.5 |
| Community | 0.7 |

Keyword has the highest weight because exact name matches (function names, class names) are the most reliable signal. Community has the lowest because it's the most indirect.

### Subgraph Construction

After fusion, the top seed nodes are connected through an **MST-based shortest path** algorithm:

```python
# 1. Subset nodes to top-K seeds + all intermediate graph nodes
# 2. Connect seeds via shortest paths through the full graph
# 3. Keep only edges on those paths
# 4. Return seeds + subgraph edges
```

The result is not a flat list but a **graph** showing how the relevant code connects:

```
seeds:
  core/db.py:42                # Database connection function
  storage/pool.py:15           # Connection pool class

edges:
  core/db.py:42 -calls-> storage/pool.py:15
  core/db.py:0 -defines-> core/db.py:42
```

This tells the agent: "The database connection function is in `core/db.py:42`, and it calls the connection pool in `storage/pool.py:15`." The agent can then `Read` those two files directly.

### Caching

Search results are cached (LRU, 128 entries). Identical queries return instantly (<1ms) without re-running any signal. Cache is cleared on graph rebuild.

---

## Integration with AI Agents

codeloom integrates with AI coding agents through three mechanisms:

### 1. Skill Files (`SKILL.md`)

A markdown file with YAML frontmatter that agents read to understand how to use codeloom. Installed via `codeloom <agent> install` to the agent's skill/rules directory.

Supported agents: Claude Code, OpenCode, Cursor, Windsurf, Cline, Aider, Codex CLI, Gemini CLI.

### 2. Hook Files (PreToolUse / BeforeTool)

For agents that support hooks (Claude Code, Codex, Gemini), a hook fires before every `Glob`/`Grep`/`Bash`/`read_file` call to remind the agent: "There's a code graph — search before grepping."

### 3. MCP Server (`codeloom mcp`)

A **Model Context Protocol** server over stdio transport. Exposes 5 tools:

| Tool | Description |
|------|-------------|
| `search` | Hybrid search with subgraph — primary tool |
| `node` | Node details with edges |
| `stats` | Graph statistics |
| `communities` | List/search communities |
| `build` | (Re)build the code graph |

The MCP server is transport-agnostic — it works with any MCP-compatible client (Claude Code, OpenCode, Cursor, VS Code via `vscode-mcp`).

---

## Incremental Auto-Rebuild

When integrated via hooks, codeloom detects code changes at session end:

1. `Stop` / `SessionEnd` hook fires
2. Runs `git diff --name-only` to find changed files
3. If any source files changed, triggers `codeloom build . --incremental`
4. Background process, zero user/agent intervention

The graph is always up-to-date for the next session.

---

## Memory Management

codeloom runs on a **4GB memory budget** with stage-wise release:

| Stage | Memory peak | Freed after |
|-------|-------------|-------------|
| Extraction | ~500MB | Graph build |
| Graph build | ~1GB | DB persistence |
| Embeddings | ~1.5GB (torch) | Batched, freed per batch |
| FAISS index | ~100MB | DB write |
| Search | ~200MB (models cached) | Session end |

GC triggers proactively at 75% of the 4GB threshold.

---

## Performance

Benchmarks on codeloom's own codebase (~3,500 lines, 90 files, 1,300 nodes):

| Operation | Time |
|-----------|------|
| Full build | ~14s |
| Incremental (small change) | ~4s |
| Incremental (no changes) | ~0.4s |
| Cold search (dual model) | ~2.8s |
| Cold search (`--fast` mode) | ~0.2s |
| Warm search (models cached) | ~0.08s |
| Cached search | <1ms |

Embedding models: ~180MB total, downloaded once to `~/.codeloom/models/`.
Database: ~2MB for SQLite + FTS5 + FAISS indices.

---

## 100% Local Guarantee

codeloom verifies no network leakage:

- **Zero HTTP/networking libraries** in dependencies (no `requests`, `aiohttp`, `httpx`, `urllib3`, `socket`)
- **Zero telemetry/analytics** (no Segment, Mixpanel, Datadog, Sentry)
- **Zero API keys** required
- **Zero cloud services**
- **MCP server uses stdio only** — no TCP/HTTP server mode
- **Only outbound network**: one-time download of embedding model weights from Hugging Face Hub (`huggingface_hub` library), cached locally and never re-downloaded unless the model cache is deleted
- **Telemetry disabled**: sets `HF_HUB_DISABLE_TELEMETRY=1` and `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` at startup

All data — graph nodes, edges, embeddings, communities, indices — lives in `.codeloom/knowledge.db` on your local machine.
