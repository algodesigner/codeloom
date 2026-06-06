"""End-to-end integration test: real build + impact/dependencies.

Builds a small project using the actual pipeline, then calls
impact and dependencies on the result — no mocks.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import networkx as nx


def _make_project(src: Path) -> None:
    """Create a small project with call relationships."""
    (src / "math_ops.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def multiply(a, b):\n"
        "    return a * b\n"
    )
    (src / "calculator.py").write_text(
        "from math_ops import add, multiply\n"
        "\n"
        "def calculate(x, y):\n"
        "    s = add(x, y)\n"
        "    p = multiply(x, y)\n"
        "    return s, p\n"
    )
    (src / "main.py").write_text(
        "from calculator import calculate\n"
        "\n"
        "def run():\n"
        "    result = calculate(3, 4)\n"
        "    print(result)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    run()\n"
    )


def _load_graph_from_db(db_path: Path) -> nx.DiGraph:
    """Load graph from a pipeline-built database."""
    from codeloom.storage.store import KnowledgeStore

    store = KnowledgeStore(str(db_path))
    G = store.load_graph()
    store.close()
    return G


def _build_project(
    src: Path, tmp_path: Path, embed: bool = False
) -> Path:
    """Build a code graph for the project and return the db path."""
    from codeloom.core.pipeline import run_pipeline

    output_dir = tmp_path / ".codeloom"
    result = run_pipeline(
        str(src),
        output_dir=str(output_dir),
        embed=embed,
        incremental=False,
    )
    return Path(result.db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_e2e_impact_finds_callers(tmp_path):
    """Real build: impact('calculate') should show caller 'run'."""
    src = tmp_path / "project"
    src.mkdir()
    _make_project(src)
    db_path = _build_project(src, tmp_path, embed=False)

    G = _load_graph_from_db(db_path)

    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        mock_load.return_value = (store, G)
        result = impact("calculate", max_depth=2)

    assert "run" in result, (
        f"Expected 'run' in impact results for 'calculate', got: {result}"
    )
    assert "def run" in result or "function" in result.lower()
    store.close()


def test_e2e_impact_finds_transitive(tmp_path):
    """Real build: impact('add') should transitively include 'run'."""
    src = tmp_path / "project"
    src.mkdir()
    _make_project(src)
    db_path = _build_project(src, tmp_path, embed=False)

    G = _load_graph_from_db(db_path)

    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        mock_load.return_value = (store, G)
        # 'add' is called by 'calculate', which is called by 'run'
        result = impact("add", max_depth=3)

    assert "calculate" in result, (
        f"Expected 'calculate' in impact for 'add', got: {result}"
    )
    # run() transitively depends on add() via calculate()
    assert "run" in result


def test_e2e_dependencies_shows_upstream(tmp_path):
    """Real build: dependencies('run') should show calculate, add, multiply."""
    src = tmp_path / "project"
    src.mkdir()
    _make_project(src)
    db_path = _build_project(src, tmp_path, embed=False)

    G = _load_graph_from_db(db_path)

    from codeloom.mcp_server import dependencies

    with patch("codeloom.mcp_server._load") as mock_load:
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        mock_load.return_value = (store, G)
        result = dependencies("run", max_depth=3)

    assert "calculate" in result
    assert "add" in result
    assert "multiply" in result


def test_e2e_impact_on_unknown_symbol(tmp_path):
    """Real build: impact on non-existent symbol should return error."""
    src = tmp_path / "project"
    src.mkdir()
    _make_project(src)
    db_path = _build_project(src, tmp_path, embed=False)

    G = _load_graph_from_db(db_path)

    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        mock_load.return_value = (store, G)
        result = impact("nonexistent_symbol_xyz", max_depth=2)

    assert "No node found" in result


def test_e2e_impact_json_format(tmp_path):
    """Real build: impact with format=json should return valid JSON."""
    import json

    src = tmp_path / "project"
    src.mkdir()
    _make_project(src)
    db_path = _build_project(src, tmp_path, embed=False)

    G = _load_graph_from_db(db_path)

    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        mock_load.return_value = (store, G)
        result = impact("calculate", max_depth=2, format="json")

    data = json.loads(result)
    assert "target" in data
    assert "levels" in data
    assert data["target_label"] is not None


def test_e2e_impact_no_graph_nodes(tmp_path):
    """Empty directory build should result in no nodes."""
    src = tmp_path / "empty_project"
    src.mkdir()
    db_path = _build_project(src, tmp_path, embed=False)

    G = _load_graph_from_db(db_path)

    from codeloom.mcp_server import impact

    with patch("codeloom.mcp_server._load") as mock_load:
        from codeloom.storage.store import KnowledgeStore

        store = KnowledgeStore(str(db_path))
        mock_load.return_value = (store, G)
        result = impact("anything", max_depth=2)

    assert "No node found" in result
