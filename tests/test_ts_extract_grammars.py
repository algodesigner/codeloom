"""Parametrised tests for all tree-sitter grammar languages.

Verifies that each grammar loads and its tags.scm compiles, and that
extract_file_tags produces meaningful results for a tiny code snippet.
"""

from __future__ import annotations

import pytest

from codeloom.core.tags_extract import (
    _cache,
    _get_lang_resources,
    extract_file_tags,
)

# Each entry: (language, file_ext, code_snippet, expected_name)
GRAMMAR_CHECKS: list[tuple[str, str, str, str]] = [
    # New tree-sitter grammars (with local tags.scm)
    ("haskell", ".hs", "add x y = x + y\n", "add"),
    ("julia", ".jl", "function add(x, y)\n  x + y\nend\n", "add"),
    ("perl", ".pl", "sub hello { print \"hi\" }\n", "hello"),
    ("zig", ".zig", "fn add(x: i32, y: i32) i32 { return x + y; }\n", "add"),
    ("nix", ".nix", "let x = 1; in x\n", None),
    ("graphql", ".graphql", "type User {\n  name: String!\n}\n", "User"),
    ("css", ".css", ".my-class { color: red; }\n", "my-class"),
    # Built-in tags.scm or TAGS_QUERY
    ("solidity", ".sol", "contract MyContract { }\n", "MyContract"),
    ("ocaml", ".ml", "let add x y = x + y\n", "add"),
    ("commonlisp", ".lisp", "(defun hello () (print \"hi\"))\n", "hello"),
    # New additions
    ("fortran", ".f90",
     "program hello\n  print *, \"Hello\"\nend program hello\n", None),
    ("powershell", ".ps1",
     "function Get-Help { param($Name) Write-Output $Name }\n", "Get-Help"),
    ("groovy", ".groovy", "def greet(name) {\n  println \"Hello $name\"\n}\n",
     "greet"),
    ("xml", ".xml", "<root><item>content</item></root>\n", "root"),
]


def _grammar_available(language: str) -> bool:
    _cache.clear()
    res = _get_lang_resources(language)
    _cache.clear()
    return res is not None


def _make_skip_reason(language: str) -> str:
    return f"tree-sitter-{language} not installed"


@pytest.mark.parametrize(
    "language,ext,code,expected_name",
    GRAMMAR_CHECKS,
)
def test_grammar_loads(language, ext, code, expected_name):
    if not _grammar_available(language):
        pytest.skip(_make_skip_reason(language))

    res = _get_lang_resources(language)
    assert res is not None
    assert "parser" in res
    assert "lang_obj" in res
    assert "tags_query_str" in res
    assert len(res["tags_query_str"]) > 0


@pytest.mark.parametrize(
    "language,ext,code,expected_name",
    GRAMMAR_CHECKS,
)
def test_tags_extraction(language, ext, code, expected_name, tmp_path):
    if not _grammar_available(language):
        pytest.skip(_make_skip_reason(language))

    f = tmp_path / f"test{ext}"
    f.write_text(code)
    result = extract_file_tags(str(f), language)
    assert result is not None, f"{language} extract_file_tags returned None"
    assert len(result.nodes) >= 1  # at least module node
    if expected_name is not None:
        names = [n.name for n in result.nodes]
        assert expected_name in names, (
            f"{language}: expected '{expected_name}' in {names}"
        )


@pytest.mark.parametrize(
    "language,ext,code,expected_name",
    GRAMMAR_CHECKS,
)
def test_tags_extraction_handles_empty_file(
    language, ext, code, expected_name, tmp_path
):
    if not _grammar_available(language):
        pytest.skip(_make_skip_reason(language))

    f = tmp_path / f"empty{ext}"
    f.write_text("")
    result = extract_file_tags(str(f), language)
    # Should not crash, at minimum return module node or None
    if result is not None:
        assert len(result.nodes) >= 1
