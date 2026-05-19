"""Tests for CLI commands — smoke tests and basic functionality."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
from click.testing import CliRunner

from codeloom.cli.main import cli
from codeloom.storage.store import KnowledgeStore


def _create_test_project(tmp_path: Path) -> Path:
    """Create a minimal test project with Python files."""
    src = tmp_path / "project"
    src.mkdir()
    (src / "main.py").write_text(
        "from app import App\n\ndef main():\n    app = App()\n    app.run()\n"
    )
    (src / "app.py").write_text(
        "class App:\n"
        '    """Application class."""\n'
        "    def run(self):\n"
        "        pass\n"
    )
    return src


def _create_test_db(tmp_path: Path) -> Path:
    """Create a pre-built knowledge base for search/stats/export tests."""
    db_dir = tmp_path / ".codeloom"
    db_dir.mkdir()
    db_path = db_dir / "knowledge.db"

    store = KnowledgeStore(db_path)
    G = nx.DiGraph()
    G.add_node(
        "m::module::app",
        label="app",
        kind="module",
        file_path="app.py",
        language="python",
        start_line=0,
        end_line=10,
        docstring="App module",
        signature="",
        source_snippet="class App:",
        pagerank=0.5,
        community_ids=[0],
    )
    G.add_node(
        "m::class::App",
        label="App",
        kind="class",
        file_path="app.py",
        language="python",
        start_line=1,
        end_line=8,
        docstring="Application class",
        signature="class App",
        source_snippet="class App:\n    def run(self):",
        pagerank=0.3,
        community_ids=[0],
    )
    G.add_edge(
        "m::module::app",
        "m::class::App",
        relation="defines",
        confidence="EXTRACTED",
    )
    store.save_graph(G)

    from codeloom.core.cluster import Community

    communities = {
        0: Community(
            id=0,
            level=0,
            resolution=1.0,
            node_ids=["m::module::app", "m::class::App"],
            summary="app, App",
        ),
    }
    store.save_communities(communities)
    store.set_meta("source_dir", str(tmp_path))
    store.set_meta("status", "complete")
    store.close()
    return tmp_path


class TestCLIHelp:
    """Test that all commands show help without errors."""

    def test_main_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "codeloom" in result.output

    def test_build_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["build", "--help"])
        assert result.exit_code == 0
        assert "SOURCE_DIR" in result.output

    def test_search_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "QUERY" in result.output

    def test_stats_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--help"])
        assert result.exit_code == 0

    def test_export_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert (
            "json" in result.output.lower()
            or "graphml" in result.output.lower()
        )

    def test_node_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["node", "--help"])
        assert result.exit_code == 0
        assert "NODE_ID" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "codeloom" in result.output


class TestCLIBuild:
    """Test the build command."""

    def test_build_basic(self, tmp_path):
        """Test build CLI invokes pipeline (embed=True by default)."""
        from unittest.mock import MagicMock, patch

        src = _create_test_project(tmp_path)
        mock_detect = MagicMock()
        mock_detect.files = ["a.py", "b.py"]
        mock_detect.skipped = []
        mock_cluster = MagicMock()
        mock_cluster.communities = [1, 2]
        mock_result = MagicMock()
        mock_result.detect_result = mock_detect
        mock_result.cluster_result = mock_cluster
        mock_result.node_count = 5
        mock_result.edge_count = 3
        mock_result.embeddings_count = 4
        mock_result.db_path = str(tmp_path / "out" / "knowledge.db")
        mock_result.stage_timings = {}
        with patch(
            "codeloom.core.pipeline.run_pipeline",
            return_value=mock_result,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["build", str(src), "--output", str(tmp_path / "out")],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "nodes" in data

    def test_build_nonexistent_dir(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["build", "/nonexistent/path"])
        assert result.exit_code != 0


class TestCLIStats:
    """Test the stats command."""

    def test_stats_with_db(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--source-dir", str(project_dir)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "nodes" in data
        assert "edges" in data

    def test_stats_shows_graph_quality(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--source-dir", str(project_dir)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "density" in data
        assert "connected_components" in data
        assert "avg_clustering_coeff" in data

    def test_stats_no_db(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--source-dir", str(tmp_path)])
        assert result.exit_code != 0


class TestCLIExport:
    """Test the export command."""

    def test_export_json(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        out_file = tmp_path / "export.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "export",
                "--source-dir",
                str(project_dir),
                "--format",
                "json",
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "nodes" in data or "links" in data

    def test_export_graphml(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        out_file = tmp_path / "export.graphml"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "export",
                "--source-dir",
                str(project_dir),
                "--format",
                "graphml",
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()


class TestCLICommunities:
    """Test the communities command."""

    def test_communities_list(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["communities", "--source-dir", str(project_dir)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_communities_search(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "communities",
                "--source-dir",
                str(project_dir),
                "--search",
                "app",
            ],
        )
        assert result.exit_code == 0

    def test_communities_no_db(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["communities", "--source-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_communities_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["communities", "--help"])
        assert result.exit_code == 0


class TestCLISearch:
    """Test the search command."""

    def test_search_no_db(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "search",
                "test query",
                "--source-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_search_keyword(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "search",
                "App",
                "--source-dir",
                str(project_dir),
            ],
        )
        # May return results or "No results" depending on vector index
        assert result.exit_code == 0

    def test_search_json_output(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "search",
                "App",
                "--source-dir",
                str(project_dir),
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "seeds" in data
        assert "edges" in data
        assert "isolated" in data

    def test_search_kind_filter(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "search",
                "App",
                "--source-dir",
                str(project_dir),
                "--kind",
                "class",
            ],
        )
        assert result.exit_code == 0

    def test_search_kind_invalid(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "search",
                "test",
                "--source-dir",
                str(tmp_path),
                "--kind",
                "invalid_kind",
            ],
        )
        assert result.exit_code != 0
        assert "invalid value" in result.output.lower()

    def test_search_file_pattern(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "search",
                "App",
                "--source-dir",
                str(project_dir),
                "--file",
                "*.py",
            ],
        )
        assert result.exit_code == 0


class TestCLIExportD3:
    """Test D3 export format."""

    def test_export_d3(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        out_file = tmp_path / "graph_d3.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "export",
                "--source-dir",
                str(project_dir),
                "--format",
                "d3",
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "nodes" in data
        assert "links" in data
        assert "metadata" in data
        assert data["metadata"]["node_count"] == 2


class TestCLIVisualize:
    """Test the visualize command."""

    def test_visualize_creates_html(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        out_file = tmp_path / "viz.html"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "visualize",
                "--source-dir",
                str(project_dir),
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        html = out_file.read_text()
        assert "d3.forceSimulation" in html

    def test_visualize_offline(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        out_file = tmp_path / "viz_offline.html"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "visualize",
                "--source-dir",
                str(project_dir),
                "--offline",
                "-o",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        html = out_file.read_text()
        # CDN script tag should be replaced (D3 source itself contains the URL)
        assert '<script src="https://d3js.org/d3.v7.min.js">' not in html
        assert len(html) > 280000  # ~280KB D3 inlined
        assert "d3.forceSimulation" in html
        assert (
            "Offline mode" in result.output
            or "offline" in result.output.lower()
        )

    def test_visualize_no_db(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "visualize",
                "--source-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_visualize_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["visualize", "--help"])
        assert result.exit_code == 0
        assert "max-nodes" in result.output
        assert "offline" in result.output


class TestCLIQuery:
    """Test the query REPL command."""

    def test_query_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["query", "--help"])
        assert result.exit_code == 0
        assert "Interactive search REPL" in result.output

    def test_query_no_db(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["query", "--source-dir", str(tmp_path)])
        assert result.exit_code != 0

    def test_query_exit_immediately(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "query",
                "--source-dir",
                str(project_dir),
            ],
            input=":quit\n",
        )
        assert result.exit_code == 0
        data = json.loads(result.output.splitlines()[0])
        assert data["status"] == "ready"
        assert "session_ended" in result.output

    def test_query_search_and_exit(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "query",
                "--source-dir",
                str(project_dir),
            ],
            input="App\nexit\n",
        )
        assert result.exit_code == 0
        data = json.loads(result.output.splitlines()[0])
        assert data["status"] == "ready"

    def test_query_stats_command(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "query",
                "--source-dir",
                str(project_dir),
            ],
            input=":stats\n:quit\n",
        )
        assert result.exit_code == 0
        assert '"nodes":' in result.output

    def test_query_node_command(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "query",
                "--source-dir",
                str(project_dir),
            ],
            input=":node App\n:quit\n",
        )
        assert result.exit_code == 0
        # Should show node details or "not found"
        assert "App" in result.output or "not found" in result.output


class TestCLIClean:
    """Test the clean command."""

    def test_clean_removes_db(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        kb_dir = project_dir / ".codeloom"
        assert kb_dir.exists()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "clean",
                "--source-dir",
                str(project_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert not kb_dir.exists()

    def test_clean_no_db(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "clean",
                "--source-dir",
                str(tmp_path),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "No .codeloom/" in result.output

    def test_clean_specific_file(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        db_file = project_dir / ".codeloom" / "knowledge.db"
        assert db_file.exists()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "clean",
                "--db",
                str(db_file),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert not db_file.exists()

    def test_clean_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["clean", "--help"])
        assert result.exit_code == 0
        assert "yes" in result.output


class TestCLINode:
    """Test the node command."""

    def test_node_exact_match(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "node",
                "m::class::App",
                "--source-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0
        assert "App" in result.output

    def test_node_fuzzy_match(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "node",
                "App",
                "--source-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0
        assert "App" in result.output

    def test_node_not_found(self, tmp_path):
        project_dir = _create_test_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "node",
                "NonExistentNode12345",
                "--source-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "not found" in data["error"].lower()


# ---------------------------------------------------------------------------
# Cline integration tests
# ---------------------------------------------------------------------------


class TestClineIntegration:
    def test_cline_install_creates_rules(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["cline", "install"])
            assert result.exit_code == 0
            rules = Path(".clinerules")
            assert rules.exists()
            content = rules.read_text()
            assert "codeloom" in content
            assert "HybridRAG" in content

    def test_cline_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["cline", "install"])
            result = runner.invoke(cli, ["cline", "install"])
            assert result.exit_code == 0
            assert "already" in result.output.lower()

    def test_cline_install_appends_to_existing(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".clinerules").write_text("# Existing rules\nDo stuff.\n")
            result = runner.invoke(cli, ["cline", "install"])
            assert result.exit_code == 0
            content = Path(".clinerules").read_text()
            assert "Existing rules" in content
            assert "codeloom" in content

    def test_cline_uninstall(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["cline", "install"])
            result = runner.invoke(cli, ["cline", "uninstall"])
            assert result.exit_code == 0

    def test_cline_uninstall_no_file(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["cline", "uninstall"])
            assert result.exit_code == 0
            assert "not found" in result.output.lower()


class TestOpenCodeIntegration:
    def test_opencode_install_project_scope(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "project"],
            )
            assert result.exit_code == 0
            skill_file = Path(".opencode/skills/codeloom/SKILL.md")
            assert skill_file.exists()
            assert "codeloom" in skill_file.read_text()

    def test_opencode_install_user_scope(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "user"],
            )
            assert result.exit_code == 0
            home = Path.home()
            skill_file = (
                home
                / ".config"
                / "opencode"
                / "skills"
                / "codeloom"
                / "SKILL.md"
            )
            assert skill_file.exists()
            assert "codeloom" in skill_file.read_text()
            # Clean up
            import shutil

            shutil.rmtree(home / ".config" / "opencode" / "skills" / "codeloom")

    def test_opencode_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result1 = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "project"],
            )
            result2 = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "project"],
            )
            assert result1.exit_code == 0
            assert result2.exit_code == 0
            assert "already exists" in result2.output.lower()

    def test_opencode_uninstall_project_scope(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli,
                ["opencode", "install", "--scope", "project"],
            )
            result = runner.invoke(
                cli,
                ["opencode", "uninstall", "--scope", "project"],
            )
            assert result.exit_code == 0
            skill_dir = Path(".opencode/skills/codeloom")
            assert not skill_dir.exists()

    def test_opencode_uninstall_no_install(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["opencode", "uninstall", "--scope", "project"],
            )
            assert result.exit_code == 0
            assert "not found" in result.output.lower()

    def test_opencode_install_writes_mcp_config_project(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "project"],
            )
            assert result.exit_code == 0
            config_file = Path("opencode.json")
            assert config_file.exists()
            config = json.loads(config_file.read_text())
            assert "mcp" in config
            assert "codeloom" in config["mcp"]
            assert config["mcp"]["codeloom"]["command"] == ["codeloom", "mcp"]

    def test_opencode_install_writes_mcp_config_user(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "user"],
            )
            assert result.exit_code == 0
            config_file = Path.home() / ".config" / "opencode" / "config.json"
            assert config_file.exists()
            config = json.loads(config_file.read_text())
            assert "mcp" in config
            assert "codeloom" in config["mcp"]
            # Clean up
            import shutil

            shutil.rmtree(Path.home() / ".config" / "opencode")

    def test_opencode_install_merges_existing_mcp_config(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            existing = {"mcp": {"other-tool": {"command": ["other"]}}}
            Path("opencode.json").write_text(json.dumps(existing))
            result = runner.invoke(
                cli,
                ["opencode", "install", "--scope", "project"],
            )
            assert result.exit_code == 0
            config = json.loads(Path("opencode.json").read_text())
            assert "other-tool" in config["mcp"]
            assert "codeloom" in config["mcp"]
            assert config["mcp"]["codeloom"]["type"] == "local"


class TestClaudeIntegration:
    def test_claude_install_creates_skill(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["claude", "install", "--scope", "project"],
            )
            assert result.exit_code == 0
            skill_file = Path(".claude/skills/codeloom/SKILL.md")
            assert skill_file.exists()
            assert "codeloom" in skill_file.read_text()

    def test_claude_install_creates_claude_md(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["claude", "install", "--scope", "project"],
            )
            assert result.exit_code == 0
            claude_md = Path("CLAUDE.md")
            assert claude_md.exists()
            assert "codeloom" in claude_md.read_text()

    def test_claude_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            r1 = runner.invoke(cli, ["claude", "install", "--scope", "project"])
            r2 = runner.invoke(cli, ["claude", "install", "--scope", "project"])
            assert r1.exit_code == 0
            assert r2.exit_code == 0
            assert "already exists" in r2.output.lower()

    def test_claude_uninstall_project(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(
                cli,
                ["claude", "install", "--scope", "project"],
            )
            result = runner.invoke(
                cli,
                ["claude", "uninstall", "--scope", "project"],
            )
            assert result.exit_code == 0
            assert not Path(".claude/skills/codeloom").exists()


class TestCodexIntegration:
    def test_codex_install_creates_agents_md(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["codex", "install"])
            assert result.exit_code == 0
            agents_md = Path("AGENTS.md")
            assert agents_md.exists()
            assert "codeloom" in agents_md.read_text()

    def test_codex_install_creates_hooks(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["codex", "install"])
            assert result.exit_code == 0
            hooks_file = Path(".codex/hooks.json")
            assert hooks_file.exists()
            hooks = json.loads(hooks_file.read_text())
            assert "codeloom" in json.dumps(hooks)

    def test_codex_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            r1 = runner.invoke(cli, ["codex", "install"])
            r2 = runner.invoke(cli, ["codex", "install"])
            assert r1.exit_code == 0
            assert r2.exit_code == 0
            assert "already exists" in r2.output.lower()

    def test_codex_uninstall(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["codex", "install"])
            result = runner.invoke(cli, ["codex", "uninstall"])
            assert result.exit_code == 0
            agents_md = Path("AGENTS.md")
            assert (
                not agents_md.exists()
                or "codeloom" not in agents_md.read_text()
            )


class TestGeminiIntegration:
    def test_gemini_install_creates_gemini_md(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["gemini", "install"])
            assert result.exit_code == 0
            gemini_md = Path("GEMINI.md")
            assert gemini_md.exists()
            assert "codeloom" in gemini_md.read_text()

    def test_gemini_install_creates_settings(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["gemini", "install"])
            assert result.exit_code == 0
            settings_file = Path(".gemini/settings.json")
            assert settings_file.exists()
            settings = json.loads(settings_file.read_text())
            assert "codeloom" in json.dumps(settings)

    def test_gemini_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            r1 = runner.invoke(cli, ["gemini", "install"])
            r2 = runner.invoke(cli, ["gemini", "install"])
            assert r1.exit_code == 0
            assert r2.exit_code == 0
            assert "already exists" in r2.output.lower()


class TestCursorIntegration:
    def test_cursor_install_creates_rules(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["cursor", "install"])
            assert result.exit_code == 0
            rules_file = Path(".cursor/rules/codeloom.mdc")
            assert rules_file.exists()
            assert "codeloom" in rules_file.read_text()

    def test_cursor_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            r1 = runner.invoke(cli, ["cursor", "install"])
            r2 = runner.invoke(cli, ["cursor", "install"])
            assert r1.exit_code == 0
            assert r2.exit_code == 0
            assert "already exists" in r2.output.lower()

    def test_cursor_uninstall(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["cursor", "install"])
            result = runner.invoke(cli, ["cursor", "uninstall"])
            assert result.exit_code == 0
            assert not Path(".cursor/rules/codeloom.mdc").exists()


class TestWindsurfIntegration:
    def test_windsurf_install_creates_rules(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["windsurf", "install"])
            assert result.exit_code == 0
            rules_file = Path(".windsurf/rules/codeloom.md")
            assert rules_file.exists()
            assert "codeloom" in rules_file.read_text()

    def test_windsurf_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            r1 = runner.invoke(cli, ["windsurf", "install"])
            r2 = runner.invoke(cli, ["windsurf", "install"])
            assert r1.exit_code == 0
            assert r2.exit_code == 0
            assert "already exists" in r2.output.lower()

    def test_windsurf_uninstall(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["windsurf", "install"])
            result = runner.invoke(cli, ["windsurf", "uninstall"])
            assert result.exit_code == 0
            assert not Path(".windsurf/rules/codeloom.md").exists()


class TestAiderIntegration:
    def test_aider_install_creates_conventions(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["aider", "install"])
            assert result.exit_code == 0
            conventions = Path("CONVENTIONS.md")
            assert conventions.exists()
            assert "codeloom" in conventions.read_text()

    def test_aider_install_idempotent(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            r1 = runner.invoke(cli, ["aider", "install"])
            r2 = runner.invoke(cli, ["aider", "install"])
            assert r1.exit_code == 0
            assert r2.exit_code == 0
            assert "already exists" in r2.output.lower()

    def test_aider_uninstall(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["aider", "install"])
            result = runner.invoke(cli, ["aider", "uninstall"])
            assert result.exit_code == 0
            conventions = Path("CONVENTIONS.md")
            assert (
                not conventions.exists()
                or "codeloom" not in conventions.read_text()
            )
