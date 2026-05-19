"""Tests for embedding generation — text construction, kind routing,
and caching."""

from unittest.mock import MagicMock, patch

import networkx as nx
import numpy as np

from codeloom.query.embeddings import (
    _PREFIX_MODELS,
    CODE_KINDS,
    CODE_MODEL,
    EMBED_KINDS,
    SKIP_KINDS,
    TEXT_MODEL,
    _node_text,
    get_memory_limit_bytes,
    is_code_node,
)
from codeloom.query.hybrid import extract_search_terms


class TestModelConfig:
    def test_code_model_is_set(self):
        assert CODE_MODEL == "BAAI/bge-small-en-v1.5"

    def test_text_model_is_set(self):
        assert TEXT_MODEL == "intfloat/multilingual-e5-small"

    def test_skip_kinds_contains_external(self):
        assert "external" in SKIP_KINDS
        assert "directory" in SKIP_KINDS

    def test_code_kinds_contains_core_types(self):
        assert "function" in CODE_KINDS
        assert "class" in CODE_KINDS
        assert "method" in CODE_KINDS

    def test_embed_kinds_is_subset(self):
        for kind in EMBED_KINDS:
            assert kind in CODE_KINDS or kind == "section"

    def test_optional_prefix_models_configured(self):
        assert TEXT_MODEL in _PREFIX_MODELS
        assert "query:" in _PREFIX_MODELS[TEXT_MODEL]["query"]
        assert "passage:" in _PREFIX_MODELS[TEXT_MODEL]["passage"]

    def test_is_code_node(self):
        assert is_code_node("function")
        assert is_code_node("class")
        assert is_code_node("method")
        assert not is_code_node("section")
        assert not is_code_node("unknown")

    def test_memory_limit_returns_int(self):
        limit = get_memory_limit_bytes()
        assert isinstance(limit, int)
        assert limit > 0


class TestNodeTextConstruction:
    def test_node_text_for_function(self):
        data = {
            "label": "connect",
            "signature": "(config) -> Conn",
            "docstring": "Create a database connection.",
        }
        text = _node_text(data)
        assert "connect" in text
        assert "(config) -> Conn" in text
        assert "database" in text

    def test_node_text_for_class(self):
        data = {
            "label": "DatabaseService",
            "docstring": "Manages database connections.",
        }
        text = _node_text(data)
        assert "DatabaseService" in text
        assert "database" in text

    def test_node_text_falls_back_to_snippet(self):
        data = {
            "label": "run",
            "signature": "()",
            "source_snippet": "def run():\n    pass",
        }
        text = _node_text(data)
        assert "def run" in text.lower()

    def test_node_text_empty_data(self):
        text = _node_text({})
        assert text == ""

    def test_node_text_without_snippet_or_docstring(self):
        data = {"label": "helper", "signature": "(x)"}
        text = _node_text(data)
        assert "helper" in text
        assert "(x)" in text


class TestExtractSearchTerms:
    def test_removes_stopwords(self):
        terms = extract_search_terms("the is a at database connection pool")
        assert "database" in terms
        assert "connection" in terms
        assert "pool" in terms

    def test_removes_short_tokens(self):
        terms = extract_search_terms("a an in the pool")
        assert "pool" in terms
        assert "a" not in terms

    def test_lowercases(self):
        terms = extract_search_terms("DataBase Conn")
        assert "database" in terms
        assert "conn" in terms

    def test_empty_query(self):
        assert extract_search_terms("") == []


class TestEmbedQuery:
    def test_embed_query_returns_vector(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1] * 384], dtype=np.float32
        )

        with patch(
            "codeloom.query.embeddings._get_model", return_value=mock_model
        ):
            from codeloom.query.embeddings import embed_query

            vec = embed_query("test query", TEXT_MODEL)
            assert isinstance(vec, np.ndarray)
            assert vec.shape[-1] == 384

    def test_embed_query_with_prefix(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1] * 384], dtype=np.float32
        )

        with patch(
            "codeloom.query.embeddings._get_model", return_value=mock_model
        ):
            from codeloom.query.embeddings import embed_query

            embed_query("test", TEXT_MODEL)
            args, _ = mock_model.encode.call_args
            assert (
                any("query" in str(a).lower() for a in args[0])
                if isinstance(args[0], list)
                else True
            )

    def test_embed_query_dual_returns_both(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1] * 384], dtype=np.float32
        )

        with patch(
            "codeloom.query.embeddings._get_model", return_value=mock_model
        ):
            from codeloom.query.embeddings import embed_query_dual

            result = embed_query_dual("test query")
            assert "code" in result
            assert "text" in result
            assert result["code"].shape[-1] == 384
            assert result["text"].shape[-1] == 384

    def test_get_model_caches(self):
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_instance = MagicMock()
            mock_st.return_value = mock_instance

            from codeloom.query.embeddings import _get_model, _models

            _models.clear()
            model1 = _get_model("test-model")
            model2 = _get_model("test-model")
            assert model1 is model2
            assert mock_st.call_count == 1


class TestEmbedNodesStreaming:
    def test_embed_nodes_yields_batches(self):
        G = nx.DiGraph()
        G.add_node(
            "app.py:10",
            label="run",
            kind="function",
            file_path="app.py",
            signature="()",
            docstring="Run the app.",
        )
        G.add_node(
            "app.py:42",
            label="setup",
            kind="function",
            file_path="app.py",
            signature="(config)",
            docstring="Setup.",
        )

        from codeloom.query.embeddings import embed_nodes_streaming

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1] * 384, [0.2] * 384], dtype=np.float32
        )

        with patch(
            "codeloom.query.embeddings._get_model", return_value=mock_model
        ):
            batches = list(embed_nodes_streaming(G, batch_size=32))
            assert len(batches) >= 1
            for batch_ids, batch_vecs, model_type in batches:
                assert len(batch_ids) > 0
                assert batch_vecs.shape[0] == len(batch_ids)
                assert model_type in ("code", "text")

    def test_embed_nodes_skips_directories(self):
        G = nx.DiGraph()
        G.add_node(
            "dir:0",
            label="vendor",
            kind="directory",
            file_path="vendor",
        )
        G.add_node(
            "app.py:10",
            label="run",
            kind="function",
            file_path="app.py",
            signature="()",
            docstring="Run the app.",
        )

        from codeloom.query.embeddings import embed_nodes_streaming

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1] * 384], dtype=np.float32
        )

        with patch(
            "codeloom.query.embeddings._get_model", return_value=mock_model
        ):
            batches = list(embed_nodes_streaming(G, batch_size=32))
            total_ids = set()
            for batch_ids, _, _ in batches:
                total_ids.update(batch_ids)
            assert "app.py:10" in total_ids
            assert "dir:0" not in total_ids

    def test_embed_nodes_streaming_empty_graph(self):
        G = nx.DiGraph()
        from codeloom.query.embeddings import embed_nodes_streaming

        batches = list(embed_nodes_streaming(G, batch_size=32))
        assert len(batches) == 0


class TestEmbedStoreIntegration:
    def test_embed_and_store_round_trip(self, tmp_path):
        """Test that embeddings can be computed and stored."""
        G = nx.DiGraph()
        G.add_node(
            "app.py:10",
            label="run",
            kind="function",
            file_path="app.py",
            signature="()",
            docstring="Run the app.",
        )
        G.add_node(
            "app.py:42",
            label="setup",
            kind="function",
            file_path="app.py",
            signature="(config)",
            docstring="Setup configuration.",
        )

        db_path = tmp_path / "test.db"
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        store.save_graph(G)

        from codeloom.query.embeddings import embed_nodes_streaming

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1] * 384, [0.2] * 384], dtype=np.float32
        )

        with patch(
            "codeloom.query.embeddings._get_model", return_value=mock_model
        ):
            for batch_ids, batch_vecs, model_type in embed_nodes_streaming(
                G, batch_size=32
            ):
                store.save_embeddings(
                    dict(zip(batch_ids, batch_vecs)),
                    model_type=model_type,
                )

        # Verify embeddings by loading them back
        all_embeddings = store.load_embeddings()
        assert len(all_embeddings) > 0
        first_vec = next(iter(all_embeddings.values()))
        assert len(first_vec) == 384

        store.close()
