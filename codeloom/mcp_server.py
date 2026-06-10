"""codeloom MCP Server — exposes code graph tools to AI agents.

Provides 16 tools over the Model Context Protocol (MCP):
- search: 5-signal HybridRAG (vector + keyword + graph + community + RRF)
- search_keyword: FTS5 keyword-only search (fast, for known names)
- search_vector: Vector-only semantic search
- node: Get detailed node information
- context: 360-degree symbol view (refs, community, edges, source)
- impact: Blast radius — find all downstream dependents
- dependencies: Upstream dependency analysis
- stats: Graph statistics overview
- communities: List or search communities
- list_repos: Discover available code graphs and staleness
- detect_changes: Map unstaged git changes to affected nodes
- rename: Find all locations for safe multi-file rename
- explain_flow: Trace execution path through call chains
- export_subgraph: Export focused subgraph as D3.js JSON
- build: Trigger incremental graph rebuild
- watch: Watch files for changes and rebuild automatically

Usage:
    codeloom mcp
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import traceback
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from codeloom.cli._helpers import suppress_library_logs

suppress_library_logs()

logger = logging.getLogger(__name__)


def _safe_tool(func):
    """Decorator: wrap any MCP tool to catch exceptions and return
    a helpful error string instead of crashing."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            return str(e)
        except BaseException as e:
            if isinstance(e, (SystemExit, KeyboardInterrupt)):
                raise
            logger.error(
                "Tool %s failed: %s\n%s",
                func.__name__,
                e,
                traceback.format_exc(),
            )
            return (
                f"Error in {func.__name__}: {e}. "
                f"Run 'codeloom doctor' for diagnostics or "
                f"'codeloom build .' to rebuild the graph."
            )

    return wrapper

mcp = FastMCP(
    "codeloom",
    instructions=(
        "You are an expert software engineer with access to a high-fidelity "
        "code graph. \n\n"
        "GUIDELINES:\n"
        "1. **Always search before grepping.** Use 'search' as your primary "
        "discovery tool. It uses 5-signal HybridRAG which is far more "
        "accurate than text-only search.\n"
        "2. **Use 'search_keyword' for fast, exact-name lookups.** When you "
        "know the symbol name, this returns results instantly.\n"
        "3. **Use 'search_vector' for semantic matching.** When you need "
        "conceptually similar code (not exact names), this is the signal.\n"
        "4. **Analyze impact before editing.** If you are about to modify a "
        "function or class, use 'impact' to see what might break.\n"
        "5. **Use 'context' for a 360-degree view** of any symbol — all "
        "references, community membership, and relationships.\n"
        "6. **Use 'detect_changes' after edits.** It maps git-diff'd files "
        "to affected graph nodes so you know what to re-check.\n"
        "7. **Drill down.** Don't stop at the first search results. Use "
        "'node' to explore connections and 'dependencies' to understand "
        "the sub-system.\n"
        "8. **Stay current.** Run 'build' after you make significant code "
        "changes to refresh your mental model."
    ),
)

# ---------------------------------------------------------------------------
# Lazy-loaded shared state
# ---------------------------------------------------------------------------
_store = None
_graph = None
_db_path: str | None = None
_reload_lock = threading.Lock()


def _get_db_path(source_dir: str | None = None) -> str:
    """Resolve the code graph database path.

    Priority:
    1. CODELOOM_DB environment variable
    2. Walk up from cwd looking for .codeloom/knowledge.db
    3. Walk up from source_dir (if provided) as fallback
    4. Default to cwd/.codeloom/knowledge.db
    """
    global _db_path
    if _db_path:
        return _db_path
    env_path = os.environ.get("CODELOOM_DB")
    if env_path and Path(env_path).exists():
        _db_path = env_path
        return _db_path

    def _walk_from(start: Path) -> str | None:
        for parent in [start, *start.parents]:
            candidate = parent / ".codeloom" / "knowledge.db"
            if candidate.exists():
                return str(candidate)
        return None

    cwd = Path.cwd()
    found = _walk_from(cwd)
    if found:
        _db_path = found
        return _db_path

    if source_dir:
        found = _walk_from(Path(source_dir).resolve())
        if found:
            _db_path = found
            return _db_path

    _db_path = str(cwd / ".codeloom" / "knowledge.db")
    return _db_path


def _store_path() -> Path:
    return Path(_get_db_path()).parent.parent


def _reload():
    """Force reload after a build."""
    global _store, _graph
    _store = None
    _graph = None
    return _load()


def _load():
    """Lazy-load store and graph."""
    global _store, _graph
    if _store is not None and _graph is not None:
        return _store, _graph
    with _reload_lock:
        if _store is not None and _graph is not None:
            return _store, _graph
        from codeloom.storage.store import KnowledgeStore

        db = _get_db_path()
        if not Path(db).exists():
            parent_list = [Path.cwd(), *list(Path.cwd().parents)[:3]]
            cwd_parents = "/".join(p.name for p in parent_list)
            raise FileNotFoundError(
                f"Code graph not found at {db}. "
                f"Run 'codeloom build <dir>' first. "
                f"Searched from cwd ({Path.cwd()}) "
                f"and parents ({cwd_parents})."
                f"Tip: set CODELOOM_DB env var to point to "
                f"your knowledge.db."
            )
        _store = KnowledgeStore(db)
        _graph = _store.load_graph()
        n, e = _graph.number_of_nodes(), _graph.number_of_edges()
        logger.info("Loaded graph: %d nodes, %d edges", n, e)
    return _store, _graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_node(node_id: str, G) -> list[str]:
    """Resolve a node ID with fuzzy matching.

    Tries exact match first, then partial match on label, then
    partial match on full ID (file path). Label matches take
    priority so a function named 'run' beats a coincidental
    'run' substring in /home/runner/... paths.
    Returns list of matching node IDs (empty if none found).
    """
    if node_id in G:
        return [node_id]
    q = node_id.lower()
    label_matches = [
        n for n in G.nodes
        if q in G.nodes[n].get("label", "").lower()
    ]
    id_matches = [
        n for n in G.nodes
        if q in n.lower()
    ]
    return label_matches + [n for n in id_matches if n not in label_matches]


def _node_label(G, node_id: str) -> str:
    return G.nodes[node_id].get("label", node_id)


def _read_file_snippet(
    file_path: str, start_line: int, context: int = 2
) -> str:
    """Read a few lines around start_line from a file."""
    try:
        p = Path(file_path)
        if not p.exists():
            return ""
        lines = p.read_text().splitlines()
        if not lines:
            return ""
        begin = max(0, start_line - 1 - context)
        end = min(len(lines), start_line - 1 + context + 1)
        return "\n".join(lines[begin:end])
    except Exception:
        return ""


def _run_git(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stdout."""
    try:
        return subprocess.check_output(
            ["git"] + args, cwd=cwd, stderr=subprocess.DEVNULL, text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


# ---------------------------------------------------------------------------
# MCP Tools — Search
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def search(
    query: str,
    top_k: int = 30,
    fast: bool = False,
    kind: str | None = None,
    file_pattern: str | None = None,
    include_tests: bool = False,
    snippets: bool = True,
    explain: bool = False,
) -> str:
    """Search the code graph using full 5-signal HybridRAG.

    This is the PRIMARY search tool. It fuses vector, keyword, graph,
    and community signals into a unified ranking with subgraph edges.

    Args:
        query: What to search for. Be specific (e.g. "JWT token validation").
        top_k: Number of results (default 30).
        fast: Use text model only for lower latency (default False).
        kind: Filter by symbol kind: function, class, method, interface,
              enum, struct, trait, section.
        file_pattern: Filter by file path glob (e.g. "src/auth/*").
        include_tests: Give test files equal ranking weight (default False).
        snippets: Show source snippets for top results (default True).
    """
    store, G = _load()
    from codeloom.query.hybrid import hybrid_search

    graph = hybrid_search(
        query,
        store,
        G,
        top_k=top_k,
        fast=fast,
        kind=kind,
        file_pattern=file_pattern,
        penalise_tests=not include_tests,
        snippet_count=3 if snippets else 0,
    )
    source_dir = str(_store_path()) + "/"
    return graph.to_text(source_dir=source_dir, explain=explain)


@mcp.tool()
@_safe_tool
def search_keyword(query: str, top_k: int = 20) -> str:
    """Fast keyword-only search using FTS5 (BM25 ranking).

    Use this when you know the exact symbol name or when you need
    instant results without vector embedding overhead.
    Does NOT return subgraph edges — use 'search' for that.

    Args:
        query: Space-separated search terms.
        top_k: Number of results (default 20).
    """
    store, G = _load()
    terms = [t.strip() for t in query.split() if t.strip()]
    if not terms:
        return "No search terms provided."

    results = store.keyword_search(terms, top_k=top_k)
    if not results:
        return f"No keyword matches for '{query}'."

    lines = [f"## Keyword Search: '{query}' ({len(results)} results)\n"]
    for r in results:
        label = r.get("label", r.get("node_id", "?"))
        kind = r.get("kind", "?")
        fpath = r.get("file_path", "?")
        bm25 = r.get("bm25_score", 0)
        lines.append(f"- **{label}** ({kind}) in `{fpath}` (score: {bm25:.2f})")

    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def search_vector(query: str, top_k: int = 20, fast: bool = False) -> str:
    """Vector-only semantic search (no keyword, no graph signals).

    Use this when you need conceptually similar code regardless of
    naming. Good for finding alternative implementations or related
    patterns. Does NOT return subgraph edges.

    Args:
        query: Natural language description of the code you want.
        top_k: Number of results (default 20).
        fast: Use text model only (faster, but code-specific signals
              may be weaker).
    """
    store, G = _load()
    from codeloom.query.embeddings import embed_query_dual

    vectors = embed_query_dual(query)
    mode_label = "fast (text)" if fast else "dual (code + text)"

    results: dict[str, float] = {}
    if not fast and "code" in vectors:
        code_hits = store.vector_search(
            vectors["code"], top_k=top_k, model_type="code"
        )
        for nid, score in code_hits:
            results[nid] = max(results.get(nid, 0), score)
    if "text" in vectors:
        text_hits = store.vector_search(
            vectors["text"], top_k=top_k, model_type="text"
        )
        for nid, score in text_hits:
            results[nid] = max(results.get(nid, 0), score)

    sorted_results = sorted(results.items(), key=lambda x: -x[1])[:top_k]
    if not sorted_results:
        return f"No vector matches for '{query}'."

    lines = [
        f"## Vector Search: '{query}' (mode: {mode_label})",
        f"({len(sorted_results)} results)\n",
    ]
    for nid, score in sorted_results:
        data = G.nodes.get(nid, {})
        label = data.get("label", nid)
        kind = data.get("kind", "?")
        fpath = data.get("file_path", "?")
        lines.append(
            f"- **{label}** ({kind}) in `{fpath}` (similarity: {score:.4f})"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tools — Analysis
# ---------------------------------------------------------------------------


def _risk_score(G, source_id: str, target_id: str) -> str:
    """Heuristic risk level for a dependency relationship."""
    s_fp = G.nodes[source_id].get("file_path", "")
    t_fp = G.nodes[target_id].get("file_path", "")
    # Within-file edges are lower risk regardless of relation
    if s_fp and t_fp and s_fp == t_fp and s_fp != "":
        return "low"
    edge_data = G.get_edge_data(source_id, target_id)
    if edge_data:
        rel = edge_data.get("relation", "")
        if rel in ("inherits", "implements"):
            return "high"
        if rel == "calls":
            return "high"
        if rel in ("references", "imports"):
            return "medium"
    return "medium"


def _group_by_file(
    G, node_ids: list[str], target_fp: str
) -> dict[str, list[tuple[str, str, str]]]:
    """Group nodes into same-file and cross-file."""
    groups: dict[str, list[tuple[str, str, str]]] = {
        "same file": [], "cross-file": []
    }
    for nid in node_ids:
        fp = G.nodes[nid].get("file_path", "?")
        label = _node_label(G, nid)
        kind = G.nodes[nid].get("kind", "?")
        entry = (label, kind, fp)
        if fp == target_fp:
            groups["same file"].append(entry)
        else:
            groups["cross-file"].append(entry)
    return groups


@mcp.tool()
@_safe_tool
def impact(
    node_id: str,
    max_depth: int = 3,
    kind: str | None = None,
    format: str = "text",
) -> str:
    """Analyze the 'blast radius' of a change.

    Returns all symbols that transitively depend on the given node.
    Use this BEFORE modifying code to avoid breaking downstream consumers.

    Args:
        node_id: Full or partial node ID to analyze.
        max_depth: How many levels of dependents to trace (default 3).
        kind: Filter by edge relation (e.g. 'calls', 'imports', 'references',
              'inherits'). Defaults to all relations.
        format: Output format ('text' or 'json').
    """
    import json as json_mod

    import networkx as nx

    store, G = _load()
    matches = _resolve_node(node_id, G)
    if not matches:
        return (
            json_mod.dumps({"error": f"No node found matching '{node_id}'."})
            if format == "json"
            else f"No node found matching '{node_id}'."
        )
    target = matches[0]

    target_fp = G.nodes[target].get("file_path", "")
    rgraph = G.reverse(copy=False)
    label = _node_label(G, target)

    levels: list[dict] = []
    for d in range(1, max_depth + 1):
        layer = nx.descendants_at_distance(rgraph, target, d)
        if not layer:
            break
        if kind:
            filtered = set()
            for nid in layer:
                edge_data = rgraph.get_edge_data(target, nid)
                if edge_data and edge_data.get("relation") == kind:
                    filtered.add(nid)
            if not filtered:
                continue
            layer = filtered

        level_nodes: list[dict] = []
        for nid in sorted(layer):
            data = G.nodes[nid]
            snippet = ""
            fp = data.get("file_path", "")
            sl = data.get("start_line")
            if fp and sl:
                snippet = _read_file_snippet(fp, sl, context=1)
            risk = _risk_score(G, nid, target)
            level_nodes.append({
                "id": nid,
                "label": data.get("label", nid),
                "kind": data.get("kind", "?"),
                "file_path": fp,
                "start_line": sl,
                "risk": risk,
                "snippet": snippet,
            })
        levels.append({"depth": d, "nodes": level_nodes})

    if format == "json":
        return json_mod.dumps(
            {
                "target": target,
                "target_label": label,
                "levels": levels,
                "total_depth": len(levels),
            },
            indent=2,
        )

    lines = [f"## Impact Analysis (Blast Radius) for '{label}'\n"]
    for level in levels:
        d = level["depth"]
        groups = _group_by_file(
            G, [n["id"] for n in level["nodes"]], target_fp
        )
        same = groups["same file"]
        cross = groups["cross-file"]
        lines.append(
            f"### Level {d} Dependents "
            f"({len(level['nodes'])} total, "
            f"{len(same)} same file, {len(cross)} cross-file)"
        )
        if cross:
            lines.append("**Cross-file:**")
            for lbl, knd, fp in cross[:10]:
                lines.append(f"- {lbl} ({knd}) in `{fp}`")
            if len(cross) > 10:
                lines.append(f"  ... and {len(cross) - 10} more")
        if same:
            lines.append("**Same file:**")
            for lbl, knd, _ in same[:5]:
                lines.append(f"- {lbl} ({knd})")
            if len(same) > 5:
                lines.append(f"  ... and {len(same) - 5} more")
        lines.append("")

    if len(lines) == 1:
        return f"No downstream dependents found for '{node_id}'."
    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def dependencies(
    node_id: str,
    max_depth: int = 3,
    kind: str | None = None,
    format: str = "text",
) -> str:
    """Analyze the upstream dependencies of a symbol.

    Returns all symbols that the given node transitively depends on.
    Use this to understand what context a piece of code requires.

    Args:
        node_id: Full or partial node ID to analyze.
        max_depth: How many levels to trace (default 3).
        kind: Filter by edge relation (e.g. 'calls', 'imports', 'inherits').
              Defaults to all relations.
        format: Output format ('text' or 'json').
    """
    import json as json_mod

    import networkx as nx

    store, G = _load()
    matches = _resolve_node(node_id, G)
    if not matches:
        return (
            json_mod.dumps({"error": f"No node found matching '{node_id}'."})
            if format == "json"
            else f"No node found matching '{node_id}'."
        )
    target = matches[0]

    target_fp = G.nodes[target].get("file_path", "")
    label = _node_label(G, target)

    levels: list[dict] = []
    for d in range(1, max_depth + 1):
        layer = nx.descendants_at_distance(G, target, d)
        if not layer:
            break
        if kind:
            filtered = set()
            for nid in layer:
                edge_data = G.get_edge_data(target, nid)
                if edge_data and edge_data.get("relation") == kind:
                    filtered.add(nid)
            if not filtered:
                continue
            layer = filtered

        level_nodes: list[dict] = []
        for nid in sorted(layer):
            data = G.nodes[nid]
            snippet = ""
            fp = data.get("file_path", "")
            sl = data.get("start_line")
            if fp and sl:
                snippet = _read_file_snippet(fp, sl, context=1)
            risk = _risk_score(G, target, nid)
            level_nodes.append({
                "id": nid,
                "label": data.get("label", nid),
                "kind": data.get("kind", "?"),
                "file_path": fp,
                "start_line": sl,
                "risk": risk,
                "snippet": snippet,
            })
        levels.append({"depth": d, "nodes": level_nodes})

    if format == "json":
        return json_mod.dumps(
            {
                "target": target,
                "target_label": label,
                "levels": levels,
                "total_depth": len(levels),
            },
            indent=2,
        )

    lines = [f"## Dependency Analysis for '{label}'\n"]
    for level in levels:
        d = level["depth"]
        groups = _group_by_file(
            G, [n["id"] for n in level["nodes"]], target_fp
        )
        same = groups["same file"]
        cross = groups["cross-file"]
        lines.append(
            f"### Level {d} Dependencies "
            f"({len(level['nodes'])} total, "
            f"{len(same)} same file, {len(cross)} cross-file)"
        )
        if cross:
            lines.append("**Cross-file:**")
            for lbl, knd, fp in cross[:10]:
                lines.append(f"- {lbl} ({knd}) in `{fp}`")
            if len(cross) > 10:
                lines.append(f"  ... and {len(cross) - 10} more")
        if same:
            lines.append("**Same file:**")
            for lbl, knd, _ in same[:5]:
                lines.append(f"- {lbl} ({knd})")
            if len(same) > 5:
                lines.append(f"  ... and {len(same) - 5} more")
        lines.append("")

    if len(lines) == 1:
        return f"No dependencies found for '{node_id}'."
    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def context(node_id: str) -> str:
    """Get a 360-degree view of a symbol.

    Returns all metadata, relationships (incoming and outgoing),
    community membership, and source context for the given symbol.
    Use this when you need the full picture before making changes.

    Args:
        node_id: Full or partial node ID.
    """
    store, G = _load()
    matches = _resolve_node(node_id, G)
    if not matches:
        return f"No node found matching '{node_id}'."
    target = matches[0]

    data = G.nodes[target]
    lines = [
        f"## Context: {_node_label(G, target)}",
        f"- **ID**: {target}",
        f"- **Kind**: {data.get('kind', '?')}",
        f"- **File**: {data.get('file_path', '?')}",
    ]
    if data.get("signature"):
        lines.append(f"- **Signature**: `{data['signature']}`")
    if data.get("docstring"):
        lines.append(f"- **Docstring**: {data['docstring'][:400]}")
    if data.get("start_line"):
        sl = data.get("start_line")
        el = data.get("end_line", "?")
        lines.append(f"- **Lines**: {sl}-{el}")
    pr = data.get("pagerank", 0)
    lines.append(f"- **PageRank**: {pr:.4f}")

    # Source snippet
    fpath = data.get("file_path", "")
    sl = data.get("start_line")
    if fpath and sl:
        snippet = _read_file_snippet(fpath, sl)
        if snippet:
            lines.append(f"\n### Source Context (around line {sl})")
            lines.append(f"```\n{snippet}\n```")

    # Community memberships
    comm_ids = data.get("community_ids", [])
    if comm_ids:
        lines.append(f"\n### Communities ({len(comm_ids)})")
        for cid in comm_ids[:5]:
            try:
                row = store.conn.execute(
                    "SELECT summary FROM communities WHERE id = ?", (cid,)
                ).fetchone()
                summary = row["summary"][:120] if row else ""
            except Exception:
                summary = ""
            tag = (
                f"- Community {cid}: {summary}"
                if summary else f"- Community {cid}"
            )
            lines.append(tag)

    # Outgoing edges
    out_edges = list(G.out_edges(target, data=True))
    if out_edges:
        lines.append(f"\n### Outgoing ({len(out_edges)} edges)")
        for _, tgt, edata in out_edges[:15]:
            tlabel = _node_label(G, tgt)
            rel = edata.get("relation", "?")
            lines.append(f"  → {tlabel} ({rel})")

    # Incoming edges
    in_edges = list(G.in_edges(target, data=True))
    if in_edges:
        lines.append(f"\n### Incoming ({len(in_edges)} edges)")
        for src, _, edata in in_edges[:15]:
            slabel = _node_label(G, src)
            rel = edata.get("relation", "?")
            lines.append(f"  ← {slabel} ({rel})")

    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def node(node_id: str) -> str:
    """Get detailed information about a specific node in the code graph.

    Args:
        node_id: Full or partial node ID. Partial matches are supported
                 (e.g. "KnowledgeStore" will match the full node ID).
    """
    store, G = _load()
    matches = _resolve_node(node_id, G)
    if not matches:
        return f"No node found matching '{node_id}'."

    lines = []
    for nid in matches[:5]:
        data = G.nodes[nid]
        lines.append(f"## {_node_label(G, nid)}")
        lines.append(f"- **ID**: {nid}")
        lines.append(f"- **Kind**: {data.get('kind', '?')}")
        lines.append(f"- **File**: {data.get('file_path', '?')}")
        if data.get("signature"):
            lines.append(f"- **Signature**: `{data['signature']}`")
        if data.get("docstring"):
            lines.append(f"- **Docstring**: {data['docstring'][:300]}")
        if data.get("start_line"):
            sl = data.get("start_line")
            el = data.get("end_line", "?")
            lines.append(f"- **Lines**: {sl}-{el}")
        lines.append(f"- **PageRank**: {data.get('pagerank', 0):.4f}")

        out_edges = list(G.out_edges(nid, data=True))[:10]
        in_edges = list(G.in_edges(nid, data=True))[:10]
        if out_edges:
            lines.append("- **Outgoing edges**:")
            for _, target, edata in out_edges:
                tlabel = _node_label(G, target)
                rel = edata.get("relation", "?")
                w = edata.get("weight", 0)
                lines.append(f"  - → {tlabel} ({rel}, w={w:.2f})")
        if in_edges:
            lines.append("- **Incoming edges**:")
            for source, _, edata in in_edges:
                slabel = _node_label(G, source)
                rel = edata.get("relation", "?")
                w = edata.get("weight", 0)
                lines.append(f"  - ← {slabel} ({rel}, w={w:.2f})")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tools — Graph Statistics & Inspection
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def stats() -> str:
    """Get code graph statistics.

    Returns node/edge counts, kind distribution, community count,
    and high-fanout nodes. Quick overview of graph health.
    """
    store, G = _load()
    from codeloom.core.analyze import analyze as analyze_graph

    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()

    kinds: dict[str, int] = {}
    for _, data in G.nodes(data=True):
        k = data.get("kind", "unknown")
        kinds[k] = kinds.get(k, 0) + 1

    community_ids: set[int] = set()
    for _, data in G.nodes(data=True):
        for cid in data.get("community_ids", []):
            community_ids.add(cid)

    analysis = analyze_graph(G, top_k=10)
    god_nodes = analysis.god_nodes

    lines = [
        "## Code Graph Statistics\n",
        f"- **Nodes**: {n_nodes}",
        f"- **Edges**: {n_edges}",
        f"- **Communities**: {len(community_ids)}",
        f"- **Density**: {n_edges / max(n_nodes * (n_nodes - 1), 1):.6f}",
        "",
        "### Node Kinds",
    ]
    for kind, count in sorted(kinds.items(), key=lambda x: -x[1]):
        lines.append(f"- {kind}: {count}")

    if god_nodes:
        lines.append("\n### God Nodes (high fan-out)")
        for gn in god_nodes[:10]:
            lines.append(
                f"- {gn['label']} ({gn['kind']}): {gn['degree']} connections"
            )

    lines.append(f"\n- **Database**: {_get_db_path()}")
    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def list_repos() -> str:
    """List all available code graphs and their basic stats.

    Use this first to discover which code graphs are available
    and whether they are up to date.
    """
    db_path = _get_db_path()
    db = Path(db_path)
    if not db.exists():
        return "No code graph found. Run 'codeloom build <dir>' first."

    try:
        store, G = _load()
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()
        source = _store_path()

        # Check git status
        dirty = _run_git(["status", "--porcelain"], cwd=str(source))
        n_dirty = len(dirty.splitlines()) if dirty else 0
        staleness = (
            "unchanged" if not dirty else f"{n_dirty} modified files"
        )

        lines = [
            "## Code Graph\n",
            f"- **Source**: {source}",
            f"- **Database**: {db_path}",
            f"- **Nodes**: {n_nodes}",
            f"- **Edges**: {n_edges}",
            f"- **Status**: {staleness}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading graph: {e}"


@mcp.tool()
@_safe_tool
def communities(search_query: str = "", level: int = -1) -> str:
    """Browse community clusters.

    Communities group related code entities by topic. The 'search' tool
    already factors community signals into ranking, so only use this
    when you need to explore the community structure itself.

    Args:
        search_query: Filter communities by keyword (leave empty to list all).
        level: Hierarchy level (-1 for all levels).
    """
    store, G = _load()

    if search_query:
        terms = search_query.lower().split()
        results = store.community_search(terms, top_k=10)
        if not results:
            return f"No communities found matching '{search_query}'."

        lines = [f"## Communities matching '{search_query}'\n"]
        for comm in results:
            cid = comm.get("community_id", comm.get("id", "?"))
            lvl = comm.get("level", "?")
            lines.append(f"### Community {cid} (level {lvl})")
            lines.append(f"- **Score**: {comm['score']:.2f}")
            lines.append(f"- **Nodes**: {len(comm.get('node_ids', []))}")
            if comm.get("summary"):
                lines.append(f"- **Summary**: {comm['summary'][:200]}")
            if comm.get("node_ids"):
                sample = comm["node_ids"][:5]
                labels = [_node_label(G, n) for n in sample]
                lines.append(f"- **Sample members**: {', '.join(labels)}")
            lines.append("")
        return "\n".join(lines)

    query = "SELECT id, level, summary FROM communities"
    params: list = []
    if level >= 0:
        query += " WHERE level = ?"
        params.append(level)
    query += " ORDER BY level, id"
    rows = store.conn.execute(query, params).fetchall()
    if not rows:
        return "No communities found."

    lines = [f"## All Communities ({len(rows)} total)\n"]
    for row in rows[:20]:
        cnt_row = store.conn.execute(
            "SELECT COUNT(*) as c FROM community_members"
            " WHERE community_id = ?",
            (row["id"],),
        )
        cnt = cnt_row.fetchone()["c"]
        summary = (row["summary"] or "No summary")[:100]
        lines.append(
            f"- **Community {row['id']}** (level {row['level']}): "
            f"{cnt} nodes — {summary}"
        )
    if len(rows) > 20:
        remaining = len(rows) - 20
        lines.append(f"\n... and {remaining} more. Use search_query to filter.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tools — Code Change & Refactoring
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def detect_changes() -> str:
    """Detect which graph nodes are affected by unstaged git changes.

    Runs git diff and intersects changed files with graph nodes.
    Use this after making edits to understand the impact surface.
    """
    store, G = _load()
    source = _store_path()

    changed_files = _run_git(
        ["diff", "--name-only", "HEAD"], cwd=str(source)
    ).splitlines()
    untracked = _run_git(
        ["ls-files", "--others", "--exclude-standard"], cwd=str(source)
    ).splitlines()
    all_changed = list({f for f in changed_files + untracked if f})

    if not all_changed:
        return "No changes detected."

    # Find graph nodes that live in changed files
    changed_nodes: list[tuple[str, str, str, int | None]] = []
    for nid in G.nodes:
        data = G.nodes[nid]
        fp = data.get("file_path", "")
        if any(fp.endswith(changed) for changed in all_changed):
            label = data.get("label", nid)
            kind = data.get("kind", "?")
            sl = data.get("start_line")
            changed_nodes.append((fp, label, kind, sl))

    lines = [
        f"## Change Detection ({len(all_changed)} changed files, "
        f"{len(changed_nodes)} affected nodes)\n"
    ]
    for fp, label, kind, sl in sorted(changed_nodes, key=lambda x: x[0]):
        loc = f":{sl}" if sl else ""
        lines.append(f"- **{label}** ({kind}) in `{fp}{loc}`")

    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def rename(old_name: str, new_name: str) -> str:
    """Find all locations where a symbol is used across the codebase.

    Returns a list of file:line locations plus graph relationships
    for safe multi-file renaming. Does NOT make changes — it tells
    you what to edit.

    Args:
        old_name: Current symbol name to find.
        new_name: Intended new name (for reference in results).
    """
    store, G = _load()
    matches = _resolve_node(old_name, G)

    if not matches:
        return f"No graph nodes found matching '{old_name}'."

    lines = [
        f"## Rename: '{old_name}' → '{new_name}'\n",
        f"({len(matches)} matching nodes)\n",
    ]

    for nid in matches[:20]:
        data = G.nodes[nid]
        fp = data.get("file_path", "?")
        sl = data.get("start_line")
        loc = f":{sl}" if sl else ""
        kind = data.get("kind", "?")
        lines.append(f"### {_node_label(G, nid)} ({kind})")
        lines.append(f"- **ID**: {nid}")
        lines.append(f"- **File**: `{fp}{loc}`")
        if data.get("signature"):
            lines.append(f"- **Signature**: `{data['signature']}`")

        # Find references (incoming edges)
        refs = list(G.in_edges(nid, data=True))
        if refs:
            lines.append(f"- **Referenced by** ({len(refs)}):")
            for src, _, edata in refs[:10]:
                sdata = G.nodes[src]
                sfile = sdata.get("file_path", "?")
                ssl = sdata.get("start_line")
                sloc = f":{ssl}" if ssl else ""
                lines.append(f"  - {_node_label(G, src)} in `{sfile}{sloc}`")
        lines.append("")

    if len(matches) > 20:
        lines.append(f"... and {len(matches) - 20} more matches.")
    lines.append("Use these file:line locations to perform the rename.")
    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def explain_flow(entry_node_id: str, max_depth: int = 5) -> str:
    """Trace an execution flow through call chains starting from a node.

    Follows 'calls' edges BFS-style and produces an indented
    call tree. Useful for understanding how code is executed.

    Args:
        entry_node_id: Starting node (function or method name).
        max_depth: How deep to trace (default 5).
    """
    store, G = _load()
    matches = _resolve_node(entry_node_id, G)
    if not matches:
        return f"No node found matching '{entry_node_id}'."

    target = matches[0]
    lines = [f"## Execution Flow: {_node_label(G, target)}\n"]

    visited: set[str] = set()
    current_level = [(target, 0)]

    while current_level:
        nid, depth = current_level.pop(0)
        if nid in visited or depth > max_depth:
            continue
        visited.add(nid)

        indent = "  " * depth
        data = G.nodes[nid]
        kind = data.get("kind", "?")
        fp = data.get("file_path", "?")
        sl = data.get("start_line", "?")
        lines.append(f"{indent}▶ {_node_label(G, nid)} ({kind}) — `{fp}:{sl}`")

        if depth < max_depth:
            # Follow outgoing calls edges
            out = [
                (t, edata)
                for _, t, edata in G.out_edges(nid, data=True)
                if edata.get("relation") == "calls" and t not in visited
            ]
            # Also follow references suggests flow
            out += [
                (t, edata)
                for _, t, edata in G.out_edges(nid, data=True)
                if edata.get("relation") in ("imports", "inherits")
                and t not in visited
            ]
            for tgt, _ in out[:5]:
                current_level.append((tgt, depth + 1))

    if len(lines) == 1:
        return f"No flow found from '{entry_node_id}'."
    return "\n".join(lines)


@mcp.tool()
@_safe_tool
def export_subgraph(
    node_id: str, depth: int = 2, max_nodes: int = 50
) -> str:
    """Export a focused subgraph around a symbol as D3.js JSON.

    Useful for passing graph context to other tools or for
    visualization. Returns JSON with nodes and links arrays.

    Args:
        node_id: Central node to export around.
        depth: How many hops of neighbors to include (default 2).
        max_nodes: Maximum nodes in the subgraph (default 50).
    """
    import json

    store, G = _load()
    matches = _resolve_node(node_id, G)
    if not matches:
        return json.dumps({"error": f"No node found matching '{node_id}'."})

    target = matches[0]

    # BFS from target to collect neighbors
    sub_nodes: set[str] = {target}
    frontier = {target}
    for _ in range(depth):
        if len(sub_nodes) >= max_nodes:
            break
        next_frontier: set[str] = set()
        for n in frontier:
            neighbors = set(G.successors(n)) | set(G.predecessors(n))
            for nb in neighbors:
                if nb not in sub_nodes:
                    sub_nodes.add(nb)
                    if len(sub_nodes) >= max_nodes:
                        break
                    next_frontier.add(nb)
            if len(sub_nodes) >= max_nodes:
                break
        frontier = next_frontier

    subgraph = G.subgraph(sub_nodes).copy()

    # Build D3 format
    kinds = sorted(
        {d.get("kind", "unknown") for _, d in subgraph.nodes(data=True)}
    )
    kind_to_group = {k: i for i, k in enumerate(kinds)}

    d3_nodes = []
    for n in subgraph.nodes:
        data = subgraph.nodes[n]
        pr = data.get("pagerank", 0.0)
        d3_nodes.append(
            {
                "id": n,
                "label": data.get("label", n),
                "kind": data.get("kind", "unknown"),
                "group": kind_to_group.get(data.get("kind", "unknown"), 0),
                "size": 4 + 16 * pr if pr > 0 else 4,
                "file_path": data.get("file_path", ""),
                "pagerank": round(pr, 4),
            }
        )

    d3_links = []
    for u, v, edata in subgraph.edges(data=True):
        d3_links.append(
            {
                "source": u,
                "target": v,
                "relation": edata.get("relation", ""),
                "value": edata.get("weight", 1.0),
            }
        )

    result = {
        "seed": target,
        "nodes": d3_nodes,
        "links": d3_links,
        "metadata": {
            "node_count": len(d3_nodes),
            "link_count": len(d3_links),
        },
    }
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# MCP Tools — Build
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def build(
    directory: str = ".",
    incremental: bool = True,
    max_workers: int | None = None,
) -> str:
    """Build or rebuild the code graph from source code.

    Args:
        directory: Directory to analyze (default: current directory).
        incremental: If true, only re-process changed files (default: true).
        max_workers: Number of parallel extraction workers
            (default: os.cpu_count()).
    """
    from codeloom.core.pipeline import run_pipeline
    from codeloom.storage.store import KnowledgeStore

    target = Path(directory).resolve()
    if not target.is_dir():
        return f"Error: '{directory}' is not a valid directory."

    existing_db = _get_db_path(source_dir=str(target))
    db_path = Path(existing_db)
    if db_path.exists():
        try:
            existing_store = KnowledgeStore(str(db_path))
            G = existing_store.load_graph()
            n_nodes = G.number_of_nodes()
            n_edges = G.number_of_edges()
            existing_store.close()
            if n_nodes > 0:
                if not incremental:
                    return (
                        f"## Database Already Exists\n\n"
                        f"- **Location**: {existing_db}\n"
                        f"- **Nodes**: {n_nodes}\n"
                        f"- **Edges**: {n_edges}\n"
                        f"- **Source**: {target}\n\n"
                        f"Use `build . --incremental` to update, or set "
                        f"`incremental=true` (the default)."
                    )
        except Exception:
            pass

    result = run_pipeline(
        str(target), incremental=incremental, max_workers=max_workers
    )

    nodes = getattr(result, "node_count", 0) or (
        result.graph.number_of_nodes()
        if getattr(result, "graph", None)
        else 0
    )
    edges = getattr(result, "edge_count", 0) or (
        result.graph.number_of_edges()
        if getattr(result, "graph", None)
        else 0
    )
    dr = getattr(result, "detect_result", None)
    files = len(dr.files) if dr else 0

    if hasattr(result, "release_memory"):
        result.release_memory()

    _reload()

    db_info = _get_db_path(source_dir=str(target))
    return (
        f"## Build Complete\n\n"
        f"- **Directory**: {target}\n"
        f"- **Mode**: {'incremental' if incremental else 'full'}\n"
        f"- **Nodes**: {nodes}\n"
        f"- **Edges**: {edges}\n"
        f"- **Files detected**: {files}\n"
        f"- **Database**: {db_info}\n"
    )


class _WatchRebuildHandler:
    """File system event handler for auto-rebuild on file changes.

    Responds to file modification events by triggering an incremental
    graph rebuild. Skips directories and unrecognised file extensions.
    Cooldown prevents rapid re-triggering during bulk writes.
    """

    def __init__(self, source_path: str, output: str | None = None):
        self.source_path = source_path
        self.output = output
        self.last_rebuild = 0.0
        self.cooldown = 1.0

    def dispatch(self, event) -> None:
        """Watchdog-compatible dispatch — routes events to on_modified."""
        self.on_modified(event)

    def on_modified(self, event) -> None:
        """Called by watchdog on file modification events."""
        if event.is_directory:
            return
        from codeloom.core.detect import EXT_TO_LANG

        if Path(event.src_path).suffix.lower() not in EXT_TO_LANG:
            return
        import time

        now = time.time()
        if now - self.last_rebuild < self.cooldown:
            return
        self.last_rebuild = now
        logger.info(
            "Watch: change detected in %s — rebuilding...",
            Path(event.src_path).name,
        )
        try:
            from codeloom.core.pipeline import run_pipeline

            run_pipeline(
                str(self.source_path),
                output_dir=self.output,
                incremental=True,
            )
            _reload()
            logger.info("Watch: rebuild complete")
        except Exception as e:
            logger.error("Watch: rebuild failed: %s", e)


@mcp.tool()
@_safe_tool
def watch(
    directory: str = ".",
    output: str | None = None,
) -> str:
    """Watch for file changes and update the code graph in real-time.

    Starts a background file system watcher that triggers incremental
    builds on file save events. The graph is automatically reloaded
    after each change so subsequent tool calls see fresh data.

    Uses the watchdog library. Requires 'watchdog' to be installed
    (pip install watchdog). If unavailable, returns an error message
    instructing the user to install it.

    Args:
        directory: Directory to watch (default: current directory).
        output: Optional output directory for the database.
    """
    from pathlib import Path

    source_path = Path(directory).resolve()
    if not source_path.is_dir():
        return f"Error: '{directory}' is not a valid directory."

    try:
        from watchdog.observers import Observer
    except ImportError:
        return (
            "watchdog library not found. "
            "Install it with: pip install watchdog"
        )

    handler = _WatchRebuildHandler(str(source_path), output=output)
    observer = Observer()
    observer.schedule(handler, str(source_path), recursive=True)
    observer.start()

    # Stop the observer when the MCP server shuts down
    import atexit
    atexit.register(observer.stop)

    return (
        f"## Watching '{source_path}' for changes\n\n"
        f"File changes will trigger incremental graph rebuilds "
        f"and auto-reload the graph for subsequent tool calls.\n"
        f"- **Directory**: {source_path}\n"
        f"- **Database**: {_get_db_path()}\n"
        f"- **Status**: Active\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(warmup: bool = True):
    """Run the MCP server with stdio transport.

    Args:
        warmup: If True, preload embedding models synchronously
            before starting the server so the first search call is fast.
            Models are cached in ~/.codeloom/models/ after first download.
    """
    if warmup:
        try:
            from codeloom.query.embeddings import (
                CODE_MODEL,
                TEXT_MODEL,
                _get_model,
            )

            _get_model(CODE_MODEL)
            _get_model(TEXT_MODEL)
            logger.info("Embedding models preloaded")
        except Exception:
            logger.warning(
                "Model warmup failed. Models will load on first search call."
            )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
