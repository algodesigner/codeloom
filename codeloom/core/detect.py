"""File detection and classification module.

Scans directories, classifies files by type, and respects ignore patterns.
Supports .gitignore and .codeloom-ignore with full gitignore spec via pathspec.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

# Supported languages mapped to file extensions
LANGUAGE_MAP: dict[str, list[str]] = {
    "python": [".py"],
    "javascript": [".js", ".jsx", ".mjs"],
    "typescript": [".ts", ".tsx"],
    "java": [".java"],
    "go": [".go"],
    "rust": [".rs"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".hpp", ".cc", ".cxx"],
    "ruby": [".rb"],
    "php": [".php"],
    "swift": [".swift"],
    "kotlin": [".kt", ".kts"],
    "c_sharp": [".cs"],
    "objc": [".m", ".mm"],
    "scala": [".scala"],
    "shell": [".sh", ".bash", ".zsh"],
    "lua": [".lua"],
    "elixir": [".ex", ".exs"],
    "r": [".r", ".R"],
    "terraform": [".tf"],
    "hcl": [".hcl"],
    "markdown": [".md", ".mdx"],
    "yaml": [".yml", ".yaml"],
    "json": [".json"],
    "toml": [".toml"],
    "pdf": [".pdf"],
    "html": [".html", ".htm"],
    "csv": [".csv", ".tsv"],
    "docx": [".docx"],
    "xlsx": [".xlsx"],
    "odt": [".odt"],
    "ods": [".ods"],
    "odp": [".odp"],
}

EXT_TO_LANG: dict[str, str] = {}
for lang, exts in LANGUAGE_MAP.items():
    for ext in exts:
        EXT_TO_LANG[ext] = lang

DEFAULT_IGNORE = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    ".DS_Store",
    ".codeloom",
}

SENSITIVE_PATTERNS = {
    "*.env",
    "*.pem",
    "*.key",
    "*.secret",
    "*credentials*",
    "*password*",
    "*.p12",
    "*.pfx",
}


@dataclass
class DetectedFile:
    path: Path
    language: str
    file_type: str  # "code", "config", "doc"
    size_bytes: int = 0


@dataclass
class DetectResult:
    files: list[DetectedFile] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    root: Path = field(default_factory=lambda: Path("."))


def _load_gitignore_spec(root: Path) -> pathspec.PathSpec | None:
    """Load .gitignore from root directory as a PathSpec matcher."""
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    try:
        raw = gitignore.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except Exception:
        return None


def _load_codeloom_ignore_spec(root: Path) -> pathspec.PathSpec | None:
    """Load .codeloom-ignore from root directory as a PathSpec matcher."""
    ignore_file = root / ".codeloom-ignore"
    if not ignore_file.exists():
        return None
    try:
        raw = ignore_file.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except Exception:
        return None


def _is_default_ignored(path: Path, patterns: set[str]) -> bool:
    """Check against DEFAULT_IGNORE patterns (simple fnmatch)."""
    name = path.name
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    for pattern in SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in EXT_TO_LANG:
        return "code"
    if ext in {".md", ".mdx", ".rst", ".txt"}:
        return "doc"
    if ext in {
        ".pdf",
        ".html",
        ".htm",
        ".csv",
        ".tsv",
        ".docx",
        ".xlsx",
        ".odt",
        ".ods",
        ".odp",
    }:
        return "doc"
    if ext in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        return "config"
    return "other"


def get_file_info(path: Path) -> DetectedFile | None:
    """Return info for a single file, or None if it should be skipped."""
    if not path.is_file():
        return None
    if _is_sensitive(path):
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None

    ext = path.suffix.lower()
    lang = EXT_TO_LANG.get(ext, "unknown")
    file_type = _classify_file(path)

    if file_type == "other":
        return None

    return DetectedFile(
        path=path,
        language=lang,
        file_type=file_type,
        size_bytes=size,
    )


def detect(
    root: Path,
    ignore_patterns: set[str] | None = None,
    max_file_size: int = 1_000_000,  # 1MB default
    git: bool = False,
) -> DetectResult:
    """Scan directory tree and classify files.

    Respects ignore patterns from three sources (all use gitignore spec):
    1. DEFAULT_IGNORE — built-in patterns for common non-source dirs
    2. .gitignore — standard git ignore file (full gitignore spec via pathspec)
    3. .codeloom-ignore — project-specific overrides (full gitignore spec)

    Args:
        root: Root directory to scan.
        ignore_patterns: Additional glob patterns to ignore.
        max_file_size: Skip files larger than this (bytes).
        git: Use git status to find changed files (accelerator).

    Returns:
        DetectResult with classified files and skip reasons.
    """
    root = Path(root).resolve()
    default_patterns = DEFAULT_IGNORE | (ignore_patterns or set())
    result = DetectResult(root=root)

    # 1. Git-powered delta discovery (Accelerator)
    if git:
        from .git import get_git_deltas

        deltas = get_git_deltas(root)
        if deltas:
            # For modified/added/renamed files, we need their info
            files_to_check = set(deltas.modified + deltas.added)
            for _, new_path in deltas.renamed:
                files_to_check.add(new_path)

            for path in sorted(files_to_check):
                info = get_file_info(path)
                if info:
                    result.files.append(info)
            return result
        # Fall back to full scan if git failed or not a repo

    # 2. Traditional full scan
    # Load gitignore-spec matchers
    gitignore_spec = _load_gitignore_spec(root)
    codeloom_spec = _load_codeloom_ignore_spec(root)

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        # 1. Check DEFAULT_IGNORE against filename and parent dirs
        if any(
            _is_default_ignored(p, default_patterns)
            for p in [path] + list(path.relative_to(root).parents)
        ):
            result.skipped.append(f"ignored: {path}")
            continue

        # 2. Check .gitignore patterns (full gitignore spec with
        #    negation support)
        rel_path = str(path.relative_to(root))
        if gitignore_spec and gitignore_spec.match_file(rel_path):
            result.skipped.append(f"gitignored: {path}")
            continue

        # 3. Check .codeloom-ignore patterns (full gitignore spec)
        if codeloom_spec and codeloom_spec.match_file(rel_path):
            result.skipped.append(f"codeloom-ignored: {path}")
            continue

        info = get_file_info(path)
        if info:
            if info.size_bytes > max_file_size:
                result.skipped.append(f"too_large ({info.size_bytes}B): {path}")
            else:
                result.files.append(info)
        else:
            # Re-check sensitive or unsupported for logging skip reason
            if _is_sensitive(path):
                result.skipped.append(f"sensitive: {path}")
            elif path.suffix.lower() not in EXT_TO_LANG:
                result.skipped.append(f"unsupported: {path}")
            elif path.stat().st_size == 0:
                result.skipped.append(f"empty: {path}")

    return result
