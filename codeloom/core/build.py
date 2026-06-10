"""Graph build module — assembles extracted nodes/edges into a NetworkX graph.

Handles node deduplication, edge merging, and cross-file relationship
resolution.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import networkx as nx

from codeloom.core.extract import ExtractedEdge, ExtractionResult

if TYPE_CHECKING:
    import igraph

    from codeloom.storage.store import KnowledgeStore


def build_graph(extractions: list[ExtractionResult]) -> nx.DiGraph:
    """Build a unified directed graph from multiple extraction results.

    Three-phase deduplication:
    1. Intra-file: merge identical nodes within a file
    2. Inter-file: resolve wildcard references (*::name) across files
    3. Semantic: (handled later by embeddings module)

    Uses path interning to reduce per-node memory for redundant file_path
    strings, and skips empty default attributes to save dict slots.

    Args:
        extractions: List of per-file extraction results.

    Returns:
        Unified NetworkX directed graph.
    """
    G = nx.DiGraph()
    name_index: dict[str, list[str]] = defaultdict(list)  # name -> [node_ids]
    wildcard_edges: list[ExtractedEdge] = []

    # Path interning pool — same file_path shared across all nodes
    _path_pool: dict[str, str] = {}

    def _intern(p: str) -> str:
        if p not in _path_pool:
            _path_pool[p] = p
        return _path_pool[p]

    # Phase 1: Add all nodes
    for ext in extractions:
        for node in ext.nodes:
            if G.has_node(node.id):
                continue
            attrs = {
                "label": node.name,
                "kind": node.kind,
                "file_path": _intern(node.file_path),
                "language": node.language,
                "start_line": node.start_line,
                "end_line": node.end_line,
            }
            # Skip empty defaults to save ~200 bytes/node of dict slots
            if node.docstring:
                attrs["docstring"] = node.docstring
            if node.signature:
                attrs["signature"] = node.signature
            if node.decorators:
                attrs["decorators"] = node.decorators
            if node.source_snippet:
                attrs["source_snippet"] = node.source_snippet
            G.add_node(node.id, **attrs)
            name_index[node.name].append(node.id)

    # Phase 2: Add edges, collecting wildcards for resolution
    for ext in extractions:
        for edge in ext.edges:
            if edge.target.startswith("*::"):
                wildcard_edges.append(edge)
            elif G.has_node(edge.source) and G.has_node(edge.target):
                G.add_edge(
                    edge.source,
                    edge.target,
                    relation=edge.relation,
                    confidence=edge.confidence,
                )

    # Phase 3: Resolve wildcard references
    for edge in wildcard_edges:
        # Extract target name from wildcard pattern like *::class::ClassName
        parts = edge.target.split("::")
        target_name = parts[-1]

        candidates = name_index.get(target_name, [])
        if len(candidates) == 1:
            confidence = "EXTRACTED"
        elif len(candidates) > 1:
            # Multiple candidates: ambiguous reference — skip entirely.
            # AMBIGUOUS edges connect unrelated nodes sharing a common name
            # (e.g. "logger", "Config"), creating false bridges that inflate
            # community sizes and degrade search quality.
            continue
        else:
            # Create a placeholder external node
            ext_id = f"external::{target_name}"
            if not G.has_node(ext_id):
                G.add_node(
                    ext_id,
                    label=target_name,
                    kind="external",
                    file_path="",
                    language="",
                )
            candidates = [ext_id]
            confidence = "INFERRED"

        for candidate in candidates:
            if G.has_node(edge.source):
                G.add_edge(
                    edge.source,
                    candidate,
                    relation=edge.relation,
                    confidence=confidence,
                )

    # Phase 4: Build directory hierarchy
    _add_directory_nodes(G)

    return G


def _add_directory_nodes(G: nx.DiGraph) -> None:
    """Create directory nodes and connect them to files and parent
    directories."""
    file_paths: set[str] = set()
    for _, data in G.nodes(data=True):
        fp = data.get("file_path", "")
        if fp and data.get("kind") in ("module", "document"):
            file_paths.add(fp)

    dir_nodes: set[str] = set()

    for fp in file_paths:
        parts = PurePosixPath(fp).parts
        # Create directory nodes for each level (skip the filename)
        for i in range(1, len(parts)):
            dir_path = str(PurePosixPath(*parts[:i]))
            dir_id = f"dir::{dir_path}"

            if dir_id not in dir_nodes:
                dir_nodes.add(dir_id)
                if not G.has_node(dir_id):
                    G.add_node(
                        dir_id,
                        label=parts[i - 1],
                        kind="directory",
                        file_path=dir_path,
                        language="",
                        start_line=0,
                        end_line=0,
                        docstring="",
                        signature="",
                        source_snippet=f"Directory: {dir_path}",
                    )

            # Connect parent → child directory
            if i >= 2:
                parent_path = str(PurePosixPath(*parts[: i - 1]))
                parent_id = f"dir::{parent_path}"
                if G.has_node(parent_id) and not G.has_edge(parent_id, dir_id):
                    G.add_edge(
                        parent_id,
                        dir_id,
                        relation="contains",
                        confidence="EXTRACTED",
                    )

        # Connect deepest directory → file (module/document node)
        if len(parts) >= 2:
            parent_dir = str(PurePosixPath(*parts[:-1]))
            parent_id = f"dir::{parent_dir}"
            # Find the module/document node for this file
            for node_id, data in G.nodes(data=True):
                if (
                    data.get("file_path") == fp
                    and data.get("kind") in ("module", "document")
                    and not G.has_edge(parent_id, node_id)
                ):
                    G.add_edge(
                        parent_id,
                        node_id,
                        relation="contains",
                        confidence="EXTRACTED",
                    )


# Tier 3: マージ/削除対象ノード種別
MERGE_KINDS = frozenset(
    {
        "constructor",
        "property",
        "variable",
        "decorator",
        "type_alias",
    }
)


def merge_tier3_nodes(G: nx.DiGraph) -> nx.DiGraph:
    """Tier 3ノードを親ノードにマージし、エッジをリダイレクト。

    - constructor → classにsig/doc統合
    - property → classのメンバーリストに追加
    - variable → moduleのメンバーリストに追加
    - decorator → 親のdecoratorsリストに追加
    - type_alias → moduleのメンバーリストに追加
    - external → 削除（エッジも削除）
    """
    nodes_to_remove: list[str] = []

    for node_id in list(G.nodes()):
        data = G.nodes[node_id]
        kind = data.get("kind", "")

        if kind not in MERGE_KINDS:
            continue

        # 親ノードを探す（incoming "defines" or "contains" エッジ）
        parent_id = None
        for pred in G.predecessors(node_id):
            edge_data = G.edges[pred, node_id]
            if edge_data.get("relation") in ("defines", "contains"):
                parent_id = pred
                break

        if parent_id is None:
            # 親がなければノードだけ削除
            nodes_to_remove.append(node_id)
            continue

        parent_data = G.nodes[parent_id]
        _merge_into_parent(parent_data, data, kind)

        # このノードの他のエッジを親にリダイレクト
        for _, target, edata in list(G.out_edges(node_id, data=True)):
            if target != parent_id and not G.has_edge(parent_id, target):
                G.add_edge(parent_id, target, **edata)
        for source, _, edata in list(G.in_edges(node_id, data=True)):
            if source != parent_id and not G.has_edge(source, parent_id):
                G.add_edge(source, parent_id, **edata)

        nodes_to_remove.append(node_id)

    # externalノードも削除
    for node_id in list(G.nodes()):
        if G.nodes[node_id].get("kind") == "external":
            nodes_to_remove.append(node_id)

    G.remove_nodes_from(nodes_to_remove)
    return G


def _merge_into_parent(parent: dict, child: dict, kind: str) -> None:
    """子ノードの情報を親ノードにマージ。"""
    if kind == "constructor":
        # constructorのsignature/docstringをclassに統合
        if child.get("signature") and not parent.get("signature"):
            parent["signature"] = child["signature"]
        if child.get("docstring"):
            existing = parent.get("docstring", "")
            if existing:
                parent["docstring"] = f"{existing}\n\n{child['docstring']}"
            else:
                parent["docstring"] = child["docstring"]
    elif kind in ("property", "variable", "type_alias"):
        # メンバー名をリストとして追加
        members = parent.get("merged_members", [])
        label = child.get("label", "")
        if label:
            members.append(label)
        parent["merged_members"] = members
    elif kind == "decorator":
        # デコレータを親の属性リストに追加
        decorators = parent.get("decorators", [])
        label = child.get("label", "")
        if label and label not in decorators:
            decorators.append(label)
        parent["decorators"] = decorators


_CONFIDENCE_SCORES: dict[str, float] = {
    "EXTRACTED": 1.0,
    "INFERRED": 0.5,
    "AMBIGUOUS": 0.3,
}


def compute_edge_weights(
    G: nx.DiGraph,
    embeddings: dict[str, list[float]] | None = None,
    store: KnowledgeStore | None = None,
) -> None:
    """Compute composite edge weights combining multiple signals.

    weight = 0.4 * semantic + 0.3 * confidence
            + 0.2 * proximity + 0.1 * bidirectional

    Accepts both NetworkX DiGraph and igraph Graph.
    When given an igraph graph, embeddings are loaded lazily from
    *store* (a KnowledgeStore) instead of an in-memory dict.

    Args:
        G: The code graph (modified in-place). NetworkX or igraph.
        embeddings: Node_id -> embedding vector mapping for
            semantic similarity (NetworkX path only).
        store: KnowledgeStore for lazy embedding loading (igraph path).
    """
    if hasattr(G, 'vs'):
        _compute_edge_weights_igraph(G, store)
        return
    _compute_edge_weights_nx(G, embeddings)


def _compute_edge_weights_nx(
    G: nx.DiGraph,
    embeddings: dict[str, list[float]] | None = None,
) -> None:
    """NetworkX implementation of edge weight computation."""
    import numpy as np

    bidir_pairs: set[tuple[str, str]] = set()
    for u, v in G.edges():
        if G.has_edge(v, u):
            bidir_pairs.add((u, v))
            bidir_pairs.add((v, u))

    for u, v, data in G.edges(data=True):
        semantic = 0.0
        if embeddings and u in embeddings and v in embeddings:
            vec_u = np.array(embeddings[u], dtype=np.float32)
            vec_v = np.array(embeddings[v], dtype=np.float32)
            norm_u = np.linalg.norm(vec_u)
            norm_v = np.linalg.norm(vec_v)
            if norm_u > 0 and norm_v > 0:
                semantic = float(np.dot(vec_u, vec_v) / (norm_u * norm_v))
                semantic = max(0.0, semantic)

        confidence = _CONFIDENCE_SCORES.get(
            data.get("confidence", "EXTRACTED"),
            0.5,
        )

        u_path = G.nodes[u].get("file_path", "") if G.has_node(u) else ""
        v_path = G.nodes[v].get("file_path", "") if G.has_node(v) else ""
        if u_path and v_path and u_path == v_path:
            proximity = 1.0
        elif u_path and v_path:
            u_dir = str(PurePosixPath(u_path).parent)
            v_dir = str(PurePosixPath(v_path).parent)
            proximity = 0.7 if u_dir == v_dir else 0.4
        else:
            proximity = 0.4

        bidir = 1.0 if (u, v) in bidir_pairs else 0.0
        weight = (
            0.4 * semantic + 0.3 * confidence + 0.2 * proximity + 0.1 * bidir
        )
        data["weight"] = round(weight, 4)
        data["semantic_similarity"] = round(semantic, 4)


def _compute_edge_weights_igraph(
    G: "igraph.Graph",
    store: "KnowledgeStore | None" = None,
) -> None:
    """igraph implementation of edge weight computation.

    Loads embeddings lazily from *store* using batched SQL queries
    instead of keeping all vectors in memory.
    """
    import numpy as np

    node_names = G.vs["name"]

    # Precompute bidirectionality
    bidir_pairs: set[tuple[int, int]] = set()
    for e in G.es:
        if G.get_eid(e.target, e.source, directed=True, error=False) != -1:
            bidir_pairs.add((e.source, e.target))
            bidir_pairs.add((e.target, e.source))

    # Load embeddings in batches from store
    emb_cache: dict[str, np.ndarray] = {}
    _EMB_BATCH = 500

    def _get_emb(
        u_name: str, v_name: str
    ) -> tuple[np.ndarray, np.ndarray] | None:
        missing = [n for n in (u_name, v_name) if n not in emb_cache]
        if missing and store is not None:
            for i in range(0, len(missing), _EMB_BATCH):
                batch = missing[i:i + _EMB_BATCH]
                placeholders = ",".join("?" for _ in batch)
                rows = store.conn.execute(
                    "SELECT node_id, vector FROM embeddings "
                    f"WHERE node_id IN ({placeholders})",
                    batch,
                ).fetchall()
                for row in rows:
                    emb_cache[row["node_id"]] = np.frombuffer(
                        row["vector"], dtype=np.float32
                    )
        if u_name in emb_cache and v_name in emb_cache:
            return emb_cache[u_name], emb_cache[v_name]
        return None

    for i, e in enumerate(G.es):
        u_idx = e.source
        v_idx = e.target
        u_name = node_names[u_idx]
        v_name = node_names[v_idx]
        edge_data = G.es[i]

        semantic = 0.0
        pair = _get_emb(u_name, v_name)
        if pair is not None:
            vec_u, vec_v = pair
            norm_u = np.linalg.norm(vec_u)
            norm_v = np.linalg.norm(vec_v)
            if norm_u > 0 and norm_v > 0:
                semantic = float(np.dot(vec_u, vec_v) / (norm_u * norm_v))
                semantic = max(0.0, semantic)

        confidence = _CONFIDENCE_SCORES.get(
            edge_data.attributes().get("confidence", "EXTRACTED"),
            0.5,
        )

        u_path = G.vs[u_idx].attributes().get("file_path", "")
        v_path = G.vs[v_idx].attributes().get("file_path", "")
        if u_path and v_path and u_path == v_path:
            proximity = 1.0
        elif u_path and v_path:
            u_dir = str(PurePosixPath(u_path).parent)
            v_dir = str(PurePosixPath(v_path).parent)
            proximity = 0.7 if u_dir == v_dir else 0.4
        else:
            proximity = 0.4

        bidir = 1.0 if (u_idx, v_idx) in bidir_pairs else 0.0
        weight = (
            0.4 * semantic + 0.3 * confidence + 0.2 * proximity + 0.1 * bidir
        )
        edge_data["weight"] = round(weight, 4)
        edge_data["semantic_similarity"] = round(semantic, 4)


def compute_pagerank(
    G: nx.DiGraph,
    personalization: dict[str, float] | None = None,
    initial_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute PageRank importance scores for all nodes.

    Accepts both NetworkX DiGraph and igraph Graph.

    Args:
        G: The code graph. NetworkX or igraph.
        personalization: Optional per-node bias (ignored for igraph).
        initial_scores: Optional hot-start scores (ignored for igraph).

    Returns:
        Dict mapping node_id to importance score.
    """
    if hasattr(G, 'vs'):
        return _compute_pagerank_igraph(G)
    return _compute_pagerank_nx(G, personalization, initial_scores)


def _compute_pagerank_nx(
    G: nx.DiGraph,
    personalization: dict[str, float] | None = None,
    initial_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    """NetworkX PageRank implementation."""
    if len(G) == 0:
        return {}

    nstart = None
    if initial_scores:
        nstart = {n: s for n, s in initial_scores.items() if n in G}
        if not nstart:
            nstart = None

    try:
        return nx.pagerank(
            G,
            personalization=personalization,
            nstart=nstart,
            max_iter=200
        )
    except nx.PowerIterationFailedConvergence:
        return {n: 1.0 / len(G) for n in G}


def _compute_pagerank_igraph(G: "igraph.Graph") -> dict[str, float]:
    """igraph PageRank implementation.

    Hot-start is not supported by igraph so incremental builds may
    converge slightly slower; results are equally correct.
    """
    if G.vcount() == 0:
        return {}
    try:
        scores = G.pagerank(directed=True, niter=200)
        return dict(zip(G.vs["name"], scores))
    except Exception:
        n = G.vcount()
        return {G.vs[i]["name"]: 1.0 / n for i in range(n)}


def graph_stats(G: nx.DiGraph) -> dict:
    """Compute basic graph statistics.

    Accepts both NetworkX DiGraph and igraph Graph.
    """
    if hasattr(G, 'vs'):
        n = G.vcount()
        e = G.ecount()
        density = (2.0 * e) / max(n * (n - 1), 1)
        wcc = len(G.components(mode="weak"))
        isolates = sum(1 for v in G.vs if G.degree(v) == 0)
        return {
            "nodes": n, "edges": e, "density": round(density, 6),
            "components": wcc, "isolates": isolates,
        }
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "density": nx.density(G),
        "components": nx.number_weakly_connected_components(G),
        "isolates": len(list(nx.isolates(G))),
    }
