from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitDelta:
    modified: list[Path]
    added: list[Path]
    deleted: list[Path]
    renamed: list[tuple[Path, Path]]  # (old, new)

def get_git_deltas(repo_root: str | Path) -> GitDelta | None:
    """Get file deltas since last index using git.

    Uses `git status --porcelain -u` and `git diff --name-status` to
    identify changed, added, and deleted files.
    """
    try:
        # Check if it's a git repo
        subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_root,
            stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    modified, added, deleted, renamed = [], [], [], []

    # Get status of staged and unstaged changes
    # --porcelain=v1: XY path [-> path]
    # X/Y are status codes: M=modified, A=added, D=deleted, R=renamed
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain", "-uall"],
            cwd=repo_root,
            encoding="utf-8",
        )

        for line in output.splitlines():
            if not line:
                continue
            status = line[:2]
            path_part = line[3:]

            # Simplified status check
            if "M" in status:
                modified.append(Path(repo_root) / path_part)
            elif "A" in status or "?" in status:
                added.append(Path(repo_root) / path_part)
            elif "D" in status:
                deleted.append(Path(repo_root) / path_part)
            elif "R" in status:
                # Renames: "old -> new"
                if " -> " in path_part:
                    old_path, new_path = path_part.split(" -> ", 1)
                    renamed.append(
                        (Path(repo_root) / old_path, Path(repo_root) / new_path)
                    )
                else:
                    # git status sometimes just shows the new name if not staged
                    modified.append(Path(repo_root) / path_part)

        return GitDelta(
            modified=modified, added=added, deleted=deleted, renamed=renamed
        )
    except Exception:
        return None

