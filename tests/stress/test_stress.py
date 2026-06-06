"""Stress test harness for codeloom at scale.

Generates synthetic repositories at various sizes and measures
build time, memory, and search latency.

Usage:
    pytest tests/stress/test_stress.py -v --benchmark-only

    SKIP_STRESS=1 pytest tests/stress/  # skip if no benchmark flag
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest

# Only run stress tests when explicitly requested
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_STRESS", "0") == "1"
    and "--benchmark-only" not in sys.argv,
    reason="Stress tests skipped. Use SKIP_STRESS=0 or --benchmark-only",
)

# Sizes to test
SIZES = [
    ("tiny", 10, 5),
    ("small", 100, 20),
]

if os.environ.get("FULL_STRESS"):
    SIZES += [
        ("medium", 1000, 50),
        ("large", 5000, 20),
    ]


def _generate_repo(path: Path, n_files: int, n_classes: int):
    """Generate a synthetic Python repo."""
    src = path / "src"
    src.mkdir(parents=True)

    for i in range(n_files):
        file_path = src / f"mod{i:04d}.py"
        with open(file_path, "w") as f:
            f.write(f'"""Module {i}."""\n\n')
            # Generate imports (chain dependencies)
            if i > 0:
                deps = [f"mod{j:04d}" for j in range(max(0, i - 3), i)]
                for d_idx, dep in enumerate(deps):
                    f.write(
                        f"from {dep} import Class{d_idx % n_classes}\n"
                    )
            f.write("\n\n")
            # Generate classes
            for c in range(n_classes):
                base = f"BaseClass{c}" if c > 0 else "object"
                f.write(f"class Class{c}({base}):\n")
                f.write(f'    """Class {c} in module {i}."""\n\n')
                f.write("    def method(self):\n")
                f.write('        """Example method."""\n')
                f.write("        pass\n\n")


@pytest.mark.parametrize("label, n_files, n_classes", SIZES)
def test_build_and_search(label, n_files, n_classes):
    """Measure build time and search latency on a synthetic repo."""
    tmp = Path(tempfile.mkdtemp(prefix=f"codeloom_stress_{label}_"))
    try:
        _generate_repo(tmp, n_files, n_classes)
        repo_root = tmp / "src"

        # Build
        from codeloom.core.pipeline import run_pipeline

        output_dir = tmp / ".codeloom"

        tracemalloc.start()
        t0 = time.perf_counter()
        # Disable embeddings for stress tests — they dominate build time
        # and are benchmarked separately. We measure here extraction +
        # graph construction + DB persistence.
        result = run_pipeline(
            str(repo_root),
            output_dir=str(output_dir),
            incremental=False,
            embed=False,
        )
        build_time = time.perf_counter() - t0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Print results for manual inspection
        print(
            f"\n--- Stress: {label} ({n_files} files, "
            f"{n_classes} classes) ---"
        )
        print(f"  Build time: {build_time:.2f}s")
        print(f"  Peak memory: {peak / 1024 / 1024:.1f} MB")
        print(f"  Nodes: {result.node_count}")
        print(f"  Edges: {result.edge_count}")
        print(f"  Files: {len(result.detect_result.files)}")

        # Assert basic health
        assert result.node_count > 0
        assert result.edge_count > 0
        assert build_time < 300  # Should never take > 5 min

        # Warm search
        from codeloom.query.hybrid import hybrid_search
        from codeloom.storage.store import KnowledgeStore

        db_path = output_dir / "knowledge.db"
        store = KnowledgeStore(str(db_path))
        G = store.load_graph()

        # Build vector index
        try:
            store.build_vector_index()
        except Exception:
            pass

        t0 = time.perf_counter()
        search_result = hybrid_search(
            "class method example",
            store,
            G,
            top_k=5,
            use_cache=False,
        )
        search_time = time.perf_counter() - t0
        print(f"  Search time: {search_time:.4f}s")
        print(f"  Search results: {len(search_result.nodes)}")

        store.close()
        assert search_time < 30  # Should never take > 30s

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
