"""Graph analysis module — structural and semantic analysis.

Identifies god nodes, surprising connections, and computes quality metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    import igraph

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    god_nodes: list[dict] = field(default_factory=list)
    surprising_connections: list[dict] = field(default_factory=list)
    quality_metrics: dict = field(default_factory=dict)
    hub_nodes: list[dict] = field(default_factory=list)


def analyze(
    G: nx.DiGraph,
    pagerank: dict[str, float] | None = None,
    top_k: int = 10,
) -> AnalysisResult:
    """Run structural analysis on the code graph.

    Accepts both NetworkX DiGraph and igraph Graph.

    Args:
        G: The code graph (NetworkX or igraph).
        pagerank: Pre-computed PageRank scores.
        top_k: Number of top results per category.

    Returns:
        AnalysisResult with findings.
    """
    if hasattr(G, 'vs'):
        return _analyze_igraph(G, pagerank, top_k)
    return _analyze_nx(G, pagerank, top_k)


def _analyze_nx(
    G: nx.DiGraph,
    pagerank: dict[str, float] | None,
    top_k: int,
) -> AnalysisResult:
    """NetworkX implementation of graph analysis."""
    result = AnalysisResult()

    if len(G) == 0:
        return result

    pr = pagerank or nx.pagerank(G, max_iter=200)
    degree = dict(G.degree())

    scored = []
    for node in G.nodes():
        d = degree.get(node, 0)
        p = pr.get(node, 0)
        scored.append({
            "id": node,
            "label": G.nodes[node].get("label", node),
            "kind": G.nodes[node].get("kind", ""),
            "degree": d,
            "pagerank": round(p, 6),
            "score": d * p,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    result.god_nodes = scored[:top_k]

    try:
        bc = nx.betweenness_centrality(G, k=min(100, len(G)))
        hub_scored = [
            {"id": n, "label": G.nodes[n].get("label", n),
             "betweenness": round(v, 6)}
            for n, v in bc.items()
        ]
        hub_scored.sort(key=lambda x: x["betweenness"], reverse=True)
        result.hub_nodes = hub_scored[:top_k]
    except Exception:
        logger.debug("Betweenness centrality computation failed", exc_info=True)

    _find_surprising_connections_nx(G, result, top_k)
    result.quality_metrics = _compute_quality_nx(G)

    return result


def _analyze_igraph(
    G: "igraph.Graph",
    pagerank: dict[str, float] | None,
    top_k: int,
) -> AnalysisResult:
    """igraph implementation of graph analysis.

    Betweenness centrality is skipped for igraph (no approximate sampler)
    to avoid O(N*E) cost on large graphs.
    """
    result = AnalysisResult()

    if G.vcount() == 0:
        return result

    names = G.vs["name"]
    pr = pagerank or dict(zip(names, G.pagerank(directed=True, niter=200)))
    degrees = G.degree(mode='all')

    scored = []
    for i in range(G.vcount()):
        nid = names[i]
        d = degrees[i]
        p = pr.get(nid, 0)
        attrs = G.vs[i].attributes()
        scored.append({
            "id": nid,
            "label": attrs.get("label", nid),
            "kind": attrs.get("kind", ""),
            "degree": d,
            "pagerank": round(p, 6),
            "score": d * p,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    result.god_nodes = scored[:top_k]

    _find_surprising_connections_igraph(G, result, top_k)
    result.quality_metrics = _compute_quality_igraph(G)

    return result


def _find_surprising_connections_nx(
    G: nx.DiGraph, result: AnalysisResult, top_k: int
) -> None:
    """Find cross-file edges with low confidence (nx)."""
    for u, v, data in G.edges(data=True):
        u_file = G.nodes[u].get("file_path", "")
        v_file = G.nodes[v].get("file_path", "")
        if u_file and v_file and u_file != v_file:
            conf = data.get("confidence", "EXTRACTED")
            if conf in ("INFERRED", "AMBIGUOUS"):
                result.surprising_connections.append({
                    "source": G.nodes[u].get("label", u),
                    "target": G.nodes[v].get("label", v),
                    "relation": data.get("relation", ""),
                    "confidence": conf,
                    "source_file": u_file,
                    "target_file": v_file,
                })
    result.surprising_connections = result.surprising_connections[: top_k * 2]


def _find_surprising_connections_igraph(
    G: "igraph.Graph", result: AnalysisResult, top_k: int
) -> None:
    """Find cross-file edges with low confidence (igraph)."""
    names = G.vs["name"]
    for e in G.es:
        src_attrs = G.vs[e.source].attributes()
        tgt_attrs = G.vs[e.target].attributes()
        u_file = src_attrs.get("file_path", "")
        v_file = tgt_attrs.get("file_path", "")
        if u_file and v_file and u_file != v_file:
            conf = e.attributes().get("confidence", "EXTRACTED")
            if conf in ("INFERRED", "AMBIGUOUS"):
                result.surprising_connections.append({
                    "source": src_attrs.get("label", names[e.source]),
                    "target": tgt_attrs.get("label", names[e.target]),
                    "relation": e.attributes().get("relation", ""),
                    "confidence": conf,
                    "source_file": u_file,
                    "target_file": v_file,
                })
    result.surprising_connections = result.surprising_connections[: top_k * 2]


def _compute_quality_nx(G: nx.DiGraph) -> dict:
    """Compute graph quality metrics (nx)."""
    total_edges = G.number_of_edges()
    if total_edges == 0:
        return {"coverage": 0, "density": 0}

    conf_counts = {"EXTRACTED": 0, "INFERRED": 0, "AMBIGUOUS": 0}
    for _, _, data in G.edges(data=True):
        c = data.get("confidence", "EXTRACTED")
        if c in conf_counts:
            conf_counts[c] += 1

    isolated = len([n for n in G if G.degree(n) == 0])

    return {
        "nodes": G.number_of_nodes(),
        "edges": total_edges,
        "density": round(nx.density(G), 6),
        "isolated_nodes": isolated,
        "extracted_ratio": round(
            conf_counts["EXTRACTED"] / max(total_edges, 1), 4
        ),
        "inferred_ratio": round(
            conf_counts["INFERRED"] / max(total_edges, 1), 4
        ),
        "ambiguous_ratio": round(
            conf_counts["AMBIGUOUS"] / max(total_edges, 1), 4
        ),
        "weakly_connected_components": nx.number_weakly_connected_components(G),
    }


def _compute_quality_igraph(G: "igraph.Graph") -> dict:
    """Compute graph quality metrics (igraph)."""
    total_edges = G.ecount()
    if total_edges == 0:
        return {"coverage": 0, "density": 0}

    conf_counts = {"EXTRACTED": 0, "INFERRED": 0, "AMBIGUOUS": 0}
    for e in G.es:
        c = e.attributes().get("confidence", "EXTRACTED")
        if c in conf_counts:
            conf_counts[c] += 1

    n = G.vcount()
    e = total_edges
    density = (2.0 * e) / max(n * (n - 1), 1)
    isolated = sum(1 for v in G.vs if G.degree(v) == 0)
    wcc = len(G.components(mode="weak"))

    return {
        "nodes": n,
        "edges": e,
        "density": round(density, 6),
        "isolated_nodes": isolated,
        "extracted_ratio": round(
            conf_counts["EXTRACTED"] / max(e, 1), 4
        ),
        "inferred_ratio": round(
            conf_counts["INFERRED"] / max(e, 1), 4
        ),
        "ambiguous_ratio": round(
            conf_counts["AMBIGUOUS"] / max(e, 1), 4
        ),
        "weakly_connected_components": wcc,
    }
