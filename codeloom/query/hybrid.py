"""Hybrid search engine: vector + keyword + graph expansion + community + FTS5.

5-signal search + shortest-path subgraph response:
1. Code vector search (bge-small) -> semantic code matches
2. Text vector search (multilingual-e5) -> semantic text matches
3. Graph expansion (BFS from vector seeds) -> structurally related nodes
4. Keyword search (FTS5 BM25) -> exact name matching
5. Community search (FTS5 on summaries) -> topic-level discovery
6. Weighted RRF fusion -> unified ranking
7. Shortest-path subgraph -> how results connect
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import networkx as nx

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from codeloom.storage.store import KnowledgeStore


# Stopwords for keyword search noise removal
STOPWORDS: frozenset[str] = frozenset({
    "the", "is", "at", "which", "on", "a", "an", "and", "or", "but",
    "in", "with", "to", "for", "of", "not", "no", "can", "had", "has",
    "have", "was", "were", "been", "being", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "must", "need",
    "this", "that", "these", "those", "it", "its", "from", "by", "as",
    "are", "be", "if", "so", "than", "too", "very", "just", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "then", "once",
    "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such",
    "only", "own", "same", "also", "what", "who", "whom",
})

# Multiplier applied to test files when penalty is active.
# 0.0 = all tests excluded; 1.0 = no penalty.
TEST_PENALTY_FACTOR = 0.3

# Path components that identify test directories.
_TEST_DIRS = frozenset({
    "test", "tests", "spec", "specs", "tst", "__tests__",
})

# Additional directory names that clearly indicate test code.
_TEST_DIR_PREFIXES = frozenset({
    "testing", "testdata", "testutils", "testhelpers", "testfixtures",
    "testharness", "testdriver", "testsuite",
})

# Directories ending in "test" that are common in test code bases.
# Does NOT include common English words (protest, contest, detest, etc.).
_TEST_DIR_SUFFIXES = frozenset({
    "mytest", "unittest", "integrationtest", "unittests",
})

# Common directory names that should NOT be treated as test dirs
# despite starting with "test".
_TEST_DIR_FALSE_POSITIVES = frozenset({
    "testimonial", "testament", "testify", "testimony",
})

# Filename patterns for test files (case-insensitive match).
# Patterns use fnmatch; explicit extensions prevent false positives
# like "protest.py" matching "*Test.*".
_TEST_NAME_PATTERNS = frozenset({
    # Python
    "test_*.py", "*_test.py",
    # JavaScript / TypeScript
    "*.test.js", "*.test.ts", "*.test.jsx", "*.test.tsx",
    "*.spec.js", "*.spec.ts", "*.spec.jsx", "*.spec.tsx",
    "*.test", "*.spec",
    # Java
    "*Test.java", "*Tests.java", "*IT.java", "*Spec.java",
    # Go
    "*_test.go",
    # Rust
    "*_test.rs",
    # C# / .NET
    "*Tests.cs", "*Test.cs",
    # Ruby
    "*_spec.rb", "*_test.rb",
})

# Maven/Java src/test/java convention — path prefix.
_SRC_TEST_PREFIXES = ("src/test/", "src\\test\\")


# Data classes

@dataclass
class SearchResult:
    """Individual search result node."""
    node_id: str
    label: str
    kind: str
    file_path: str
    score: float
    source: str  # "seed" | "path"
    start_line: int = 0
    end_line: int = 0
    signature: str = ""
    docstring: str = ""
    signal_contributions: dict[str, float] = field(default_factory=dict)


@dataclass
class SearchEdge:
    """Edge in the subgraph (on a shortest path)."""
    source: str
    target: str
    relation: str


@dataclass
class SearchGraph:
    """Search results as a subgraph.

    Seed nodes + path nodes (MST intermediates) + edges (MST paths only).
    Isolated seeds (unreachable from other seeds) go in isolated.
    """
    nodes: list[SearchResult]
    edges: list[SearchEdge]
    isolated: list[SearchResult] = field(default_factory=list)
    hint: str = ""

    def to_text(self, source_dir: str = "") -> str:
        """Compact graph response shared by MCP and CLI.

        Format:
            seeds: node_id1 (score: 0.047), node_id2 (score: 0.032)

            edges:
            node_a -relation-> node_b
            node_b -relation-> node_c
        """
        def _s(node_id: str) -> str:
            """Strip source_dir prefix to get relative path."""
            if source_dir and node_id.startswith(source_dir):
                return node_id[len(source_dir):]
            return node_id

        seed_ids = []
        for n in self.nodes:
            if n.source == "seed":
                sid = _s(n.node_id)
                seed_ids.append(f"{sid} (score: {n.score})")

        lines = ["seeds:"]
        for sid in seed_ids:
            lines.append(sid)

        if self.edges:
            lines.append("")
            lines.append("edges:")
            for e in self.edges:
                lines.append(f"{_s(e.source)} -{e.relation}-> {_s(e.target)}")

        if self.hint:
            lines.append("")
            lines.append(f"Hint: {self.hint}")

        return "\n".join(lines)

    def to_json(self, source_dir: str = "") -> dict:
        """Structured JSON response for programmatic consumption.

        Returns:
            {
                "seeds": [...], "edges": [...], "isolated": [...],
                "hint": "..."
            }
        """
        def _s(node_id: str) -> str:
            if source_dir and node_id.startswith(source_dir):
                return node_id[len(source_dir):]
            return node_id

        seeds = []
        for n in self.nodes:
            if n.source == "seed":
                seeds.append({
                    "id": _s(n.node_id),
                    "label": n.label,
                    "kind": n.kind,
                    "file": n.file_path,
                    "line": n.start_line,
                    "score": n.score,
                    "signature": n.signature,
                    "signal_contributions": n.signal_contributions,
                })

        edges = [
            {"from": _s(e.source), "to": _s(e.target), "relation": e.relation}
            for e in self.edges
        ]

        isolated = [
            {
                "id": _s(n.node_id),
                "file": n.file_path,
                "line": n.start_line,
                "score": n.score,
            }
            for n in self.isolated
        ]

        hint_val = self.hint if self.hint else None
        return {"seeds": seeds, "edges": edges, "isolated": isolated, "hint": hint_val}

_search_cache: OrderedDict[str, SearchGraph] = OrderedDict()
_CACHE_MAX_SIZE = 128


# Valid values for --kind filter
VALID_KINDS = frozenset({
    "function", "class", "method", "interface", "enum",
    "struct", "trait", "section",
})


def _generate_filter_hint(
    seed_nodes: list[tuple[str, float, dict]],
    kind_filter: str | None,
    file_filter: str | None,
    top_k: int,
) -> str:
    """Generate a contextual hint when no filter was used.

    If >5 results returned and no filter applied, suggests the
    most common kind among results to guide the agent toward
    using --kind or --file filtering.
    """
    if kind_filter or file_filter:
        return ""

    if len(seed_nodes) <= 5:
        return ""

    from collections import Counter
    kind_counts: Counter = Counter()
    for _, _, data in seed_nodes:
        kind = data.get("kind", "unknown")
        kind_counts[kind] += 1

    if not kind_counts:
        return ""

    top_kind, top_count = kind_counts.most_common(1)[0]
    threshold = len(seed_nodes) * 0.3
    if top_count >= threshold:
        return (
            f"{top_count} of {len(seed_nodes)} results are {top_kind}s. "
            f"Use `--kind {top_kind}` to narrow."
        )

    return ""


def _cache_key(query: str, top_k: int) -> str:
    """Generate cache key for a search query."""
    raw = f"{query}|{top_k}"
    return hashlib.md5(raw.encode()).hexdigest()


def clear_search_cache() -> None:
    """Clear search cache (called after graph rebuild)."""
    _search_cache.clear()


# Signal settings (5 signals: code_vector, text_vector, graph, keyword, community)

SIGNAL_NAMES = ["code_vector", "text_vector", "graph", "keyword", "community"]

# code_vector(1.0): semantic code matching (identifiers, signatures)
# text_vector(1.0): semantic text matching (docs, comments)
# graph(0.8): structural proximity (BFS from vector seeds)
# keyword(1.5): exact name matching (function names, class names)
# community(0.7): topic-level discovery (community summaries)
DEFAULT_WEIGHTS = [1.0, 1.0, 0.8, 1.5, 0.7]


def reciprocal_rank_fusion(
    *ranked_lists: list[tuple[str, float]],
    k: int = 60,
    weights: list[float] | None = None,
    signal_names: list[str] | None = None,
) -> tuple[list[tuple[str, float]], dict[str, dict[str, float]]]:
    """Weighted Reciprocal Rank Fusion to merge multiple rankings.

    RRF score = sum(w_i / (k + rank_i))
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    if signal_names is None:
        signal_names = SIGNAL_NAMES[:len(ranked_lists)]

    scores: dict[str, float] = {}
    breakdowns: dict[str, dict[str, float]] = {}
    for w, rlist, sname in zip(weights, ranked_lists, signal_names):
        for rank, (item_id, _) in enumerate(rlist):
            contribution = w / (k + rank + 1)
            scores[item_id] = scores.get(item_id, 0) + contribution
            if item_id not in breakdowns:
                breakdowns[item_id] = {}
            breakdowns[item_id][sname] = breakdowns[item_id].get(sname, 0) + contribution

    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return fused, breakdowns


def _is_test_file(file_path: str) -> bool:
    """Heuristic: is this file likely a test file?

    Checks (in order):
    1. Path contains a test directory component (test/, tests/, spec/, etc.)
    2. File in Maven/Gradle src/test/java or similar
    3. Filename matches a test-naming convention (*Test.java, test_*.py, *.spec.ts, etc.)
    """
    from fnmatch import fnmatch

    # Normalise separators
    fp = file_path.replace("\\", "/")

    # 1. Test directory component
    parts = fp.split("/")
    for part in parts:
        lower = part.lower()
        if lower in _TEST_DIRS:
            return True
        if lower in _TEST_DIR_PREFIXES:
            return True
        if lower in _TEST_DIR_SUFFIXES:
            return True
        # Prefixed directories: integrationTest, e2eTest, test_utils, etc.
        # Use a whitelist approach to avoid false positives.
        if lower not in _TEST_DIR_FALSE_POSITIVES:
            if lower.startswith("test"):
                remainder = lower[4:]
                if not remainder or remainder[0] in ("_", "-"):
                    return True
            if lower.endswith("test") and len(lower) > 4:
                prefix = lower[:-4]
                if prefix in ("integration", "unit", "e2e", "smoke", "regression"):
                    return True

    # 2. src/test/ prefix (Maven / Gradle convention)
    for prefix in _SRC_TEST_PREFIXES:
        if fp.startswith(prefix):
            return True

    # 3. Filename pattern (case-insensitive)
    fname = parts[-1] if parts else ""
    if not fname:
        return False
    fname_lower = fname.lower()
    for pat in _TEST_NAME_PATTERNS:
        if fnmatch(fname, pat):
            return True
        if fnmatch(fname_lower, pat):
            return True
        # Also try with lowercase pattern for patterns containing uppercase
        if not pat.islower() and fnmatch(fname_lower, pat.lower()):
            return True

    return False


def _generate_source_test_hint(
    seed_nodes: list[tuple[str, float, dict]],
) -> str:
    """Generate a hint when results mix source and test files.

    If results contain both source and test files, report the split
    so the agent can decide whether to re-query with different filters.
    """
    if len(seed_nodes) <= 3:
        return ""

    test_count = 0
    source_count = 0
    for _, _, data in seed_nodes:
        fp = data.get("file_path", "")
        if _is_test_file(fp):
            test_count += 1
        else:
            source_count += 1

    if test_count == 0 or source_count == 0:
        return ""

    if test_count > source_count:
        return (
            f"Found {test_count} test-file results and {source_count} "
            f"source-file results. Tests dominate the ranking. "
            f"Use `--include-tests off` to focus on source files."
        )
    else:
        return (
            f"Found {source_count} source-file results and {test_count} "
            f"test-file results."
        )


def extract_search_terms(query: str) -> list[str]:
    """Extract search terms by removing stopwords and short tokens."""
    return [
        t.lower() for t in query.split()
        if len(t) > 2 and t.lower() not in STOPWORDS
    ]


# Shortest-path subgraph

def _build_seed_subtree(
    G: nx.DiGraph,
    seed_ids: list[str],
    max_path_length: int = 6,
) -> tuple[list[str], list[SearchEdge], list[str]]:
    """Build MST-based minimum subtree connecting all seeds.

    Steiner Tree approximation:
    1. Compute shortest distance matrix between seed pairs
    2. Build MST between seeds (Kruskal)
    3. Expand MST edges to actual shortest paths
    4. Separate unreachable seeds as isolated

    Args:
        G: Code graph.
        seed_ids: List of seed node IDs.
        max_path_length: Maximum path length for MST inclusion.

    Returns:
        (intermediate node IDs, path edges, isolated seed IDs)
    """
    if len(seed_ids) < 2:
        return [], [], []

    undirected = G.to_undirected(as_view=True)
    seed_set = set(seed_ids)

    # Step 1: Compute shortest distance and paths between seed pairs
    pair_paths: dict[tuple[int, int], list[str]] = {}
    valid_seeds = [s for s in seed_ids if undirected.has_node(s)]

    for i, src in enumerate(valid_seeds):
        for j in range(i + 1, len(valid_seeds)):
            tgt = valid_seeds[j]
            try:
                path = nx.shortest_path(undirected, src, tgt)
            except nx.NetworkXNoPath:
                continue
            if len(path) <= max_path_length:
                pair_paths[(i, j)] = path

    if not pair_paths:
        # No connectable pairs -> all seeds isolated
        return [], [], list(seed_ids)

    # Step 2: Build MST (Kruskal)
    mst_edges: list[tuple[int, int, int]] = sorted(
        (len(path) - 1, i, j) for (i, j), path in pair_paths.items()
    )

    # Union-Find
    parent = list(range(len(valid_seeds)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> bool:
        rx, ry = find(x), find(y)
        if rx == ry:
            return False
        parent[rx] = ry
        return True

    selected_pairs: list[tuple[int, int]] = []
    for _dist, i, j in mst_edges:
        if union(i, j):
            selected_pairs.append((i, j))
            if len(selected_pairs) == len(valid_seeds) - 1:
                break

    # Step 3: Collect nodes and edges from MST paths
    intermediate_ids: set[str] = set()
    edges: list[SearchEdge] = []
    seen_edges: set[tuple[str, str]] = set()
    connected_seeds: set[str] = set()

    for i, j in selected_pairs:
        path = pair_paths[(i, j)]
        connected_seeds.add(valid_seeds[i])
        connected_seeds.add(valid_seeds[j])

        # Collect intermediate nodes
        for node_id in path[1:-1]:
            if node_id not in seed_set:
                intermediate_ids.add(node_id)

        # Collect edges (direction from original graph)
        for k in range(len(path) - 1):
            a, b = path[k], path[k + 1]
            edge_key = (min(a, b), max(a, b))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            if G.has_edge(a, b):
                rel = G.edges[a, b].get("relation", "")
                edges.append(SearchEdge(source=a, target=b, relation=rel))
            elif G.has_edge(b, a):
                rel = G.edges[b, a].get("relation", "")
                edges.append(SearchEdge(source=b, target=a, relation=rel))

    # Step 4: Isolated seeds (not included in MST)
    isolated = [s for s in seed_ids if s not in connected_seeds]

    return list(intermediate_ids), edges, isolated


# Graph expansion helper

def _expand_from_seeds(
    G: nx.DiGraph,
    seed_ids: list[str],
    hops: int = 2,
    max_nodes: int = 30,
) -> list[tuple[str, float]]:
    """BFS expansion from seed nodes through the graph.

    Scores decrease with distance from seeds:
    - hop 1: weight 1.0
    - hop 2: weight 0.5
    - hop 3+: not included

    Returns list of (node_id, score) sorted by score descending.
    """
    if not seed_ids or not G:
        return []

    scored: dict[str, float] = {}
    visited: set[str] = set(seed_ids)
    current_frontier: list[str] = seed_ids

    for hop in range(1, hops + 1):
        weight = 1.0 / hop
        next_frontier: list[str] = []
        for nid in current_frontier:
            if not G.has_node(nid):
                continue
            for neighbor in G.neighbors(nid):
                if neighbor not in visited:
                    visited.add(neighbor)
                    data = G.nodes.get(neighbor, {})
                    kind = data.get("kind", "")
                    if kind in ("external", "directory"):
                        continue
                    scored[neighbor] = scored.get(neighbor, 0) + weight
                    next_frontier.append(neighbor)
        current_frontier = next_frontier
        if not current_frontier:
            break

    return sorted(scored.items(), key=lambda x: x[1], reverse=True)[:max_nodes]


# Main search function

def hybrid_search(
    query: str,
    store: "KnowledgeStore",
    G: nx.DiGraph,
    top_k: int = 10,
    vector_candidates: int = 40,
    weights: list[float] | None = None,
    use_cache: bool = True,
    fast: bool = False,
    text_model: str | None = None,
    *,
    graph_hops: int = 2,
    kind: str | None = None,
    file_pattern: str | None = None,
    penalise_tests: bool = True,
) -> SearchGraph:
    """5-signal search + shortest-path subgraph response.

    Args:
        query: Natural language query.
        store: KnowledgeStore with embeddings + FTS5.
        G: Code graph.
        top_k: Number of seed nodes in response.
        vector_candidates: Number of candidates per signal.
        weights: Signal weights [code_vector, text_vector, graph, keyword, community].
        use_cache: Use LRU cache.
        fast: Use text model only (faster cold start).
        text_model: Text model name override.
        graph_hops: BFS hop count for graph expansion signal.
        kind: Filter by symbol kind (function, class, method, interface,"
            " enum, struct, trait, section).
        file_pattern: Filter by file path glob (e.g. "src/auth/*").
        penalise_tests: Demote test files in ranking by TEST_PENALTY_FACTOR (default True).

    Returns:
        SearchGraph containing seed nodes, path nodes, and edges.
    """
    # Stage 1: Cache check
    if use_cache:
        key = _cache_key(query, top_k)
        if key in _search_cache:
            _search_cache.move_to_end(key)
            return _search_cache[key]

    signal_weights = weights or DEFAULT_WEIGHTS
    top_terms = extract_search_terms(query)

    # Stage 2: Vector search (dual-model) — signals 1 and 2
    if fast:
        from codeloom.query.embeddings import TEXT_MODEL, embed_query
        effective_text = text_model or TEXT_MODEL
        query_vec = embed_query(query, effective_text)
        code_vector_hits = store.vector_search(
            query_vec, top_k=vector_candidates, model_type="code",
        )
        text_vector_hits = store.vector_search(
            query_vec, top_k=vector_candidates, model_type="text",
        )
    else:
        from codeloom.query.embeddings import embed_query_dual
        query_vecs = embed_query_dual(query, text_model=text_model)
        code_vector_hits = store.vector_search(
            query_vecs["code"], top_k=vector_candidates, model_type="code",
        )
        text_vector_hits = store.vector_search(
            query_vecs["text"], top_k=vector_candidates, model_type="text",
        )

    # Stage 3: Graph expansion from vector seeds — signal 3
    vector_seeds = [nid for nid, _ in (code_vector_hits + text_vector_hits)[:20]]
    graph_hits = _expand_from_seeds(G, vector_seeds, hops=graph_hops, max_nodes=vector_candidates)

    # Stage 4: Keyword search (FTS5) — signal 4
    keyword_results = store.keyword_search(top_terms, top_k=vector_candidates) if top_terms else []
    keyword_hits = [(r["id"], r["score"]) for r in keyword_results]

    # Stage 5: Community search — signal 5
    community_hits: list[tuple[str, float]] = []
    if top_terms:
        comm_results = store.community_search(top_terms, top_k=5)
        for cr in comm_results:
            member_ids = cr.get("node_ids", [])
            community_score = cr.get("score", 1.0)
            for mid in member_ids:
                community_hits.append((mid, community_score))

    # Stage 6: 5-signal RRF fusion
    fused, breakdowns = reciprocal_rank_fusion(
        code_vector_hits, text_vector_hits, graph_hits,
        keyword_hits, community_hits,
        weights=signal_weights,
        signal_names=SIGNAL_NAMES,
    )

    # Stage 6.5: Test penalty — demote test files in ranking
    if penalise_tests:
        penalised: dict[str, float] = {}
        kept: list[tuple[str, float, float]] = []
        for node_id, rrf_score in fused:
            data = G.nodes.get(node_id, {})
            if not data:
                kept.append((node_id, rrf_score, rrf_score))
                continue
            fp = data.get("file_path", "")
            if _is_test_file(fp):
                penalised_score = rrf_score * TEST_PENALTY_FACTOR
                penalised[node_id] = penalised_score
                kept.append((node_id, rrf_score, penalised_score))
            else:
                kept.append((node_id, rrf_score, rrf_score))
        # Re-sort by effective (possibly penalised) score
        kept.sort(key=lambda x: x[2], reverse=True)
    else:
        kept = [(nid, score, score) for nid, score in fused]

    # Stage 7: Seed node selection with optional filters
    import fnmatch

    seed_nodes: list[tuple[str, float, dict]] = []
    for node_id, _original_score, effective_score in kept:
        if len(seed_nodes) >= top_k:
            break
        data = G.nodes.get(node_id, {})
        if not data:
            continue
        kind_val = data.get("kind", "")
        if kind_val in ("external", "directory"):
            continue
        # Apply --kind filter
        if kind and kind_val != kind:
            continue
        # Apply --file filter
        if file_pattern:
            file_path = data.get("file_path", "")
            if not fnmatch.fnmatch(file_path, file_pattern):
                continue
        seed_nodes.append((node_id, effective_score, data))

    # Stage 8: MST-based subgraph construction
    seed_ids = [nid for nid, _, _ in seed_nodes]
    intermediate_ids, path_edges, isolated_ids = _build_seed_subtree(G, seed_ids)
    isolated_set = set(isolated_ids)

    # Stage 9: Build SearchGraph
    nodes: list[SearchResult] = []
    isolated_nodes: list[SearchResult] = []

    def _make_result(node_id: str, score: float, data: dict,
                     source: str) -> SearchResult:
        return SearchResult(
            node_id=node_id,
            label=data.get("label", node_id),
            kind=data.get("kind", ""),
            file_path=data.get("file_path", ""),
            score=round(score, 4),
            source=source,
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
            signature=data.get("signature", ""),
            docstring=data.get("docstring", ""),
            signal_contributions=breakdowns.get(node_id, {}),
        )

    for node_id, score, data in seed_nodes:
        sr = _make_result(node_id, score, data, "seed")
        if node_id in isolated_set:
            isolated_nodes.append(sr)
        else:
            nodes.append(sr)

    for node_id in intermediate_ids:
        data = G.nodes.get(node_id, {})
        if not data:
            continue
        nodes.append(_make_result(node_id, 0.0, data, "path"))

    result = SearchGraph(nodes=nodes, edges=path_edges, isolated=isolated_nodes)

    # Generate filter hint
    hint = _generate_filter_hint(seed_nodes, kind, file_pattern, top_k)
    if penalise_tests and not hint:
        hint = _generate_source_test_hint(seed_nodes)
    elif penalise_tests:
        source_hint = _generate_source_test_hint(seed_nodes)
        if source_hint:
            hint = hint + " " + source_hint
    if hint:
        result.hint = hint

    # Cache result
    if use_cache:
        key = _cache_key(query, top_k)
        _search_cache[key] = result
        if len(_search_cache) > _CACHE_MAX_SIZE:
            _search_cache.popitem(last=False)

    return result


def extract_result_edges(
    G: nx.DiGraph,
    results: SearchGraph | list[SearchResult],
) -> list[dict]:
    """Backward-compatible edge extraction helper.

    Converts SearchGraph edges to dict format.
    Falls back to extracting edges between result nodes for legacy list format.
    """
    if isinstance(results, SearchGraph):
        edges = []
        for e in results.edges:
            src_label = G.nodes.get(e.source, {}).get("label", e.source)
            tgt_label = G.nodes.get(e.target, {}).get("label", e.target)
            edges.append({
                "from": src_label,
                "to": tgt_label,
                "rel": e.relation,
            })
        return edges

    # Legacy: list[SearchResult]
    result_ids = {getattr(r, "node_id", None) for r in results} - {None}
    if not result_ids:
        return []
    edges = []
    seen: set[tuple[str, str]] = set()
    for r in results:
        nid = getattr(r, "node_id", None)
        if not nid or not G.has_node(nid):
            continue
        for _, target, edata in G.out_edges(nid, data=True):
            if target in result_ids:
                key = (nid, target)
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "from": G.nodes[nid].get("label", nid),
                        "to": G.nodes[target].get("label", target),
                        "rel": edata.get("relation", ""),
                    })
    return edges
