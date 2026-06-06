"""Tests for tree-sitter Shell/Bash extraction via the tags.scm extractor."""

from __future__ import annotations

import os

import pytest

from codeloom.core.tags_extract import (
    _LANG_TO_PACKAGE,
    _cache,
    _get_lang_resources,
    extract_file_tags,
)
from codeloom.core.ts_extract import extract_file_ts


@pytest.fixture(autouse=True)
def _reset_caches():
    """Reset caches between tests."""
    _cache.clear()
    from codeloom.core import ts_extract
    ts_extract._parsers.clear()
    ts_extract._languages.clear()


@pytest.fixture
def tmp_sh(tmp_path):
    """Return a function that creates a temp .sh file with given content."""
    def _make(content: str) -> str:
        p = tmp_path / f"{os.urandom(4).hex()}.sh"
        p.write_text(content)
        return str(p)
    return _make


@pytest.fixture
def tmp_file(tmp_path):
    """Return function creating a temp file with given suffix and content."""
    def _make(suffix: str, content: str) -> str:
        p = tmp_path / f"{os.urandom(4).hex()}{suffix}"
        p.write_text(content)
        return str(p)
    return _make


# Check if bash grammar is available
BASH_AVAILABLE = _get_lang_resources("shell") is not None
_cache.clear()  # Don't leak into tests

pytestmark = pytest.mark.skipif(
    not BASH_AVAILABLE, reason="tree-sitter-bash not installed"
)


# ---------------------------------------------------------------------------
# _LANG_TO_PACKAGE mapping
# ---------------------------------------------------------------------------


class TestLangToPackageMapping:
    def test_shell_maps_to_bash(self):
        assert _LANG_TO_PACKAGE["shell"] == "bash"

    def test_unknown_language_falls_through(self):
        fallback = _LANG_TO_PACKAGE.get("unknown_lang", "unknown_lang")
        assert fallback == "unknown_lang"


# ---------------------------------------------------------------------------
# _get_lang_resources
# ---------------------------------------------------------------------------


class TestGetLangResources:
    def test_shell_grammar_is_available(self):
        res = _get_lang_resources("shell")
        assert res is not None
        assert "parser" in res
        assert "lang_obj" in res
        assert "tags_query_str" in res

    def test_tags_query_contains_function_pattern(self):
        res = _get_lang_resources("shell")
        assert res is not None
        assert "function_definition" in res["tags_query_str"]

    def test_unknown_grammar_returns_none(self):
        res = _get_lang_resources("r")
        assert res is None

    def test_results_are_cached(self):
        _cache.clear()
        assert "shell" not in _cache
        _get_lang_resources("shell")
        assert "shell" in _cache


# ---------------------------------------------------------------------------
# extract_file_tags — tags.scm-based extraction
# ---------------------------------------------------------------------------


class TestExtractFileTags:
    """Test the tags.scm universal extractor for shell files."""

    def test_extracts_function_definitions(self, tmp_sh):
        fpath = tmp_sh('greet() {\n  echo "Hello"\n}')
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "greet" in names
        kinds = {n.kind for n in result.nodes}
        assert "function" in kinds

    def test_extracts_multiple_functions(self, tmp_sh):
        code = (
            "foo() {\n  echo foo\n}\n"
            "bar() {\n  echo bar\n}\n"
            "baz() {\n  echo baz\n}\n"
        )
        fpath = tmp_sh(code)
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "foo" in names
        assert "bar" in names
        assert "baz" in names

    def test_detects_command_calls(self, tmp_sh):
        code = 'greet() {\n  echo "Hello, $1"\n}\ngreet "World"'
        fpath = tmp_sh(code)
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        call_edges = [e for e in result.edges if e.relation == "calls"]
        assert len(call_edges) > 0

    def test_returns_none_for_unsupported_language(self, tmp_file):
        fpath = tmp_file(".r", "x <- 1")
        result = extract_file_tags(fpath, "r")
        assert result is None

    def test_empty_file_returns_module_only(self, tmp_sh):
        fpath = tmp_sh("")
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        assert len(result.nodes) == 1  # module node only
        assert result.nodes[0].kind == "module"

    def test_include_keyword_function(self, tmp_sh):
        fpath = tmp_sh("function greet {\n  echo hello\n}")
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "greet" in names

    def test_variable_extraction(self, tmp_sh):
        fpath = tmp_sh("MY_VAR=42\necho $MY_VAR\n")
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        kinds = {n.kind for n in result.nodes}
        assert "function" not in kinds  # No function defs here

    def test_reads_from_disk_when_no_content(self, tmp_sh):
        fpath = tmp_sh('hello() {\n  echo world\n}')
        result = extract_file_tags(fpath, "shell")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "hello" in names


# ---------------------------------------------------------------------------
# extract_file_ts — priority chain (tags.scm → legacy → regex)
# ---------------------------------------------------------------------------


class TestExtractFileTs:
    """Test the priority chain in extract_file_ts."""

    def test_tags_scm_wins_for_shell(self, tmp_sh):
        fpath = tmp_sh('my_func() {\n  echo "works"\n}')
        result = extract_file_ts(fpath, "shell")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "my_func" in names

    def test_falls_back_to_module_only_for_r(self, tmp_file):
        """R has no grammar, should produce module-only node."""
        fpath = tmp_file(".r", "x <- 1")
        result = extract_file_ts(fpath, "r")
        assert result is not None
        assert len(result.nodes) == 1
        assert result.nodes[0].kind == "module"

    def test_python_still_extracts_via_tags_scm(self, tmp_file):
        fpath = tmp_file(".py", "def my_test_func():\n    pass\n")
        result = extract_file_ts(fpath, "python")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "my_test_func" in names

    def test_legacy_ast_walker_for_javascript(self, tmp_file):
        fpath = tmp_file(".js", "function legacyJsFunc() { return 42; }")
        result = extract_file_ts(fpath, "javascript")
        assert result is not None
        names = [n.name for n in result.nodes]
        assert "legacyJsFunc" in names

    def test_terraform_custom_extractor_still_works(self, tmp_file):
        code = 'resource "aws_instance" "web" {\n  ami = "ami-123"\n}'
        fpath = tmp_file(".tf", code)
        result = extract_file_ts(fpath, "terraform")
        assert result is not None
        assert any(n.kind in ("module", "resource") for n in result.nodes)
