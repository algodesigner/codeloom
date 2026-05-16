"""Tests for hybrid search and RRF fusion."""

from codeloom.query.hybrid import (
    VALID_KINDS,
    SearchEdge,
    SearchGraph,
    SearchResult,
    _generate_filter_hint,
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
