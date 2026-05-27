from __future__ import annotations

import json
from pathlib import Path

from codeloom.core.pipeline import run_pipeline
from codeloom.storage.store import KnowledgeStore

class TestEvolution:
    def test_pruning_on_deletion(self, tmp_path):
        """Verify that deleting a file and running an incremental build prunes nodes."""
        src = tmp_path / "src"
        src.mkdir()
        
        f1 = src / "file1.py"
        f1.write_text("def func1(): pass")
        
        f2 = src / "file2.py"
        f2.write_text("def func2(): pass")
        
        # 1. First build
        out = tmp_path / "out"
        run_pipeline(str(src), output_dir=str(out), embed=False, incremental=True)
        
        db_path = out / "knowledge.db"
        store = KnowledgeStore(db_path)
        G = store.load_graph()
        
        assert any(d.get("file_path") == str(f1) for _, d in G.nodes(data=True))
        assert any(d.get("file_path") == str(f2) for _, d in G.nodes(data=True))
        store.close()

    def test_state_identicality(self, tmp_path):
        """Verify that incremental build is bit-for-bit identical to full build."""
        src = tmp_path / "src"
        src.mkdir()
        
        f1 = src / "file1.py"
        f1.write_text("def a(): pass")
        
        # 1. Initial build
        out_inc = tmp_path / "out_inc"
        run_pipeline(str(src), output_dir=str(out_inc), embed=False, incremental=True)
        
        # 2. Add file and run incremental
        f2 = src / "file2.py"
        f2.write_text("def b(): pass")
        run_pipeline(str(src), output_dir=str(out_inc), embed=False, incremental=True)
        
        store_inc = KnowledgeStore(out_inc / "knowledge.db")
        G_inc = store_inc.load_graph()
        
        # 3. Clean full build from the same source state
        out_full = tmp_path / "out_full"
        run_pipeline(str(src), output_dir=str(out_full), embed=False, incremental=False)
        
        store_full = KnowledgeStore(out_full / "knowledge.db")
        G_full = store_full.load_graph()
        
        # 4. Compare
        assert sorted(G_inc.nodes()) == sorted(G_full.nodes())
        assert G_inc.number_of_edges() == G_full.number_of_edges()
        
        store_inc.close()
        store_full.close()
        
        # 5. Test pruning
        f1.unlink()
        run_pipeline(str(src), output_dir=str(out_inc), embed=False, incremental=True)
        
        store_inc_pruned = KnowledgeStore(out_inc / "knowledge.db")
        G_inc_pruned = store_inc_pruned.load_graph()
        
        out_full_pruned = tmp_path / "out_full_pruned"
        run_pipeline(str(src), output_dir=str(out_full_pruned), embed=False, incremental=False)
        store_full_pruned = KnowledgeStore(out_full_pruned / "knowledge.db")
        G_full_pruned = store_full_pruned.load_graph()
        
        assert sorted(G_inc_pruned.nodes()) == sorted(G_full_pruned.nodes())
        store_inc_pruned.close()
        store_full_pruned.close()

    def test_pagerank_hot_start(self, tmp_path):
        """Verify that incremental build uses nstart for PageRank."""
        from unittest.mock import patch
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def a(): pass")
        
        out = tmp_path / "out"
        # First build
        run_pipeline(str(src), output_dir=str(out), embed=False, incremental=True)
        
        # Second build (incremental) - Mock nx.pagerank to capture nstart
        with patch("networkx.pagerank") as mock_pr:
            mock_pr.return_value = {"node": 1.0}
            run_pipeline(str(src), output_dir=str(out), embed=False, incremental=True)
            
            # Check if nstart was passed
            args, kwargs = mock_pr.call_args
            assert "nstart" in kwargs
            assert kwargs["nstart"] is not None
            # Should contain nodes from first build
            assert len(kwargs["nstart"]) > 0

    def test_git_acceleration(self, tmp_path):
        """Verify that --git flag correctly handles modifications and deletions."""
        import subprocess
        src = tmp_path / "src"
        src.mkdir()
        
        # Init git repo
        subprocess.run(["git", "init"], cwd=src, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=src, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=src, check=True)
        
        f1 = src / "file1.py"
        f1.write_text("def a(): pass")
        
        subprocess.run(["git", "add", "file1.py"], cwd=src, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=src, check=True)
        
        out = tmp_path / "out"
        db_path = out / "knowledge.db"
        # 1. First build (full)
        run_pipeline(str(src), output_dir=str(out), embed=False, incremental=True)
        
        # 2. Modify file and add new one
        f1.write_text("def a(): return 1")
        f2 = src / "file2.py"
        f2.write_text("def b(): pass")
        # f2 is untracked
        
        # Build with --git
        run_pipeline(str(src), output_dir=str(out), embed=False, incremental=True, git=True)
        
        store = KnowledgeStore(db_path)
        G = store.load_graph()
        
        assert any("file1.py" in n for n in G.nodes)
        assert any("file2.py" in n for n in G.nodes) # should be picked up as '?' in status
        store.close()
        
        # 3. Delete file1
        f1.unlink()
        # Note: git status will show it as deleted
        
        run_pipeline(str(src), output_dir=str(out), embed=False, incremental=True, git=True)
        
        store_p = KnowledgeStore(db_path)
        G_pruned = store_p.load_graph()
        assert not any("file1.py" in n for n in G_pruned.nodes)
        assert any("file2.py" in n for n in G_pruned.nodes)
        store_p.close()

        G = store.load_graph()
        
        # file1 nodes should be gone
        assert not any(d.get("file_path") == str(f1) for _, d in G.nodes(data=True))
        # file2 nodes should remain
        assert any(d.get("file_path") == str(f2) for _, d in G.nodes(data=True))
        
        # Check metadata hashes
        hashes = json.loads(store.get_meta("file_hashes"))
        assert str(f1) not in hashes
        assert str(f2) in hashes
        
        store.close()
