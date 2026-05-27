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
            result = runner.invoke(cli, ["setup"], input="n\n")
            
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
        runner.invoke(cli, ["setup", "claude"], input="project\n")
        runner.invoke(cli, ["setup", "cursor"])
        
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
            result = runner.invoke(cli, ["setup"], input="project\naider\n")
            
            assert result.exit_code == 0
            assert "Error: Got unexpected extra argument" not in result.output
            assert "Setup complete!" in result.output

