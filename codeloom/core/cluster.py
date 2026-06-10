"""Hierarchical community detection using Leiden algorithm.

Implements multi-resolution clustering to build a community hierarchy tree,
producing coarse-to-fine community layers for richer structural analysis.
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
class Community:
    id: int
    level: int  # 0=coarsest, higher=finer
    resolution: float
    node_ids: list[str] = field(default_factory=list)
    summary: str = ""
    parent_id: int | None = None
    children_ids: list[int] = field(default_factory=list)


@dataclass
class ClusterResult:
    communities: dict[int, Community] = field(default_factory=dict)
    # node -> [community_ids at each level]
    node_to_community: dict[str, list[int]] = field(default_factory=dict)
    hierarchy_levels: int = 0


def _detect_hub_nodes(
    G: nx.DiGraph,
    percentile: float = 97,
    min_threshold: int = 10,
) -> set[str]:
    """Detect hub nodes with abnormally high in-degree.

    Hub nodes (builtins like len/max, minified JS vars, common utilities)
    act as false bridges in community detection, merging unrelated clusters.

    Uses adaptive thresholding: P97 of in-degree distribution with a
    minimum floor of 10 to avoid over-filtering in small graphs.

    Args:
        G: The code graph (NetworkX or igraph).

    Returns:
        Set of node IDs to exclude from clustering.
    """
    import numpy as np

    if hasattr(G, 'vs'):
        n = G.vcount()
        if n == 0:
            return set()
        in_degrees = G.degree(mode='in')
        threshold = max(
            float(np.percentile(in_degrees, percentile)), min_threshold
        )
        names = G.vs["name"]
        return {names[i] for i in range(n) if in_degrees[i] > threshold}
    else:
        if len(G) == 0:
            return set()
        in_degrees = [G.in_degree(n) for n in G.nodes()]
        threshold = max(
            float(np.percentile(in_degrees, percentile)), min_threshold
        )
        return {n for n in G.nodes() if G.in_degree(n) > threshold}


def hierarchical_cluster(
    G: nx.DiGraph,
    resolutions: list[float] | None = None,
    min_community_size: int = 2,
) -> ClusterResult:
    """Run multi-resolution Leiden clustering to build a hierarchy.

    Accepts both NetworkX DiGraph and igraph Graph. When given an igraph
    graph, skips the internal nx→igraph conversion, saving both memory
    and CPU.

    Args:
        G: The code graph (NetworkX or igraph).
        resolutions: List of resolution parameters (low=coarse, high=fine).
        min_community_size: Minimum nodes per community.

    Returns:
        ClusterResult with hierarchical community structure.
    """
    if resolutions is None:
        resolutions = [0.25, 0.5, 1.0, 2.0]

    if hasattr(G, 'vs'):
        return _hierarchical_cluster_igraph(
            G, resolutions, min_community_size
        )
    return _hierarchical_cluster_nx(G, resolutions, min_community_size)


def _hierarchical_cluster_nx(
    G: nx.DiGraph,
    resolutions: list[float],
    min_community_size: int,
) -> ClusterResult:
    """NetworkX implementation of hierarchical clustering."""
    if len(G) < min_community_size:
        return ClusterResult()

    result = ClusterResult(hierarchy_levels=len(resolutions))

    hub_nodes = _detect_hub_nodes(G)
    if hub_nodes:
        logger.info(
            "Excluding %d hub nodes from clustering (in-degree outliers)",
            len(hub_nodes),
        )
    G_filtered = G.copy()
    G_filtered.remove_nodes_from(hub_nodes)
    G_undirected = G_filtered.to_undirected()

    try:
        import igraph as ig

        node_list = list(G_undirected.nodes())
        node_index = {n: i for i, n in enumerate(node_list)}
        edges = [
            (node_index[u], node_index[v])
            for u, v in G_undirected.edges()
            if u in node_index and v in node_index
        ]
        ig_graph = ig.Graph(n=len(node_list), edges=edges, directed=False)

        return _run_leiden(
            ig_graph, node_list, resolutions, min_community_size, result
        )
    except ImportError:
        return _louvain_fallback(
            G_undirected, min_community_size, result
        )


def _hierarchical_cluster_igraph(
    G: "igraph.Graph",
    resolutions: list[float],
    min_community_size: int,
) -> ClusterResult:
    """igraph-native implementation of hierarchical clustering.

    Skips the nx→igraph conversion entirely, avoiding the memory cost
    of duplicating the graph in two formats.
    """
    if G.vcount() < min_community_size:
        return ClusterResult()

    result = ClusterResult(hierarchy_levels=len(resolutions))

    hub_nodes = _detect_hub_nodes(G)
    if hub_nodes:
        logger.info(
            "Excluding %d hub nodes from clustering (in-degree outliers)",
            len(hub_nodes),
        )
    # Remove hub nodes: build filtered undirected graph
    all_names = G.vs["name"]
    keep_mask = [n not in hub_nodes for n in all_names]
    keep_indices = [i for i, keep in enumerate(keep_mask) if keep]
    keep_names = [all_names[i] for i in keep_indices]

    # Build undirected edge list for kept nodes
    name_to_idx = {n: i for i, n in enumerate(keep_names)}
    edges_undirected = set()
    for e in G.es:
        src_name = all_names[e.source]
        tgt_name = all_names[e.target]
        if src_name in hub_nodes or tgt_name in hub_nodes:
            continue
        i, j = name_to_idx[src_name], name_to_idx[tgt_name]
        if i < j:
            edges_undirected.add((i, j))
        else:
            edges_undirected.add((j, i))

    node_list = keep_names
    if not node_list:
        return result

    import igraph as ig

    ig_graph = ig.Graph(
        n=len(node_list),
        edges=list(edges_undirected),
        directed=False,
    )

    try:
        return _run_leiden(
            ig_graph, node_list, resolutions, min_community_size, result
        )
    except ImportError:
        # No fallback for igraph path — louvain requires nx
        logger.debug(
            "leidenalg not available; clustering skipped"
        )
        return result


def _run_leiden(
    ig_graph: "igraph.Graph",
    node_list: list[str],
    resolutions: list[float],
    min_community_size: int,
    result: ClusterResult,
) -> ClusterResult:
    """Run multi-resolution Leiden on an already-constructed igraph."""
    import leidenalg

    community_counter = len(result.communities)
    prev_level_map: dict[str, int] = {}

    for level_idx, res in enumerate(resolutions):
        partition = leidenalg.find_partition(
            ig_graph,
            leidenalg.RBConfigurationVertexPartition,
            resolution_parameter=res,
        )

        level_communities: dict[int, list[str]] = {}
        for node_idx, comm_idx in enumerate(partition.membership):
            node_id = node_list[node_idx]
            if comm_idx not in level_communities:
                level_communities[comm_idx] = []
            level_communities[comm_idx].append(node_id)

        for local_id, members in level_communities.items():
            if len(members) < min_community_size:
                continue

            comm = Community(
                id=community_counter,
                level=level_idx,
                resolution=res,
                node_ids=members,
            )

            if prev_level_map:
                parent_candidates: dict[int, int] = {}
                for node_id in members:
                    if node_id in prev_level_map:
                        pid = prev_level_map[node_id]
                        parent_candidates[pid] = (
                            parent_candidates.get(pid, 0) + 1
                        )
                if parent_candidates:
                    comm.parent_id = max(
                        parent_candidates, key=parent_candidates.get
                    )
                    result.communities[comm.parent_id].children_ids.append(
                        community_counter
                    )

            result.communities[community_counter] = comm

            for node_id in members:
                if node_id not in result.node_to_community:
                    result.node_to_community[node_id] = []
                result.node_to_community[node_id].append(community_counter)

            community_counter += 1

        prev_level_map = {}
        for comm_id, comm in result.communities.items():
            if comm.level == level_idx:
                for node_id in comm.node_ids:
                    prev_level_map[node_id] = comm_id

    return result


def _louvain_fallback(
    G_undirected: nx.Graph,
    min_community_size: int,
    result: ClusterResult,
) -> ClusterResult:
    """NetworkX Louvain fallback when leidenalg is unavailable."""
    try:
        from networkx.algorithms.community import louvain_communities

        communities = louvain_communities(G_undirected, resolution=1.0)
        community_counter = 0
        for members_set in communities:
            members = list(members_set)
            if len(members) < min_community_size:
                continue
            comm = Community(
                id=community_counter,
                level=0,
                resolution=1.0,
                node_ids=members,
            )
            result.communities[community_counter] = comm
            for node_id in members:
                result.node_to_community[node_id] = [community_counter]
            community_counter += 1
        result.hierarchy_levels = 1
    except Exception:
        logger.debug("Louvain fallback failed", exc_info=True)

    return result


def get_community_nodes(G: nx.DiGraph, community: Community) -> nx.DiGraph:
    """Extract subgraph for a specific community.

    Accepts both NetworkX and igraph graphs.
    """
    if hasattr(G, 'vs'):
        return G.subgraph(community.node_ids)
    return G.subgraph(community.node_ids).copy()


def community_label(
    G: nx.DiGraph, community: Community, max_labels: int = 5
) -> str:
    """Generate a descriptive label for a community based on its top nodes.

    Accepts both NetworkX and igraph graphs.
    """
    names = _collect_labels(G, community.node_ids, max_labels)
    return ", ".join(names)


def _collect_labels(
    graph, node_ids: list[str], max_labels: int
) -> list[str]:
    """Extract top labels from a graph node set (igraph or nx)."""
    if hasattr(graph, 'vs'):
        sub = graph.subgraph(node_ids)
        degrees = sub.degree()
        ranked = sorted(
            range(sub.vcount()), key=lambda i: degrees[i], reverse=True
        )[:max_labels]
        return [
            sub.vs[i].attributes().get("label", sub.vs[i]["name"])
            for i in ranked
        ]
    else:
        sub = graph.subgraph(node_ids)
        centrality = nx.degree_centrality(sub)
        top_nodes = sorted(centrality, key=centrality.get, reverse=True)[
            :max_labels
        ]
        return [graph.nodes[n].get("label", n) for n in top_nodes]


def summarize_communities(
    G: nx.DiGraph,
    cluster_result: ClusterResult,
    max_keywords: int = 10,
) -> ClusterResult:
    """Generate text summaries for each community for search indexing.

    Builds a keyword-rich summary from node labels, kinds, docstrings,
    and file paths. This enables community-level search without an LLM.

    Accepts both NetworkX and igraph graphs.

    Args:
        G: The code graph (NetworkX or igraph).
        cluster_result: Clustering output to enrich.
        max_keywords: Max keywords to extract per community.

    Returns:
        The same ClusterResult with summaries populated.
    """
    if hasattr(G, 'vs'):
        _summarize_igraph(G, cluster_result, max_keywords)
    else:
        _summarize_nx(G, cluster_result, max_keywords)
    return cluster_result


def _summarize_nx(
    G: nx.DiGraph,
    cluster_result: ClusterResult,
    max_keywords: int,
) -> None:
    """NetworkX implementation of summarize_communities."""
    for comm_id, comm in cluster_result.communities.items():
        if comm.summary:
            continue

        subgraph = G.subgraph(comm.node_ids)
        centrality = nx.degree_centrality(subgraph)
        top_nodes = sorted(centrality, key=centrality.get, reverse=True)

        labels = []
        kinds: dict[str, int] = {}
        files: set[str] = set()
        docstrings: list[str] = []

        for node_id in top_nodes[:20]:
            data = G.nodes.get(node_id, {})
            label = data.get("label", "")
            if label:
                labels.append(label)
            kind = data.get("kind", "")
            if kind:
                kinds[kind] = kinds.get(kind, 0) + 1
            fp = data.get("file_path", "")
            if fp:
                from pathlib import Path
                files.add(Path(fp).name)
            doc = data.get("docstring", "")
            if doc:
                docstrings.append(doc[:100])

        _build_summary(comm, labels, kinds, files, docstrings, max_keywords)


def _summarize_igraph(
    G: "igraph.Graph",
    cluster_result: ClusterResult,
    max_keywords: int,
) -> None:
    """igraph implementation of summarize_communities."""
    for comm_id, comm in cluster_result.communities.items():
        if comm.summary:
            continue

        sub = G.subgraph(comm.node_ids)
        degrees = sub.degree()
        ranked = sorted(
            range(sub.vcount()), key=lambda i: degrees[i], reverse=True
        )

        labels = []
        kinds: dict[str, int] = {}
        files: set[str] = set()
        docstrings: list[str] = []

        for idx in ranked[:20]:
            attrs = sub.vs[idx].attributes()
            label = attrs.get("label", "")
            if label:
                labels.append(label)
            kind = attrs.get("kind", "")
            if kind:
                kinds[kind] = kinds.get(kind, 0) + 1
            fp = attrs.get("file_path", "")
            if fp:
                from pathlib import Path
                files.add(Path(fp).name)
            doc = attrs.get("docstring", "")
            if doc:
                docstrings.append(doc[:100])

        _build_summary(comm, labels, kinds, files, docstrings, max_keywords)


def _build_summary(
    comm: Community,
    labels: list[str],
    kinds: dict[str, int],
    files: set[str],
    docstrings: list[str],
    max_keywords: int,
) -> None:
    """Build a community summary string from collected signals."""
    top_labels = labels[:max_keywords]
    kind_desc = ", ".join(
        f"{count} {kind}{'s' if count > 1 else ''}"
        for kind, count in sorted(kinds.items(), key=lambda x: -x[1])[:5]
    )
    file_list = ", ".join(sorted(files)[:5])

    parts = []
    if kind_desc:
        parts.append(f"Contains {kind_desc}.")
    if top_labels:
        parts.append(f"Key elements: {', '.join(top_labels)}.")
    if file_list:
        parts.append(f"Files: {file_list}.")
    if docstrings:
        parts.append(f"Context: {' | '.join(docstrings[:3])}")

    comm.summary = " ".join(parts)

    if not comm.summary:
        comm.summary = ", ".join(labels[:max_keywords])
