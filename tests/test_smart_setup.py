import json
from pathlib import Path

from click.testing import CliRunner

from codeloom.cli.integrations import get_codeloom_context
from codeloom.cli.main import cli


def test_surgical_update(tmp_path):
    """Verify that only the codeloom block is updated, leaving other notes intact."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Create a file with old rules and custom notes
        initial_content = (
            "<!-- codeloom-start -->\n"
            "## codeloom\n\n"
            "Old rules here.\n"
            "<!-- codeloom-end -->\n\n"
            "# Project Notes\n"
            "Do not delete this."
        )
        Path("CLAUDE.md").write_text(initial_content)

        result = runner.invoke(cli, ["claude", "install", "--scope", "project"])
        assert result.exit_code == 0

        updated_content = Path("CLAUDE.md").read_text()
        assert "# Project Notes" in updated_content
        assert "Do not delete this." in updated_content
        assert get_codeloom_context().strip() in updated_content
        assert "Old rules here." not in updated_content

def test_positional_enforcement(tmp_path):
    """Verify that codeloom block is moved to the top if found elsewhere."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        initial_content = (
            "# Top Notes\n"
            "Keep me below rules.\n\n"
            "<!-- codeloom-start -->\n"
            "## codeloom\n"
            "Rules at bottom.\n"
            "<!-- codeloom-end -->"
        )
        Path("CLAUDE.md").write_text(initial_content)

        runner.invoke(cli, ["claude", "install", "--scope", "project"])

        content = Path("CLAUDE.md").read_text()
        assert content.startswith("<!-- codeloom-start -->")
        assert "# Top Notes" in content.split("<!-- codeloom-end -->")[1]

def test_legacy_support(tmp_path):
    """Verify that legacy unmarked headers are preserved while adding a marked block."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        initial_content = "## codeloom\nLegacy unmarked rules."
        Path("CLAUDE.md").write_text(initial_content)

        runner.invoke(cli, ["claude", "install", "--scope", "project"])

        content = Path("CLAUDE.md").read_text()
        assert content.startswith("<!-- codeloom-start -->")
        assert "Legacy unmarked rules." in content

def test_json_merge_idempotency(tmp_path):
    """Verify that JSON merging doesn't duplicate hooks and preserves existing config."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Existing config with another tool
        existing = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Linter", "hooks": [{"type": "cmd", "command": "lint"}]}
                ]
            }
        }
        settings_file = Path(".claude/settings.json")
        settings_file.parent.mkdir(parents=True)
        settings_file.write_text(json.dumps(existing))

        # Run twice
        runner.invoke(cli, ["claude", "install", "--scope", "project"])
        runner.invoke(cli, ["claude", "install", "--scope", "project"])

        data = json.loads(settings_file.read_text())
        hooks = data["hooks"]["PreToolUse"]

        # Should have 3 hooks total (linter + Glob|Grep + Bash), not 2
        assert len(hooks) == 3
        assert any("Linter" in h["matcher"] for h in hooks)
        assert any("codeloom" in json.dumps(h) for h in hooks)

def test_skill_safety(tmp_path):
    """Verify that edited skill files are not overwritten without --force."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # 1. Install official version
        runner.invoke(cli, ["claude", "install", "--scope", "project"])
        skill_file = Path(".claude/skills/codeloom/SKILL.md")

        # 2. Manually edit it
        skill_file.write_text("User edit")

        # 3. Try to update without force
        result = runner.invoke(cli, ["claude", "install", "--scope", "project"])
        assert "manual edits" in result.output
        assert skill_file.read_text() == "User edit"

        # 4. Update with force
        result = runner.invoke(cli, ["claude", "install", "--scope", "project", "--force"])
        assert "Force-updated skill" in result.output
        assert "User edit" not in skill_file.read_text()
