"""Tests for doctor --deep and _repair_indexes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_HAS_FTS5: bool = True
try:
    _tmp = sqlite3.connect(":memory:")
    _tmp.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content='')")
    _tmp.close()
except Exception:
    _HAS_FTS5 = False

# ---------------------------------------------------------------------------
# _run_deep_checks
# ---------------------------------------------------------------------------


def _make_db_with_graph(db_path: Path) -> sqlite3.Connection:
    """Create a minimal knowledge.db with nodes, edges, and community tables."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            label TEXT,
            kind TEXT,
            file_path TEXT,
            language TEXT,
            start_line INTEGER,
            end_line INTEGER,
            docstring TEXT,
            signature TEXT,
            source_snippet TEXT,
            code_vec BLOB,
            text_vec BLOB,
            pagerank REAL,
            community_ids TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS edges (
            source TEXT,
            target TEXT,
            relation TEXT,
            confidence TEXT DEFAULT 'EXTRACTED',
            weight REAL DEFAULT 1.0,
            PRIMARY KEY (source, target, relation)
        );
        CREATE TABLE IF NOT EXISTS communities (
            id INTEGER PRIMARY KEY,
            level INTEGER,
            summary TEXT
        );
        CREATE TABLE IF NOT EXISTS community_members (
            node_id TEXT,
            community_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS resolved_references (
            id INTEGER PRIMARY KEY,
            source TEXT,
            target TEXT
        );
    """)
    conn.execute(
        "INSERT INTO nodes (id, label, kind, file_path, code_vec, text_vec,"
        " community_ids) VALUES ('n1', 'N1', 'function', 'mod/a.py',"
        " x'00', x'00', '[]')"
    )
    conn.execute(
        "INSERT INTO nodes (id, label, kind, file_path, code_vec, text_vec,"
        " community_ids) VALUES ('n2', 'N2', 'function', 'mod/b.py',"
        " x'00', NULL, '[]')"
    )
    conn.execute(
        "INSERT INTO edges (source, target, relation) "
        "VALUES ('n1', 'n2', 'calls')"
    )
    conn.execute(
        "INSERT INTO communities (id, level, summary) "
        "VALUES (0, 0, 'Test community')"
    )
    conn.execute(
        "INSERT INTO community_members (node_id, community_id) "
        "VALUES ('n1', 0)"
    )
    conn.commit()
    return conn


def test_deep_checks_ok(tmp_path):
    """doctor --deep with a healthy graph should pass all checks."""
    from codeloom.cli.main import _run_deep_checks

    db_path = tmp_path / ".codeloom" / "knowledge.db"
    db_path.parent.mkdir(parents=True)
    conn = _make_db_with_graph(db_path)

    ok_calls = []
    warn_calls = []
    fail_calls = []

    _run_deep_checks(
        conn, tmp_path,
        lambda s, m: ok_calls.append((s, m)),
        lambda s, m: warn_calls.append((s, m)),
        lambda s, m: fail_calls.append((s, m)),
    )

    ok_sections = {s for s, _ in ok_calls}
    warn_sections = {s for s, _ in warn_calls}
    assert "graph" in ok_sections
    assert "embeddings" in ok_sections
    # FTS5 index check may warn if index not present in test DB
    assert "index" in ok_sections or "index" in warn_sections
    assert len(fail_calls) == 0


def test_deep_checks_empty_graph(tmp_path):
    """doctor --deep on an empty graph should warn, not crash."""
    from codeloom.cli.main import _run_deep_checks

    conn = sqlite3.connect(str(tmp_path / "empty.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, label TEXT, kind TEXT,
            file_path TEXT, code_vec BLOB, text_vec BLOB,
            community_ids TEXT DEFAULT '[]');
        CREATE TABLE edges (source TEXT, target TEXT, relation TEXT,
            confidence TEXT, weight REAL);
        CREATE TABLE communities (id INTEGER PRIMARY KEY, level INTEGER,
            summary TEXT);
        CREATE TABLE community_members (node_id TEXT, community_id INTEGER);
        CREATE TABLE resolved_references (id INTEGER PRIMARY KEY,
            source TEXT, target TEXT);
    """)
    conn.commit()

    ok_calls = []
    warn_calls = []
    fail_calls = []

    _run_deep_checks(
        conn, tmp_path,
        lambda s, m: ok_calls.append((s, m)),
        lambda s, m: warn_calls.append((s, m)),
        lambda s, m: fail_calls.append((s, m)),
    )
    assert len(fail_calls) == 0


# ---------------------------------------------------------------------------
# _repair_indexes
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FTS5, reason="FTS5 not available")
def test_repair_fts5_rebuild(tmp_path):
    """_repair_indexes should rebuild missing FTS5 index."""
    from codeloom.cli.main import _repair_indexes

    db_path = tmp_path / ".codeloom" / "knowledge.db"
    db_path.parent.mkdir(parents=True)
    conn = _make_db_with_graph(db_path)
    # Drop FTS5 table to simulate missing index
    conn.execute("DROP TABLE IF EXISTS nodes_fts")
    conn.commit()

    ok_calls = []
    warn_calls = []
    fail_calls = []

    _repair_indexes(
        conn, tmp_path,
        lambda s, m: ok_calls.append((s, m)),
        lambda s, m: warn_calls.append((s, m)),
        lambda s, m: fail_calls.append((s, m)),
    )

    # Check FTS5 was rebuilt
    cursor = conn.execute("SELECT COUNT(*) FROM nodes_fts")
    assert cursor.fetchone()[0] > 0
    assert any("FTS5" in msg for _, msg in ok_calls)


def test_repair_orphaned_edges(tmp_path):
    """_repair_indexes should remove orphaned edges."""
    from codeloom.cli.main import _repair_indexes

    db_path = tmp_path / ".codeloom" / "knowledge.db"
    db_path.parent.mkdir(parents=True)
    conn = _make_db_with_graph(db_path)
    # Add a dangling edge pointing to a non-existent node
    conn.execute(
        "INSERT INTO edges (source, target, relation) "
        "VALUES ('n1', 'nonexistent_node', 'calls')"
    )
    conn.commit()

    before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    ok_calls = []
    warn_calls = []
    fail_calls = []

    _repair_indexes(
        conn, tmp_path,
        lambda s, m: ok_calls.append((s, m)),
        lambda s, m: warn_calls.append((s, m)),
        lambda s, m: fail_calls.append((s, m)),
    )

    after = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert after < before  # Orphan removed
    assert after == 1  # Only the original valid edge remains


@pytest.mark.skipif(not _HAS_FTS5, reason="FTS5 not available")
def test_repair_fts5_already_exists(tmp_path):
    """_repair_indexes should not fail when FTS5 already exists."""
    from codeloom.cli.main import _repair_indexes

    db_path = tmp_path / ".codeloom" / "knowledge.db"
    db_path.parent.mkdir(parents=True)
    conn = _make_db_with_graph(db_path)

    ok_calls = []
    warn_calls = []
    fail_calls = []

    # Should complete without error
    _repair_indexes(
        conn, tmp_path,
        lambda s, m: ok_calls.append((s, m)),
        lambda s, m: warn_calls.append((s, m)),
        lambda s, m: fail_calls.append((s, m)),
    )
    assert len(fail_calls) == 0


# ---------------------------------------------------------------------------
# doctor CLI integration (smoke test)
# ---------------------------------------------------------------------------


def test_doctor_help():
    """doctor --help should list options."""
    from click.testing import CliRunner

    from codeloom.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--deep" in result.output
    assert "--fix" in result.output


def test_doctor_basic():
    """doctor without arguments should complete without error."""
    from click.testing import CliRunner

    from codeloom.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "codeloom" in result.output.lower()


def test_doctor_deep_no_db():
    """doctor --deep without a database should warn but not crash."""
    from click.testing import CliRunner

    from codeloom.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["doctor", "--deep"])
        assert result.exit_code == 0
        assert "No database" in result.output


def test_doctor_fix_no_db():
    """doctor --fix without a database should warn but not crash."""
    from click.testing import CliRunner

    from codeloom.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["doctor", "--fix"])
        assert result.exit_code == 0
