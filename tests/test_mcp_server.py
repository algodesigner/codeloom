"""Tests for the MCP server tools.

Verifies that all 15 MCP tools return well-formatted output and
handle edge cases gracefully. Uses mocked store/graph to avoid
requiring a real database.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

# Skip entire module if mcp is not installed (optional dependency)
pytest.importorskip("mcp", reason="mcp package not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_graph() -> nx.DiGraph:
    """Create a small test graph with realistic node attributes."""
    G = nx.DiGraph()
    G.add_node(
        "auth.py:1",
        label="AuthHandler",
        kind="class",
        file_path="auth.py",
        signature="class AuthHandler",
        docstring="Handles user authentication.",
        start_line=1,
        end_line=20,
        community_ids=[0],
    )
    G.add_node(
        "auth.py:5",
        label="login",
        kind="method",
        file_path="auth.py",
        signature="def login(self, username, password)",
        docstring="Authenticate a user.",
        start_line=5,
        end_line=8,
        community_ids=[0],
    )
    G.add_node(
        "server.py:10",
        label="handle_request",
        kind="function",
        file_path="server.py",
        signature="def handle_request(req)",
        docstring="Handle incoming HTTP request.",
        start_line=10,
        end_line=25,
        community_ids=[1],
    )
    # Edges
    G.add_edge(
        "auth.py:1",
        "auth.py:5",
        relation="has_method",
        weight=1.0,
    )
    G.add_edge(
        "server.py:10",
        "auth.py:1",
        relation="calls",
        weight=0.8,
    )
    return G


def _make_store(G: nx.DiGraph) -> MagicMock:
    """Create a mock KnowledgeStore."""
    store = MagicMock()
    store.conn = MagicMock()
    # community_search returns list of dicts
    store.community_search.return_value = [
        {
            "community_id": 0,
            "level": 0,
            "score": 0.95,
            "node_ids": ["auth.py:1", "auth.py:5"],
            "summary": "Authentication module with login handling.",
        }
    ]
    return store


@pytest.fixture()
def mock_load():
    """Patch _load to return test graph and store."""
    G = _make_graph()
    store = _make_store(G)
    with patch("codeloom.mcp_server._load", return_value=(store, G)):
        yield store, G


@pytest.fixture()
def mock_load_empty():
    """Patch _load to return empty graph."""
    G = nx.DiGraph()
    store = _make_store(G)
    with patch("codeloom.mcp_server._load", return_value=(store, G)):
        yield store, G


# ---------------------------------------------------------------------------
# Tests: search tool
# ---------------------------------------------------------------------------


class TestSearchTool:
    def test_search_returns_results(self, mock_load):
        from codeloom.mcp_server import search
        from codeloom.query.hybrid import SearchGraph, SearchResult

        mock_graph = SearchGraph(
            nodes=[
                SearchResult(
                    node_id="auth.py:1",
                    label="AuthHandler",
                    kind="class",
                    file_path="auth.py",
                    start_line=1,
                    end_line=20,
                    score=0.85,
                    source="seed",
                    signal_contributions={"vector": 0.4, "keyword": 0.15},
                ),
            ],
            edges=[],
        )
        with patch(
            "codeloom.query.hybrid.hybrid_search", return_value=mock_graph
        ):
            result = search("authentication")

        assert "auth.py:1" in result

    def test_search_no_results(self, mock_load):
        from codeloom.mcp_server import search
        from codeloom.query.hybrid import SearchGraph

        empty = SearchGraph(nodes=[], edges=[])
        with patch("codeloom.query.hybrid.hybrid_search", return_value=empty):
            result = search("nonexistent_query_xyz")

        assert result.startswith("seeds:")

    def test_search_fast_mode(self, mock_load):
        from codeloom.mcp_server import search
        from codeloom.query.hybrid import SearchGraph

        empty = SearchGraph(nodes=[], edges=[])
        with patch(
            "codeloom.query.hybrid.hybrid_search", return_value=empty
        ) as mock_hs:
            search("test query", fast=True)
            mock_hs.assert_called_once()
            _, kwargs = mock_hs.call_args
            assert kwargs.get("fast") is True

    def test_search_custom_top_k(self, mock_load):
        from codeloom.mcp_server import search
        from codeloom.query.hybrid import SearchGraph

        empty = SearchGraph(nodes=[], edges=[])
        with patch(
            "codeloom.query.hybrid.hybrid_search", return_value=empty
        ) as mock_hs:
            search("test", top_k=5)
            _, kwargs = mock_hs.call_args
            assert kwargs.get("top_k") == 5

    def test_search_result_without_end_line(self, mock_load):
        from codeloom.mcp_server import search
        from codeloom.query.hybrid import SearchGraph, SearchResult

        mock_graph = SearchGraph(
            nodes=[
                SearchResult(
                    node_id="test.py:10",
                    label="func",
                    kind="function",
                    file_path="test.py",
                    start_line=10,
                    end_line=10,
                    score=0.5,
                    source="seed",
                ),
            ],
            edges=[],
        )
        with patch(
            "codeloom.query.hybrid.hybrid_search", return_value=mock_graph
        ):
            result = search("func")

        assert "test.py:10" in result

    def test_search_result_no_line_numbers(self, mock_load):
        from codeloom.mcp_server import search
        from codeloom.query.hybrid import SearchGraph, SearchResult

        mock_graph = SearchGraph(
            nodes=[
                SearchResult(
                    node_id="README.md:0",
                    label="readme",
                    kind="document",
                    file_path="README.md",
                    start_line=0,
                    end_line=0,
                    score=0.3,
                    source="seed",
                ),
            ],
            edges=[],
        )
        with patch(
            "codeloom.query.hybrid.hybrid_search", return_value=mock_graph
        ):
            result = search("readme")

        assert "README.md:0" in result


# ---------------------------------------------------------------------------
# Tests: node tool
# ---------------------------------------------------------------------------


class TestNodeTool:
    def test_node_exact_match(self, mock_load):
        from codeloom.mcp_server import node

        result = node("auth.py:1")
        assert "AuthHandler" in result
        assert "class" in result
        assert "auth.py" in result
        assert "Handles user authentication" in result
        assert "login" in result  # outgoing edge label

    def test_node_partial_match(self, mock_load):
        from codeloom.mcp_server import node

        result = node("AuthHandler")
        assert "AuthHandler" in result

    def test_node_not_found(self, mock_load):
        from codeloom.mcp_server import node

        result = node("NonExistentNode12345")
        assert "No node found" in result

    def test_node_shows_edges(self, mock_load):
        from codeloom.mcp_server import node

        result = node("auth.py:1")
        assert "Outgoing edges" in result
        assert "has_method" in result
        assert "w=1.00" in result

    def test_node_shows_incoming_edges(self, mock_load):
        from codeloom.mcp_server import node

        result = node("auth.py:1")
        assert "Incoming edges" in result
        assert "calls" in result

    def test_node_case_insensitive_partial(self, mock_load):
        from codeloom.mcp_server import node

        result = node("authhandler")
        assert "AuthHandler" in result

    def test_node_shows_signature(self, mock_load):
        from codeloom.mcp_server import node

        result = node("auth.py:5")
        assert "def login" in result

    def test_node_shows_line_numbers(self, mock_load):
        from codeloom.mcp_server import node

        result = node("auth.py:5")
        assert "5" in result
        assert "8" in result


# ---------------------------------------------------------------------------
# Tests: stats tool
# ---------------------------------------------------------------------------


class TestStatsTool:
    def test_stats_basic(self, mock_load):
        from codeloom.mcp_server import stats

        with patch(
            "codeloom.core.analyze.analyze",
            return_value=SimpleNamespace(god_nodes=[]),
        ):
            result = stats()
        assert "3" in result  # 3 nodes
        assert "2" in result  # 2 edges
        assert "class" in result
        assert "method" in result
        assert "function" in result

    def test_stats_shows_communities(self, mock_load):
        from codeloom.mcp_server import stats

        with patch(
            "codeloom.core.analyze.analyze",
            return_value=SimpleNamespace(god_nodes=[]),
        ):
            result = stats()
        assert "Communities" in result

    def test_stats_shows_density(self, mock_load):
        from codeloom.mcp_server import stats

        with patch(
            "codeloom.core.analyze.analyze",
            return_value=SimpleNamespace(god_nodes=[]),
        ):
            result = stats()
        assert "Density" in result

    def test_stats_empty_graph(self, mock_load_empty):
        from codeloom.mcp_server import stats

        with patch(
            "codeloom.core.analyze.analyze",
            return_value=SimpleNamespace(god_nodes=[]),
        ):
            result = stats()
        assert "Nodes" in result
        assert "0" in result


# ---------------------------------------------------------------------------
# Tests: communities tool
# ---------------------------------------------------------------------------


class TestCommunitiesTool:
    def test_communities_search(self, mock_load):
        from codeloom.mcp_server import communities

        result = communities(search_query="auth")
        store, _ = mock_load
        store.community_search.assert_called_once()
        assert "Authentication" in result
        assert "Community 0" in result

    def test_communities_search_no_results(self, mock_load):
        from codeloom.mcp_server import communities

        store, _ = mock_load
        store.community_search.return_value = []
        result = communities(search_query="xyz_nonexistent")
        assert "No communities found" in result

    def test_communities_list_all(self, mock_load):
        from codeloom.mcp_server import communities

        store, _ = mock_load
        # Mock the SQLite query
        mock_row1 = {"id": 0, "level": 0, "summary": "Auth community"}
        mock_row2 = {"id": 1, "level": 0, "summary": "Server community"}
        mock_count = {"c": 2}
        store.conn.execute.return_value.fetchall.return_value = [
            mock_row1,
            mock_row2,
        ]
        store.conn.execute.return_value.fetchone.return_value = mock_count

        result = communities()
        assert "All Communities" in result
        assert "2 total" in result

    def test_communities_list_empty(self, mock_load):
        from codeloom.mcp_server import communities

        store, _ = mock_load
        store.conn.execute.return_value.fetchall.return_value = []

        result = communities()
        assert "No communities found" in result

    def test_communities_filter_by_level(self, mock_load):
        from codeloom.mcp_server import communities

        store, _ = mock_load
        store.conn.execute.return_value.fetchall.return_value = []

        communities(level=1)
        # Verify the SQL query includes level filter
        call_args = store.conn.execute.call_args_list
        sql_calls = [str(c) for c in call_args]
        assert any("level" in s for s in sql_calls)


# ---------------------------------------------------------------------------
# Tests: build tool
# ---------------------------------------------------------------------------


class TestBuildTool:
    def test_build_success(self, tmp_path):
        from codeloom.mcp_server import build

        # Create a minimal project
        src = tmp_path / "proj"
        src.mkdir()
        (src / "hello.py").write_text("def hello(): pass\n")

        mock_graph = _make_graph()
        mock_result = SimpleNamespace(
            graph=mock_graph,
            detected_files=["hello.py"],
        )
        with (
            patch(
                "codeloom.core.pipeline.run_pipeline", return_value=mock_result
            ),
            patch("codeloom.mcp_server._reload"),
        ):
            result = build(str(src))

        assert "Build Complete" in result
        assert "incremental" in result
        assert "3" in result  # nodes from mock graph

    def test_build_invalid_directory(self):
        from codeloom.mcp_server import build

        result = build("/nonexistent/path/xyz123")
        assert "Error" in result
        assert "not a valid directory" in result

    def test_build_full_mode(self, tmp_path):
        from codeloom.mcp_server import build

        src = tmp_path / "proj"
        src.mkdir()
        (src / "hello.py").write_text("def hello(): pass\n")
        (src / ".codeloom").mkdir()
        (src / ".codeloom" / "knowledge.db").touch()

        mock_graph = _make_graph()
        mock_result = SimpleNamespace(
            graph=mock_graph,
            detected_files=["hello.py"],
        )
        with (
            patch(
                "codeloom.core.pipeline.run_pipeline", return_value=mock_result
            ) as mock_pipe,
            patch("codeloom.mcp_server._reload"),
            patch(
                "codeloom.mcp_server._get_db_path",
                return_value=str(src / ".codeloom" / "knowledge.db"),
            ),
        ):
            build(str(src), incremental=False)
            _, kwargs = mock_pipe.call_args
            assert kwargs.get("incremental") is False


# ---------------------------------------------------------------------------
# Tests: search_keyword tool
# ---------------------------------------------------------------------------


class TestSearchKeywordTool:
    def test_search_keyword_returns_results(self, mock_load):
        from codeloom.mcp_server import search_keyword

        store, _ = mock_load
        store.keyword_search.return_value = [
            {
                "node_id": "auth.py:1",
                "label": "AuthHandler",
                "kind": "class",
                "file_path": "auth.py",
                "bm25_score": 0.8,
            },
        ]
        result = search_keyword("AuthHandler")
        assert "AuthHandler" in result
        assert "auth.py" in result
        assert "0.80" in result
        store.keyword_search.assert_called_once()

    def test_search_keyword_no_terms(self, mock_load):
        from codeloom.mcp_server import search_keyword

        result = search_keyword("")
        assert "No search terms" in result

    def test_search_keyword_no_results(self, mock_load):
        from codeloom.mcp_server import search_keyword

        store, _ = mock_load
        store.keyword_search.return_value = []
        result = search_keyword("NONEXISTENT_12345")
        assert "No keyword matches" in result


# ---------------------------------------------------------------------------
# Tests: search_vector tool
# ---------------------------------------------------------------------------


class TestSearchVectorTool:
    def test_search_vector_returns_results(self, mock_load):
        from codeloom.mcp_server import search_vector

        store, G = mock_load
        fake_vectors = {"code": "fake_code_vec", "text": "fake_text_vec"}
        store.vector_search.side_effect = lambda vec, **kw: (
            [("auth.py:1", 0.85)] if "code" in str(type(vec)) else []
        )
        with patch(
            "codeloom.query.embeddings.embed_query_dual",
            return_value=fake_vectors,
        ):
            result = search_vector("authentication")
        assert "auth.py:1" in result or "auth" in result.lower()

    def test_search_vector_fast_mode_no_code(self, mock_load):
        from codeloom.mcp_server import search_vector

        store, _ = mock_load
        fake_vectors = {"text": "fake_text_vec"}
        store.vector_search.return_value = [("server.py:10", 0.72)]
        with patch(
            "codeloom.query.embeddings.embed_query_dual",
            return_value=fake_vectors,
        ):
            result = search_vector("request handler", fast=True)
        assert "server.py:10" in result or "request" in result.lower()

    def test_search_vector_no_results(self, mock_load):
        from codeloom.mcp_server import search_vector

        store, _ = mock_load
        fake_vectors = {"code": "vec", "text": "vec"}
        store.vector_search.return_value = []
        with patch(
            "codeloom.query.embeddings.embed_query_dual",
            return_value=fake_vectors,
        ):
            result = search_vector("xyznonexistent_12345")
        assert "No vector matches" in result


# ---------------------------------------------------------------------------
# Tests: context tool
# ---------------------------------------------------------------------------


class TestContextTool:
    def test_context_exact_match(self, mock_load):
        from codeloom.mcp_server import context

        store, G = mock_load
        # Mock community query
        store.conn.execute.return_value.fetchone.return_value = {
            "summary": "Authentication module",
        }
        result = context("auth.py:1")
        assert "AuthHandler" in result
        assert "class" in result
        assert "auth.py" in result
        assert "Handles user authentication" in result
        assert "Community 0" in result
        assert "Outgoing" in result or "Incoming" in result

    def test_context_partial_match(self, mock_load):
        from codeloom.mcp_server import context

        store, G = mock_load
        store.conn.execute.return_value.fetchone.return_value = {
            "summary": "Auth module",
        }
        result = context("AuthHandler")
        assert "AuthHandler" in result

    def test_context_not_found(self, mock_load):
        from codeloom.mcp_server import context

        result = context("NonExistentSymbol_XYZ")
        assert "No node found" in result

    def test_context_shows_pagerank(self, mock_load):
        from codeloom.mcp_server import context

        store, G = mock_load
        store.conn.execute.return_value.fetchone.return_value = {
            "summary": "Auth module",
        }
        result = context("auth.py:1")
        assert "PageRank" in result


# ---------------------------------------------------------------------------
# Tests: list_repos tool
# ---------------------------------------------------------------------------


class TestListReposTool:
    def test_list_repos_shows_graph_info(self, mock_load, tmp_path):
        from codeloom.mcp_server import list_repos

        fake_db = tmp_path / ".codeloom" / "knowledge.db"
        fake_db.parent.mkdir(parents=True)
        fake_db.touch()
        with (
            patch("codeloom.mcp_server._run_git", return_value=""),
            patch(
                "codeloom.mcp_server._get_db_path",
                return_value=str(fake_db),
            ),
        ):
            result = list_repos()
        assert "Code Graph" in result
        assert "3" in result  # 3 nodes
        assert "2" in result  # 2 edges

    def test_list_repos_no_db(self, mock_load):
        from codeloom.mcp_server import list_repos

        with patch(
            "codeloom.mcp_server._get_db_path",
            return_value="/nonexistent/.codeloom/knowledge.db",
        ):
            result = list_repos()
        assert "No code graph found" in result


# ---------------------------------------------------------------------------
# Tests: detect_changes tool
# ---------------------------------------------------------------------------


class TestDetectChangesTool:
    def test_detect_changes_no_changes(self, mock_load):
        from codeloom.mcp_server import detect_changes

        with (
            patch("codeloom.mcp_server._run_git", return_value=""),
            patch(
                "codeloom.mcp_server._get_db_path",
                return_value="/fake/.codeloom/knowledge.db",
            ),
        ):
            result = detect_changes()
        assert "No changes detected" in result

    def test_detect_changes_with_changes(self, mock_load):
        from codeloom.mcp_server import detect_changes

        with (
            patch("codeloom.mcp_server._run_git", return_value="auth.py\n"),
            patch(
                "codeloom.mcp_server._get_db_path",
                return_value="/fake/.codeloom/knowledge.db",
            ),
        ):
            result = detect_changes()
        assert "Change Detection" in result
        assert "AuthHandler" in result
        assert "login" in result


# ---------------------------------------------------------------------------
# Tests: rename tool
# ---------------------------------------------------------------------------


class TestRenameTool:
    def test_rename_shows_node_info(self, mock_load):
        from codeloom.mcp_server import rename

        result = rename("AuthHandler", "NewAuthHandler")
        assert "AuthHandler" in result
        assert "NewAuthHandler" in result
        assert "auth.py" in result
        assert "class" in result

    def test_rename_not_found(self, mock_load):
        from codeloom.mcp_server import rename

        result = rename("NonExistent_12345", "NewName")
        assert "No graph nodes found" in result

    def test_rename_shows_references(self, mock_load):
        from codeloom.mcp_server import rename

        result = rename("auth.py:1", "AuthHandler")
        assert "Referenced by" in result or "handle_request" in result


# ---------------------------------------------------------------------------
# Tests: explain_flow tool
# ---------------------------------------------------------------------------


class TestExplainFlowTool:
    def test_explain_flow_shows_call_chain(self, mock_load):
        from codeloom.mcp_server import explain_flow

        result = explain_flow("handle_request")
        assert "handle_request" in result
        assert "server.py" in result

    def test_explain_flow_not_found(self, mock_load):
        from codeloom.mcp_server import explain_flow

        result = explain_flow("NonExistent_12345")
        assert "No node found" in result

    def test_explain_flow_entry_point(self, mock_load):
        from codeloom.mcp_server import explain_flow

        result = explain_flow("auth.py:1")
        assert "AuthHandler" in result


# ---------------------------------------------------------------------------
# Tests: export_subgraph tool
# ---------------------------------------------------------------------------


class TestExportSubgraphTool:
    def test_export_subgraph_returns_json(self, mock_load):
        from codeloom.mcp_server import export_subgraph

        result = export_subgraph("auth.py:1", depth=1)
        import json

        data = json.loads(result)
        assert "seed" in data
        assert data["seed"] == "auth.py:1"
        assert "nodes" in data
        assert "links" in data
        assert data["metadata"]["node_count"] > 0

    def test_export_subgraph_not_found(self, mock_load):
        import json

        from codeloom.mcp_server import export_subgraph

        result = json.loads(export_subgraph("NonExistent_12345"))
        assert "error" in result

    def test_export_subgraph_node_fields(self, mock_load):
        import json

        from codeloom.mcp_server import export_subgraph

        data = json.loads(export_subgraph("server.py:10"))
        for node in data["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "kind" in node
            assert "file_path" in node


# ---------------------------------------------------------------------------
# Tests: _resolve_node helper
# ---------------------------------------------------------------------------


class TestResolveNode:
    def test_exact_match(self, mock_load):
        from codeloom.mcp_server import _resolve_node

        _, G = mock_load
        matches = _resolve_node("auth.py:1", G)
        assert matches == ["auth.py:1"]

    def test_partial_match(self, mock_load):
        from codeloom.mcp_server import _resolve_node

        _, G = mock_load
        matches = _resolve_node("AuthHandler", G)
        assert "auth.py:1" in matches

    def test_case_insensitive_partial(self, mock_load):
        from codeloom.mcp_server import _resolve_node

        _, G = mock_load
        matches = _resolve_node("authhandler", G)
        assert "auth.py:1" in matches

    def test_no_match(self, mock_load):
        from codeloom.mcp_server import _resolve_node

        _, G = mock_load
        matches = _resolve_node("NonExistent_12345", G)
        assert matches == []

    def test_label_match(self, mock_load):
        from codeloom.mcp_server import _resolve_node

        _, G = mock_load
        matches = _resolve_node("login", G)
        assert "auth.py:5" in matches


# ---------------------------------------------------------------------------
# Tests: _load / _get_db_path helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_get_db_path_env_var(self, tmp_path):
        import codeloom.mcp_server as mod

        db_file = tmp_path / "knowledge.db"
        db_file.touch()
        mod._db_path = None  # reset cache
        with patch.dict("os.environ", {"CODELOOM_DB": str(db_file)}):
            result = mod._get_db_path()
            assert result == str(db_file)
        mod._db_path = None  # cleanup

    def test_get_db_path_cwd_fallback(self, tmp_path):
        import codeloom.mcp_server as mod

        mod._db_path = None
        # Create .codeloom/knowledge.db in tmp_path
        (tmp_path / ".codeloom").mkdir()
        (tmp_path / ".codeloom" / "knowledge.db").touch()
        with (
            patch("codeloom.mcp_server.Path.cwd", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = mod._get_db_path()
            assert "knowledge.db" in result
        mod._db_path = None

    def test_load_file_not_found(self):
        import codeloom.mcp_server as mod

        mod._store = None
        mod._graph = None
        mod._db_path = None
        with patch(
            "codeloom.mcp_server._get_db_path",
            return_value="/fake/path/knowledge.db",
        ):
            with pytest.raises(FileNotFoundError, match="Run 'codeloom build"):
                mod._load()

    def test_reload_clears_cache(self):
        import codeloom.mcp_server as mod

        mod._store = "old"
        mod._graph = "old"
        with patch(
            "codeloom.mcp_server._load",
            return_value=("new_store", "new_graph"),
        ) as mock_l:
            mod._reload()
            assert mod._store is None or mock_l.called

    def test_get_db_path_source_dir_fallback(self, tmp_path):
        import codeloom.mcp_server as mod

        mod._db_path = None
        # Create DB in a subdir, not under cwd
        source = tmp_path / "project"
        (source / ".codeloom").mkdir(parents=True)
        (source / ".codeloom" / "knowledge.db").touch()
        # CWD has no DB
        cwd_no_db = tmp_path / "somewhere_else"
        cwd_no_db.mkdir()
        with (
            patch("codeloom.mcp_server.Path.cwd", return_value=cwd_no_db),
            patch.dict("os.environ", {}, clear=True),
        ):
            # Without source_dir, falls back to cwd default
            mod._db_path = None
            result = mod._get_db_path()
            assert str(cwd_no_db) in result  # default fallback

            # With source_dir, finds DB in source tree
            mod._db_path = None
            result = mod._get_db_path(source_dir=str(source))
            assert "knowledge.db" in result
        mod._db_path = None

    def test_load_file_not_found_mentions_codeloom_db_env(self):
        import codeloom.mcp_server as mod

        mod._store = None
        mod._graph = None
        mod._db_path = None
        with patch(
            "codeloom.mcp_server._get_db_path",
            return_value="/fake/path/knowledge.db",
        ):
            with pytest.raises(FileNotFoundError, match="CODELOOM_DB"):
                mod._load()

    def test_build_existing_db_incremental_runs_pipeline(self, tmp_path):
        import codeloom.mcp_server as mod

        src = tmp_path / "proj"
        src.mkdir()
        (src / "hello.py").write_text("def hello(): pass\n")
        (src / ".codeloom").mkdir()
        (src / ".codeloom" / "knowledge.db").touch()

        mock_graph = _make_graph()
        mock_result = SimpleNamespace(
            graph=mock_graph,
            detected_files=["hello.py"],
        )
        mock_existing = MagicMock()
        mock_existing.load_graph.return_value = mock_graph
        mock_existing.close = MagicMock()
        with (
            patch(
                "codeloom.core.pipeline.run_pipeline", return_value=mock_result
            ) as mock_pipe,
            patch("codeloom.mcp_server._reload"),
            patch(
                "codeloom.storage.store.KnowledgeStore",
                return_value=mock_existing,
            ),
        ):
            result = mod.build(str(src))
            mock_pipe.assert_called_once()
            assert "Build Complete" in result
        mod._db_path = None

    def test_build_existing_db_non_incremental_skips(self, tmp_path):
        import codeloom.mcp_server as mod

        src = tmp_path / "proj"
        src.mkdir()
        (src / "hello.py").write_text("def hello(): pass\n")
        (src / ".codeloom").mkdir()
        (src / ".codeloom" / "knowledge.db").touch()

        mock_graph = _make_graph()
        mock_existing = MagicMock()
        mock_existing.load_graph.return_value = mock_graph
        mock_existing.close = MagicMock()
        with (
            patch("codeloom.core.pipeline.run_pipeline") as mock_pipe,
            patch(
                "codeloom.storage.store.KnowledgeStore",
                return_value=mock_existing,
            ),
        ):
            result = mod.build(str(src), incremental=False)
            mock_pipe.assert_not_called()
            assert "Database Already Exists" in result
            assert "3" in result  # node count
        mod._db_path = None

    def test_build_existing_db_corrupt_falls_through_to_rebuild(self, tmp_path):
        import codeloom.mcp_server as mod

        src = tmp_path / "proj"
        src.mkdir()
        (src / "hello.py").write_text("def hello(): pass\n")
        (src / ".codeloom").mkdir()
        (src / ".codeloom" / "knowledge.db").touch()

        mock_graph = _make_graph()
        mock_result = SimpleNamespace(
            graph=mock_graph,
            detected_files=["hello.py"],
        )
        mock_existing = MagicMock()
        mock_existing.load_graph.side_effect = Exception("corrupt database")
        mock_existing.close = MagicMock()
        with (
            patch(
                "codeloom.core.pipeline.run_pipeline", return_value=mock_result
            ) as mock_pipe,
            patch("codeloom.mcp_server._reload"),
            patch(
                "codeloom.storage.store.KnowledgeStore",
                return_value=mock_existing,
            ),
        ):
            result = mod.build(str(src))
            mock_pipe.assert_called_once()
            assert "Build Complete" in result
        mod._db_path = None
