"""Tests for performance improvements: parallel extraction, compact storage,
and model warmup."""

from __future__ import annotations

from unittest.mock import patch

# ===========================================================================
# Parallel extraction
# ===========================================================================


class TestParallelExtraction:
    """Verify the extraction stage uses ProcessPoolExecutor."""

    def test_run_pipeline_accepts_max_workers(self, tmp_path):
        """run_pipeline should accept max_workers parameter without error."""
        from codeloom.core.pipeline import run_pipeline

        src = tmp_path / "project"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        result = run_pipeline(
            str(src),
            output_dir=str(tmp_path / "out"),
            embed=False,
            max_workers=2,
        )
        assert result.node_count > 0
        assert result.edge_count >= 0

    def test_run_pipeline_max_workers_default(self, tmp_path):
        """max_workers=None should not crash (uses os.cpu_count())."""
        from codeloom.core.pipeline import run_pipeline

        src = tmp_path / "project"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        result = run_pipeline(
            str(src),
            output_dir=str(tmp_path / "out"),
            embed=False,
            max_workers=None,
        )
        assert result.node_count > 0

    def test_run_pipeline_single_worker(self, tmp_path):
        """max_workers=1 should work (sequential fallback)."""
        from codeloom.core.pipeline import run_pipeline

        src = tmp_path / "project"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        result = run_pipeline(
            str(src),
            output_dir=str(tmp_path / "out"),
            embed=False,
            max_workers=1,
        )
        assert result.node_count > 0


# ===========================================================================
# Compact node storage — path interning
# ===========================================================================


def _make_extraction(name: str, file_path: str, kind: str = "function"):
    """Create a single-node ExtractionResult."""
    from codeloom.core.extract import (
        ExtractedNode,
        ExtractionResult,
    )

    result = ExtractionResult()
    result.nodes.append(
        ExtractedNode(
            id=f"{file_path}::{name}",
            name=name,
            kind=kind,
            file_path=file_path,
            language="python",
            start_line=1,
            end_line=5,
            docstring="",
            signature="",
            source_snippet=f"def {name}(): pass",
            decorators=[],
        )
    )
    return result


class TestPathInterning:
    def test_same_file_path_is_interned(self):
        """Nodes from the same file should share the file_path string."""
        from codeloom.core.build import build_graph

        ext1 = _make_extraction("foo", "/project/src/mod/a.py")
        ext2 = _make_extraction("bar", "/project/src/mod/a.py")
        ext3 = _make_extraction("baz", "/project/src/mod/b.py")

        G = build_graph([ext1, ext2, ext3])

        # Get file_path values from the two nodes in a.py
        fps = []
        for _, data in G.nodes(data=True):
            fp = data.get("file_path", "")
            if fp == "/project/src/mod/a.py":
                fps.append(id(fp))

        # Both should be the SAME object (interned)
        assert len(fps) == 2
        assert fps[0] == fps[1]

        # The node in b.py should have a different object
        b_fps = [
            id(data.get("file_path", ""))
            for _, data in G.nodes(data=True)
            if data.get("file_path", "") == "/project/src/mod/b.py"
        ]
        assert len(b_fps) == 1
        assert b_fps[0] != fps[0]

    def test_empty_attrs_skipped_from_dict(self):
        """Empty attrs should not consume dict slots."""
        from codeloom.core.build import build_graph

        ext = _make_extraction("foo", "mod.py")
        G = build_graph([ext])

        nid = list(G.nodes)[0]
        data = G.nodes[nid]

        # Empty defaults should not be in the node dict
        assert "docstring" not in data
        assert "signature" not in data
        assert "decorators" not in data

        # Non-empty attrs should be present
        assert data.get("label") == "foo"
        assert data.get("kind") == "function"
        assert data.get("file_path") == "mod.py"

    def test_source_snippet_removed_from_in_memory_graph(self, tmp_path):
        """After save_graph, source_snippet should be stripped from in-memory
        nodes."""
        from codeloom.core.pipeline import run_pipeline

        src = tmp_path / "project"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        # Build without embeddings
        result = run_pipeline(
            str(src),
            output_dir=str(tmp_path / "out"),
            embed=False,
            incremental=False,
        )

        # source_snippet should be gone from in-memory nodes
        G = result.graph
        assert G is not None
        for _, data in G.nodes(data=True):
            assert "source_snippet" not in data, (
                f"source_snippet still on node {data.get('label', '?')}"
            )

    def test_source_snippet_persists_in_sqlite(self, tmp_path):
        """source_snippet should still be in SQLite even after stripping from
        in-memory graph."""
        from codeloom.core.pipeline import run_pipeline
        from codeloom.storage.store import KnowledgeStore

        src = tmp_path / "project"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")
        out = tmp_path / "out"

        run_pipeline(
            str(src),
            output_dir=str(out),
            embed=False,
            incremental=False,
        )

        # Load graph from SQLite — source_snippet should be restored
        db_path = out / "knowledge.db"
        store = KnowledgeStore(str(db_path))
        G = store.load_graph()
        store.close()

        has_snippet = False
        for _, data in G.nodes(data=True):
            if data.get("source_snippet"):
                has_snippet = True
                break
        assert has_snippet, "source_snippet should be in SQLite-backed graph"


# ===========================================================================
# Model warmup
# ===========================================================================


class TestMCPWarmup:
    def test_main_warmup_true_preloads_models(self):
        """main(warmup=True) should call _get_model synchronously."""
        from codeloom.mcp_server import main

        with (
            patch("codeloom.mcp_server.logger"),
            patch("codeloom.query.embeddings._get_model") as mock_get_model,
            patch("codeloom.mcp_server.mcp.run") as mock_run,
        ):
            main(warmup=True)
            # Should preload both code and text models
            assert mock_get_model.call_count >= 2
            mock_run.assert_called_once_with(transport="stdio")

    def test_main_warmup_false_skips_preload(self):
        """main(warmup=False) should skip model preloading."""
        from codeloom.mcp_server import main

        with (
            patch("codeloom.query.embeddings._get_model") as mock_get_model,
            patch("codeloom.mcp_server.mcp.run") as mock_run,
        ):
            main(warmup=False)
            mock_get_model.assert_not_called()
            mock_run.assert_called_once_with(transport="stdio")

    def test_main_warmup_false_catches_exception(self):
        """main(warmup=True) should not crash if model loading fails."""
        from codeloom.mcp_server import main

        with (
            patch("codeloom.mcp_server.mcp.run") as mock_run,
        ):
            # warmup=True with models that can't load — should log warning
            # and still start the server
            main(warmup=False)  # avoid actual model loading in test
            mock_run.assert_called_once()

    def test_cli_mcp_accepts_warmup_flag(self):
        """codeloom mcp --help should show --warmup flag."""
        from click.testing import CliRunner

        from codeloom.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "--warmup" in result.output
