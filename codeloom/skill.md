---
name: codeloom
description: Local-first code graph builder with 5-signal hybrid search. Use when analyzing codebases, searching for code architecture, exploring dependencies, or building code graphs from source code and documents.
compatibility: opencode, claude-code
metadata:
  install: codeloom opencode install
  location: .opencode/skills/codeloom/SKILL.md
---

# codeloom

codeloom is NOT a search engine that finds answers. It is a **map builder** — it tells you **what the codebase looks like** and **what to read next**. Use it as the starting point of every investigation, then drill deeper with Read and Grep.

Builds code graphs from source code and documents. Hybrid search (vector + FTS5 keyword → RRF fusion) with MST-based subgraph response showing how results connect. Supports 17 languages with deep AST extraction. 100% local.

## When to Use What

| Task | codeloom | Grep | Read |
|------|-----------|------|------|
| "Where is it?" (file discovery) | **best** | moderate | no |
| "What's the structure?" (architecture) | good | moderate | **best** |
| "What exactly exists?" (symbols, types) | moderate | **best** | good |
| "How does it connect?" (dependencies) | good | good | **best** |

**codeloom excels at**: Cross-service file discovery, document structure, ranking what to read first.
**Grep excels at**: Finding specific type/const/function definitions.
**Read excels at**: Understanding complete function bodies and data flow.

## Recommended Workflow

```
Step 1: codeloom search → identify relevant files and services
Step 2: Read → deeply understand architecture and data flow
Step 3: Grep → find specific symbols, types, constants
```

Always start with codeloom to get the big picture, then use Read/Grep for details.

## Search (PRIMARY — use this first)

```bash
codeloom search "database connection pool"       # default: 30 results, 3 snippets
codeloom search "auth" --fast                    # text model only, faster
codeloom search "error handling" --top-k 10      # custom count
codeloom search "handler" --kind function        # filter by symbol kind
codeloom search "api" --file "src/auth/*"        # filter by file path
codeloom search "Optimiser" --snippets 5         # show 5 source snippets
codeloom search "login" --include-tests          # give tests equal ranking
```

Response (compact text — seeds + scores + snippets + subgraph edges):
```
seeds:
core/build.py:15 (score: 0.047)
  │ def build_graph(self, sources: list[Path]) -> Graph:
  │     """Assemble the code graph from extracted units."""
  │     G = nx.DiGraph()
storage/store.py:20 (score: 0.032)
  │ class KnowledgeStore:

edges:
core/build.py:15 -calls-> storage/store.py:20
core/build.py:0 -co_change-> storage/store.py:0
core/build.py:0 -defines-> core/build.py:15
```

- `seeds`: Node IDs (file:line format) found by vector + keyword search. Use to read the code directly via `Read(file, offset=line)`.
- `edges`: Subgraph showing how seeds connect through the code graph. Intermediate nodes (e.g. `core/build.py:0` module) appear in edges but not in seeds.
- Edge relations: `calls`, `imports`, `inherits`, `defines`, `co_change` (files frequently committed together), `contains`, `references`.
- Node IDs use relative paths with 1-based line numbers (file:line). Use `node` tool for details.

## Important: Query in English

**Always query in English for best results.** Non-English queries (Japanese, Korean, Chinese, etc.) return significantly lower precision. If the user's request is in another language, translate the key concepts to English before searching.

```bash
# Good — English query
codeloom search "subscription promotion"     # score: 0.047, precise results

# Bad — Korean query
codeloom search "프로모션 구독 할인"           # score: 0.028, irrelevant results
```

## Search Strategy — Drill Down, Don't Stop at First Results

**Don't search once and stop.** Use results to discover domain-specific terms, then search deeper. The goal is to build a mental map, not to find a single answer.

### Example: "결제 관련 코드 찾아봐"

**Round 1** — Start broad with natural language:
```bash
codeloom search "payment processing"
```
→ Results mention `StripeClient`, `checkout_handler`, `PaymentProvider`

**Round 2** — Drill into discovered terms:
```bash
codeloom search "StripeClient"
```
→ Results reveal `create_charge`, `refund_payment`, `validate_card`, `WebhookHandler`

**Round 3** — Follow interesting connections:
```bash
codeloom search "webhook payment callback"
```
→ Found `StripeWebhookHandler`, `handle_charge_succeeded`, `update_order_status`

**Round 4** — Explore the related service:
```bash
codeloom search "order status update"
```
→ Found `OrderService.complete_order`, `NotificationService.send_receipt`

Now you have the full picture: Stripe → Webhook → Order → Notification.
**Then use Read to understand each file, and Grep to find specific type definitions.**

### The pattern:

1. **Start broad** — natural language describing intent (in English)
2. **Read results** — look for class names, function names, domain terms you didn't know
3. **Search specific** — use those discovered terms as next query
4. **Follow edges** — when results mention related services/modules, search those too
5. **Switch to Read/Grep** when you need specific details (types, constants, function bodies)
6. **Stop** when you have enough context to act

## Build

Before building, always check if a code graph already exists — call `codeloom stats` first. If stats returns node/edge counts, the graph is ready and you can skip building entirely.

```bash
codeloom build .                # Full build (only if no DB exists)
codeloom build . --incremental  # Update changed files only
```

## Inspect

```bash
codeloom stats                  # Graph overview
codeloom node "AuthHandler"     # Node details (partial match)
```

## Rules

- **You MUST search before grepping.** `codeloom search` covers 5 signals (code vector, text vector, graph expansion, keyword, community) in one call, plus shows how results connect via subgraph edges.
- **Use --kind and --file to narrow results.** When you know what kind of symbol you need, add `--kind function|class|method` (or interface, enum, struct, trait, section). When you know where it lives, add `--file "src/auth/*"`. This reduces noise and returns only relevant nodes.
- **Use --snippets to see source code inline.** Results include up to 5 lines of source context by default. Increase with `--snippets N`, disable with `--snippets 0`.
- **Use --include-tests to surface test code.** By default, test files are demoted 0.3× in ranking. Pass `--include-tests` to give them equal weight.
- **Check stats before building.** Call `codeloom stats` first to see if a DB already exists. If it returns node/edge counts, the graph is built and ready — skip the build step.
- **Do not stop at first results.** Drill into discovered terms for deeper understanding.
- **Query in English.** Non-English queries have significantly lower precision.
- **codeloom finds what to read; Read/Grep finds the details.** Seeds give you file:line locations. Use `node` tool or Read for details.
- **Follow the edges.** Subgraph edges reveal how code connects (calls, imports, co_change). Intermediate nodes on edges are path connectors (modules, directories).
- Use seed node IDs (file:line) to read code directly — `Read(file, offset=line)`.
- Run `codeloom build . --incremental` after code changes.
