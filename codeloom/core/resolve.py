"""Cross-file reference resolution using spatial indexing.

Resolves edges that reference file:line positions to their containing
definition nodes (function, class, method, etc.). Uses a position-based
spatial index: for each file, definitions are sorted by start_line and
binary-searched to find which definition contains a given line.

This works language-agnostically across all 17+ supported languages
without needing per-language alias resolution logic.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field

import networkx as nx

logger = logging.getLogger(__name__)

# Kinds that form "definitions" — things that can be referenced
DEFINITION_KINDS = frozenset({
    "function", "class", "method", "interface", "enum", "struct",
    "trait", "constructor", "property", "type_alias", "variable",
    "module", "section",
})

# Edge relations that can be resolved
RESOLVABLE_RELATIONS = frozenset({
    "calls", "imports", "inherits", "references", "defines", "contains",
})


@dataclass
class Span:
    """A definition span within a file."""
    node_id: str
    start_line: int
    end_line: int
    kind: str
    label: str


@dataclass
class ResolutionResult:
    """Result of running reference resolution."""
    resolved: int = 0
    already_resolved: int = 0
    unresolved: int = 0
    skipped_relation: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_line(node_id: str) -> int | None:
    """Extract line number from a node ID (file:line format).

    Returns None if the node ID has no line component.
    """
    try:
        _, line_str = node_id.rsplit(":", 1)
        return int(line_str)
    except (ValueError, IndexError):
        return None


def _extract_file_path(node_id: str) -> str:
    """Extract the file path from a node ID by removing the line suffix."""
    idx = node_id.rfind(":")
    if idx == -1:
        return node_id
    # Check if the part after : is a number (line) or part of the path (Windows C:)
    line_part = node_id[idx + 1:]
    if line_part.isdigit():
        return node_id[:idx]
    return node_id


def build_spatial_index(
    G: nx.DiGraph,
    definition_kinds: frozenset[str] = DEFINITION_KINDS,
) -> dict[str, list[Span]]:
    """Build a spatial index mapping file_path -> sorted list of definition spans.

    Each file's spans are sorted by start_line for binary search lookup.

    Args:
        G: The code graph.
        definition_kinds: Node kinds considered definitions.

    Returns:
        Dict mapping file_path to sorted list of Span objects.
    """
    index: dict[str, list[Span]] = {}

    for node_id, data in G.nodes(data=True):
        kind = data.get("kind", "")
        if kind not in definition_kinds:
            continue

        file_path = data.get("file_path", "")
        if not file_path:
            continue

        start_line = data.get("start_line", 0)
        end_line = data.get("end_line", 0)

        span = Span(
            node_id=node_id,
            start_line=start_line,
            end_line=end_line,
            kind=kind,
            label=data.get("label", node_id),
        )
        index.setdefault(file_path, []).append(span)

    # Sort each file's spans by start_line, then end_line
    for file_path in index:
        index[file_path].sort(key=lambda s: (s.start_line, s.end_line))

    return index


def _find_containing_definition(
    spans: list[Span],
    line: int,
) -> Span | None:
    """Binary-search for the definition containing a given line.

    Uses bisect to find the rightmost definition with start_line <= line,
    then checks if the line falls within its span.

    Args:
        spans: Sorted list of Span objects for a file.
        line: Target line number (1-based).

    Returns:
        The containing Span, or None if no definition contains this line.
    """
    if not spans:
        return None

    # Binary search for rightmost span with start_line <= line
    idx = bisect.bisect_right(spans, line, key=lambda s: s.start_line) - 1
    if idx < 0:
        return None

    candidate = spans[idx]
    # If end_line is 0, treat as single-line span
    if candidate.end_line == 0:
        candidate_end = candidate.start_line
    else:
        candidate_end = candidate.end_line

    if candidate.start_line <= line <= candidate_end:
        return candidate

    return None


def resolve_graph(
    G: nx.DiGraph,
    definition_kinds: frozenset[str] = DEFINITION_KINDS,
    resolvable_relations: frozenset[str] = RESOLVABLE_RELATIONS,
) -> ResolutionResult:
    """Resolve all resolvable edges in the graph to their containing definitions.

    For each edge whose target refers to a file:line position, looks up
    which definition contains that line and updates the edge target to
    point to the actual definition node.

    The graph is modified in place. Edges already pointing to definition
    nodes are left unchanged (counted as already_resolved).

    Args:
        G: The code graph (modified in place).
        definition_kinds: Node kinds considered definitions.
        resolvable_relations: Edge relations to attempt resolution for.

    Returns:
        ResolutionResult with counts of resolved/unresolved/error edges.
    """
    result = ResolutionResult()

    if G.number_of_nodes() == 0:
        return result

    # Build a quick lookup: node_id -> file_path for existing definitions
    existing_definitions: dict[str, str] = {}
    definitions_by_file: dict[str, list[tuple[int, str]]] = {}
    for node_id, data in G.nodes(data=True):
        kind = data.get("kind", "")
        if kind in definition_kinds and data.get("file_path", ""):
            existing_definitions[node_id] = data["file_path"]
            file_path = data["file_path"]
            start_line = data.get("start_line", 0)
            definitions_by_file.setdefault(file_path, []).append((start_line, node_id))

    # Sort definitions within each file by start_line
    for file_path in definitions_by_file:
        definitions_by_file[file_path].sort(key=lambda x: x[0])

    # Build spatial index for fine-grained lookups
    spatial = build_spatial_index(G, definition_kinds)

    # Process each edge
    edges_to_process = list(G.edges(data=True))
    edges_added = 0
    edges_removed = 0

    for source, target, data in edges_to_process:
        relation = data.get("relation", "")

        if relation not in resolvable_relations:
            result.skipped_relation += 1
            continue

        # Check if target is already a definition node
        if target in existing_definitions:
            result.already_resolved += 1
            continue

        # Parse target as file:line
        target_line = _parse_line(target)
        if target_line is None:
            result.unresolved += 1
            continue

        target_file = _extract_file_path(target)

        # Look up in spatial index
        file_spans = spatial.get(target_file)
        if not file_spans:
            result.unresolved += 1
            continue

        containing = _find_containing_definition(file_spans, target_line)
        if containing is None:
            result.unresolved += 1
            continue

        # Edge already points to this definition
        if containing.node_id == target:
            result.already_resolved += 1
            continue

        # Update the edge to point to the actual definition
        # We add a new edge and mark the old one for removal
        G.add_edge(source, containing.node_id, **data)
        edges_added += 1
        G.remove_edge(source, target)
        edges_removed += 1
        result.resolved += 1

    if edges_added > 0:
        logger.info(
            "Resolved %d edges to definition targets "
            "(%d already resolved, %d still unresolved, %d skipped relation)",
            result.resolved, result.already_resolved,
            result.unresolved, result.skipped_relation,
        )

    return result
