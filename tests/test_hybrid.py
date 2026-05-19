"""Tests for hybrid search and RRF fusion."""

from codeloom.query.hybrid import (
    TEST_PENALTY_FACTOR,
    VALID_KINDS,
    SearchEdge,
    SearchGraph,
    SearchResult,
    _generate_filter_hint,
    _generate_source_test_hint,
    _is_test_file,
    _read_snippet,
    reciprocal_rank_fusion,
)


class TestRRF:
    def test_single_list(self):
        ranked = [("a", 0.9), ("b", 0.5), ("c", 0.1)]
        fused, breakdowns = reciprocal_rank_fusion(ranked)
        assert fused[0][0] == "a"
        assert fused[1][0] == "b"
        assert fused[2][0] == "c"
        # Breakdowns should have entries for all items
        assert "a" in breakdowns
        assert len(breakdowns["a"]) > 0

    def test_multi_list_fusion(self):
        list1 = [("a", 0.9), ("b", 0.5)]
        list2 = [("b", 0.8), ("c", 0.3)]
        list3 = [("a", 0.7), ("c", 0.6)]
        fused, breakdowns = reciprocal_rank_fusion(list1, list2, list3)
        scores = {item: score for item, score in fused}
        assert len(scores) == 3
        assert all(s > 0 for s in scores.values())

    def test_item_in_all_lists_ranks_higher(self):
        list1 = [("x", 0.9), ("y", 0.5)]
        list2 = [("x", 0.8), ("z", 0.3)]
        list3 = [("x", 0.7), ("w", 0.6)]
        fused, breakdowns = reciprocal_rank_fusion(
            list1, list2, list3,
            signal_names=["s1", "s2", "s3"],
        )
        assert fused[0][0] == "x"
        assert len(breakdowns["x"]) == 3

    def test_empty_lists(self):
        fused, breakdowns = reciprocal_rank_fusion([], [])
        assert fused == []
        assert breakdowns == {}

    def test_rrf_constant(self):
        ranked = [("a", 0.9)]
        fused_k60, _ = reciprocal_rank_fusion(ranked, k=60)
        fused_k1, _ = reciprocal_rank_fusion(ranked, k=1)
        assert fused_k1[0][1] > fused_k60[0][1]


class TestSearchResult:
    def test_dataclass(self):
        sr = SearchResult(
            node_id="test.py:1",
            label="foo",
            kind="function",
            file_path="test.py",
            score=0.95,
            source="seed",
        )
        assert sr.label == "foo"
        assert sr.signal_contributions == {}


class TestSearchGraph:
    def test_graph_structure(self):
        nodes = [
            SearchResult(node_id="a", label="a", kind="function",
                         file_path="a.py", score=0.9, source="seed"),
            SearchResult(node_id="b", label="b", kind="function",
                         file_path="b.py", score=0.8, source="seed"),
            SearchResult(node_id="m", label="m", kind="module",
                         file_path="m.py", score=0.0, source="path"),
        ]
        edges = [
            SearchEdge(source="a", target="m", relation="defines"),
            SearchEdge(source="m", target="b", relation="co_change"),
        ]
        sg = SearchGraph(nodes=nodes, edges=edges)
        assert len(sg.nodes) == 3
        assert len(sg.edges) == 2
        seed_nodes = [n for n in sg.nodes if n.source == "seed"]
        path_nodes = [n for n in sg.nodes if n.source == "path"]
        assert len(seed_nodes) == 2
        assert len(path_nodes) == 1


class TestSearchGraphJson:
    def test_to_json_structure(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="mod:0", label="app", kind="module",
                             file_path="app.py", score=0.5, source="seed",
                             start_line=0),
                SearchResult(node_id="app.py:10", label="run", kind="function",
                             file_path="app.py", score=0.3, source="seed",
                             start_line=10, signature="()",
                             signal_contributions={"vector": 0.2}),
            ],
            edges=[SearchEdge(source="mod:0", target="app.py:10", relation="defines")],
            isolated=[
                SearchResult(node_id="old.py:5", label="old_func", kind="function",
                             file_path="old.py", score=0.1, source="seed",
                             start_line=5),
            ],
        )
        j = sg.to_json()
        assert set(j.keys()) == {"seeds", "edges", "isolated", "hint"}
        assert len(j["seeds"]) == 2
        assert len(j["edges"]) == 1
        assert len(j["isolated"]) == 1

    def test_to_json_seed_fields(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="app.py:10", label="run", kind="function",
                             file_path="app.py", score=0.3, source="seed",
                             start_line=10, signature="()",
                             signal_contributions={"vector": 0.2}),
            ],
            edges=[], isolated=[],
        )
        seed = sg.to_json()["seeds"][0]
        assert seed["id"] == "app.py:10"
        assert seed["label"] == "run"
        assert seed["kind"] == "function"
        assert seed["file"] == "app.py"
        assert seed["line"] == 10
        assert seed["score"] == 0.3
        assert seed["signature"] == "()"
        assert seed["signal_contributions"] == {"vector": 0.2}

    def test_to_json_edge_fields(self):
        sg = SearchGraph(
            nodes=[], isolated=[],
            edges=[SearchEdge(source="a.py:1", target="b.py:2", relation="calls")],
        )
        edge = sg.to_json()["edges"][0]
        assert edge["from"] == "a.py:1"
        assert edge["to"] == "b.py:2"
        assert edge["relation"] == "calls"

    def test_to_json_isolated_separate(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="a.py:1", label="a", kind="function",
                             file_path="a.py", score=0.5, source="seed", start_line=1),
                SearchResult(node_id="b.py:1", label="b", kind="function",
                             file_path="b.py", score=0.1, source="seed", start_line=1),
            ],
            edges=[SearchEdge(source="a.py:1", target="b.py:1", relation="calls")],
            isolated=[
                SearchResult(node_id="c.py:1", label="c", kind="function",
                             file_path="c.py", score=0.05, source="seed", start_line=1),
            ],
        )
        j = sg.to_json()
        assert len(j["seeds"]) == 2
        assert len(j["isolated"]) == 1
        assert j["isolated"][0]["id"] == "c.py:1"

    def test_to_json_strips_source_dir(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="/project/app.py:10", label="run", kind="function",
                             file_path="/project/app.py", score=0.5, source="seed",
                             start_line=10),
            ],
            edges=[], isolated=[],
        )
        j = sg.to_json(source_dir="/project/")
        assert j["seeds"][0]["id"] == "app.py:10"

    def test_to_json_empty(self):
        sg = SearchGraph(nodes=[], edges=[], isolated=[])
        j = sg.to_json()
        assert j == {"seeds": [], "edges": [], "isolated": [], "hint": None}


class TestValidateKinds:
    def test_valid_kinds_contains_core(self):
        assert "function" in VALID_KINDS
        assert "class" in VALID_KINDS
        assert "method" in VALID_KINDS


class TestGenerateFilterHint:
    def test_no_hint_when_filter_applied(self):
        hint = _generate_filter_hint([], kind_filter="function", file_filter=None, top_k=10)
        assert hint == ""

    def test_no_hint_when_few_results(self):
        hint = _generate_filter_hint([], kind_filter=None, file_filter=None, top_k=10)
        assert hint == ""

    def test_hint_when_kind_dominates(self):
        seed_nodes = [
            ("a:1", 0.5, {"kind": "function"}),
            ("a:2", 0.4, {"kind": "function"}),
            ("a:3", 0.3, {"kind": "function"}),
            ("a:4", 0.2, {"kind": "function"}),
            ("a:5", 0.1, {"kind": "function"}),
            ("a:6", 0.1, {"kind": "function"}),
            ("a:7", 0.1, {"kind": "class"}),
        ]
        hint = _generate_filter_hint(seed_nodes, kind_filter=None, file_filter=None, top_k=10)
        assert hint is not None
        assert "function" in hint
        assert "--kind" in hint

    def test_no_hint_when_kind_mixed(self):
        seed_nodes = [
            ("a:1", 0.5, {"kind": "function"}),
            ("a:2", 0.4, {"kind": "class"}),
            ("a:3", 0.3, {"kind": "method"}),
            ("a:4", 0.2, {"kind": "class"}),
            ("a:5", 0.1, {"kind": "function"}),
            ("a:6", 0.1, {"kind": "section"}),
            ("a:7", 0.1, {"kind": "struct"}),
        ]
        hint = _generate_filter_hint(seed_nodes, kind_filter=None, file_filter=None, top_k=10)
        assert hint == ""


class TestSearchGraphHint:
    def test_hint_in_text_output(self):
        sg = SearchGraph(nodes=[], edges=[], hint="Try --kind function")
        text = sg.to_text()
        assert "Hint: Try --kind function" in text

    def test_no_hint_in_text_output(self):
        sg = SearchGraph(nodes=[], edges=[], hint="")
        text = sg.to_text()
        assert "Hint:" not in text

    def test_hint_in_json_output(self):
        sg = SearchGraph(nodes=[], edges=[], hint="Try --kind function")
        j = sg.to_json()
        assert j["hint"] == "Try --kind function"


class TestHybridSearchFiltering:
    """Test hybrid_search with kind and file_pattern filters using mocked store."""

    def _clear(self):
        from codeloom.query.hybrid import clear_search_cache
        clear_search_cache()

    def test_filters_by_kind(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("a.py:1", kind="function", file_path="a.py", label="fn", start_line=1)
        G.add_node("b.py:1", kind="class", file_path="b.py", label="Cls", start_line=1)
        G.add_node("c.py:1", kind="method", file_path="c.py", label="meth", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [("a.py:1", 0.9), ("b.py:1", 0.5), ("c.py:1", 0.3)]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search
            result = hybrid_search("test", mock_store, G, top_k=10, kind="function")
            seed_ids = {n.node_id for n in result.nodes if n.source == "seed"}
            assert "a.py:1" in seed_ids
            assert "b.py:1" not in seed_ids
            assert "c.py:1" not in seed_ids

    def test_filters_by_file_pattern(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/api/handler.py:1", kind="function", file_path="src/api/handler.py",
                    label="handle", start_line=1)
        G.add_node("src/db/pool.py:1", kind="function", file_path="src/db/pool.py",
                    label="connect", start_line=1)
        G.add_node("tests/test_api.py:1", kind="function", file_path="tests/test_api.py",
                    label="test_handle", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("src/api/handler.py:1", 0.9),
            ("src/db/pool.py:1", 0.5),
            ("tests/test_api.py:1", 0.3),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search
            result = hybrid_search("api", mock_store, G, top_k=10, file_pattern="src/api/*")
            seed_ids = {n.node_id for n in result.nodes if n.source == "seed"}
            assert "src/api/handler.py:1" in seed_ids
            assert "src/db/pool.py:1" not in seed_ids
            assert "tests/test_api.py:1" not in seed_ids

    def test_kind_and_file_filter_together(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/api/handler.py:1", kind="function", file_path="src/api/handler.py",
                    label="handle", start_line=1)
        G.add_node("src/api/types.py:1", kind="class", file_path="src/api/types.py",
                    label="RequestType", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("src/api/handler.py:1", 0.9),
            ("src/api/types.py:1", 0.5),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search
            result = hybrid_search("api", mock_store, G, top_k=10,
                                    kind="function", file_pattern="src/api/*")
            seed_ids = {n.node_id for n in result.nodes if n.source == "seed"}
            assert "src/api/handler.py:1" in seed_ids
            assert "src/api/types.py:1" not in seed_ids

    def test_filter_with_no_results(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("a.py:1", kind="function", file_path="a.py", label="fn", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [("a.py:1", 0.9)]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search
            result = hybrid_search("test", mock_store, G, top_k=10, kind="class")
            seeds = [n for n in result.nodes if n.source == "seed"]
            assert len(seeds) == 0

    def test_filter_by_kind_generates_hint(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        for i in range(6):
            G.add_node(f"a.py:{i}", kind="function", file_path="a.py",
                        label=f"fn{i}", start_line=i)
        G.add_node("b.py:1", kind="class", file_path="b.py", label="Cls", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (f"a.py:{i}", 0.9 - i * 0.1) for i in range(6)
        ] + [("b.py:1", 0.1)]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        from codeloom.query.hybrid import clear_search_cache

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search
            clear_search_cache()

            # No kind filter -> hint should suggest function
            result = hybrid_search("find functions", mock_store, G, top_k=10, kind=None)
            assert result.hint != ""
            assert "function" in result.hint

            clear_search_cache()

            # With kind filter -> no hint
            result2 = hybrid_search("find functions filtered", mock_store, G,
                                     top_k=10, kind="function")
            assert result2.hint == ""


class TestIsTestFile:
    """Tests for _is_test_file heuristic."""

    # -- Directory-based detection --

    def test_top_level_test_dir(self):
        assert _is_test_file("test/test_foo.py")
        assert _is_test_file("tests/util.py")

    def test_nested_test_dir(self):
        assert _is_test_file("src/test/java/Foo.java")
        assert _is_test_file("packages/backend/src/test/unit.py")

    def test_spec_dir(self):
        assert _is_test_file("spec/models/user_spec.rb")
        assert _is_test_file("specs/controllers/api_spec.js")

    def test_tst_dir(self):
        assert _is_test_file("tst/config_test.py")

    def test_dunder_tests_dir(self):
        assert _is_test_file("__tests__/component.js")

    def test_deeply_nested_test_dir(self):
        assert _is_test_file("modules/auth/integrationTest/java/TestAuth.java")
        assert _is_test_file("common/testutils/helpers.py")
        assert _is_test_file("lib/testhelpers/mock.py")

    def test_dir_named_test_but_not_exact_match(self):
        assert _is_test_file("testing/utils.py")
        assert _is_test_file("mytest/run.py")

    # -- src/test/ prefix (Maven/Gradle) --

    def test_maven_src_test_java(self):
        assert _is_test_file("src/test/java/com/example/FooTest.java")
        assert _is_test_file("src\\test\\java\\com\\example\\FooTest.java")

    def test_src_main_not_test(self):
        assert not _is_test_file("src/main/java/com/example/Foo.java")
        assert not _is_test_file("src/main/__init__.py")

    # -- Filename-based detection --

    # Python
    def test_python_test_prefix(self):
        assert _is_test_file("test_foo.py")
        assert _is_test_file("deeply/nested/test_config.py")

    def test_python_test_suffix(self):
        assert _is_test_file("foo_test.py")
        assert _is_test_file("bar_test.py")

    # JavaScript / TypeScript
    def test_js_test_dot_pattern(self):
        assert _is_test_file("button.test.js")
        assert _is_test_file("button.test.ts")
        assert _is_test_file("button.test.jsx")
        assert _is_test_file("button.test.tsx")

    def test_js_spec_dot_pattern(self):
        assert _is_test_file("button.spec.js")
        assert _is_test_file("button.spec.ts")

    def test_js_test_patterns(self):
        assert _is_test_file("api.test")
        assert _is_test_file("api.spec")

    # Java
    def test_java_test_class(self):
        assert _is_test_file("FooTest.java")
        assert _is_test_file("com/example/FooTests.java")

    def test_java_integration_test(self):
        assert _is_test_file("FooIT.java")

    def test_java_spec_class(self):
        assert _is_test_file("UserSpec.java")

    # Go
    def test_go_test_file(self):
        assert _is_test_file("server_test.go")
        assert _is_test_file("pkg/handler_test.go")

    def test_go_non_test_file(self):
        assert not _is_test_file("server.go")

    # Rust
    def test_rust_test_file(self):
        assert _is_test_file("lib_test.rs")
        assert _is_test_file("mod_test.rs")

    # C# / .NET
    def test_csharp_test_file(self):
        assert _is_test_file("UserTests.cs")
        assert _is_test_file("LoginTest.cs")

    # Ruby
    def test_ruby_spec(self):
        assert _is_test_file("user_spec.rb")
        assert _is_test_file("user_test.rb")

    # -- Non-test files (should return False) --

    def test_source_files_not_test(self):
        assert not _is_test_file("src/main.py")
        assert not _is_test_file("lib/helpers.py")
        assert not _is_test_file("app/models/user.rb")

    def test_source_dirs_not_test(self):
        assert not _is_test_file("src/foo.py")
        assert not _is_test_file("lib/bar.js")
        assert not _is_test_file("pkg/server.go")

    def test_false_positives_avoided(self):
        assert not _is_test_file("models/testimonial.rb")
        assert not _is_test_file("protest.py")
        assert not _is_test_file("contest.js")
        assert not _is_test_file("latest_news.md")
        assert not _is_test_file("testament.txt")

    def test_empty_path(self):
        assert not _is_test_file("")

    def test_file_without_extension(self):
        assert not _is_test_file("src/run")

    # -- Edge cases --

    def test_test_in_middle_of_path(self):
        assert _is_test_file("projects/myapp/test/integration/user.go")

    def test_case_insensitivity_on_dirs(self):
        assert _is_test_file("TESTs/foo.py")
        assert _is_test_file("Spec/api.rb")

    def test_case_insensitivity_on_filenames(self):
        assert _is_test_file("FOOTEST.java")


class TestGenerateSourceTestHint:
    """Tests for _generate_source_test_hint."""

    def _node(self, file_path, kind="function"):
        return ("id", 0.5, {"file_path": file_path, "kind": kind})

    def test_all_source_no_hint(self):
        hint = _generate_source_test_hint([
            self._node("src/a.py"),
            self._node("src/b.py"),
            self._node("src/c.py"),
            self._node("src/d.py"),
        ])
        assert hint == ""

    def test_all_tests_no_hint(self):
        hint = _generate_source_test_hint([
            self._node("tests/test_a.py"),
            self._node("tests/test_b.py"),
            self._node("tests/test_c.py"),
            self._node("tests/test_d.py"),
        ])
        assert hint == ""

    def test_too_few_results_no_hint(self):
        hint = _generate_source_test_hint([
            self._node("src/a.py"),
            self._node("tests/test_a.py"),
        ])
        assert hint == ""

    def test_tests_dominate(self):
        hint = _generate_source_test_hint([
            self._node("src/a.py"),
            self._node("tests/test_a.py"),
            self._node("tests/test_b.py"),
            self._node("tests/test_c.py"),
            self._node("tests/test_d.py"),
            self._node("tests/test_e.py"),
        ])
        assert "test" in hint.lower()
        assert hint != ""

    def test_sources_dominate(self):
        hint = _generate_source_test_hint([
            self._node("src/a.py"),
            self._node("src/b.py"),
            self._node("src/c.py"),
            self._node("src/d.py"),
            self._node("tests/test_a.py"),
        ])
        assert "source" in hint.lower()
        assert hint != ""

    def test_equal_split(self):
        hint = _generate_source_test_hint([
            self._node("src/a.py"),
            self._node("src/b.py"),
            self._node("tests/test_a.py"),
            self._node("tests/test_b.py"),
        ])
        assert "source" in hint.lower()
        assert hint != ""


class TestHybridSearchTestPenalty:
    """Integration tests for test file penalty in hybrid_search."""

    def _clear(self):
        from codeloom.query.hybrid import clear_search_cache
        clear_search_cache()

    def test_penalise_tests_demotes_test_files(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/handler.py:1", kind="function", file_path="src/handler.py",
                    label="handle", start_line=1)
        G.add_node("tests/test_handler.py:1", kind="function",
                    file_path="tests/test_handler.py", label="test_handle", start_line=1)
        G.add_node("tests/test_utils.py:1", kind="function",
                    file_path="tests/test_utils.py", label="test_utils", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("tests/test_handler.py:1", 0.95),
            ("src/handler.py:1", 0.90),
            ("tests/test_utils.py:1", 0.85),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            # With penalty (default)
            result = hybrid_search("handler", mock_store, G, top_k=10,
                                    penalise_tests=True)
            all_seeds = [n for n in result.nodes if n.source == "seed"]
            all_seeds += [n for n in result.isolated if n.source == "seed"]
            # Source file should rank higher than tests despite lower initial score
            assert all_seeds[0].node_id == "src/handler.py:1"

    def test_penalise_tests_disabled(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/handler.py:1", kind="function", file_path="src/handler.py",
                    label="handle", start_line=1)
        G.add_node("tests/test_handler.py:1", kind="function",
                    file_path="tests/test_handler.py", label="test_handle", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("tests/test_handler.py:1", 0.95),
            ("src/handler.py:1", 0.90),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            # Without penalty — test retains its higher rank
            result = hybrid_search("handler", mock_store, G, top_k=10,
                                    penalise_tests=False)
            all_seeds = [n for n in result.nodes if n.source == "seed"]
            all_seeds += [n for n in result.isolated if n.source == "seed"]
            assert all_seeds[0].node_id == "tests/test_handler.py:1"

    def test_penalise_tests_all_tests_shuffled(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        for i in range(11):
            G.add_node(f"tests/test_{i}.py:{i}", kind="function",
                        file_path=f"tests/test_{i}.py", label=f"test_{i}", start_line=i)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (f"tests/test_{i}.py:{i}", 0.95 - i * 0.05) for i in range(11)
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("test", mock_store, G, top_k=5,
                                    penalise_tests=True)
            seeds = [n for n in result.nodes if n.source == "seed"]
            assert len(seeds) <= 5
            # All results are test files; penalty still applies but all are tests
            for s in seeds:
                assert s.file_path.startswith("tests/")

    def test_penalise_tests_generates_hint(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        # 1 source, 5 test files — tests dominate
        G.add_node("src/handler.py:1", kind="function", file_path="src/handler.py",
                    label="handle", start_line=1)
        for i in range(5):
            G.add_node(f"tests/test_{i}.py:{i}", kind="function",
                        file_path=f"tests/test_{i}.py", label=f"test_{i}", start_line=i)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("src/handler.py:1", 0.95),
        ] + [(f"tests/test_{i}.py:{i}", 0.90 - i * 0.05) for i in range(5)]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("find", mock_store, G, top_k=10,
                                    penalise_tests=True)
            # Should include a hint about test/source mix
            assert "test" in result.hint.lower()

    def test_penalise_tests_disabled_no_hint(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/handler.py:1", kind="function", file_path="src/handler.py",
                    label="handle", start_line=1)
        for i in range(5):
            G.add_node(f"tests/test_{i}.py:{i}", kind="function",
                        file_path=f"tests/test_{i}.py", label=f"test_{i}", start_line=i)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("src/handler.py:1", 0.95),
        ] + [(f"tests/test_{i}.py:{i}", 0.90 - i * 0.05) for i in range(5)]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            # Without penalty — no source/test hint generated
            result = hybrid_search("find", mock_store, G, top_k=10,
                                    penalise_tests=False)
            assert "test" not in result.hint.lower()

    def test_penalty_factor_is_0_3(self):
        assert TEST_PENALTY_FACTOR == 0.3

    def test_test_score_multiplied_by_penalty(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("tests/test_a.py:1", kind="function",
                    file_path="tests/test_a.py", label="test_a", start_line=1)
        G.add_node("tests/test_b.py:1", kind="function",
                    file_path="tests/test_b.py", label="test_b", start_line=1)
        G.add_node("tests/test_c.py:1", kind="function",
                    file_path="tests/test_c.py", label="test_c", start_line=1)
        G.add_node("src/real.py:1", kind="function",
                    file_path="src/real.py", label="real", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("tests/test_a.py:1", 0.99),
            ("tests/test_b.py:1", 0.98),
            ("tests/test_c.py:1", 0.97),
            ("src/real.py:1", 0.50),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("target", mock_store, G, top_k=10,
                                    penalise_tests=True)
            all_seeds = [n for n in result.nodes if n.source == "seed"]
            all_seeds += [n for n in result.isolated if n.source == "seed"]
            seed_ids = {n.node_id for n in all_seeds}
            # Source file should push ahead of at least one high-score test
            assert "src/real.py:1" in seed_ids
            # Source file should rank first after test penalty
            assert all_seeds[0].node_id == "src/real.py:1"

    def test_penalise_tests_with_kind_filter(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/handler.py:1", kind="function", file_path="src/handler.py",
                    label="handle", start_line=1)
        G.add_node("tests/test_handler.py:1", kind="class",
                    file_path="tests/test_handler.py", label="TestHandler", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("tests/test_handler.py:1", 0.95),
            ("src/handler.py:1", 0.90),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            # Filter by kind=function — test file is a class, should be excluded
            result = hybrid_search("handler", mock_store, G, top_k=10,
                                    penalise_tests=True, kind="function")
            seed_ids = {n.node_id for n in result.nodes if n.source == "seed"}
            assert "src/handler.py:1" in seed_ids
            assert "tests/test_handler.py:1" not in seed_ids

    def test_penalise_tests_with_file_filter(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node("src/api/handler.py:1", kind="function", file_path="src/api/handler.py",
                    label="handle", start_line=1)
        G.add_node("tests/test_api.py:1", kind="function",
                    file_path="tests/test_api.py", label="test_api", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            ("tests/test_api.py:1", 0.95),
            ("src/api/handler.py:1", 0.90),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            # File filter excludes test file entirely
            result = hybrid_search("api", mock_store, G, top_k=10,
                                    penalise_tests=True, file_pattern="src/api/*")
            seed_ids = {n.node_id for n in result.nodes if n.source == "seed"}
            assert "src/api/handler.py:1" in seed_ids
            assert "tests/test_api.py:1" not in seed_ids


class TestReadSnippet:
    """Tests for _read_snippet helper."""

    def test_reads_first_5_lines(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
        snippet = _read_snippet(str(f), start_line=1)
        assert snippet is not None
        assert "def foo" in snippet
        assert snippet.endswith("pass")

    def test_respects_max_lines_default_5(self, tmp_path):
        f = tmp_path / "b.py"
        content = "\n".join(f"line {i}" for i in range(1, 11))
        f.write_text(content)
        snippet = _read_snippet(str(f), start_line=3)
        assert snippet is not None
        assert snippet.count("\n") == 4  # 5 lines = 4 newlines

    def test_respects_end_line_boundary(self, tmp_path):
        f = tmp_path / "c.py"
        content = "\n".join(f"line {i}" for i in range(1, 11))
        f.write_text(content)
        snippet = _read_snippet(str(f), start_line=3, end_line=5)
        assert snippet is not None
        assert snippet.count("\n") == 2  # lines 3, 4, 5 = 3 lines

    def test_end_line_after_max_lines(self, tmp_path):
        f = tmp_path / "d.py"
        content = "\n".join(f"line {i}" for i in range(1, 11))
        f.write_text(content)
        snippet = _read_snippet(str(f), start_line=3, end_line=20)
        assert snippet is not None
        assert snippet.count("\n") == 4  # capped at 5 lines

    def test_returns_none_for_missing_file(self):
        assert _read_snippet("/nonexistent/file.py", start_line=1) is None

    def test_returns_none_for_empty_path(self):
        assert _read_snippet("", start_line=1) is None

    def test_returns_none_for_zero_start_line(self):
        assert _read_snippet("some/file.py", start_line=0) is None

    def test_returns_none_for_start_line_beyond_eof(self, tmp_path):
        f = tmp_path / "e.py"
        f.write_text("single line\n")
        assert _read_snippet(str(f), start_line=100) is None

    def test_strips_trailing_newlines(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("def foo():\n    pass\n\n\n")
        snippet = _read_snippet(str(f), start_line=1)
        assert snippet is not None
        assert not snippet.endswith("\n")

    def test_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "g.py"
        f.write_text("")
        assert _read_snippet(str(f), start_line=1) is None

    def test_single_line_file(self, tmp_path):
        f = tmp_path / "h.py"
        f.write_text("x = 1")
        snippet = _read_snippet(str(f), start_line=1)
        assert snippet == "x = 1"

    def test_start_line_mid_file(self, tmp_path):
        f = tmp_path / "i.py"
        f.write_text("a\nb\nc\nd\ne\nf\ng\n")
        snippet = _read_snippet(str(f), start_line=4)
        assert snippet == "d\ne\nf\ng"


class TestSearchResultWithSnippet:
    """Tests for SearchResult context_snippet field."""

    def test_default_is_empty_string(self):
        sr = SearchResult(
            node_id="a.py:1", label="fn", kind="function",
            file_path="a.py", score=0.5, source="seed",
        )
        assert sr.context_snippet == ""

    def test_snippet_preserved(self):
        sr = SearchResult(
            node_id="a.py:1", label="fn", kind="function",
            file_path="a.py", score=0.5, source="seed",
            context_snippet="def fn():\n    pass",
        )
        assert sr.context_snippet == "def fn():\n    pass"

    def test_snippet_in_json_output(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="a.py:1", label="fn", kind="function",
                             file_path="a.py", score=0.5, source="seed",
                             start_line=1,
                             context_snippet="def fn():\n    pass"),
            ],
            edges=[], isolated=[],
        )
        seed = sg.to_json()["seeds"][0]
        assert seed["snippet"] == "def fn():\n    pass"

    def test_omits_snippet_key_when_empty(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="a.py:1", label="fn", kind="function",
                             file_path="a.py", score=0.5, source="seed",
                             start_line=1, context_snippet=""),
            ],
            edges=[], isolated=[],
        )
        seed = sg.to_json()["seeds"][0]
        assert "snippet" not in seed


class TestSearchGraphSnippetOutput:
    """Tests for snippet rendering in to_text and to_json."""

    def test_to_text_shows_snippet_with_pipe_prefix(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="a.py:1", label="fn", kind="function",
                             file_path="a.py", score=0.5, source="seed",
                             context_snippet="def fn():\n    pass"),
            ],
            edges=[], isolated=[],
        )
        text = sg.to_text()
        assert "def fn()" in text
        assert "  │ def fn()" in text
        assert "  │     pass" in text

    def test_to_text_without_snippet_stays_clean(self):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="a.py:1", label="fn", kind="function",
                             file_path="a.py", score=0.5, source="seed",
                             context_snippet=""),
            ],
            edges=[], isolated=[],
        )
        text = sg.to_text()
        assert "a.py:1" in text
        assert "│" not in text

    def test_to_text_multiline_snippet(self, tmp_path):
        sg = SearchGraph(
            nodes=[
                SearchResult(node_id="a.py:1", label="fn", kind="function",
                             file_path="a.py", score=0.5, source="seed",
                             context_snippet="line1\nline2\nline3"),
            ],
            edges=[], isolated=[],
        )
        text = sg.to_text()
        lines = text.split("\n")
        assert lines[1] == "a.py:1 (score: 0.5)"
        assert lines[2] == "  │ line1"
        assert lines[3] == "  │ line2"
        assert lines[4] == "  │ line3"


class TestHybridSearchSnippets:
    """Integration tests for snippet_count in hybrid_search."""

    def _clear(self):
        from codeloom.query.hybrid import clear_search_cache
        clear_search_cache()

    def _write_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_snippet_count_zero_no_snippets(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        self._write_file(tmp_path / "src" / "a.py", "def foo():\n    return 1\n")

        G = nx.DiGraph()
        G.add_node(str(tmp_path / "src/a.py:1"), kind="function",
                    file_path=str(tmp_path / "src/a.py"), label="foo", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (str(tmp_path / "src/a.py:1"), 0.9),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("foo", mock_store, G, top_k=10, snippet_count=0)
            for node in result.nodes:
                if node.source == "seed":
                    assert node.context_snippet == ""

    def test_snippet_count_3_populates_top_seeds(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        self._write_file(tmp_path / "a.py", "def one():\n    return 1\n")
        self._write_file(tmp_path / "b.py", "def two():\n    return 2\n")
        self._write_file(tmp_path / "c.py", "def three():\n    return 3\n")
        self._write_file(tmp_path / "d.py", "def four():\n    return 4\n")

        G = nx.DiGraph()
        G.add_node(str(tmp_path / "a.py:1"), kind="function",
                    file_path=str(tmp_path / "a.py"), label="one", start_line=1)
        G.add_node(str(tmp_path / "b.py:1"), kind="function",
                    file_path=str(tmp_path / "b.py"), label="two", start_line=1)
        G.add_node(str(tmp_path / "c.py:1"), kind="function",
                    file_path=str(tmp_path / "c.py"), label="three", start_line=1)
        G.add_node(str(tmp_path / "d.py:1"), kind="function",
                    file_path=str(tmp_path / "d.py"), label="four", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (str(tmp_path / "a.py:1"), 0.9),
            (str(tmp_path / "b.py:1"), 0.8),
            (str(tmp_path / "c.py:1"), 0.7),
            (str(tmp_path / "d.py:1"), 0.6),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("functions", mock_store, G, top_k=10, snippet_count=3)
            all_seeds = [n for n in result.nodes if n.source == "seed"]
            all_seeds += [n for n in result.isolated if n.source == "seed"]
            populated = [s for s in all_seeds if s.context_snippet]
            assert len(populated) == 3
            assert "def one" in all_seeds[0].context_snippet
            assert "def two" in all_seeds[1].context_snippet
            assert "def three" in all_seeds[2].context_snippet
            assert all_seeds[3].context_snippet == ""

    def test_snippet_count_greater_than_available_seeds(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        self._write_file(tmp_path / "a.py", "def one():\n    return 1\n")

        G = nx.DiGraph()
        G.add_node(str(tmp_path / "a.py:1"), kind="function",
                    file_path=str(tmp_path / "a.py"), label="one", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (str(tmp_path / "a.py:1"), 0.9),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("one", mock_store, G, top_k=10, snippet_count=5)
            seeds = [n for n in result.nodes if n.source == "seed"]
            # Should populate the only available seed
            assert len(seeds) == 1
            assert "def one" in seeds[0].context_snippet

    def test_path_nodes_never_get_snippets(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        self._write_file(tmp_path / "a.py", "def a():\n    return 1\n")
        self._write_file(tmp_path / "b.py", "def b():\n    return 2\n")

        G = nx.DiGraph()
        a = str(tmp_path / "a.py:1")
        b = str(tmp_path / "b.py:1")
        G.add_node(a, kind="function", file_path=str(tmp_path / "a.py"),
                    label="a_fn", start_line=1)
        G.add_node(b, kind="function", file_path=str(tmp_path / "b.py"),
                    label="b_fn", start_line=1)
        G.add_edge(a, b, relation="calls")

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (a, 0.9),
            (b, 0.8),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("functions", mock_store, G, top_k=10, snippet_count=5)
            for node in result.nodes:
                if node.source == "path":
                    assert node.context_snippet == ""

    def test_snippet_in_to_text_format(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        self._write_file(tmp_path / "a.py", "def foo():\n    pass\n")

        G = nx.DiGraph()
        G.add_node(str(tmp_path / "a.py:1"), kind="function",
                    file_path=str(tmp_path / "a.py"), label="foo", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (str(tmp_path / "a.py:1"), 0.9),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("foo", mock_store, G, top_k=10, snippet_count=3)
            text = result.to_text()
            assert "  │ def foo()" in text
            assert "  │     pass" in text

    def test_missing_file_snippet_is_empty(self, tmp_path):
        self._clear()
        from unittest.mock import MagicMock, patch

        import networkx as nx

        G = nx.DiGraph()
        G.add_node(str(tmp_path / "missing.py:1"), kind="function",
                    file_path=str(tmp_path / "missing.py"), label="gone", start_line=1)

        mock_store = MagicMock()
        mock_store.vector_search.return_value = [
            (str(tmp_path / "missing.py:1"), 0.9),
        ]
        mock_store.keyword_search.return_value = []
        mock_store.community_search.return_value = []

        with patch("codeloom.query.embeddings.embed_query_dual") as mock_eq:
            mock_eq.return_value = {"code": None, "text": None}

            from codeloom.query.hybrid import hybrid_search

            result = hybrid_search("gone", mock_store, G, top_k=10, snippet_count=3)
            seeds = [n for n in result.nodes if n.source == "seed"]
            assert len(seeds) == 1
            assert seeds[0].context_snippet == ""
