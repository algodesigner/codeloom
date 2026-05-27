"""AI agent platform integrations (install/uninstall commands)."""

from __future__ import annotations

import json as _json
from pathlib import Path

import click

from ._helpers import (
    auto_rebuild_command,
    human_choose,
    human_done,
    human_header,
    human_ok,
    human_skip,
    human_warn,
)


def get_codeloom_context() -> str:
    """Returns the authoritative context rules for AI agents."""
    return (
        "<!-- codeloom-start -->\n"
        "## codeloom\n\n"
        "This project has a codeloom code graph at `.codeloom/`.\n\n"
        "Rules:\n"
        "- **You MUST use `codeloom search \"<query>\"` as your primary search "
        "method.** It runs 5-signal HybridRAG (vector + graph + keyword + "
        "community → RRF fusion) which is far more accurate than grep.\n"
        "- **Analyze impact before editing.** Use `codeloom impact \"<id>\"` "
        "to see the blast radius of your changes.\n"
        "- **Drill down into connections.** Use `codeloom node \"<id>\"` and "
        "`codeloom dependencies \"<id>\"` to understand structural "
        "requirements.\n"
        "- Before grepping raw files, you MUST run `codeloom search` first. "
        "Only fall back to Grep if the code graph has no results.\n"
        "- After modifying code files, run `codeloom build . --incremental` "
        "to keep your mental model and the graph current.\n"
        "- Use `codeloom stats` for structural overview (god nodes, "
        "communities, density).\n"
        "<!-- codeloom-end -->\n\n"
    )


def sync_codeloom_context(file_path: Path):
    """Surgically updates or prepends codeloom context to a file."""
    import re

    new_context = get_codeloom_context()
    start_marker = "<!-- codeloom-start -->"
    end_marker = "<!-- codeloom-end -->"

    if not file_path.exists():
        file_path.write_text(new_context)
        human_ok(f"{file_path.name} created with codeloom rules at the TOP.")
        return

    content = file_path.read_text()

    # Determine ideal position (after frontmatter if present)
    frontmatter_pattern = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
    fm_match = frontmatter_pattern.match(content)
    fm_text = fm_match.group(0) if fm_match else ""
    main_content = content[len(fm_text) :]

    # Try to find the marked block in the whole file
    block_pattern = re.compile(
        f"{re.escape(start_marker)}.*?{re.escape(end_marker)}\\s*",
        re.DOTALL,
    )
    match = block_pattern.search(content)

    if match:
        # Block found. Check if it's already identical
        existing_block = match.group(0)
        if existing_block.strip() == new_context.strip():
            # Already identical. Now check positioning.
            # It should be immediately after frontmatter.
            if main_content.lstrip().startswith(start_marker):
                msg = f"{file_path.name} context is up-to-date and at TOP."
                human_skip(msg)
                return
            else:
                # Move to correct position
                clean_main = block_pattern.sub("", main_content).lstrip()
                new_file_content = fm_text + new_context + clean_main
                file_path.write_text(new_file_content)
                human_ok(f"Moved codeloom context to TOP of {file_path.name}.")
                return

        # Content differs or position is wrong.
        clean_main = block_pattern.sub("", main_content).lstrip()
        new_file_content = fm_text + new_context + clean_main
        file_path.write_text(new_file_content)
        human_ok(f"Updated and moved codeloom context in {file_path.name}.")
    else:
        # No marked block found. Check for legacy unmarked header.
        legacy_marker = "## codeloom"
        if legacy_marker in content:
            # Safety fallback: Prepend marked block after FM and leave
            # legacy alone
            new_file_content = fm_text + new_context + main_content
            file_path.write_text(new_file_content)
            human_warn(
                f"Legacy context found in {file_path.name}. "
                "Prepended new marked block at TOP."
            )
        else:
            # Clean file. Just prepend after FM.
            new_file_content = fm_text + new_context + main_content.lstrip()
            file_path.write_text(new_file_content)
            human_ok(f"Prepended codeloom rules to {file_path.name}.")


def uninstall_codeloom_context(file_path: Path):
    """Removes the marked codeloom block from a file."""
    import re

    if not file_path.exists():
        human_skip(f"{file_path.name} not found")
        return

    content = file_path.read_text()
    start_marker = "<!-- codeloom-start -->"
    end_marker = "<!-- codeloom-end -->"

    pattern = re.compile(
        f"{re.escape(start_marker)}.*?{re.escape(end_marker)}\\s*",
        re.DOTALL,
    )

    if pattern.search(content):
        new_content = pattern.sub("", content).strip()
        if new_content:
            file_path.write_text(new_content + "\n")
        else:
            file_path.unlink()
        human_ok(f"Removed codeloom context from {file_path.name}")
    else:
        # Fallback for legacy unmarked header
        lines = content.splitlines(keepends=True)
        filtered = []
        skip = False
        for line in lines:
            if line.strip() == "## codeloom":
                skip = True
                continue
            if (
                skip
                and line.startswith("##")
                and "codeloom" not in line.lower()
            ):
                skip = False
            if not skip:
                filtered.append(line)

        new_content = "".join(filtered).strip()
        if new_content:
            file_path.write_text(new_content + "\n")
        else:
            file_path.unlink()
        human_ok(f"Removed legacy codeloom section from {file_path.name}")


def sync_skill_file(source: Path, dest: Path, force: bool = False):
    """Updates a skill file if it's an official version or forced."""
    import hashlib

    if not source.exists():
        human_warn(f"Skill source not found: {source}")
        return

    def get_hash(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    if not dest.exists():
        import shutil

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        human_ok(f"Skill installed to {dest.parent}/")
        return

    # Compare hashes
    src_hash = get_hash(source)
    dst_hash = get_hash(dest)

    if src_hash == dst_hash:
        human_skip(f"Skill in {dest.parent} is already up-to-date.")
        return

    if force:
        import shutil

        shutil.copy2(source, dest)
        human_ok(f"Force-updated skill in {dest.parent}/")
    else:
        human_warn(
            f"Skill in {dest.parent}/ has manual edits. "
            "Use --force to overwrite."
        )


def merge_json_config(file_path: Path, new_data: dict, key_path: list[str]):
    """Surgically merges data into a JSON file."""
    import json

    if not file_path.exists():
        # Create new with proper structure
        data = {}
        curr = data
        for k in key_path[:-1]:
            curr[k] = {}
            curr = curr[k]
        curr[key_path[-1]] = new_data
        file_path.write_text(json.dumps(data, indent=2) + "\n")
        human_ok(f"Created {file_path.name} with codeloom config.")
        return

    try:
        data = json.loads(file_path.read_text())
    except Exception as e:
        human_warn(f"Could not parse {file_path.name}: {e}. Skipping update.")
        return

    # Drill down to the target location
    curr = data
    for k in key_path[:-1]:
        curr = curr.setdefault(k, {})

    target_key = key_path[-1]

    # In settings.json, hooks is usually a dict of lists
    if target_key == "hooks" and isinstance(new_data, dict):
        hooks = curr.setdefault("hooks", {})
        for event, entry_list in new_data.items():
            existing_event_hooks = hooks.setdefault(event, [])
            already = any(
                "codeloom" in _json.dumps(h) for h in existing_event_hooks
            )
            if not already:
                existing_event_hooks.extend(entry_list)
                human_ok(f"Added codeloom {event} hook to {file_path.name}.")
            else:
                msg = f"codeloom {event} hook already in {file_path.name}."
                human_skip(msg)
    else:
        # Standard dict update
        if (
            target_key in curr
            and isinstance(curr[target_key], dict)
            and isinstance(new_data, dict)
        ):
            curr[target_key].update(new_data)
        else:
            curr[target_key] = new_data
        human_ok(f"Updated {target_key} in {file_path.name}.")

    file_path.write_text(_json.dumps(data, indent=2) + "\n")


# ─── Claude Code ─────────────────────────────────────────────────────────────


@click.group(name="claude")
def claude_group():
    """Manage Claude Code integration (skill + CLAUDE.md + hooks)."""
    pass


@claude_group.command(name="install")
@click.option(
    "--scope",
    type=click.Choice(["user", "project"], case_sensitive=False),
    default=None,
    help="Install scope: 'user' (global) or 'project' (local).",
)
@click.option("--force", is_flag=True, help="Overwrite manual skill edits.")
def claude_install(scope: str | None, force: bool = False):
    """Install Claude Code integration."""
    project_root = Path.cwd()

    if scope is None:
        scope = human_choose(
            "Where should codeloom be installed?",
            ["user", "project"],
            descriptions=[
                "Global (~/.claude/skills/) — available in ALL projects",
                "Local (.claude/skills/) — available only in THIS project",
            ],
            default=1,
        )

    human_header(f"Installing codeloom for Claude Code (scope: {scope})")

    skill_source = Path(__file__).parent.parent / "skill.md"
    if scope == "user":
        skill_dir = Path.home() / ".claude" / "skills" / "codeloom"
    else:
        skill_dir = project_root / ".claude" / "skills" / "codeloom"

    skill_dest = skill_dir / "SKILL.md"
    sync_skill_file(skill_source, skill_dest, force=force)

    claude_md = project_root / "CLAUDE.md"
    sync_codeloom_context(claude_md)

    settings_dir = project_root / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"

    new_hooks = {
        "PreToolUse": [
            {
                "matcher": "Glob|Grep",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "[ -f .codeloom/knowledge.db ] && echo "
                            '\'{"hookSpecificOutput":{"hookEventName":'
                            '"PreToolUse","additionalContext":"codeloom: '
                            '5-signal code graph available. STOP grepping. '
                            'Use `codeloom search \\"<query>\\"` for far '
                            'better results. Use `codeloom impact '
                            '\\"<id>\\"` before editing."'
                            "\"}}' || true"
                        ),
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "echo '{\"hookSpecificOutput\":{\"hookEventName\":"
                            "\"PostToolUse\",\"additionalContext\":\"codeloom: "
                            "Changes detected. Run `codeloom build . "
                            "--incremental` to update the code graph and "
                            "your mental model.\"}}'"
                        ),
                    }
                ],
            }
        ],
        "Stop": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": auto_rebuild_command(),
                        "timeout": 10,
                    }
                ],
            }
        ],
    }

    merge_json_config(settings_file, new_hooks, ["hooks"])
    human_done("Done! Run 'codeloom build .' to create your first code graph.")


@claude_group.command(name="uninstall")
@click.option(
    "--scope",
    type=click.Choice(["user", "project", "all"], case_sensitive=False),
    default="all",
    help="Uninstall scope: 'user', 'project', or 'all' (default).",
)
def claude_uninstall(scope: str):
    """Remove Claude Code integration."""
    import shutil

    human_header("Removing codeloom from Claude Code")
    project_root = Path.cwd()

    if scope in ("user", "all"):
        user_skill = Path.home() / ".claude" / "skills" / "codeloom"
        if user_skill.exists():
            shutil.rmtree(user_skill)
            human_ok("User skill removed")
    if scope in ("project", "all"):
        proj_skill = project_root / ".claude" / "skills" / "codeloom"
        if proj_skill.exists():
            shutil.rmtree(proj_skill)
            human_ok("Project skill removed")

    claude_md = project_root / "CLAUDE.md"
    uninstall_codeloom_context(claude_md)

    settings_file = project_root / ".claude" / "settings.json"
    if settings_file.exists():
        settings = _json.loads(settings_file.read_text())
        hooks = settings.get("hooks", {})
        for event in ("PreToolUse", "PostToolUse", "Stop"):
            event_hooks = hooks.get(event, [])
            hooks[event] = [
                h
                for h in event_hooks
                if (
                    "codeloom" not in _json.dumps(h)
                    and "auto_rebuild" not in _json.dumps(h)
                )
            ]
            if not hooks[event]:
                hooks.pop(event, None)
        if not hooks:
            settings.pop("hooks", None)
        settings_file.write_text(_json.dumps(settings, indent=2) + "\n")
        human_ok("Hooks removed from .claude/settings.json")

    human_done("codeloom integration removed.")


# ─── Codex CLI ───────────────────────────────────────────────────────────────


@click.group(name="codex")
def codex_group():
    """Manage per-project OpenAI Codex CLI integration."""
    pass


@codex_group.command(name="install")
def codex_install():
    """Install per-project Codex CLI integration (AGENTS.md + hooks.json)."""
    human_header("Installing codeloom for Codex CLI...")
    project_root = Path.cwd()

    agents_md = project_root / "AGENTS.md"
    sync_codeloom_context(agents_md)

    hooks_dir = project_root / ".codex"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = hooks_dir / "hooks.json"

    new_hooks = {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "[ -f .codeloom/knowledge.db ] && echo "
                            '\'{"hookSpecificOutput":{"hookEventName":'
                            '"PreToolUse","additionalContext":"codeloom: '
                            'code graph available. Use `codeloom search '
                            '\\"<query>\\"` (5-signal HybridRAG) instead '
                            "of grepping raw files. You can also add "
                            '`--kind function|class|method` or `--file '
                            '\\"src/*\\"` to narrow results."'
                            "\"}}' || true"
                        ),
                    }
                ],
            }
        ],
        "Stop": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": auto_rebuild_command(),
                        "timeout": 10,
                    }
                ],
            }
        ],
    }

    merge_json_config(hooks_file, new_hooks, ["hooks"])
    human_done()


@codex_group.command(name="uninstall")
def codex_uninstall():
    """Remove per-project Codex CLI integration."""
    human_header("Removing codeloom from Codex CLI")
    project_root = Path.cwd()

    agents_md = project_root / "AGENTS.md"
    uninstall_codeloom_context(agents_md)

    hooks_file = project_root / ".codex" / "hooks.json"
    if hooks_file.exists():
        hooks_data = _json.loads(hooks_file.read_text())
        hooks = hooks_data.get("hooks", {})
        for event in ("PreToolUse", "Stop"):
            event_hooks = hooks.get(event, [])
            hooks[event] = [
                h
                for h in event_hooks
                if (
                    "codeloom" not in _json.dumps(h)
                    and "auto_rebuild" not in _json.dumps(h)
                )
            ]
            if not hooks[event]:
                hooks.pop(event, None)
        if not hooks:
            hooks_data.pop("hooks", None)
        hooks_file.write_text(_json.dumps(hooks_data, indent=2) + "\n")
        human_ok("Hooks removed from .codex/hooks.json")

    human_done("codeloom integration removed.")


# ─── Gemini CLI ──────────────────────────────────────────────────────────────


@click.group(name="gemini")
def gemini_group():
    """Manage per-project Google Gemini CLI integration."""
    pass


@gemini_group.command(name="install")
def gemini_install():
    """Install per-project Gemini CLI integration (GEMINI.md + hooks)."""
    human_header("Installing codeloom for Gemini CLI...")
    project_root = Path.cwd()

    gemini_md = project_root / "GEMINI.md"
    sync_codeloom_context(gemini_md)

    settings_dir = project_root / ".gemini"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"

    new_hooks = {
        "BeforeTool": [
            {
                "matcher": "read_file",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "[ -f .codeloom/knowledge.db ] && echo "
                            '\'{"hookSpecificOutput":{"additionalContext":'
                            '"codeloom: code graph available. '
                            'Use `codeloom search \\"<query>\\"` (5-signal '
                            "HybridRAG) instead of reading raw files. This "
                            "single command covers vector, graph, keyword, "
                            'and community search with RRF fusion."'
                            "\"}}' || true"
                        ),
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": auto_rebuild_command(),
                        "timeout": 10,
                    }
                ],
            }
        ],
    }

    merge_json_config(settings_file, new_hooks, ["hooks"])
    human_done()


@gemini_group.command(name="uninstall")
def gemini_uninstall():
    """Remove per-project Gemini CLI integration."""
    human_header("Removing codeloom from Gemini CLI")
    project_root = Path.cwd()

    gemini_md = project_root / "GEMINI.md"
    uninstall_codeloom_context(gemini_md)

    settings_file = project_root / ".gemini" / "settings.json"
    if settings_file.exists():
        settings = _json.loads(settings_file.read_text())
        hooks = settings.get("hooks", {})
        for event in ("BeforeTool", "SessionEnd"):
            event_hooks = hooks.get(event, [])
            hooks[event] = [
                h
                for h in event_hooks
                if (
                    "codeloom" not in _json.dumps(h)
                    and "auto_rebuild" not in _json.dumps(h)
                )
            ]
            if not hooks[event]:
                hooks.pop(event, None)
        if not hooks:
            settings.pop("hooks", None)
        settings_file.write_text(_json.dumps(settings, indent=2) + "\n")
        human_ok("Hooks removed from .gemini/settings.json")

    human_done("codeloom integration removed.")


# ─── Cursor IDE ──────────────────────────────────────────────────────────────


@click.group(name="cursor")
def cursor_group():
    """Manage per-project Cursor IDE integration."""
    pass


@cursor_group.command(name="install")
def cursor_install():
    """Install per-project Cursor integration (.cursor/rules/codeloom.mdc)."""
    human_header("Installing codeloom for Cursor IDE...")
    project_root = Path.cwd()

    rules_dir = project_root / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rules_file = rules_dir / "codeloom.mdc"

    if not rules_file.exists():
        rule_content = (
            "---\n"
            "description: codeloom code graph search rules\n"
            "globs: **/*\n"
            "alwaysApply: true\n"
            "---\n\n"
        ) + get_codeloom_context()
        rules_file.write_text(rule_content)
        human_ok(".cursor/rules/codeloom.mdc created")
    else:
        sync_codeloom_context(rules_file)

    human_done()


@cursor_group.command(name="uninstall")
def cursor_uninstall():
    """Remove per-project Cursor integration."""
    human_header("Removing codeloom from Cursor IDE")
    project_root = Path.cwd()

    rules_file = project_root / ".cursor" / "rules" / "codeloom.mdc"
    if rules_file.exists():
        rules_file.unlink()
        human_ok(".cursor/rules/codeloom.mdc removed")
    else:
        human_skip(".cursor/rules/codeloom.mdc not found")

    human_done("codeloom integration removed.")


# ─── Windsurf IDE ────────────────────────────────────────────────────────────


@click.group(name="windsurf")
def windsurf_group():
    """Manage per-project Windsurf IDE integration."""
    pass


@windsurf_group.command(name="install")
def windsurf_install():
    """Install per-project Windsurf integration
    (.windsurf/rules/codeloom.md)."""
    human_header("Installing codeloom for Windsurf IDE...")
    project_root = Path.cwd()

    rules_dir = project_root / ".windsurf" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rules_file = rules_dir / "codeloom.md"

    sync_codeloom_context(rules_file)
    human_done()


@windsurf_group.command(name="uninstall")
def windsurf_uninstall():
    """Remove per-project Windsurf integration."""
    human_header("Removing codeloom from Windsurf IDE")
    project_root = Path.cwd()

    rules_file = project_root / ".windsurf" / "rules" / "codeloom.md"
    uninstall_codeloom_context(rules_file)
    human_done("codeloom integration removed.")


# ─── Cline ───────────────────────────────────────────────────────────────────


@click.group(name="cline")
def cline_group():
    """Manage per-project Cline (VS Code extension) integration."""
    pass


@cline_group.command(name="install")
def cline_install():
    """Install per-project Cline integration (.clinerules)."""
    human_header("Installing codeloom for Cline...")
    project_root = Path.cwd()

    rules_file = project_root / ".clinerules"
    sync_codeloom_context(rules_file)
    human_done()


@cline_group.command(name="uninstall")
def cline_uninstall():
    """Remove per-project Cline integration."""
    human_header("Removing codeloom from Cline")
    project_root = Path.cwd()

    rules_file = project_root / ".clinerules"
    uninstall_codeloom_context(rules_file)
    human_done("codeloom integration removed.")


# ─── Aider CLI ───────────────────────────────────────────────────────────────



@click.group(name="aider")
def aider_group():
    """Manage per-project Aider CLI integration."""
    pass


@aider_group.command(name="install")
def aider_install():
    """Install per-project Aider integration (CONVENTIONS.md +
    .aider.conf.yml)."""
    import yaml

    human_header("Installing codeloom for Aider CLI...")
    project_root = Path.cwd()

    conventions_md = project_root / "CONVENTIONS.md"
    sync_codeloom_context(conventions_md)

    conf_file = project_root / ".aider.conf.yml"
    if conf_file.exists():
        conf = yaml.safe_load(conf_file.read_text()) or {}
    else:
        conf = {}

    read_list = conf.get("read", [])
    if isinstance(read_list, str):
        read_list = [read_list]
    if "CONVENTIONS.md" not in read_list:
        read_list.append("CONVENTIONS.md")
        conf["read"] = read_list
        conf_file.write_text(yaml.dump(conf, default_flow_style=False))
        human_ok("CONVENTIONS.md added to .aider.conf.yml read list")
    else:
        human_skip("CONVENTIONS.md already in .aider.conf.yml read list")

    human_done()


@aider_group.command(name="uninstall")
def aider_uninstall():
    """Remove per-project Aider integration."""
    import yaml

    human_header("Removing codeloom from Aider CLI")
    project_root = Path.cwd()

    conventions_md = project_root / "CONVENTIONS.md"
    uninstall_codeloom_context(conventions_md)

    conf_file = project_root / ".aider.conf.yml"
    if conf_file.exists():
        conf = yaml.safe_load(conf_file.read_text()) or {}
        read_list = conf.get("read", [])
        if isinstance(read_list, str):
            read_list = [read_list]
        if "CONVENTIONS.md" in read_list:
            read_list.remove("CONVENTIONS.md")
            if read_list:
                conf["read"] = read_list
            else:
                conf.pop("read", None)
            if conf:
                conf_file.write_text(yaml.dump(conf, default_flow_style=False))
            else:
                conf_file.unlink()
            human_ok("CONVENTIONS.md removed from .aider.conf.yml read list")

    human_done("codeloom integration removed.")


# ─── OpenCode ───────────────────────────────────────────────────────────


@click.group(name="opencode")
def opencode_group():
    """Manage OpenCode integration (skill in .opencode/skills/)."""
    pass


@opencode_group.command(name="install")
@click.option(
    "--scope",
    type=click.Choice(["user", "project"], case_sensitive=False),
    default=None,
    help="Install scope: 'user' (global) or 'project' (local).",
)
@click.option("--force", is_flag=True, help="Overwrite manual skill edits.")
def opencode_install(scope: str | None, force: bool = False):
    """Install the codeloom skill for OpenCode."""
    project_root = Path.cwd()

    if scope is None:
        scope = human_choose(
            "Where should codeloom be installed?",
            ["user", "project"],
            descriptions=[
                "Global (~/.config/opencode/skills/) — "
                "available in ALL projects",
                "Local (.opencode/skills/) — available only in THIS project",
            ],
            default=1,
        )

    human_header(f"Installing codeloom for OpenCode (scope: {scope})")

    skill_source = Path(__file__).parent.parent / "skill.md"
    if scope == "user":
        skill_dir = Path.home() / ".config" / "opencode" / "skills" / "codeloom"
    else:
        skill_dir = project_root / ".opencode" / "skills" / "codeloom"

    skill_dest = skill_dir / "SKILL.md"
    sync_skill_file(skill_source, skill_dest, force=force)

    # Manage project context file
    agents_md = project_root / "AGENTS.md"
    sync_codeloom_context(agents_md)

    if scope == "user":
        mcp_config_path = Path.home() / ".config" / "opencode" / "config.json"
    else:
        mcp_config_path = project_root / "opencode.json"

    mcp_codeloom_config = {
        "codeloom": {
            "type": "local",
            "command": ["codeloom", "mcp"],
        }
    }

    merge_json_config(mcp_config_path, mcp_codeloom_config, ["mcp"])
    human_done(
        "Done! OpenCode will discover the skill and MCP tools automatically."
    )


@opencode_group.command(name="uninstall")
@click.option(
    "--scope",
    type=click.Choice(["user", "project"], case_sensitive=False),
    default="project",
    help="Uninstall scope: 'user' (global) or 'project' (default).",
)
def opencode_uninstall(scope: str):
    """Remove OpenCode integration."""
    import shutil

    human_header("Removing codeloom from OpenCode...")
    project_root = Path.cwd()

    if scope == "user":
        skill_dir = Path.home() / ".config" / "opencode" / "skills" / "codeloom"
    else:
        skill_dir = project_root / ".opencode" / "skills" / "codeloom"

    if skill_dir.exists():
        shutil.rmtree(skill_dir)
        human_ok(f"Removed {skill_dir}/")
    else:
        human_skip(f"{skill_dir}/ not found")

    agents_md = project_root / "AGENTS.md"
    uninstall_codeloom_context(agents_md)

    parent = skill_dir.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        human_ok(f"Removed empty {parent}/ directory")

    human_done("codeloom integration removed.")


# ─── Detection Logic ──────────────────────────────────────────────────────────


def detect_agents() -> list[str]:
    """Detect which agents are present on the machine or in the project."""
    import shutil

    detected = []
    project_root = Path.cwd()

    # Heuristics - mostly restricted to project root to avoid false positives
    # in test environments (which share the real home directory).
    heuristics = {
        "claude": lambda: shutil.which("claude")
        or (project_root / ".claude").exists()
        or (project_root / "CLAUDE.md").exists(),
        "opencode": lambda: shutil.which("opencode")
        or (project_root / "opencode.json").exists()
        or (project_root / ".opencode").exists(),
        "aider": lambda: shutil.which("aider")
        or (project_root / ".aider.conf.yml").exists()
        or (project_root / "CONVENTIONS.md").exists(),
        "cursor": lambda: (project_root / ".cursor").exists(),
        "windsurf": lambda: (project_root / ".windsurf").exists(),
        "cline": lambda: (project_root / ".clinerules").exists(),
        "codex": lambda: (project_root / ".codex").exists()
        or (project_root / "AGENTS.md").exists(),
        "gemini": lambda: (project_root / ".gemini").exists()
        or (project_root / "GEMINI.md").exists(),
    }

    for agent, check in heuristics.items():
        try:
            if check():
                detected.append(agent)
        except Exception:
            pass

    return detected


# ─── Register all groups ─────────────────────────────────────────────────────


def register_integration_commands(cli_group):
    """Register all integration subcommands on the given CLI group."""
    cli_group.add_command(claude_group)
    cli_group.add_command(codex_group)
    cli_group.add_command(gemini_group)
    cli_group.add_command(cursor_group)
    cli_group.add_command(windsurf_group)
    cli_group.add_command(cline_group)
    cli_group.add_command(aider_group)
    cli_group.add_command(opencode_group)
