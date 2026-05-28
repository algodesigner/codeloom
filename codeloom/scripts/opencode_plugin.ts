// codeloom OpenCode Plugin
// Automatically injects code graph context before grep/glob calls
// and registers codeloom custom tools.
//
// Install: codeloom opencode install
// Location: .opencode/plugins/codeloom.ts

import { type Plugin, tool } from "@opencode-ai/plugin";

const DB_CHECK = "[ -f .codeloom/knowledge.db ] && echo 'ready' || echo 'missing'";

function isSearchCommand(cmd: string): boolean {
  const trimmed = cmd.trim();
  return (
    trimmed.startsWith("grep ") ||
    trimmed.startsWith("rg ") ||
    trimmed.startsWith("ag ") ||
    trimmed.startsWith("find ") ||
    trimmed.startsWith("git grep")
  );
}

function extractSearchTerms(cmdOrQuery: string): string {
  // Strip flags and extract meaningful search terms
  const cleaned = cmdOrQuery
    .replace(/^grep\s+/, "")
    .replace(/^rg\s+/, "")
    .replace(/^ag\s+/, "")
    .replace(/^find\s+\S+\s+/, "")
    .replace(/^-{1,2}\w+\s*/g, "")
    .replace(/["']/g, "")
    .replace(/[^a-zA-Z0-9_.\-\s]/g, " ")
    .trim();
  return cleaned.substring(0, 100); // cap length
}

export const CodeloomPlugin: Plugin = async ({ client, $, worktree }) => {
  // Check if codeloom graph exists on startup
  const graphReady = (await $`${DB_CHECK}`.text()).trim() === "ready";

  if (!graphReady) {
    // Graph not built yet — register tools but skip hooks
    console.log("codeloom: no graph found — hooks inactive, tools available");
    return {
      tool: {
        codeloom_search: tool({
          description:
            "Hybrid code search (vector + keyword + graph + community). "
            + "Requires `codeloom build .` first.",
          args: {
            query: tool.schema.string().describe("Search query"),
            kind: tool.schema
              .string()
              .optional()
              .describe(
                "Filter: function|class|method|interface|enum|struct|trait",
              ),
            snippets: tool.schema
              .number()
              .optional()
              .describe("Source snippets to show (default 3)"),
          },
          async execute(args) {
            const kind = args.kind ? `--kind ${args.kind}` : "";
            const snippets = args.snippets
              ? `--snippets ${args.snippets}`
              : "--snippets 3";
            try {
              return await $`codeloom search ${args.query} ${kind} ${snippets}`.text();
            } catch (e) {
              return `codeloom search failed: ${e}`;
            }
          },
        }),

        codeloom_impact: tool({
          description:
            "Blast radius analysis — who depends on this symbol?",
          args: {
            symbol: tool.schema.string().describe("Symbol name"),
            depth: tool.schema
              .number()
              .optional()
              .describe("Depth of analysis (default 3)"),
          },
          async execute(args) {
            const depth = args.depth ? `--max-depth ${args.depth}` : "";
            try {
              return await $`codeloom impact ${args.symbol} ${depth}`.text();
            } catch (e) {
              return `codeloom impact failed: ${e}`;
            }
          },
        }),

        codeloom_deps: tool({
          description:
            "Upstream dependency analysis — what does this symbol need?",
          args: {
            symbol: tool.schema.string().describe("Symbol name"),
            depth: tool.schema
              .number()
              .optional()
              .describe("Depth of analysis (default 3)"),
          },
          async execute(args) {
            const depth = args.depth ? `--max-depth ${args.depth}` : "";
            try {
              return await $`codeloom dependencies ${args.symbol} ${depth}`.text();
            } catch (e) {
              return `codeloom dependencies failed: ${e}`;
            }
          },
        }),
      },
    };
  }

  // Graph is ready — full integration
  console.log("codeloom: graph found — hooks active");

  return {
    // Before grep/glob — inject graph context into the session
    "tool.execute.before": async (input, output) => {
      try {
        let query = "";

        if (input.tool === "grep" || input.tool === "glob") {
          // Extract query from the tool args
          const rawQuery = output.args.query || output.args.pattern || "";
          query = typeof rawQuery === "string" ? rawQuery : String(rawQuery);
        } else if (input.tool === "bash" && output.args.command) {
          const cmd = output.args.command;
          if (isSearchCommand(cmd)) {
            query = extractSearchTerms(cmd);
          }
        }

        if (!query || query.length < 2) return;

        // Run codeloom search silently
        const result = await $`codeloom search ${query} --snippets 3`
          .text()
          .catch(() => "");

        if (result && !result.startsWith("No graph") && !result.startsWith("Error")) {
          // Inject context into the current session
          await client.session
            .prompt({
              body: {
                noReply: true,
                parts: [
                  {
                    type: "text",
                    text: `[codeloom graph context for "${query}"]\n${result}`,
                  },
                ],
              },
            })
            .catch(() => {
              // Silently fail — don't block the tool call
            });
        }
      } catch {
        // Don't block the user's tool call
      }
    },

    // After write/edit — detect stale graph
    "tool.execute.after": async (input) => {
      if (["write", "edit", "apply_patch"].includes(input.tool)) {
        try {
          const changed = await $`git diff --name-only 2>/dev/null | head -5`.text();
          if (changed.trim()) {
            await client.tui.showToast({
              body: {
                message:
                  "codeloom: code changed — "
                  + "run `codeloom build . --incremental` to sync graph",
                variant: "info",
              },
            });
          }
        } catch {
          // Silently fail
        }
      }
    },

    // Register custom tools alongside MCP
    tool: {
      codeloom_search: tool({
        description:
          "Hybrid code search (vector + keyword + graph + community). "
          + "Use this before grep — it finds semantic matches grep misses.",
        args: {
          query: tool.schema.string().describe("Search query"),
          kind: tool.schema
            .string()
            .optional()
            .describe(
              "Filter: function|class|method|interface|enum|struct|trait",
            ),
          file_pattern: tool.schema
            .string()
            .optional()
            .describe("Glob pattern to narrow search (e.g. src/auth/*)"),
          snippets: tool.schema
            .number()
            .optional()
            .describe("Source snippets to show (default 3)"),
        },
        async execute(args) {
          const kind = args.kind ? `--kind ${args.kind}` : "";
          const fileP = args.file_pattern ? `--file "${args.file_pattern}"` : "";
          const snippets = args.snippets
            ? `--snippets ${args.snippets}`
            : "--snippets 3";
          try {
            return await $`codeloom search ${args.query} ${kind} ${fileP} ${snippets}`.text();
          } catch (e) {
            return `codeloom search failed: ${e}`;
          }
        },
      }),

      codeloom_impact: tool({
        description:
          "Blast radius analysis — find everything that depends on a symbol. "
          + "Use before editing shared code.",
        args: {
          symbol: tool.schema.string().describe("Symbol name"),
          depth: tool.schema
            .number()
            .optional()
            .describe("Depth of analysis (default 3)"),
        },
        async execute(args) {
          const depth = args.depth ? `--max-depth ${args.depth}` : "";
          try {
            return await $`codeloom impact ${args.symbol} ${depth}`.text();
          } catch (e) {
            return `codeloom impact failed: ${e}`;
          }
        },
      }),

      codeloom_deps: tool({
        description:
          "Upstream dependency analysis — what does this symbol require?",
        args: {
          symbol: tool.schema.string().describe("Symbol name"),
          depth: tool.schema
            .number()
            .optional()
            .describe("Depth of analysis (default 3)"),
        },
        async execute(args) {
          const depth = args.depth ? `--max-depth ${args.depth}` : "";
          try {
            return await $`codeloom dependencies ${args.symbol} ${depth}`.text();
          } catch (e) {
            return `codeloom dependencies failed: ${e}`;
          }
        },
      }),

      codeloom_build: tool({
        description:
          "Rebuild the code graph incrementally after code changes.",
        args: {
          directory: tool.schema
            .string()
            .optional()
            .describe("Project directory (default .)"),
        },
        async execute(args) {
          const dir = args.directory || ".";
          try {
            return await $`codeloom build ${dir} --incremental`.text();
          } catch (e) {
            return `codeloom build failed: ${e}`;
          }
        },
      }),

      codeloom_detect: tool({
        description:
          "Detect which symbols are affected by unstaged changes.",
        args: {},
        async execute() {
          try {
            const changes = await $`codeloom impact "$(git diff --name-only HEAD 2>/dev/null | head -10)"`.text();
            return changes;
          } catch (e) {
            return `codeloom detect failed: ${e}`;
          }
        },
      }),
    },
  };
};
