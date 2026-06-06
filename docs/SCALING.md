# Scaling

Known limits and recommendations for codeloom at repository scale.

## Benchmarks

Measurements on a 2023 MacBook Pro (M2 Pro, 32GB RAM). Model cache warm
unless noted. All builds use `embed=False` (embeddings dominate the first
build time at ~16s for model download).

### codeloom's own codebase (~3,500 lines, 90 files, 1,300 nodes)

| Operation | Time |
|-----------|------|
| Full build | ~14s |
| Incremental (changes) | ~4s |
| Incremental (no changes) | ~0.4s |
| Cold search (dual model) | ~2.8s |
| Cold search (`--fast`) | ~0.2s |
| Warm search | ~0.08s |
| Cached search | <1ms |

### Synthetic stress tests (no embeddings)

| Dataset | Files | Nodes | Edges | Build Time | Peak Memory |
|---------|-------|-------|-------|-----------|-------------|
| Tiny | 10 | 119 | 142 | 1.2s* | 18 MB |
| Small | 100 | 4,109 | 4,402 | 6.5s | 18 MB |
| Medium | 1,000 | 101,009 | 104,002 | 69.5s | 449 MB |
| Large | 5,000 | 205,009 | 220,002 | 216.8s | 907 MB |

*\*Tiny build excludes first-run model download (~16s with cold cache).*

Scaling from 100 to 5,000 files: build time grows ~33× for 50× more
files, memory grows ~50×. The relationship is roughly O(n) for both —
memory is sub-linear (449 MB → 907 MB for 2× the nodes, not 10×).

The main memory cliff is the embedding model load (~180MB), which
happens once and is released after build/search. Without embeddings,
the 205k-node / 5k-file case peaks at ~900 MB.

**Search times** at scale (cold start, dual model):
- 1k files / 100k nodes: ~6.6s
- 5k files / 205k nodes: ~7.1s

Search is relatively flat across node counts — the bottleneck is model
loading, not index size. Warm search (model cached): ~2-4s.

## Memory

| Dataset | Build Memory (no embed) | Build Memory (with embed) | DB Size |
|---------|------------------------|--------------------------|---------|
| 3.5k LOC / 90 files | ~20MB | ~200MB | ~2MB |
| 10k LOC / 100 files | ~20MB | ~200MB | ~10MB |
| Estimated 50k LOC | ~50MB | ~250MB | ~50MB |
| Estimated 500k LOC | ~200MB | ~400MB | ~500MB |

The main memory driver without embeddings is the NetworkX DiGraph held
in memory. With embeddings, the models (~180MB) are loaded during build
and search, then released.

## Known Bottlenecks

- **FAISS index rebuild**: Full builds rebuild both code and text FAISS
  indexes from scratch. At 100k+ nodes this takes 10-30s. Incremental
  builds skip this.
- **NetworkX graph construction**: All nodes and edges are held in memory.
  At 500k+ nodes consider using a graph DB backend.
- **Tree-sitter extraction**: Each file is parsed independently — O(n) in
  file count and trivially parallelisable, but currently single-threaded.

## Recommendations

- **Use `.codeloom-ignore`** to exclude `node_modules/`, `vendor/`,
  `build/`, and other generated directories. This is the single biggest
  lever for performance.
- **Prefer incremental builds** (`codeloom build . --incremental`).
  SHA-256 content hashing skips unchanged files entirely.
- **Use `--fast` for search** when latency matters more than recall.
  Text-only model is ~10x faster cold start than dual-model.
- **CI environments**: Set `CODELOOM_DB` env var to a fixed path and
  run `codeloom build . --incremental` on each run. The DB persists
  across CI runs and only changed files are re-processed.

## Known Limits

- Maximum verified: **5,000 files, 205,000 nodes, ~900 MB peak**
- Estimated maximum on 32 GB machine: ~10,000 files, ~500,000 nodes,
  ~2 GB peak (projected, not stress-tested)
- FAISS index dimension: 384 (fixed, determined by embedding model)
- SQLite WAL mode: supports concurrent readers but single writer
