#!/bin/sh
# codeloom auto-rebuild: runs incremental build if source files changed.
# Called by Stop/SessionEnd hooks from AI coding agents.
# Uses a lock file to prevent concurrent rebuilds.

LOCKFILE=".codeloom/rebuild.lock"
LOCK_TIMEOUT=30

[ -f .codeloom/knowledge.db ] || exit 0

# Ensure lock directory exists
mkdir -p ".codeloom" 2>/dev/null

# Clean up lock on exit
trap 'rm -f "$LOCKFILE"' EXIT

# Acquire lock with timeout using shlock (macOS) or flock (Linux)
if command -v shlock >/dev/null 2>&1; then
    # macOS
    if ! shlock -f "$LOCKFILE" -p $$; then
        exit 0  # Another rebuild is running
    fi
elif command -v flock >/dev/null 2>&1; then
    # Linux
    exec 9>"$LOCKFILE"
    if ! flock -n -w "$LOCK_TIMEOUT" 9; then
        exit 0  # Another rebuild is running (or timed out)
    fi
else
    # Fallback: simple pid file
    if [ -f "$LOCKFILE" ]; then
        OLD_PID=$(cat "$LOCKFILE" 2>/dev/null)
        if kill -0 "$OLD_PID" 2>/dev/null; then
            exit 0  # Another rebuild is running
        fi
    fi
    echo $$ > "$LOCKFILE"
fi

# Check if any source files changed (staged, unstaged, or untracked)
CHANGED=$(git diff --name-only HEAD 2>/dev/null | grep -E '\.(py|js|jsx|ts|tsx|java|go|rs|c|h|cpp|hpp|rb|md|html|csv|pdf)$' | head -1)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | grep -E '\.(py|js|jsx|ts|tsx|java|go|rs|c|h|cpp|hpp|rb|md|html|csv|pdf)$' | head -1)

if [ -n "$CHANGED" ] || [ -n "$UNTRACKED" ]; then
    codeloom build . --incremental >/dev/null 2>&1
fi

# Lock released by trap EXIT
