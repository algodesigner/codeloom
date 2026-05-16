# Manual Testing Checklist

Run through this before each release to verify codeloom works end-to-end.

## 1. Installation

```bash
pip install codeloom
codeloom --version         # Should show 0.1.0
codeloom --help            # Should list all 23 commands
```

- [ ] `--version` shows correct version
- [ ] `--help` lists all commands (build, search, stats, node, opencode, claude, etc.)

## 2. Build a code graph

Pick a real project (codeloom itself works):

```bash
cd /path/to/codeloom
codeloom build .
```

- [ ] Build completes without errors
- [ ] Output shows stage timing breakdown (detect, extract, build, cluster, store)
- [ ] `.codeloom/knowledge.db` was created

## 3. Stats and inspect

```bash
codeloom stats
codeloom node "hybrid_search"
```

- [ ] `stats` shows node count, edge count, communities, density
- [ ] `node` finds the function and shows file path, signature, line numbers

## 4. Search (text output)

```bash
codeloom search "database"
codeloom search "error handling" --fast
```

- [ ] Results include file:line with scores: `core/db.py:42 (score: 0.047)`
- [ ] Subgraph edges shown: `node_a -calls-> node_b`
- [ ] `--fast` returns results (may differ from default)
- [ ] Empty query handled gracefully

## 5. Search (JSON output)

```bash
codeloom search "database" --json
```

- [ ] Output is valid JSON
- [ ] `seeds` key present with array of objects
- [ ] Each seed has: `id`, `label`, `kind`, `file`, `line`, `score`, `signature`, `signal_contributions`
- [ ] `edges` key present with `from`, `to`, `relation`
- [ ] `isolated` key present (may be empty)

## 6. OpenCode integration

```bash
codeloom opencode install --scope project
codeloom opencode install --scope user
codeloom opencode uninstall --scope project
codeloom opencode uninstall --scope user
```

- [ ] `--scope project` creates `.opencode/skills/codeloom/SKILL.md`
- [ ] `--scope project` writes `opencode.json` with MCP config
- [ ] `--scope user` creates `~/.config/opencode/skills/codeloom/SKILL.md`
- [ ] `--scope user` writes `~/.config/opencode/config.json` with MCP config
- [ ] Run install twice — second run says "already exists"
- [ ] Uninstall removes the skill directory
- [ ] Uninstall without prior install says "not found"

## 7. Claude Code integration

```bash
codeloom claude install --scope project
codeloom claude uninstall --scope project
```

- [ ] `--scope project` creates `.claude/skills/codeloom/SKILL.md`
- [ ] `CLAUDE.md` contains codeloom section with "You MUST use" language
- [ ] Uninstall removes the skill directory and CLAUDE.md section

## 8. Other integrations (spot-check)

```bash
codeloom codex install
codeloom gemini install
codeloom cursor install
codeloom windsurf install
codeloom cline install
codeloom aider install
```

- [ ] Each install completes without errors
- [ ] Each creates the expected files (AGENTS.md, GEMINI.md, .cursor/rules/, etc.)

## 9. MCP server

```bash
codeloom mcp --help
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":null}' | codeloom mcp
```

- [ ] `--help` mentions opencode.json config format
- [ ] JSON-RPC request returns response listing 5 tools: search, node, stats, communities, build

## 10. Edge cases

```bash
codeloom search ""                               # Empty query
codeloom search "zzzzz_nonexistent_xyzzy"        # No results
codeloom build /nonexistent/path                  # Invalid directory
codeloom clean                                    # Confirm cleanup
codeloom doctor                                   # Health check
```

- [ ] Empty query returns gracefully
- [ ] No-results query returns empty result set (not error)
- [ ] Invalid directory shows meaningful error
- [ ] `clean` removes `.codeloom/` directory after confirmation
- [ ] `doctor` reports installation health

## 11. Run the test suite

```bash
pip install -e ".[dev]"
ruff check codeloom/
pytest tests/
```

- [ ] `ruff check` — all clean
- [ ] `pytest tests/` — 337 passed

## 12. Cross-platform (if available)

- [ ] macOS (Intel)
- [ ] macOS (Apple Silicon)
- [ ] Linux (Ubuntu 22.04+)
- [ ] Python 3.10
- [ ] Python 3.11
- [ ] Python 3.12
- [ ] Python 3.13
