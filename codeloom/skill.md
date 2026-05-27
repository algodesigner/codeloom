---
name: codeloom
description: Local-first code graph builder with 5-signal hybrid search. Use when analyzing codebases, searching for code architecture, exploring dependencies, or building code graphs from source code and documents.
compatibility: opencode, claude-code
metadata:
  install: codeloom opencode install
  location: .opencode/skills/codeloom/SKILL.md
---

# codeloom

Builds code graphs from source code and documents. Searches with 5-signal hybrid search (code vector + text vector + graph traversal + FTS5 keyword + community → RRF fusion). Supports 17 languages with deep AST extraction. 100% local.

**IMPORTANT: Always use `--json` flag when running via CLI.**

## Search (PRIMARY — use this first)

```bash
codeloom --json search "database connection pool"       # default: 80 results
codeloom --json search "auth" --fast                    # text model only, faster
codeloom --json search "payment billing" --snippets 5   # with source snippets
codeloom --json search "error handling" --kind function # filter by kind
```

## Impact Analysis (Blast Radius)

**Run this BEFORE you edit code.** It traces downstream dependents.

```bash
codeloom --json impact "StripeClient"
codeloom --json impact "AuthService.validate_token" --max-depth 5
```

## Dependency Analysis

**Run this to understand what a symbol needs.** It traces upstream dependencies.

```bash
codeloom --json dependencies "CheckoutHandler"
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
