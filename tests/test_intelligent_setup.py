import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from codeloom.cli.main import cli


def test_intelligent_detection_cursor(tmp_path):
    """Verify that setup only detects agents whose footprint is present."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # 1. Mock only Cursor presence
        Path(".cursor").mkdir()

        # We need to mock shutil.which and detect_agents to ensure isolation
        with patch("shutil.which", return_value=None):
            result = runner.invoke(cli, ["install"], input="n\n")

            # Use lowercase for case-insensitive check
            output = result.output.lower()
            assert "detected agents:" in output
            assert "cursor" in output
            # Claude/Aider should not be detected if mocked correctly
            assert "claude" not in output
            assert "aider" not in output

def test_unified_uninstall_footprint_scan(tmp_path):
    """Verify that 'uninstall' (no args) detects and removes footprints."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # 1. Setup multiple
        runner.invoke(cli, ["install", "claude"], input="project\n")
        runner.invoke(cli, ["install", "cursor"])

        # 2. Run uninstall, confirm all
        result = runner.invoke(cli, ["uninstall"], input="y\n")

        output = result.output.lower()
        assert "found codeloom in:" in output
        assert "claude" in output
        assert "cursor" in output
        assert "removal complete!" in output

        # Footprints should be gone (or files cleaned)
        assert not Path("CLAUDE.md").exists()
        assert not Path(".cursor/rules/codeloom.mdc").exists()

def test_setup_unexpected_argument_fix(tmp_path):
    """Verify that setup doesn't fail with 'unexpected extra argument' anymore."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Mock detect_agents to return empty list to trigger manual selection
        with patch("codeloom.cli.integrations.detect_agents", return_value=[]):
            # Pick 'aider' from the list
            result = runner.invoke(cli, ["install"], input="project\naider\n")

            assert result.exit_code == 0
            assert "Error: Got unexpected extra argument" not in result.output
            assert "Setup complete!" in result.output

def test_opencode_agents_md_sync(tmp_path):
    """Verify that opencode install creates and cleans AGENTS.md."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # 1. Install
        runner.invoke(cli, ["install", "opencode", "--scope", "project"])
        assert Path("AGENTS.md").exists()
        assert "codeloom" in Path("AGENTS.md").read_text()

        # 2. Uninstall
        runner.invoke(cli, ["uninstall", "opencode", "--scope", "project"])
        # Should be deleted if it only had codeloom content
        assert not Path("AGENTS.md").exists()

def test_surgical_uninstall_integrity(tmp_path):
    """Verify that uninstall only removes codeloom block, leaving notes."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        notes = "# Project Notes\nCustom content."
        Path("CLAUDE.md").write_text(notes)

        # 1. Setup
        runner.invoke(cli, ["install", "claude", "--scope", "project"])

        # 2. Uninstall
        runner.invoke(cli, ["uninstall", "claude", "--scope", "project"])

        # 3. Verify notes are back to original
        assert Path("CLAUDE.md").read_text().strip() == notes.strip()

def test_command_group_uniqueness():
    """Verify that unified install/uninstall commands exist and accept agents."""
    from codeloom.cli.main import cli
    commands = list(cli.commands.keys())
    assert "install" in commands
    assert "uninstall" in commands
    # Per-platform groups should NOT exist as separate commands
    assert "cline" not in commands
    assert "aider" not in commands
    assert "opencode" not in commands

def test_json_merge_safety(tmp_path):
    """Verify JSON configuration remains valid and uncorrupted."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        settings_file = Path(".claude/settings.json")
        settings_file.parent.mkdir()

        # 1. Create invalid JSON
        settings_file.write_text("{ invalid json }")
        result = runner.invoke(cli, ["install", "claude", "--scope", "project"])
        assert "Could not parse" in result.output

        # 2. Valid JSON with existing content
        settings_file.write_text('{"existing": true}')
        runner.invoke(cli, ["install", "claude", "--scope", "project"])

        data = json.loads(settings_file.read_text())
        assert data["existing"] is True
        assert "hooks" in data
