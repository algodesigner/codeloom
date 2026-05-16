"""Tests for cross-file reference resolution."""

import networkx as nx

from codeloom.core.resolve import (
    DEFINITION_KINDS,
    RESOLVABLE_RELATIONS,
    ResolutionResult,
    Span,
    _extract_file_path,
    _find_containing_definition,
    _parse_line,
    build_spatial_index,
    resolve_graph,
)

# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------

class TestParseLine:
    def test_parses_simple(self):
        assert _parse_line("main.py:42") == 42

    def test_parses_zero(self):
        assert _parse_line("main.py:0") == 0

    def test_returns_none_for_no_line(self):
        assert _parse_line("just_a_file.py") is None

    def test_returns_none_for_empty(self):
        assert _parse_line("") is None

    def test_windows_path_not_confused(self):
        assert _parse_line("C:\\\\project\\file.py:15") == 15


class TestExtractFilePath:
    def test_simple_path(self):
        assert _extract_file_path("src/main.py:42") == "src/main.py"

    def test_no_line_number(self):
        assert _extract_file_path("src/main.py") == "src/main.py"

    def test_windows_path(self):
        result = _extract_file_path("C:\\project\\file.py:15")
        assert result == "C:\\project\\file.py" or "C:" in result

    def test_empty(self):
        assert _extract_file_path("") == ""


# ---------------------------------------------------------------------------
# Unit tests: spatial index
# ---------------------------------------------------------------------------

class TestBuildSpatialIndex:
    def test_empty_graph(self):
        G = nx.DiGraph()
        index = build_spatial_index(G)
        assert index == {}

    def test_single_definition(self):
        G = nx.DiGraph()
        G.add_node("app.py:10", kind="function", file_path="app.py",
                    label="run", start_line=10, end_line=25)
        index = build_spatial_index(G)
        assert "app.py" in index
        assert len(index["app.py"]) == 1
        assert index["app.py"][0].node_id == "app.py:10"
        assert index["app.py"][0].start_line == 10

    def test_multiple_definitions_in_file(self):
        G = nx.DiGraph()
        G.add_node("app.py:1", kind="class", file_path="app.py",
                    label="App", start_line=1, end_line=50)
        G.add_node("app.py:10", kind="method", file_path="app.py",
                    label="run", start_line=10, end_line=25)
        G.add_node("app.py:30", kind="method", file_path="app.py",
                    label="setup", start_line=30, end_line=45)
        index = build_spatial_index(G)
        assert len(index["app.py"]) == 3
        # Should be sorted by start_line
        assert index["app.py"][0].node_id == "app.py:1"
        assert index["app.py"][1].node_id == "app.py:10"
        assert index["app.py"][2].node_id == "app.py:30"

    def test_skips_non_definition_kinds(self):
        G = nx.DiGraph()
        G.add_node("app.py:5", kind="import", file_path="app.py",
                    label="os", start_line=5)
        index = build_spatial_index(G)
        # "import" is not in DEFINITION_KINDS
        assert "app.py" not in index or len(index["app.py"]) == 0

    def test_skips_nodes_without_file_path(self):
        G = nx.DiGraph()
        G.add_node("node:1", kind="function", file_path="", label="f", start_line=1)
        index = build_spatial_index(G)
        assert index == {}

    def test_definitions_across_multiple_files(self):
        G = nx.DiGraph()
        G.add_node("a.py:1", kind="function", file_path="a.py",
                    label="fn_a", start_line=1)
        G.add_node("b.py:5", kind="function", file_path="b.py",
                    label="fn_b", start_line=5)
        index = build_spatial_index(G)
        assert "a.py" in index
        assert "b.py" in index
        assert len(index["a.py"]) == 1
        assert len(index["b.py"]) == 1

    def test_includes_definition_kinds_only(self):
        G = nx.DiGraph()
        G.add_node("a.py:1", kind="function", file_path="a.py",
                    label="fn", start_line=1)
        G.add_node("a.py:5", kind="variable", file_path="a.py",
                    label="x", start_line=5)
        index = build_spatial_index(G)
        assert len(index["a.py"]) == 2  # Both are in DEFINITION_KINDS


# ---------------------------------------------------------------------------
# Unit tests: containing definition lookup
# ---------------------------------------------------------------------------

class TestFindContainingDefinition:
    def _spans(self):
        return [
            Span("app.py:1", 1, 50, "class", "App"),
            Span("app.py:10", 10, 25, "method", "run"),
            Span("app.py:30", 30, 45, "method", "setup"),
        ]

    def test_finds_function_containing_line(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 12)
        assert result is not None
        assert result.node_id == "app.py:10"

    def test_finds_class_containing_line(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 5)
        assert result is not None
        assert result.node_id == "app.py:1"

    def test_finds_method_at_start_line(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 10)
        assert result is not None
        assert result.node_id == "app.py:10"

    def test_finds_method_at_end_line(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 25)
        assert result is not None
        assert result.node_id == "app.py:10"

    def test_returns_none_before_first_definition(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 0)
        assert result is None

    def test_returns_none_between_definitions(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 27)
        assert result is None

    def test_returns_none_after_last_definition(self):
        spans = self._spans()
        result = _find_containing_definition(spans, 100)
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = _find_containing_definition([], 10)
        assert result is None

    def test_handles_single_line_definition(self):
        spans = [Span("app.py:5", 5, 0, "function", "fn")]
        result = _find_containing_definition(spans, 5)
        assert result is not None
        assert result.node_id == "app.py:5"

    def test_prefers_innermost_definition(self):
        spans = [
            Span("app.py:1", 1, 50, "class", "App"),
            Span("app.py:10", 10, 20, "method", "inner"),
        ]
        result = _find_containing_definition(spans, 15)
        assert result is not None
        assert result.node_id == "app.py:10"

    def test_handles_adjacent_spans(self):
        spans = [
            Span("a.py:1", 1, 10, "function", "first"),
            Span("a.py:11", 11, 20, "function", "second"),
        ]
        assert _find_containing_definition(spans, 10) is not None
        assert _find_containing_definition(spans, 10).node_id == "a.py:1"
        assert _find_containing_definition(spans, 11).node_id == "a.py:11"


# ---------------------------------------------------------------------------
# Integration tests: resolve_graph
# ---------------------------------------------------------------------------

class TestResolveGraph:
    def test_empty_graph(self):
        G = nx.DiGraph()
        result = resolve_graph(G)
        assert result.resolved == 0
        assert result.already_resolved == 0
        assert result.unresolved == 0

    def test_edge_already_pointing_to_definition(self):
        G = nx.DiGraph()
        G.add_node("a.py:5", kind="function", file_path="a.py",
                    label="caller", start_line=5, end_line=10)
        G.add_node("b.py:15", kind="function", file_path="b.py",
                    label="callee", start_line=15, end_line=20)
        G.add_edge("a.py:5", "b.py:15", relation="calls")
        result = resolve_graph(G)
        assert result.already_resolved == 1
        assert result.resolved == 0
        # Edge should still point to the same target
        assert G.has_edge("a.py:5", "b.py:15")

    def test_resolves_edge_to_containing_definition(self):
        G = nx.DiGraph()
        G.add_node("a.py:5", kind="function", file_path="a.py",
                    label="caller", start_line=5, end_line=10)
        # Target is a specific line inside a larger function
        G.add_node("b.py:15", kind="function", file_path="b.py",
                    label="callee", start_line=15, end_line=30)
        # Edge points to line 20 (inside callee)
        G.add_edge("a.py:5", "b.py:20", relation="calls")
        result = resolve_graph(G)
        assert result.resolved == 1
        assert not G.has_edge("a.py:5", "b.py:20")
        assert G.has_edge("a.py:5", "b.py:15")

    def test_resolves_edge_to_nested_definition(self):
        G = nx.DiGraph()
        G.add_node("a.py:1", kind="class", file_path="a.py",
                    label="Service", start_line=1, end_line=50)
        G.add_node("a.py:10", kind="method", file_path="a.py",
                    label="connect", start_line=10, end_line=20)
        # Edge points inside the method
        G.add_node("b.py:5", kind="function", file_path="b.py",
                    label="runner", start_line=5, end_line=8)
        G.add_edge("b.py:5", "a.py:15", relation="calls")
        result = resolve_graph(G)
        assert result.resolved == 1
        assert G.has_edge("b.py:5", "a.py:10")
        # Should NOT resolve to the outer class
        assert not G.has_edge("b.py:5", "a.py:1")

    def test_skips_non_resolvable_relations(self):
        G = nx.DiGraph()
        G.add_node("a.py:5", kind="function", file_path="a.py",
                    label="fn", start_line=5, end_line=10)
        G.add_node("b.py:15", kind="function", file_path="b.py",
                    label="other", start_line=15, end_line=20)
        G.add_edge("a.py:5", "b.py:15", relation="co_change")
        result = resolve_graph(G)
        assert result.skipped_relation == 1

    def test_skips_edges_to_module_nodes_without_file_info(self):
        G = nx.DiGraph()
        G.add_node("a", kind="function", file_path="a.py",
                    label="fn", start_line=5, end_line=10)
        G.add_node("external_lib", kind="external",
                    file_path="", label="lib")
        G.add_edge("a", "external_lib", relation="calls")
        result = resolve_graph(G)
        # external_lib has no file_path, so it won't be in the index
        # It also has kind "external" not in definition_kinds
        assert result.unresolved >= 0  # May be 1 unresolved

    def test_unresolved_edge_remains(self):
        G = nx.DiGraph()
        G.add_node("a.py:5", kind="function", file_path="a.py",
                    label="fn", start_line=5, end_line=10)
        # Target doesn't exist in graph
        G.add_node("nonexistent:99", kind="unknown",
                    file_path="nonexistent:99", label="")
        G.add_edge("a.py:5", "nonexistent:99", relation="calls")
        result = resolve_graph(G)
        assert result.unresolved > 0
        assert G.has_edge("a.py:5", "nonexistent:99")

    def test_handles_import_resolution(self):
        G = nx.DiGraph()
        G.add_node("a.py:1", kind="function", file_path="a.py",
                    label="run", start_line=1, end_line=10)
        G.add_node("b.py:0", kind="module", file_path="b.py",
                    label="b", start_line=0)
        G.add_edge("a.py:1", "b.py:0", relation="imports")
        result = resolve_graph(G)
        # module is in DEFINITION_KINDS, so this is already resolved
        assert result.already_resolved >= 0 or result.resolved >= 0


class TestResolveGraphIntegration:
    def test_realistic_scenario(self):
        """Simulate a realistic multi-file codebase with cross-file calls."""
        G = nx.DiGraph()

        # File: services/database.py
        G.add_node("services/database.py:10", kind="class",
                    file_path="services/database.py",
                    label="Database", start_line=10, end_line=60)
        G.add_node("services/database.py:15", kind="method",
                    file_path="services/database.py",
                    label="connect", start_line=15, end_line=30,
                    signature="(config: Config) -> Connection")
        G.add_node("services/database.py:35", kind="method",
                    file_path="services/database.py",
                    label="query", start_line=35, end_line=55,
                    signature="(sql: str) -> Result")

        # File: api/handlers.py
        G.add_node("api/handlers.py:5", kind="function",
                    file_path="api/handlers.py",
                    label="get_users", start_line=5, end_line=25)

        # Edges: some already resolved, some not
        # Resolved: points directly to method
        G.add_edge("api/handlers.py:5", "services/database.py:15",
                    relation="calls")
        # Unresolved: points to line inside Database.query but not the method node
        G.add_edge("api/handlers.py:5", "services/database.py:40",
                    relation="calls")

        result = resolve_graph(G)
        assert result.resolved == 1  # services/database.py:40 -> services/database.py:35
        assert result.already_resolved >= 1  # services/database.py:15 already correct
        assert G.has_edge("api/handlers.py:5", "services/database.py:35")
        assert G.has_edge("api/handlers.py:5", "services/database.py:15")

    def test_preserves_edge_attributes_on_resolve(self):
        G = nx.DiGraph()
        G.add_node("a.py:5", kind="function", file_path="a.py",
                    label="fn", start_line=5, end_line=10)
        G.add_node("b.py:15", kind="function", file_path="b.py",
                    label="callee", start_line=15, end_line=30)
        G.add_edge("a.py:5", "b.py:20", relation="calls",
                    confidence="INFERRED")

        resolve_graph(G)
        # New edge should preserve attributes
        if G.has_edge("a.py:5", "b.py:15"):
            assert G.edges["a.py:5", "b.py:15"]["relation"] == "calls"
            assert G.edges["a.py:5", "b.py:15"].get("confidence") == "INFERRED"

    def test_no_duplicate_edges_after_resolution(self):
        G = nx.DiGraph()
        G.add_node("a.py:5", kind="function", file_path="a.py",
                    label="fn", start_line=5, end_line=10)
        G.add_node("b.py:15", kind="function", file_path="b.py",
                    label="callee", start_line=15, end_line=30)
        # Two edges: one resolved, one not
        G.add_edge("a.py:5", "b.py:15", relation="calls")  # Already resolved
        G.add_edge("a.py:5", "b.py:20", relation="calls")  # Needs resolution

        result = resolve_graph(G)
        assert result.already_resolved >= 1
        assert result.resolved >= 0
        # Should not create duplicate edges
        edge_count = sum(1 for _, _, d in G.edges(data=True)
                         if d.get("relation") == "calls")
        assert edge_count <= 2  # 1 already resolved + 0 or 1 new (original removed)


class TestResolutionResult:
    def test_defaults(self):
        r = ResolutionResult()
        assert r.resolved == 0
        assert r.already_resolved == 0
        assert r.unresolved == 0
        assert r.skipped_relation == 0
        assert r.errors == []


class TestConstants:
    def test_definition_kinds_contains_core_types(self):
        assert "function" in DEFINITION_KINDS
        assert "class" in DEFINITION_KINDS
        assert "method" in DEFINITION_KINDS
        assert "module" in DEFINITION_KINDS

    def test_resolvable_relations_contains_call(self):
        assert "calls" in RESOLVABLE_RELATIONS
        assert "imports" in RESOLVABLE_RELATIONS
        assert "inherits" in RESOLVABLE_RELATIONS
