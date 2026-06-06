# Scaling

Known limits and recommendations for codeloom at repository scale.

## Benchmarks

Measurements on a 2023 MacBook Pro (M2 Pro, 32GB RAM). Model cache warm
unless noted. All builds use `embed=False` and parallel extraction
(default: `os.cpu_count()` workers).

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

### Synthetic stress tests (no embeddings, parallel extraction)

| Dataset | Files | Nodes | Edges | Build Time | Peak Memory |
|---------|-------|-------|-------|-----------|-------------|
| Tiny | 10 | 119 | 142 | 0.7s | 14 MB |
| Small | 100 | 4,109 | 4,402 | 2.3s | 16 MB |
| Medium | 1,000 | 101,009 | 104,002 | 53.1s | 393 MB |
| Large | 5,000 | 205,009 | 220,002 | 164.9s | 814 MB |

Improvement over the previous single-threaded baseline:
- **Tiny**: 0.7s vs 1.2s (**41% faster**), 14 MB vs 18 MB (**22% less**)
- **Small**: 2.3s vs 6.5s (**64% faster**), 16 MB vs 18 MB (**11% less**)
- **Medium**: 53.1s vs 69.5s (**24% faster**), 393 MB vs 449 MB (**12% less**)
- **Large**: 164.9s vs 216.8s (**24% faster**), 814 MB vs 907 MB (**10% less**)

Improvements come from two changes:
- **Parallel extraction** (ProcessPoolExecutor): 24-64% faster builds,
  with the biggest impact at smaller sizes where extraction dominates
  the pipeline time.
- **Compact node storage** (path interning, skipped empty attrs,
  source_snippet stripped from in-memory graph after SQLite persist):
  10-22% less peak memory across all sizes.

Scaling from 100 to 5,000 files: build time grows ~72× for 50× more
files. The relationship is sub-linear in file count because the later
pipeline stages (embed, cluster, analyze) scale with total nodes rather
than file count.

The main memory cliff is the embedding model load (~180MB), which
happens once and is released after build/search. Without embeddings,
the 205k-node / 5k-file case peaks at ~814 MB.

**Search times** at scale — model loading is the dominant cost:
- Cold start (first search, model loaded from disk): ~2-5s
- Warm search (model cached in process): ~0.1-0.4s
- Cached query (same query within 128 LRU): <1ms

Search time is flat across all dataset sizes — the bottleneck is
sentence-transformer encoding, not FAISS index size.

## Memory

| Dataset | Build Memory (no embed) | Build Memory (with embed) | DB Size |
|---------|------------------------|--------------------------|---------|
| 3.5k LOC / 90 files | ~16MB | ~196MB | ~2MB |
| 10k LOC / 100 files | ~16MB | ~196MB | ~10MB |
| 101k nodes / 1k files | ~393MB | ~573MB | ~50MB |
| 205k nodes / 5k files | ~814MB | ~994MB | ~100MB |

The main memory driver without embeddings is the NetworkX DiGraph held
in memory. With embeddings, the models (~180MB) are loaded during build
and search, then released.

## Known Bottlenecks

- **FAISS index rebuild**: Full builds rebuild both code and text FAISS
  indexes from scratch. At 100k+ nodes this takes 10-30s. Incremental
  builds skip this.
- **NetworkX graph construction**: All nodes and edges are held in memory.
  At 500k+ nodes consider using a graph DB backend.
- **Tree-sitter extraction**: Now parallelised via ProcessPoolExecutor
  (default: os.cpu_count() workers). Extraction is CPU-bound and no
  longer a bottleneck for multi-core machines.

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
