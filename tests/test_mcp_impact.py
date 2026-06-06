"""Tests for MCP impact/dependencies tools and shared helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def diamond_graph():
    """Diamond topology: a -> b -> d, a -> c -> d."""
    G = nx.DiGraph()
    G.add_node("a", label="A", kind="function", file_path="mod/a.py")
    G.add_node("b", label="B", kind="function", file_path="mod/b.py")
    G.add_node("c", label="C", kind="function", file_path="mod/c.py")
    G.add_node("d", label="D", kind="function", file_path="mod/d.py")
    G.add_edge("a", "b", relation="calls")
    G.add_edge("a", "c", relation="calls")
    G.add_edge("b", "d", relation="calls")
    G.add_edge("c", "d", relation="calls")
    return G


@pytest.fixture
def cycle_graph():
    """Contains a cycle: a -> b -> c -> a."""
    G = nx.DiGraph()
    G.add_node("a", label="A", kind="function", file_path="mod/a.py")
    G.add_node("b", label="B", kind="function", file_path="mod/b.py")
    G.add_node("c", label="C", kind="function", file_path="mod/c.py")
    G.add_edge("a", "b", relation="calls")
    G.add_edge("b", "c", relation="calls")
    G.add_edge("c", "a", relation="calls")
    return G


@pytest.fixture
def disconnected_graph():
    """Two disconnected subgraphs."""
    G = nx.DiGraph()
    G.add_node("a", label="A", kind="function", file_path="mod/a.py")
    G.add_node("b", label="B", kind="function", file_path="mod/b.py")
    G.add_node("x", label="X", kind="function", file_path="other/x.py")
    G.add_node("y", label="Y", kind="function", file_path="other/y.py")
    G.add_edge("a", "b", relation="calls")
    G.add_edge("x", "y", relation="calls")
    return G


# ---------------------------------------------------------------------------
# _resolve_node
# ---------------------------------------------------------------------------


@pytest.fixture
def resolve_graph():
    G = nx.DiGraph()
    G.add_node(
        "path/to/file.py::validate_token",
        label="validate_token",
        kind="function",
        file_path="path/to/file.py",
    )
    G.add_node(
        "path/to/file.py::authenticate",
        label="authenticate",
        kind="function",
        file_path="path/to/file.py",
    )
    return G


def test_resolve_node_exact_match(resolve_graph):
    from codeloom.mcp_server import _resolve_node

    result = _resolve_node("path/to/file.py::validate_token", resolve_graph)
    assert result == ["path/to/file.py::validate_token"]


def test_resolve_node_partial_label(resolve_graph):
    from codeloom.mcp_server import _resolve_node

    result = _resolve_node("validate", resolve_graph)
    assert "path/to/file.py::validate_token" in result


def test_resolve_node_case_insensitive(resolve_graph):
    from codeloom.mcp_server import _resolve_node

    result = _resolve_node("VALIDATE", resolve_graph)
    assert "path/to/file.py::validate_token" in result


def test_resolve_node_no_match(resolve_graph):
    from codeloom.mcp_server import _resolve_node

    result = _resolve_node("nonexistent_symbol_xyz", resolve_graph)
    assert result == []


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------


def test_risk_score_calls_is_high():
    from codeloom.mcp_server import _risk_score

    G = nx.DiGraph()
    G.add_node("a", file_path="a.py")
    G.add_node("b", file_path="b.py")
    G.add_edge("a", "b", relation="calls")
    assert _risk_score(G, "a", "b") == "high"


def test_risk_score_inherits_is_high():
    from codeloom.mcp_server import _risk_score

    G = nx.DiGraph()
    G.add_node("a", file_path="a.py")
    G.add_node("b", file_path="b.py")
    G.add_edge("a", "b", relation="inherits")
    assert _risk_score(G, "a", "b") == "high"


def test_risk_score_imports_is_medium():
    from codeloom.mcp_server import _risk_score

    G = nx.DiGraph()
    G.add_node("a", file_path="a.py")
    G.add_node("b", file_path="b.py")
    G.add_edge("a", "b", relation="imports")
    assert _risk_score(G, "a", "b") == "medium"


def test_risk_score_same_file_is_low():
    from codeloom.mcp_server import _risk_score

    G = nx.DiGraph()
    G.add_node("a", file_path="mod/same.py")
    G.add_node("b", file_path="mod/same.py")
    G.add_edge("a", "b", relation="calls")
    assert _risk_score(G, "a", "b") == "low"


def test_risk_score_no_edge_is_medium():
    from codeloom.mcp_server import _risk_score

    G = nx.DiGraph()
    G.add_node("a", file_path="a.py")
    G.add_node("b", file_path="b.py")
    G.add_edge("a", "b", relation="unknown_rel")
    assert _risk_score(G, "a", "b") == "medium"


# ---------------------------------------------------------------------------
# _group_by_file
# ---------------------------------------------------------------------------


def test_group_by_file_same_and_cross():
    from codeloom.mcp_server import _group_by_file

    G = nx.DiGraph()
    G.add_node("n1", label="F1", kind="function", file_path="mod/target.py")
    G.add_node("n2", label="F2", kind="function", file_path="mod/target.py")
    G.add_node("n3", label="F3", kind="function", file_path="mod/other.py")

    groups = _group_by_file(G, ["n1", "n2", "n3"], "mod/target.py")
    assert len(groups["same file"]) == 2
    assert len(groups["cross-file"]) == 1


# ---------------------------------------------------------------------------
# impact — diamond graph
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store_and_graph(diamond_graph):
    """Mock _load() to return a store and a diamond graph."""
    with (
        patch("codeloom.mcp_server._load") as mock_load,
        patch("codeloom.mcp_server._get_db_path", return_value="/fake/db"),
    ):
        store = MagicMock()
        mock_load.return_value = (store, diamond_graph)
        yield


def test_impact_diamond_depth_1(mock_store_and_graph):
    """Impact at depth 1 from 'd' should return b and c (direct callers)."""
    from codeloom.mcp_server import impact

    result = impact("d", max_depth=1)
    assert "- B" in result
    assert "- C" in result
    assert "- A" not in result


def test_impact_diamond_depth_2(mock_store_and_graph):
    """Impact at depth 2 from 'd' should also include a (transitive caller)."""
    from codeloom.mcp_server import impact

    result = impact("d", max_depth=2)
    assert "- B" in result
    assert "- C" in result
    assert "- A" in result


def test_impact_no_match():
    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("x", label="X", kind="function", file_path="x.py")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = impact("nonexistent")
        assert "No node found" in result


def test_impact_empty_graph():
    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = impact("a")
        assert "No node found" in result


# ---------------------------------------------------------------------------
# impact — kind filter
# ---------------------------------------------------------------------------


def test_impact_kind_filter():
    """Only 'imports' edges should appear when kind='imports'."""
    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("a", label="A", kind="module", file_path="a.py")
        G.add_node("b", label="B", kind="module", file_path="b.py")
        G.add_node("c", label="C", kind="function", file_path="c.py")
        G.add_edge("b", "a", relation="calls")  # b calls a
        G.add_edge("c", "a", relation="imports")  # c imports a
        store = MagicMock()
        mock_load.return_value = (store, G)

        result_text = impact("a", kind="imports")
        assert "- B" not in result_text
        assert "- C" in result_text


# ---------------------------------------------------------------------------
# impact — JSON format
# ---------------------------------------------------------------------------


def test_impact_json_format(mock_store_and_graph):
    """JSON output should be valid JSON with expected structure."""
    import json

    from codeloom.mcp_server import impact

    result = impact("a", format="json")
    data = json.loads(result)
    assert "target" in data
    assert "levels" in data
    assert data["target_label"] == "A"


# ---------------------------------------------------------------------------
# dependencies — diamond graph
# ---------------------------------------------------------------------------


def test_dependencies_diamond():
    """Dependencies of 'a' should show b and c at depth 1 (what a calls)."""
    from codeloom.mcp_server import dependencies

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("a", label="A", kind="function", file_path="a.py")
        G.add_node("b", label="B", kind="function", file_path="b.py")
        G.add_node("c", label="C", kind="function", file_path="c.py")
        G.add_node("d", label="D", kind="function", file_path="d.py")
        G.add_edge("a", "b", relation="calls")
        G.add_edge("a", "c", relation="calls")
        G.add_edge("b", "d", relation="calls")
        G.add_edge("c", "d", relation="calls")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = dependencies("a", max_depth=1)
        assert "- B" in result
        assert "- C" in result
        assert "- D" not in result


def test_dependencies_no_match():
    from codeloom.mcp_server import dependencies

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("x", label="X", kind="function", file_path="x.py")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = dependencies("nonexistent")
        assert "No node found" in result


# ---------------------------------------------------------------------------
# defensive wrapping — all tools return strings on error
# ---------------------------------------------------------------------------


def test_all_tools_defensive():
    """Every MCP tool should return a string when _load raises."""
    from codeloom.mcp_server import (
        build,
        communities,
        context,
        dependencies,
        detect_changes,
        explain_flow,
        export_subgraph,
        impact,
        list_repos,
        node,
        rename,
        search,
        search_keyword,
        search_vector,
        stats,
    )

    with patch("codeloom.mcp_server._load") as mock_load:
        mock_load.side_effect = FileNotFoundError(
            "No code graph found"
        )

        tools = [
            (search, ("test_query",)),
            (search_keyword, ("test",)),
            (search_vector, ("test",)),
            (impact, ("a",)),
            (dependencies, ("a",)),
            (context, ("a",)),
            (node, ("a",)),
            (stats, ()),
            (list_repos, ()),
            (communities, ()),
            (detect_changes, ()),
            (rename, ("old", "new")),
            (explain_flow, ("a",)),
            (export_subgraph, ("a",)),
            (build, ()),
        ]

        for tool, args in tools:
            result = tool(*args)
            assert isinstance(result, str), (
                f"{tool.__name__} did not return a string, got {type(result)}"
            )
            assert len(result) > 0, (
                f"{tool.__name__} returned empty string"
            )


# ---------------------------------------------------------------------------
# Edge case: kind filter with no matching edges
# ---------------------------------------------------------------------------


def test_impact_kind_filter_no_matches():
    """When no edges match the kind filter, return no dependents."""
    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("a", label="A", kind="function", file_path="a.py")
        G.add_node("b", label="B", kind="function", file_path="b.py")
        G.add_edge("b", "a", relation="calls")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = impact("a", kind="imports")
        assert "No downstream dependents" in result


def test_impact_kind_filter_no_match_dependencies():
    """dependencies with kind filter that matches nothing."""
    from codeloom.mcp_server import dependencies

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("a", label="A", kind="function", file_path="a.py")
        G.add_node("b", label="B", kind="function", file_path="b.py")
        G.add_edge("a", "b", relation="calls")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = dependencies("a", kind="inherits")
        assert "No dependencies found" in result


# ---------------------------------------------------------------------------
# Edge case: impact JSON format with error
# ---------------------------------------------------------------------------


def test_impact_json_no_match():
    import json

    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("x", label="X", kind="function", file_path="x.py")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = impact("nonexistent", format="json")
        data = json.loads(result)
        assert "error" in data
        assert "nonexistent" in data["error"]


def test_impact_json_no_match_dependencies():
    import json

    from codeloom.mcp_server import dependencies

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("x", label="X", kind="function", file_path="x.py")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = dependencies("nonexistent", format="json")
        data = json.loads(result)
        assert "error" in data
        assert "nonexistent" in data["error"]


# ---------------------------------------------------------------------------
# Edge case: depth less than any dependents
# ---------------------------------------------------------------------------


def test_impact_depth_too_shallow():
    """Setting max_depth=0 should return no results."""
    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("a", label="A", kind="function", file_path="a.py")
        G.add_node("b", label="B", kind="function", file_path="b.py")
        G.add_edge("b", "a", relation="calls")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = impact("a", max_depth=0)
        assert "No downstream dependents" in result


# ---------------------------------------------------------------------------
# Edge case: impact on node with no outgoing edges in reverse
# ---------------------------------------------------------------------------


def test_impact_no_dependents():
    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("leaf", label="Leaf", kind="function", file_path="leaf.py")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = impact("leaf", max_depth=3)
        assert "No downstream dependents" in result


def test_dependencies_no_upstream():
    from codeloom.mcp_server import dependencies

    with patch("codeloom.mcp_server._load") as mock_load:
        G = nx.DiGraph()
        G.add_node("root", label="Root", kind="function", file_path="root.py")
        store = MagicMock()
        mock_load.return_value = (store, G)

        result = dependencies("root", max_depth=3)
        assert "No dependencies found" in result
